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
from typing import NoReturn

from financas.categorias import auditar, gerar_de_para
from financas.config import (
    Configuracao,
    ErroDeConfiguracao,
    carregar_configuracao,
    raiz_do_projeto,
)
from financas.diagnostico import (
    INTERPRETACAO_401,
    diagnosticar,
    diagnosticar_item,
)
from financas.frescor import atrasadas, verificar_frescor
from financas.ingestao import ingerir
from financas.persistencia import Banco
from financas.pluggy import ErroPluggy, criar_cliente
from financas.publicacao import ErroDePublicacao, publicar
from financas.servidor import servir_local
from financas.views import ErroDeView, aplicar_views

SAIDA_OK = 0
SAIDA_ERRO = 1            # configuração inválida, uso errado, falha inesperada
SAIDA_DADOS_VELHOS = 2    # alguma instituição parou de atualizar (armadilha 4)
SAIDA_INGESTAO_PARCIAL = 3  # pelo menos uma instituição falhou
SAIDA_CONFIG_MORTA = 4    # regra que nunca casa: filtro que não filtra
SAIDA_SEM_DADOS = 5       # a API respondeu, mas não havia nada para ingerir
SAIDA_ITEM_DEGRADADO = 6  # uma conexão pediu ação sua (MFA, senha, reautorizar)

registrador = logging.getLogger("financas")


def _avisar(*linhas: object) -> None:
    """Escreve em stderr depois de esvaziar stdout.

    Quando a saída não é um terminal — que é o caso em `cron`, o uso para o
    qual os códigos de saída foram pensados — o Python bufferiza stdout em
    bloco e deixa stderr sem buffer. Redirecionar os dois para o mesmo arquivo
    fazia o resumo do erro aparecer ANTES da lista que ele resume, e relatório
    fora de ordem é relatório que ninguém lê direito.
    """
    sys.stdout.flush()
    for linha in linhas:
        print(linha, file=sys.stderr)
    sys.stderr.flush()


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
        _avisar(erro)
        return SAIDA_ERRO

    try:
        return argumentos.executar(argumentos, config)
    except ErroPluggy as erro:
        _avisar(f"erro na API da Pluggy: {erro}")
        return SAIDA_ERRO
    except ErroDeView as erro:
        _avisar(f"erro ao aplicar view: {erro}")
        return SAIDA_ERRO
    except ErroDePublicacao as erro:
        _avisar(f"erro ao publicar: {erro}")
        return SAIDA_ERRO


# ---------------------------------------------------------------------------
# Subcomandos
# ---------------------------------------------------------------------------


