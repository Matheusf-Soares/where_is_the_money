"""
CLI do pipeline.

Quatro subcomandos:

    ingerir   baixa da API (ou das fixtures) e grava na camada raw
    views     recarrega as cfg_* e aplica os .sql de staging e marts
    frescor   verifica se alguma instituição parou de trazer dado novo
    status    resumo do que existe no banco

Os códigos de saída são pensados para uso em `cron` e em script, onde ninguém
lê a saída: cada motivo de falha tem o seu, e `frescor` sair com código
não-zero é requisito da armadilha 4.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from financas.config import (
    Configuracao,
    ErroDeConfiguracao,
    carregar_configuracao,
    raiz_do_projeto,
)
from financas.frescor import atrasadas, verificar_frescor
from financas.ingestao import ingerir
from financas.persistencia import Banco
from financas.pluggy import ErroPluggy, criar_cliente
from financas.views import ErroDeView, aplicar_views

SAIDA_OK = 0
SAIDA_ERRO = 1            # configuração inválida, uso errado, falha inesperada
SAIDA_DADOS_VELHOS = 2    # alguma instituição parou de atualizar (armadilha 4)
SAIDA_INGESTAO_PARCIAL = 3  # pelo menos uma instituição falhou

registrador = logging.getLogger("financas")


def main(
    argv: Sequence[str] | None = None,
    *,
    ambiente: Mapping[str, str] | None = None,
    raiz: Path | None = None,
) -> int:
    """Ponto de entrada.

    `ambiente` e `raiz` existem para os testes rodarem contra um projeto
    temporário, sem depender do `.env` da máquina.
    """
    analisador = construir_analisador()
    argumentos = analisador.parse_args(argv)

    _configurar_log(argumentos.verboso)

    try:
        config = _carregar(argumentos, ambiente, raiz)
    except ErroDeConfiguracao as erro:
        print(erro, file=sys.stderr)
        return SAIDA_ERRO

    try:
        return argumentos.executar(argumentos, config)
    except ErroPluggy as erro:
        print(f"erro na API da Pluggy: {erro}", file=sys.stderr)
        return SAIDA_ERRO
    except ErroDeView as erro:
        print(f"erro ao aplicar view: {erro}", file=sys.stderr)
        return SAIDA_ERRO


# ---------------------------------------------------------------------------
# Subcomandos
# ---------------------------------------------------------------------------


def comando_ingerir(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Baixa da fonte configurada e grava na camada raw."""
    hoje = argumentos.hoje or date.today()

    with Banco.abrir(config.caminho_banco) as banco:
        banco.criar_schema()
        banco.gravar_regras(config.regras)
        cliente = criar_cliente(config)
        resumo = ingerir(
            cliente, banco, config.regras, hoje=hoje, desde=argumentos.desde
        )

    print(f"ingestão em modo {config.modo}, posição de {hoje}")
    for linha in resumo.linhas():
        print(linha)

    if resumo.houve_falha:
        print(file=sys.stderr)
        for falha in resumo.falhas:
            print(f"FALHOU  {falha.instituicao}: {falha.motivo}", file=sys.stderr)
        print(
            "\nAs demais instituições foram gravadas. Resolva o problema e rode "
            "de novo: a ingestão é idempotente e completa o que faltou.",
            file=sys.stderr,
        )
        return SAIDA_INGESTAO_PARCIAL

    return SAIDA_OK


