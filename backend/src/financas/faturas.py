"""Coleta faturas oficiais e atualiza os vínculos explícitos das transações.

A v2 de transações não documenta filtro billId. Relemos a janela disponível
por conta e preservamos o ID fornecido pela API, sem associar por aproximação.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from financas.config import Regras
from financas.normalizacao import normalizar_fatura, normalizar_transacao
from financas.persistencia import Banco
from financas.pluggy import Cliente, ErroPluggy
from financas.pluggy.fixtures import ErroDeFixture

registrador = logging.getLogger(__name__)


@dataclass(frozen=True)
class FalhaDeFatura:
    instituicao: str
    motivo: str


@dataclass(frozen=True)
class ResumoDeFaturas:
    contas: int
    faturas: int
    falhas: tuple[FalhaDeFatura, ...] = ()


def coletar_faturas(
    cliente: Cliente, banco: Banco, regras: Regras, *, hoje: date,
    transacoes_atualizadas: dict[str, date] | None = None,
) -> ResumoDeFaturas:
    """Atualiza cada cartão separadamente, preservando coletas anteriores.

    `hoje` delimita a posição conhecida usada para selecionar o cartão. Uma
    falha na atualização de lançamentos não descarta o total oficial obtido.
    O relatório de cobertura distingue esses dois instantes de coleta.
    `transacoes_atualizadas` evita repetir uma coleta feita pela ingestão geral
    nesta mesma execução; seu valor informa o início efetivamente consultado.
    """
    contas = banco.conexao.execute("""
        SELECT id, id_item, instituicao FROM raw_contas
        WHERE data_posicao <= ?
        QUALIFY row_number() OVER (PARTITION BY id ORDER BY data_posicao DESC) = 1
            AND upper(tipo) = 'CREDIT'
        ORDER BY id
    """, [hoje]).fetchall()
    quantidade = 0
    falhas: list[FalhaDeFatura] = []
    atualizadas = transacoes_atualizadas or {}
    for id_conta, id_item, instituicao in contas:
        inicio_conhecido = banco.conexao.execute(
            "SELECT min(data) FROM raw_transacoes WHERE id_conta = ?", [id_conta]
        ).fetchone()[0]
        desde = min(regras.data_inicial, inicio_conhecido) if inicio_conhecido else regras.data_inicial
        desde = atualizadas.get(id_conta, desde)
        mensagem = f"Lançamentos consultados desde {desde.isoformat()}; vínculo somente pelo ID informado pela instituição."
        try:
            brutas = cliente.listar_faturas(id_conta)
            if any(not isinstance(f, dict) or not isinstance(f.get("id"), str)
                   or not f["id"].strip() for f in brutas):
                raise ErroPluggy("fatura sem identificador válido; coleta anterior preservada")
            linhas = [normalizar_fatura(f, id_conta=id_conta, id_item=id_item,
                                       instituicao=instituicao) for f in brutas]
            resultado = banco.gravar_faturas(linhas)
            quantidade += resultado.inseridas + resultado.atualizadas + resultado.inalteradas
            estado = "sucesso" if brutas else "sem_faturas"
            _registrar(banco, id_conta, estado, mensagem, sucesso=True)
        except (ErroPluggy, ErroDeFixture) as erro:
            motivo = f"Faturas: {erro}"
            _registrar(banco, id_conta, "falha", motivo)
            falhas.append(FalhaDeFatura(instituicao, motivo))
            registrador.warning("%s: %s", instituicao, motivo)
            continue

        try:
            if id_conta not in atualizadas:
                brutas_tx = list(cliente.listar_transacoes(id_conta, desde))
                if any(not isinstance(t, dict) or not isinstance(t.get("id"), str)
                       or not t["id"].strip() or t.get("accountId") != id_conta
                       for t in brutas_tx):
                    raise ErroPluggy("extrato contém lançamento inválido ou de outro cartão")
                banco.gravar_transacoes(normalizar_transacao(t, id_item=id_item,
                                                           instituicao=instituicao) for t in brutas_tx)
            banco.conexao.execute("""UPDATE log_faturas SET transacoes_em = now(),
                transacoes_desde = ? WHERE id_conta = ?""", [desde, id_conta])
        except (ErroPluggy, ErroDeFixture) as erro:
            motivo = f"Total oficial atualizado; detalhamento preservado: {erro}"
            _registrar(banco, id_conta, "falha", motivo)
            falhas.append(FalhaDeFatura(instituicao, motivo))
            registrador.warning("%s: %s", instituicao, motivo)

    return ResumoDeFaturas(len(contas), quantidade, tuple(falhas))


def _registrar(banco: Banco, id_conta: str, estado: str, mensagem: str,
               *, sucesso: bool = False) -> None:
    banco.conexao.execute("""INSERT INTO log_faturas
        (id_conta, estado, coletado_em, tentado_em, mensagem)
        VALUES (?, ?, CASE WHEN ? THEN now() END, now(), ?)
        ON CONFLICT (id_conta) DO UPDATE SET estado = excluded.estado,
            coletado_em = coalesce(excluded.coletado_em, log_faturas.coletado_em),
            tentado_em = excluded.tentado_em, mensagem = excluded.mensagem""",
        [id_conta, estado, sucesso, mensagem])