def comando_ingerir(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Baixa da fonte configurada e grava na camada raw."""
    hoje = argumentos.hoje or date.today()

    with Banco.abrir(config.caminho_banco) as banco, criar_cliente(config) as cliente:
        banco.criar_schema()
        banco.gravar_regras(config.regras)
        resumo = ingerir(
            cliente, banco, config.regras, hoje=hoje, desde=argumentos.desde
        )

    print(f"ingestão em modo {config.modo}, posição de {hoje}")
    for linha in resumo.linhas():
        print(linha)

    if resumo.houve_falha:
        _avisar(
            "",
            *(f"FALHOU  {falha.instituicao}: {falha.motivo}" for falha in resumo.falhas),
            "\nAs demais instituições foram gravadas. Resolva o problema e rode "
            "de novo: a ingestão é idempotente e completa o que faltou.",
        )
        return SAIDA_INGESTAO_PARCIAL

    # Ingestão que não traz nada e sai com código 0 é a falha silenciosa que
    # este projeto existe para combater: o banco fica vazio, as views rodam, o
    # dashboard abre mostrando R$ 0,00 e nada em lugar nenhum diz que houve
    # problema. A API respondeu — só não havia o que responder.
    if resumo.itens == 0:
        _avisar("", _DIAGNOSTICO_SEM_ITENS.format(modo=config.modo))
        return SAIDA_SEM_DADOS

    if resumo.contas == 0:
        _avisar(
            "",
            f"{resumo.itens} conexão(ões) encontrada(s), mas nenhuma conta dentro "
            f"delas.\n\n"
            f"Isso costuma ser item em estado de erro ou aguardando MFA. Confira o "
            f"status de cada conexão em meu.pluggy.ai; se alguma pedir "
            f"reautorização, refaça e rode de novo.",
        )
        return SAIDA_SEM_DADOS

    # Conexão degradada não impede a ingestão de hoje, mas avisa que a de
    # amanhã pode não acontecer. Sai diferente de zero de propósito: é o único
    # jeito de um cron perceber.
    if resumo.houve_degradacao:
        _avisar(
            "",
            *(
                f"ATENÇÃO  {d.instituicao} ({d.id_item[:8]}…): {d.diagnostico}"
                for d in resumo.degradados
            ),
            "\nOs dados de hoje foram gravados. Mas a API está sinalizando que "
            "essas conexões precisam de ação sua — normalmente reautorizar em "
            "meu.pluggy.ai. Sem isso elas vão parar de trazer dado novo.",
        )
        return SAIDA_ITEM_DEGRADADO

    return SAIDA_OK


_DIAGNOSTICO_SEM_ITENS = """\
NADA FOI INGERIDO: GET /items devolveu uma lista vazia.

A autenticação funcionou — a API respondeu. O que não existe é conexão
autorizada dentro da aplicação cujas credenciais estão no .env.

A causa quase sempre é a confusão entre os dois portais da Pluggy, que têm
contas de login SEPARADAS:

  meu.pluggy.ai        onde você, como titular, autoriza os bancos
  dashboard.pluggy.ai  onde você, como desenvolvedor, cria a aplicação
                       e pega o PLUGGY_CLIENT_ID / SECRET

Autorizar os bancos no Meu Pluggy não os torna visíveis para a sua aplicação.
A ponte entre os dois é o conector MeuPluggy (id 200): dentro da aplicação
criada no Dashboard, é preciso criar um item com esse conector, autenticando
com a sua conta do Meu Pluggy. É isso que expõe, para a API, os dados que você
já autorizou do outro lado.

ANTES DISSO, CONFIRA SE O regras.toml TEM OS itemId.

Listar items é bloqueado pela Pluggy por design — a FAQ diz que não está
disponível "for security reasons, so that no data can leak across clients".
Não é permissão a pedir. Os ids precisam estar no regras.toml:

  [[item]]
  id = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
  observacao = "Nubank"

Pegue cada id em dashboard.pluggy.ai, na área de items da sua aplicação, e
valide com: python -m financas diagnostico --modo online --item <UUID>

Confira também:
  - o .env aponta para a aplicação certa, se você tiver mais de uma;
  - a aplicação está no ambiente de Desenvolvimento;
  - o modo atual é '{modo}' (use --modo online para falar com a API real).\
"""


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
        _avisar(
            "nenhuma instituição no banco. Rode 'ingerir' antes de verificar frescor."
        )
        return SAIDA_ERRO

    for situacao in situacoes:
        print(situacao.descrever())

    velhas = atrasadas(situacoes)
    if velhas:
        _avisar(
            "",
            f"{len(velhas)} instituição(ões) sem dado novo. O consentimento de "
            "Open Finance pode ter vencido — reautorize em meu.pluggy.ai.",
        )
        return SAIDA_DADOS_VELHOS

    return SAIDA_OK


def comando_publicar(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Exporta as views para o frontend e, opcionalmente, sobe o servidor."""
    frontend = argumentos.frontend or (raiz_do_projeto().parent / "frontend")
    destino = argumentos.destino or (frontend / "dados")

    with Banco.abrir(config.caminho_banco) as banco:
        banco.criar_schema()
        banco.gravar_regras(config.regras)
        aplicar_views(banco, raiz_do_projeto() / "sql")
        resultado = publicar(banco, destino)

    print(f"publicado em {destino}")
    for tabela, quantas in resultado.linhas.items():
        print(f"  {tabela:<20} {quantas:>7} linhas")

    if resultado.avisos:
        _avisar("", *(f"AVISO  {aviso}" for aviso in resultado.avisos))

    if argumentos.servir:
        print()
        servir_local(config, frontend, argumentos.porta, destino)
    else:
        print(
            f"\nPara abrir: python -m financas publicar --servir\n"
            f"(o navegador não consegue ler os Parquet por file://)"
        )

    return SAIDA_OK


def comando_servir(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Abre a aplicação com personalizações locais persistentes."""
    frontend = argumentos.frontend or (raiz_do_projeto().parent / "frontend")
    servir_local(config, frontend, argumentos.porta)
    return SAIDA_OK


def comando_categorias(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Gera o de-para a partir da API, ou audita a configuração atual."""
    if argumentos.sincronizar:
        return _sincronizar_categorias(argumentos, config)
    return _auditar_categorias(config)


def _sincronizar_categorias(
    argumentos: argparse.Namespace, config: Configuracao
) -> int:
    """Busca `GET /categories` e escreve o bloco `[[mapa_categoria]]`.

    Este é o único comando que faz sentido rodar em modo online sem ingerir
    nada: a taxonomia é lista de referência, igual para todos os clientes, e
    não contém dado financeiro.
    """
    with criar_cliente(config) as cliente:
        categorias = cliente.listar_categorias()

    if not categorias and config.offline:
        print(
            "nenhuma categoria nas fixtures. Rode com --modo online para buscar "
            "a taxonomia real da Pluggy.",
            file=sys.stderr,
        )
        return SAIDA_ERRO

    texto = gerar_de_para(categorias, existentes=config.regras)

    if argumentos.saida:
        argumentos.saida.write_text(texto, encoding="utf-8")
        print(f"{len(categorias)} categorias escritas em {argumentos.saida}")
        print(
            f"Revise os grupos e cole o conteúdo no fim de {config.caminho_regras}, "
            f"depois rode 'python -m financas views'."
        )
    else:
        print(texto)

    if not categorias:
        print(
            "\nA API não devolveu categoria nenhuma. Categorização é feature "
            "premium na Pluggy — se não estiver habilitada na sua conta, o campo "
            "'category' vem nulo em todas as transações e esta camada não tem o "
            "que fazer.",
            file=sys.stderr,
        )
        return SAIDA_ERRO

    return SAIDA_OK


def _auditar_categorias(config: Configuracao) -> int:
    """Regra que nunca casou e quanto do gasto ficou sem categoria."""
    if not config.caminho_banco.is_file():
        print("banco ainda não existe. Rode 'ingerir'.", file=sys.stderr)
        return SAIDA_ERRO

    with Banco.abrir(config.caminho_banco) as banco:
        banco.criar_schema()
        try:
            resultado = auditar(banco)
        except Exception as erro:  # a view pode não existir ainda
            print(
                f"não consegui ler stg_transacoes ({erro}). "
                f"Rode 'python -m financas views' antes.",
                file=sys.stderr,
            )
            return SAIDA_ERRO

    print(
        f"{resultado.total_transacoes} transações consideradas "
        f"(fatura, transferência própria e aplicação já fora)"
    )
    print(
        f"sem categoria: {resultado.sem_categoria} "
        f"({resultado.fracao_sem_categoria:.0%}), "
        f"{_reais(resultado.valor_sem_categoria)}"
    )

    if resultado.ids_sem_de_para:
        print("\ncategorias da Pluggy que ainda não têm de-para:")
        for id_categoria, descricao, quantidade in resultado.ids_sem_de_para[:15]:
            print(f"  {id_categoria:<12} {descricao:<28} {quantidade:>4} transações")

    if resultado.regras_mortas:
        print(file=sys.stderr)
        print(
            f"{len(resultado.regras_mortas)} regra(s) nunca casaram com nada:",
            file=sys.stderr,
        )
        for prioridade, padrao in resultado.regras_mortas:
            print(f"  prioridade {prioridade}: {padrao}", file=sys.stderr)
        print(
            "\nRegra que não casa é filtro que não filtra. Confira a redação "
            "contra as descrições reais em stg_transacoes.",
            file=sys.stderr,
        )
        return SAIDA_CONFIG_MORTA

    return SAIDA_OK


def comando_diagnostico(argumentos: argparse.Namespace, config: Configuracao) -> int:
    """Testa a conexão com a Pluggy passo a passo e mostra o que voltou.

    Não usa `ClienteHttp` de propósito: se o problema estiver no cliente, usar
    o cliente para investigar esconderia justamente o que se quer ver.
    """
    if config.offline:
        print(
            "diagnóstico só faz sentido em modo online. "
            "Rode: python -m financas diagnostico --modo online",
            file=sys.stderr,
        )
        return SAIDA_ERRO

    if argumentos.item:
        achados = diagnosticar_item(config, argumentos.item)
        for achado in achados:
            print(achado)
        return SAIDA_ERRO if any(a.ok is False for a in achados) else SAIDA_OK

    achados = diagnosticar(config)
    for achado in achados:
        print(achado)

    houve_falha = any(a.ok is False for a in achados)
    if houve_falha:
        _avisar("", INTERPRETACAO_401)
        return SAIDA_ERRO

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


def _declarar_globais(alvo: argparse.ArgumentParser, *, suprimir: bool) -> None:
    """Declara as flags globais num analisador.

    `suprimir` marca a cópia que vive nos subcomandos. Sem `SUPPRESS`, a flag
    não informada depois do subcomando gravaria o próprio default por cima do
    valor que veio antes dele, e `financas --modo online ingerir` voltaria
    silenciosamente para offline. Esse é o motivo de o padrão argparse não ser
    simplesmente copiar as opções.
    """
    padrao_contagem = argparse.SUPPRESS if suprimir else 0
    padrao = argparse.SUPPRESS if suprimir else None

    alvo.add_argument(
        "-v",
        "--verboso",
        action="count",
        default=padrao_contagem,
        help="mais detalhe no log (-vv para depuração)",
    )
    alvo.add_argument(
        "--banco",
        type=Path,
        default=padrao,
        help="caminho do arquivo DuckDB (sobrescreve FINANCAS_BANCO)",
    )
    alvo.add_argument(
        "--modo",
        choices=("offline", "online"),
        default=padrao,
        help="fonte dos dados (sobrescreve FINANCAS_MODO)",
    )


class _Analisador(argparse.ArgumentParser):
    """ArgumentParser que sai com `SAIDA_ERRO` em erro de uso.

    O argparse sai com 2 quando o comando está errado, e 2 é justamente o
    código que este projeto reserva para "alguma instituição parou de
    atualizar". Um script de `cron` que ramifica por código de saída leria um
    `--desde` digitado errado como consentimento vencido, e iria reautorizar um
    banco que não tem problema nenhum.

    Erro de uso é erro de configuração do comando, então cai em SAIDA_ERRO.
    """

    def error(self, message: str) -> "NoReturn":  # type: ignore[override]
        self.print_usage(sys.stderr)
        _avisar(f"{self.prog}: error: {message}")
        raise SystemExit(SAIDA_ERRO)


def construir_analisador() -> argparse.ArgumentParser:
    analisador = _Analisador(
        prog="financas",
        description="Pipeline de ingestão e análise de gastos via Open Finance.",
        epilog="As flags globais valem antes ou depois do subcomando: "
        "'financas --modo online ingerir' e 'financas ingerir --modo online' "
        "são equivalentes.",
    )
    _declarar_globais(analisador, suprimir=False)

    # As mesmas flags, repetidas em cada subcomando via `parents`. O argparse
    # padrão só aceita opção global ANTES do subcomando, e digitar
    # `financas ingerir --modo online` — que é a ordem natural em quase toda
    # CLI moderna — falharia com "unrecognized arguments".
    globais = argparse.ArgumentParser(add_help=False)
    _declarar_globais(globais, suprimir=True)

    # parser_class propaga o código de saída para os subcomandos: sem isto,
    # `financas ingerir --desde xx` continuaria saindo com 2.
    sub = analisador.add_subparsers(
        dest="comando", required=True, parser_class=_Analisador
    )

    ingerir_ = sub.add_parser(
        "ingerir", help="baixa da API e grava na camada raw", parents=[globais]
    )
    ingerir_.add_argument(
        "--desde",
        type=_data,
        help="data inicial (padrão: geral.data_inicial do regras.toml)",
    )
    ingerir_.add_argument(
        "--hoje", type=_data, help="data da posição gravada (padrão: hoje)"
    )
    ingerir_.set_defaults(executar=comando_ingerir)

    views_ = sub.add_parser(
        "views",
        help="recarrega cfg_* e aplica as views SQL",
        parents=[globais],
    )
    views_.add_argument("--sql", type=Path, help="diretório das views (padrão: sql/)")
    views_.set_defaults(executar=comando_views)

    frescor_ = sub.add_parser(
        "frescor",
        help="verifica se alguma instituição parou de atualizar",
        parents=[globais],
    )
    frescor_.add_argument(
        "--hoje", type=_data, help="data de referência (padrão: hoje)"
    )
    frescor_.set_defaults(executar=comando_frescor)

    publicar_ = sub.add_parser(
        "publicar",
        help="exporta as views para o frontend estático",
        parents=[globais],
    )
    publicar_.add_argument(
        "--frontend", type=Path, help="raiz do frontend (padrão: ../frontend)"
    )
    publicar_.add_argument(
        "--destino", type=Path, help="onde gravar os Parquet (padrão: <frontend>/dados)"
    )
    publicar_.add_argument(
        "--servir",
        action="store_true",
        help="sobe um servidor local depois de publicar (DuckDB-WASM exige http)",
    )
    publicar_.add_argument(
        "--porta", type=int, default=8000, help="porta do servidor (padrão: 8000)"
    )
    publicar_.set_defaults(executar=comando_publicar)

    servir_ = sub.add_parser("servir", help="abre a aplicação com edição local", parents=[globais])
    servir_.add_argument("--frontend", type=Path, help="raiz do frontend (padrão: ../frontend)")
    servir_.add_argument("--porta", type=int, default=8000, help="porta local (padrão: 8000)")
    servir_.set_defaults(executar=comando_servir)

    categorias_ = sub.add_parser(
        "categorias",
        help="gera o de-para da fase 2, ou audita o que já existe",
        parents=[globais],
    )
    categorias_.add_argument(
        "--sincronizar",
        action="store_true",
        help="busca a taxonomia em GET /categories e gera o [[mapa_categoria]]",
    )
    categorias_.add_argument(
        "--saida",
        type=Path,
        help="escreve o bloco gerado neste arquivo em vez da saída padrão",
    )
    categorias_.set_defaults(executar=comando_categorias)

    diagnostico_ = sub.add_parser(
        "diagnostico",
        help="testa a conexão com a Pluggy passo a passo (não imprime segredo)",
        parents=[globais],
    )
    diagnostico_.add_argument(
        "--item",
        metavar="UUID",
        help="valida um itemId específico em /items/{id} e mostra o estado dele",
    )
    diagnostico_.set_defaults(executar=comando_diagnostico)

    status_ = sub.add_parser(
        "status", help="resumo do que existe no banco", parents=[globais]
    )
    status_.set_defaults(executar=comando_status)

    return analisador


def _reais(valor: object) -> str:
    """Formata dinheiro no padrão brasileiro, sem depender de `locale`.

    `locale` exige que a máquina tenha o pt_BR instalado, o que não dá para
    assumir — e um relatório financeiro em português com separador americano
    confunde na leitura rápida.
    """
    americano = f"{valor:,.2f}"
    return "R$ " + americano.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


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


def _forcar_utf8() -> None:
    """Garante saída em UTF-8, inclusive redirecionada.

    No Windows, stdout redirecionado assume a codepage ANSI (cp1252). Toda
    mensagem deste projeto é em português com acento, então `financas frescor
    > log.txt` gravava um arquivo que nenhum leitor de UTF-8 abre direito — e
    um alerta ilegível é um alerta perdido, que é o modo de falha que este
    projeto combate.

    `errors="replace"` é deliberado: se um nome de estabelecimento vier com
    byte estranho, é melhor perder um caractere do que derrubar a ingestão
    inteira com UnicodeEncodeError.
    """
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar is not None:
            try:
                reconfigurar(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                # Fluxo já substituído por algo sem suporte (capture de teste,
                # pipe fechado). Não é motivo para abortar o comando.
                pass


def _configurar_log(verbosidade: int) -> None:
    _forcar_utf8()
    nivel = {0: logging.WARNING, 1: logging.INFO}.get(verbosidade, logging.DEBUG)
    logging.basicConfig(
        level=nivel, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr
    )


def main_console() -> None:  # pragma: no cover
    """Ponto de entrada do executável `financas`, declarado no pyproject.

    Existe porque `[project.scripts]` espera uma função que não devolve valor:
    quem sai com código é o `sys.exit`.
    """
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
