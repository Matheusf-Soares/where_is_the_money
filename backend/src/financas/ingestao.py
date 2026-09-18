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


# Estados em que o item está são. Qualquer outro é reportado.
STATUS_SAUDAVEL = "UPDATED"
EXECUCOES_SAUDAVEIS = ("SUCCESS", "PARTIAL_SUCCESS")

# Item cujo id não existe mais. É o único estado em que não há o que buscar,
# porque nem o item existe — então vira falha, não aviso.
STATUS_INEXISTENTE = "NOT_FOUND"


@dataclass(frozen=True)
class FalhaDeInstituicao:
    """Uma instituição que não pôde ser lida por inteiro."""

    instituicao: str
    motivo: str


@dataclass(frozen=True)
class ItemDegradado:
    """Conexão que respondeu, mas está pedindo socorro.

    Diferente de `FalhaDeInstituicao`: aqui o dado pode ter vindo. O que a API
    está dizendo é que a conexão não vai durar — MFA pendente, senha trocada,
    login falhando. Avisar agora é o que evita descobrir pelo `frescor` uma
    semana depois, com uma semana de extrato faltando.
    """

    instituicao: str
    id_item: str
    diagnostico: str


def _problema_do_item(item: dict[str, Any]) -> str:
    """Descreve o que está errado com um item, ou string vazia se está são.

    Lê só o que a API já devolveu. Nenhuma requisição a mais.
    """
    partes: list[str] = []

    status = str(item.get("status") or "").strip()
    if status and status != STATUS_SAUDAVEL:
        partes.append(f"status={status}")

    execucao = str(item.get("executionStatus") or "").strip()
    if execucao and execucao not in EXECUCOES_SAUDAVEIS:
        partes.append(f"execução={execucao}")

    acao = item.get("userAction")
    if acao:
        partes.append(f"EXIGE AÇÃO SUA: {str(acao)[:120]}")

    erro = item.get("error")
    if erro:
        mensagem = erro.get("message") if isinstance(erro, dict) else erro
        partes.append(f"erro={str(mensagem)[:120]}")

    tentativas = item.get("consecutiveFailedLoginAttempts")
    if isinstance(tentativas, int) and not isinstance(tentativas, bool) and tentativas > 0:
        partes.append(f"{tentativas} login(s) falhado(s) em sequência")

    detalhe = item.get("statusDetail")
    if detalhe:
        partes.append(f"detalhe={str(detalhe)[:120]}")

    return "; ".join(partes)


@dataclass(frozen=True)
class ResumoDaIngestao:
    """Relatório de uma execução, para a CLI imprimir e os testes conferirem."""

    itens: int
    contas: int
    transacoes: ResultadoUpsert
    contas_gravadas: ResultadoUpsert
    investimentos: ResultadoUpsert
    falhas: tuple[FalhaDeInstituicao, ...] = field(default=())
    degradados: tuple[ItemDegradado, ...] = field(default=())

    @property
    def houve_falha(self) -> bool:
        return bool(self.falhas)

    @property
    def houve_degradacao(self) -> bool:
        return bool(self.degradados)

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
    degradados: list[ItemDegradado] = []
    resultados: dict[str, list[ResultadoUpsert]] = {
        "raw_transacoes": [],
        "raw_contas": [],
        "raw_investimentos": [],
    }
    total_de_contas = 0
    estados: dict[str, list[str]] = {}

    # O nome configurado vence o do conector; ver `nome_da_instituicao`.
    rotulos = {i.id.lower(): i.instituicao for i in regras.itens}

    for item in itens:
        id_item = item.get("id", "")
        instituicao = nome_da_instituicao(item, rotulos.get(str(id_item).lower(), ""))
        estados.setdefault(instituicao, [])

        # A saúde é avaliada antes de buscar: um item cujo id não existe mais
        # não tem conta nenhuma para percorrer, e insistir só gastaria
        # requisição para receber lista vazia.
        problema = _problema_do_item(item)
        if str(item.get("status") or "") == STATUS_INEXISTENTE:
            registrador.error("%s: %s", instituicao, problema)
            falhas.append(
                FalhaDeInstituicao(
                    instituicao,
                    f"itemId {id_item} não existe mais. Reautorizar gera um id "
                    f"novo (armadilha 8): pegue o atual em dashboard.pluggy.ai "
                    f"e troque no regras.toml.",
                )
            )
            estados[instituicao].append("falha")
            continue
        if problema:
            registrador.warning("%s: %s", instituicao, problema)
            degradados.append(ItemDegradado(instituicao, id_item, problema))

        try:
            contas, transacoes, investimentos = _coletar(
                cliente, item, id_item, instituicao, inicio, hoje
            )
        except ErroPluggy as erro:
            # Falha de uma instituição não derruba as outras. Como o upsert é
            # idempotente, basta rodar de novo depois de resolver.
            registrador.error("%s: %s", instituicao, erro)
            falhas.append(FalhaDeInstituicao(instituicao, str(erro)))
            estados[instituicao].append("falha")
            continue

        total_de_contas += len(contas)
        # Grava por instituição, e não tudo no fim: assim uma queda no meio da
        # execução não joga fora o que já tinha sido baixado.
        resultados["raw_contas"].append(banco.gravar_contas(contas))
        resultados["raw_transacoes"].append(banco.gravar_transacoes(transacoes))
        resultados["raw_investimentos"].append(banco.gravar_investimentos(investimentos))
        estados[instituicao].append("acao_necessaria" if problema else "sucesso")
        registrador.info(
            "%s: %d contas, %d transações, %d investimentos",
            instituicao,
            len(contas),
            len(transacoes),
            len(investimentos),
        )

    for instituicao, tentativas in estados.items():
        # Duas conexões da mesma instituição não podem mascarar uma falha:
        # o sucesso representa uma coleta saudável do conjunto inteiro.
        estado = "falha" if "falha" in tentativas else "acao_necessaria" if "acao_necessaria" in tentativas else "sucesso"
        _registrar_sincronizacao(banco, instituicao, estado, inicio, hoje)

    return ResumoDaIngestao(
        itens=len(itens),
        contas=total_de_contas,
        transacoes=ResultadoUpsert.somar("raw_transacoes", resultados["raw_transacoes"]),
        contas_gravadas=ResultadoUpsert.somar("raw_contas", resultados["raw_contas"]),
        investimentos=ResultadoUpsert.somar(
            "raw_investimentos", resultados["raw_investimentos"]
        ),
        falhas=tuple(falhas),
        degradados=tuple(degradados),
    )


def _registrar_sincronizacao(banco: Banco, instituicao: str, estado: str, desde: date, ate: date) -> None:
    """Guarda sucesso da coleta mesmo quando os payloads não mudaram."""
    sucesso = estado == "sucesso"
    banco.conexao.execute(
        """INSERT INTO log_sincronizacoes
            (instituicao, tentado_em, sucesso_em, desde, ate, estado, mensagem)
        VALUES (?, now(), CASE WHEN ? THEN now() END, CASE WHEN ? THEN ? END,
                CASE WHEN ? THEN ? END, ?, '')
        ON CONFLICT (instituicao) DO UPDATE SET
            tentado_em = excluded.tentado_em, estado = excluded.estado,
            sucesso_em = coalesce(excluded.sucesso_em, log_sincronizacoes.sucesso_em),
            desde = coalesce(excluded.desde, log_sincronizacoes.desde),
            ate = coalesce(excluded.ate, log_sincronizacoes.ate), mensagem = excluded.mensagem""",
        [instituicao, sucesso, sucesso, desde, sucesso, ate, estado],
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
