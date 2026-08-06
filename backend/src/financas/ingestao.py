"""
Orquestração da ingestão: percorre a API e grava na camada raw.

A travessia é `item → conta → transação`, mais `item → investimento`. Nenhuma
regra de negócio acontece aqui: normaliza e grava.

A decisão de projeto que mais importa neste módulo é o **isolamento por
instituição**. Se o consentimento do Nubank venceu, isso não pode impedir a
ingestão do Santander. Cada item é processado e gravado por conta própria; a
falha de um vira aviso no relatório e código de saída não-zero, sem derrubar o
resto. Como a gravação é idempotente, rodar de novo depois de renovar o
consentimento simplesmente completa o que faltou.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from financas.config import Regras
from financas.normalizacao import (
    nome_da_instituicao,
    normalizar_conta,
    normalizar_investimento,
    normalizar_transacao,
)
from financas.persistencia import Banco, ResultadoUpsert
from financas.pluggy import Cliente, ErroPluggy

registrador = logging.getLogger(__name__)


@dataclass(frozen=True)
class FalhaDeInstituicao:
    """Uma instituição que não pôde ser lida por inteiro."""

    instituicao: str
    motivo: str


@dataclass(frozen=True)
class ResumoDaIngestao:
    """Relatório de uma execução, para a CLI imprimir e os testes conferirem."""

    itens: int
    contas: int
    transacoes: ResultadoUpsert
    contas_gravadas: ResultadoUpsert
    investimentos: ResultadoUpsert
    falhas: tuple[FalhaDeInstituicao, ...] = field(default=())

    @property
    def houve_falha(self) -> bool:
        return bool(self.falhas)

    def linhas(self) -> list[str]:
        return [
            f"{self.itens} instituições, {self.contas} contas",
            f"  {self.transacoes}",
            f"  {self.contas_gravadas}",
            f"  {self.investimentos}",
        ]


def ingerir(
    cliente: Cliente,
    banco: Banco,
    regras: Regras,
    *,
    hoje: date,
    desde: date | None = None,
) -> ResumoDaIngestao:
    """Executa a ingestão completa.

    Args:
        cliente: implementação online ou offline; a ingestão não sabe a diferença.
        banco: destino já com o schema aplicado.
        regras: usado para `data_inicial` (armadilha 9).
        hoje: data da posição gravada em `raw_contas`. Explícito para o
            resultado não depender do relógio da máquina nos testes.
        desde: sobrescreve `regras.data_inicial` numa execução pontual.
    """
    inicio = desde or regras.data_inicial
    registrador.info("ingerindo a partir de %s", inicio)

    itens = cliente.listar_itens()
    falhas: list[FalhaDeInstituicao] = []
    resultados: dict[str, list[ResultadoUpsert]] = {
        "raw_transacoes": [],
        "raw_contas": [],
        "raw_investimentos": [],
    }
    total_de_contas = 0

    for item in itens:
        id_item = item.get("id", "")
        instituicao = nome_da_instituicao(item)
        try:
            contas, transacoes, investimentos = _coletar(
                cliente, item, id_item, instituicao, inicio, hoje
            )
        except ErroPluggy as erro:
            # Falha de uma instituição não derruba as outras. Como o upsert é
            # idempotente, basta rodar de novo depois de resolver.
            registrador.error("%s: %s", instituicao, erro)
            falhas.append(FalhaDeInstituicao(instituicao, str(erro)))
            continue

        total_de_contas += len(contas)
        # Grava por instituição, e não tudo no fim: assim uma queda no meio da
        # execução não joga fora o que já tinha sido baixado.
        resultados["raw_contas"].append(banco.gravar_contas(contas))
        resultados["raw_transacoes"].append(banco.gravar_transacoes(transacoes))
        resultados["raw_investimentos"].append(banco.gravar_investimentos(investimentos))
        registrador.info(
            "%s: %d contas, %d transações, %d investimentos",
            instituicao,
            len(contas),
            len(transacoes),
            len(investimentos),
        )

    return ResumoDaIngestao(
        itens=len(itens),
        contas=total_de_contas,
        transacoes=ResultadoUpsert.somar("raw_transacoes", resultados["raw_transacoes"]),
        contas_gravadas=ResultadoUpsert.somar("raw_contas", resultados["raw_contas"]),
        investimentos=ResultadoUpsert.somar(
            "raw_investimentos", resultados["raw_investimentos"]
        ),
        falhas=tuple(falhas),
    )


def _coletar(
    cliente: Cliente,
    item: dict[str, Any],
    id_item: str,
    instituicao: str,
    desde: date,
    hoje: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Baixa e normaliza tudo de um item, sem gravar nada.

    Coletar antes de gravar mantém a gravação de cada instituição atômica: ou
    entra o conjunto inteiro, ou não entra nada e a falha é reportada.
    """
    contas: list[dict[str, Any]] = []
    transacoes: list[dict[str, Any]] = []

    for bruta in cliente.listar_contas(id_item):
        contas.append(
            normalizar_conta(
                bruta, id_item=id_item, instituicao=instituicao, data_posicao=hoje
            )
        )
        id_conta = bruta.get("id", "")
        transacoes.extend(
            normalizar_transacao(bruta_tx, id_item=id_item, instituicao=instituicao)
            for bruta_tx in cliente.listar_transacoes(id_conta, desde)
        )

    investimentos = [
        normalizar_investimento(
            bruto, id_item=id_item, instituicao=instituicao, data_posicao=hoje
        )
        for bruto in cliente.listar_investimentos(id_item)
    ]

    return contas, transacoes, investimentos
