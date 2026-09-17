"""
Publicação: exporta as views para o frontend consumir.

O frontend é estático e lê Parquet direto no navegador, com DuckDB-WASM. Isso
não é economia de infraestrutura — é o que preserva o princípio 3 do projeto.

Uma API REST teria gravidade própria: no dia em que a tela precisar de "gasto
por categoria com média móvel", o caminho de menor resistência é escrever isso
em Python dentro do endpoint. Aí a regra passa a existir em dois lugares e as
views deixam de ser o contrato. Com Parquet + WASM o frontend fala SQL contra
as **mesmas views versionadas**, e não há onde esconder lógica.

O custo é honesto: os dados são um retrato do último `publicar`, não ao vivo.
Para um pipeline que roda uma vez por dia contra uma fonte com 24h de latência,
isso não custa nada — e o manifesto carimba a data para a tela poder dizer em
voz alta de quando é o que está mostrando.

`stg_transacoes` é exportada junto de propósito, e é a tabela mais importante
para auditoria: é nela que se vê **o que foi excluído e por quê**. Publicar só
`gastos` daria uma tela bonita e incapaz de responder "cadê aquele lançamento?".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from financas.persistencia import Banco

registrador = logging.getLogger(__name__)

# O que vai para o disco. A ordem é a de importância na tela.
TABELAS_PUBLICADAS = (
    "gastos",
    "stg_transacoes",
    "recorrencias",
    "patrimonio",
    "stg_contas",
    "stg_investimentos",
)

NOME_DO_MANIFESTO = "manifesto.json"


class ErroDePublicacao(Exception):
    """Faltou uma view, ou o destino não pôde ser escrito."""


@dataclass(frozen=True)
class Publicacao:
    """Resultado de uma execução de `publicar`."""

    destino: Path
    linhas: dict[str, int]
    avisos: tuple[str, ...]

    @property
    def total(self) -> int:
        return sum(self.linhas.values())


def publicar(
    banco: Banco,
    destino: Path,
    *,
    agora: datetime | None = None,
) -> Publicacao:
    """Exporta as views para Parquet e escreve o manifesto.

    Args:
        banco: conexão com as views já aplicadas.
        destino: diretório de dados do frontend. É **limpo** antes da escrita:
            Parquet órfão de uma publicação anterior apareceria na tela como
            dado atual, sem nada indicando que está velho.
    """
    momento = agora or datetime.now(timezone.utc)

    existentes = _views_existentes(banco)
    faltando = [t for t in TABELAS_PUBLICADAS if t not in existentes]
    if faltando:
        raise ErroDePublicacao(
            f"estas views não existem no banco: {', '.join(faltando)}. "
            f"Rode 'python -m financas views' antes de publicar."
        )

    destino.mkdir(parents=True, exist_ok=True)
    _limpar(destino)

    linhas: dict[str, int] = {}
    for tabela in TABELAS_PUBLICADAS:
        arquivo = destino / f"{tabela}.parquet"
        # COPY do próprio DuckDB: sem pandas no meio, sem conversão de tipo
        # perdendo a precisão do DECIMAL.
        #
        # O caminho vai como parâmetro em vez de interpolado: `--destino` vem da
        # linha de comando, e um diretório com apóstrofo no nome fecharia a
        # string do SQL. O nome da tabela continua interpolado porque vem de
        # TABELAS_PUBLICADAS, que é constante deste módulo.
        banco.conexao.execute(
            f"COPY (SELECT * FROM {tabela}) TO ? (FORMAT PARQUET)",
            [arquivo.as_posix()],
        )
        (quantas,) = banco.conexao.execute(f"SELECT count(*) FROM {tabela}").fetchone()
        linhas[tabela] = int(quantas)

    avisos = _avisos(banco, linhas)
    manifesto = {
        "gerado_em": momento.isoformat(),
        "linhas": linhas,
        "periodo": _periodo(banco),
        "avisos": list(avisos),
        "tabelas": list(TABELAS_PUBLICADAS),
    }
    (destino / NOME_DO_MANIFESTO).write_text(
        json.dumps(manifesto, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    registrador.info("publicadas %d tabelas em %s", len(linhas), destino)
    return Publicacao(destino=destino, linhas=linhas, avisos=avisos)


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------


def _avisos(banco: Banco, linhas: dict[str, int]) -> tuple[str, ...]:
    """Coisas que a tela precisa dizer em voz alta.

    Um dashboard que mostra R$ 0,00 sem explicar por quê é pior que um erro:
    parece resposta. Cada aviso aqui vira uma tarja no topo do frontend.
    """
    avisos: list[str] = []

    if not linhas.get("gastos"):
        avisos.append(
            "Nenhum gasto. Ou o banco está vazio, ou algum filtro está excluindo "
            "tudo — a aba Auditoria mostra o que foi marcado e por quê."
        )

    (com_categoria,) = banco.conexao.execute(
        "SELECT count(*) FROM stg_transacoes WHERE coalesce(categoria_pluggy, '') <> ''"
    ).fetchone()
    if linhas.get("stg_transacoes") and not com_categoria:
        avisos.append(
            "A Pluggy não devolveu categoria em nenhuma transação. Categorização "
            "é feature premium: em conta gratuita o campo vem nulo, o de-para "
            "não resolve nada e só as regras por texto atuam."
        )

    (sem_categoria,) = banco.conexao.execute(
        "SELECT count(*) FROM stg_transacoes "
        "WHERE origem_da_categoria = 'padrao' AND valor_assinado < 0 "
        "  AND NOT e_futura "
        "  AND NOT e_pagamento_de_fatura AND NOT e_transferencia_propria "
        "  AND NOT e_aplicacao"
    ).fetchone()
    consideradas = banco.conexao.execute(
        "SELECT count(*) FROM stg_transacoes WHERE valor_assinado < 0 "
        "  AND NOT e_futura "
        "  AND NOT e_pagamento_de_fatura AND NOT e_transferencia_propria "
        "  AND NOT e_aplicacao"
    ).fetchone()[0]
    if consideradas and sem_categoria / consideradas > 0.3:
        avisos.append(
            f"{sem_categoria} de {consideradas} gastos ({sem_categoria / consideradas:.0%}) "
            f"estão sem categoria. Os gráficos por categoria vão refletir isso."
        )

    return tuple(avisos)


def _periodo(banco: Banco) -> dict[str, str | None]:
    minimo, maximo = banco.conexao.execute(
        "SELECT min(data), max(data) FROM stg_transacoes"
    ).fetchone()
    return {
        "primeira_transacao": minimo.isoformat() if minimo else None,
        "ultima_transacao": maximo.isoformat() if maximo else None,
    }


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------


def _views_existentes(banco: Banco) -> set[str]:
    return {
        linha[0]
        for linha in banco.conexao.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()
    }


def _limpar(destino: Path) -> None:
    """Apaga Parquet e manifesto anteriores, e nada além disso.

    Deliberadamente não é `rmtree`: o diretório pode ser o mesmo que o usuário
    escolheu para outra coisa, e apagar arquivo que não é nosso seria um jeito
    caro de descobrir isso.
    """
    for arquivo in destino.glob("*.parquet"):
        arquivo.unlink()
    manifesto = destino / NOME_DO_MANIFESTO
    if manifesto.is_file():
        manifesto.unlink()


def servir(diretorio: Path, porta: int) -> None:
    """Sobe um servidor estático sobre o diretório do frontend.

    Existe porque DuckDB-WASM não funciona via `file://`: ele usa Web Workers e
    faz range requests nos Parquet, e as duas coisas exigem origem HTTP. Abrir o
    HTML com dois cliques mostraria uma tela vazia e um erro no console que não
    explica nada.

    Usa `http.server` da biblioteca padrão, ligado só em 127.0.0.1: o arquivo
    servido é o seu extrato.
    """
    import functools
    import http.server
    import socketserver

    manipulador = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(diretorio)
    )
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", porta), manipulador) as servidor:
        print(f"servindo {diretorio} em http://127.0.0.1:{porta}")
        print("Ctrl+C para parar.")
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nparado.")