def comando_views(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Recarrega as `cfg_*` a partir do TOML e reaplica as views."""
    raiz_sql = argumentos.sql or (raiz_do_projeto() / "sql")

    with Banco.abrir(config.caminho_banco) as banco:
        banco.criar_schema()
        banco.gravar_regras(config.regras)
        aplicadas = aplicar_views(banco, raiz_sql)

    print(f"configuração recarregada de {config.caminho_regras}")
    if not aplicadas:
        print(f"nenhuma view encontrada em {raiz_sql}")
        return SAIDA_OK

    print(f"{len(aplicadas)} views aplicadas:")
    for view in aplicadas:
        print(f"  {view}")
    return SAIDA_OK


def comando_frescor(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Verifica se alguma instituição parou de trazer dado novo (armadilha 4)."""
    hoje = argumentos.hoje or date.today()

    with Banco.abrir(config.caminho_banco) as banco:
        banco.criar_schema()
        situacoes = verificar_frescor(banco, hoje=hoje)

    if not situacoes:
        print(
            "nenhuma instituição no banco. Rode 'ingerir' antes de verificar frescor.",
            file=sys.stderr,
        )
        return SAIDA_ERRO

    for situacao in situacoes:
        print(situacao.descrever())

    velhas = atrasadas(situacoes)
    if velhas:
        print(file=sys.stderr)
        print(
            f"{len(velhas)} instituição(ões) sem dado novo. O consentimento de "
            "Open Finance pode ter vencido — reautorize em meu.pluggy.ai.",
            file=sys.stderr,
        )
        return SAIDA_DADOS_VELHOS

    return SAIDA_OK


def comando_status(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Resumo do que existe no banco. Comando de inspeção, não altera nada."""
    print(f"modo:    {config.modo}")
    print(f"banco:   {config.caminho_banco}")
    print(f"regras:  {config.caminho_regras}")
    if config.offline:
        print(f"fixtures: {config.diretorio_fixtures}")

    if not config.caminho_banco.is_file():
        print("\nbanco ainda não existe. Rode 'ingerir'.")
        return SAIDA_OK

    with Banco.abrir(config.caminho_banco) as banco:
        banco.criar_schema()
        print()
        for tabela in (
            "raw_transacoes",
            "raw_contas",
            "raw_investimentos",
            "cfg_padroes_fatura",
            "cfg_contrapartes_proprias",
            "cfg_frescor",
        ):
            print(f"  {tabela:<28} {banco.contar(tabela):>6}")

        periodo = banco.conexao.execute(
            "SELECT min(data), max(data) FROM raw_transacoes"
        ).fetchone()
        if periodo and periodo[0]:
            print(f"\nperíodo coberto: {periodo[0]} a {periodo[1]}")

    return SAIDA_OK


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------


def construir_analisador() -> argparse.ArgumentParser:
    analisador = argparse.ArgumentParser(
        prog="financas",
        description="Pipeline de ingestão e análise de gastos via Open Finance.",
    )
    analisador.add_argument(
        "-v",
        "--verboso",
        action="count",
        default=0,
        help="mais detalhe no log (-vv para depuração)",
    )
    analisador.add_argument(
        "--banco",
        type=Path,
        help="caminho do arquivo DuckDB (sobrescreve FINANCAS_BANCO)",
    )
    analisador.add_argument(
        "--modo",
        choices=("offline", "online"),
        help="fonte dos dados (sobrescreve FINANCAS_MODO)",
    )

    sub = analisador.add_subparsers(dest="comando", required=True)

    ingerir_ = sub.add_parser("ingerir", help="baixa da API e grava na camada raw")
    ingerir_.add_argument(
        "--desde",
        type=_data,
        help="data inicial (padrão: geral.data_inicial do regras.toml)",
    )
    ingerir_.add_argument(
        "--hoje", type=_data, help="data da posição gravada (padrão: hoje)"
    )
    ingerir_.set_defaults(executar=comando_ingerir)

    views_ = sub.add_parser("views", help="recarrega cfg_* e aplica as views SQL")
    views_.add_argument("--sql", type=Path, help="diretório das views (padrão: sql/)")
    views_.set_defaults(executar=comando_views)

    frescor_ = sub.add_parser(
        "frescor", help="verifica se alguma instituição parou de atualizar"
    )
    frescor_.add_argument(
        "--hoje", type=_data, help="data de referência (padrão: hoje)"
    )
    frescor_.set_defaults(executar=comando_frescor)

    status_ = sub.add_parser("status", help="resumo do que existe no banco")
    status_.set_defaults(executar=comando_status)

    return analisador


def _data(valor: str) -> date:
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"data inválida: {valor!r}. Use o formato AAAA-MM-DD."
        ) from None


def _carregar(
    argumentos: argparse.Namespace,
    ambiente: Mapping[str, str] | None,
    raiz: Path | None,
) -> Configuracao:
    """Monta a configuração aplicando os overrides da linha de comando.

    Argumento de linha de comando vence variável de ambiente, que vence `.env`.
    """
    valores = dict(ambiente) if ambiente is not None else None
    if argumentos.banco or argumentos.modo:
        import os

        valores = dict(os.environ if valores is None else valores)
        if argumentos.banco:
            valores["FINANCAS_BANCO"] = str(argumentos.banco)
        if argumentos.modo:
            valores["FINANCAS_MODO"] = argumentos.modo

    return carregar_configuracao(ambiente=valores, raiz=raiz)


def _configurar_log(verbosidade: int) -> None:
    nivel = {0: logging.WARNING, 1: logging.INFO}.get(verbosidade, logging.DEBUG)
    logging.basicConfig(
        level=nivel, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
