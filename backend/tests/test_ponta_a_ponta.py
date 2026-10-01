"""
Testes de ponta a ponta: da API até as views, numa execução só.

Os testes das etapas anteriores exercitam cada camada isoladamente. Estes fazem
o caminho inteiro — `/auth` → paginação → normalização → upsert → staging →
marts — e cobrem explicitamente os cinco requisitos da etapa (f):

    1. idempotência do upsert
    2. paginação
    3. exclusão de pagamento de fatura
    4. exclusão de transferência entre contas próprias
    5. separação de investimento

A diferença para os demais arquivos é a fonte: aqui as fixtures são servidas
**por HTTP**, através de `ClienteHttp` e `httpx.MockTransport`, com páginas
pequenas de propósito. Nenhum socket é aberto, mas o código exercitado é o
mesmo que vai falar com a Pluggy de verdade — inclusive o laço de paginação,
que o cliente offline não usa.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from financas.cli import SAIDA_DADOS_VELHOS, SAIDA_OK, main
from financas.config import Configuracao
from financas.ingestao import ingerir
from financas.persistencia import BANCO_EM_MEMORIA, Banco
from financas.pluggy import ClienteHttp, criar_cliente
from financas.views import aplicar_views

from conftest import FIXTURES_PLUGGY, RAIZ, RelogioFalso

SQL = RAIZ / "sql"
HOJE = date(2025, 9, 20)

# Página minúscula de propósito: com 27 transações espalhadas em 8 contas, isso
# força dezenas de requisições e o laço de paginação a rodar de verdade.
TAMANHO_DE_PAGINA = 2


# ---------------------------------------------------------------------------
# API falsa servindo as fixtures do repositório
# ---------------------------------------------------------------------------


class ApiPluggyFalsa:
    """Serve `tests/fixtures/pluggy/` por HTTP, com paginação real.

    O servidor decide o tamanho da página, e não o cliente — é assim que a API
    de verdade se comporta, e é o que permite verificar que o cliente não
    assume que a primeira página é tudo.
    """

    def __init__(self, diretorio: Path, tamanho_de_pagina: int = TAMANHO_DE_PAGINA) -> None:
        self._diretorio = diretorio
        self._tamanho = tamanho_de_pagina
        self.requisicoes: list[httpx.Request] = []
        self.autenticacoes = 0

    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._atender)

    def paginas_de(self, caminho: str) -> int:
        return sum(1 for r in self.requisicoes if r.url.path == caminho)

    # -- roteamento ---------------------------------------------------------

    def _atender(self, requisicao: httpx.Request) -> httpx.Response:
        self.requisicoes.append(requisicao)
        caminho = requisicao.url.path
        consulta = requisicao.url.params

        if caminho == "/auth":
            self.autenticacoes += 1
            return httpx.Response(200, json={"apiKey": "chave-de-teste"})

        if caminho == "/items":
            return self._paginar(self._ler("items.json"), consulta)

        if caminho == "/accounts":
            arquivo = f"accounts/{consulta['itemId']}.json"
            return self._paginar(self._ler(arquivo), consulta)

        if caminho == "/investments":
            arquivo = f"investments/{consulta['itemId']}.json"
            return self._paginar(self._ler(arquivo), consulta)

        if caminho == "/bills":
            arquivo = f"bills/{consulta['accountId']}.json"
            return self._paginar(self._ler(arquivo), consulta)

        if caminho == "/transactions":
            # A Pluggy aposentou a v1 do extrato. Responder 410 aqui é o que
            # impede o cliente de voltar para ela sem ninguém perceber.
            return httpx.Response(
                410,
                json={
                    "message": "This endpoint is deprecated. Use GET "
                    "/v2/transactions with cursor pagination instead.",
                    "code": 410,
                    "codeDescription": "ENDPOINT_DEPRECATED",
                },
            )

        if caminho == "/v2/transactions":
            registros = self._ler(f"transactions/{consulta['accountId']}.json")
            desde = consulta.get("dateFrom")
            if desde:
                # O recorte por data é do servidor, exatamente como na API real.
                registros = [t for t in registros if t["date"][:10] >= desde]
            return self._paginar_por_cursor(registros, consulta)

        return httpx.Response(404, json={"message": f"rota desconhecida: {caminho}"})

    def _ler(self, relativo: str) -> list[dict[str, Any]]:
        caminho = self._diretorio / relativo
        if not caminho.is_file():
            return []
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        return conteudo["results"] if isinstance(conteudo, dict) else conteudo

    def _paginar_por_cursor(
        self, registros: list[dict[str, Any]], consulta
    ) -> httpx.Response:
        """Pagina como a v2 de verdade.

        `next` é a QUERY STRING INTEIRA da próxima página, com `?` na frente —
        não um valor de cursor solto. É assim que a Pluggy responde, e a
        diferença não é cosmética: mandar o `next` dentro de `after=` devolve
        400 INVALID_CURSOR. O formato falso anterior escondia esse bug.
        """
        inicio = int(consulta.get("after", 0))
        fatia = registros[inicio : inicio + self._tamanho]
        fim = inicio + len(fatia)

        proximo = None
        if fim < len(registros):
            proximo = (
                f"?accountId={consulta['accountId']}"
                f"&dateFrom={consulta.get('dateFrom', '')}"
                f"&after={fim}"
            )
        return httpx.Response(200, json={"results": fatia, "next": proximo})

    def _paginar(self, registros: list[dict[str, Any]], consulta) -> httpx.Response:
        pagina = int(consulta.get("page", 1))
        total_paginas = max(1, -(-len(registros) // self._tamanho))
        inicio = (pagina - 1) * self._tamanho
        return httpx.Response(
            200,
            json={
                "results": registros[inicio : inicio + self._tamanho],
                "page": pagina,
                "total": len(registros),
                "totalPages": total_paginas,
            },
        )


@pytest.fixture
def api(config_online: Configuracao) -> ApiPluggyFalsa:
    return ApiPluggyFalsa(FIXTURES_PLUGGY)


@pytest.fixture
def pipeline(
    banco: Banco, config_online: Configuracao, api: ApiPluggyFalsa
) -> Banco:
    """Executa o pipeline inteiro pela API HTTP e devolve o banco pronto."""
    banco.gravar_regras(config_online.regras)
    with ClienteHttp(
        config_online, transporte=api.transporte(), dormir=lambda _s: None
    ) as cliente:
        ingerir(cliente, banco, config_online.regras, hoje=HOJE)
    aplicar_views(banco, SQL)
    return banco


def uma(banco: Banco, consulta: str):
    return banco.conexao.execute(consulta).fetchone()


def ids(banco: Banco, consulta: str) -> set[str]:
    return {linha[0] for linha in banco.conexao.execute(consulta).fetchall()}


# ---------------------------------------------------------------------------
# Requisito 2: paginação
# ---------------------------------------------------------------------------


def test_o_pipeline_atravessa_varias_paginas(pipeline: Banco, api: ApiPluggyFalsa) -> None:
    """Com páginas de 2 registros, uma conta de 7 transações exige 4 requisições.

    Se o cliente parasse na primeira página, o banco teria uma fração do dado —
    e ninguém perceberia, porque nada falharia.
    """
    assert api.paginas_de("/v2/transactions") > 8
    assert api.paginas_de("/items") == 3  # 5 itens em páginas de 2
    assert pipeline.contar("raw_transacoes") == 27


def test_nenhuma_transacao_se_perde_na_paginacao(pipeline: Banco) -> None:
    esperadas = set()
    for arquivo in (FIXTURES_PLUGGY / "transactions").glob("*.json"):
        for transacao in json.loads(arquivo.read_text(encoding="utf-8"))["results"]:
            esperadas.add(transacao["id"])

    assert ids(pipeline, "SELECT id FROM raw_transacoes") == esperadas


def test_contas_e_investimentos_tambem_paginam(pipeline: Banco) -> None:
    """Não é só transação que pagina; assumir isso perderia conta inteira."""
    assert pipeline.contar("raw_contas") == 8
    assert pipeline.contar("raw_investimentos") == 2


def test_autentica_uma_vez_para_o_pipeline_inteiro(api: ApiPluggyFalsa, pipeline: Banco) -> None:
    """Dezenas de requisições, uma `apiKey`. E ela nunca vai para o disco."""
    assert api.autenticacoes == 1
    assert len(api.requisicoes) > 20


# ---------------------------------------------------------------------------
# Requisito 1: idempotência do upsert
# ---------------------------------------------------------------------------


def test_pipeline_rodado_duas_vezes_deixa_o_banco_identico(
    pipeline: Banco, config_online: Configuracao, api: ApiPluggyFalsa, relogio: RelogioFalso
) -> None:
    antes = pipeline.conexao.execute("SELECT * FROM raw_transacoes ORDER BY id").fetchall()
    gastos_antes = uma(pipeline, "SELECT count(*), sum(valor) FROM gastos")

    relogio.avancar(hours=8)
    with ClienteHttp(
        config_online, transporte=api.transporte(), dormir=lambda _s: None
    ) as cliente:
        resumo = ingerir(cliente, pipeline, config_online.regras, hoje=HOJE)
    aplicar_views(pipeline, SQL)

    assert pipeline.conexao.execute(
        "SELECT * FROM raw_transacoes ORDER BY id"
    ).fetchall() == antes
    assert uma(pipeline, "SELECT count(*), sum(valor) FROM gastos") == gastos_antes
    assert resumo.transacoes.inalteradas == 27
    assert resumo.transacoes.houve_mudanca is False


def test_correcao_da_api_atravessa_ate_os_marts(
    pipeline: Banco, config_online: Configuracao
) -> None:
    """A Pluggy corrige transação: PENDING vira POSTED, valor de cartão muda.

    O upsert precisa propagar a correção até `gastos` sem duplicar a linha.
    """
    api_corrigida = ApiPluggyFalsa(FIXTURES_PLUGGY)
    original = api_corrigida._ler

    def com_correcao(relativo: str) -> list[dict[str, Any]]:
        registros = original(relativo)
        for registro in registros:
            if registro.get("id") == "tx-nu-b-04":  # Supermercado Big
                registro = dict(registro)
                registro["amount"] = -400.00
                registros = [registro if r["id"] == "tx-nu-b-04" else r for r in registros]
        return registros

    api_corrigida._ler = com_correcao

    with ClienteHttp(
        config_online, transporte=api_corrigida.transporte(), dormir=lambda _s: None
    ) as cliente:
        resumo = ingerir(cliente, pipeline, config_online.regras, hoje=HOJE)
    aplicar_views(pipeline, SQL)

    assert resumo.transacoes.atualizadas == 1
    assert pipeline.contar("raw_transacoes") == 27
    assert uma(pipeline, "SELECT valor FROM gastos WHERE id_transacao = 'tx-nu-b-04'") == (
        Decimal("400.00"),
    )


def test_offline_e_http_produzem_o_mesmo_banco(
    config_offline: Configuracao, config_online: Configuracao, relogio: RelogioFalso
) -> None:
    """As duas implementações de `Cliente` são intercambiáveis de verdade.

    É o que sustenta desenvolver e testar tudo sem rede: se divergissem, o modo
    offline estaria testando outro programa.
    """
    resultados = []
    for config, cliente_de in (
        (config_offline, lambda c: criar_cliente(c)),
        (
            config_online,
            lambda c: ClienteHttp(
                c, transporte=ApiPluggyFalsa(FIXTURES_PLUGGY).transporte(),
                dormir=lambda _s: None,
            ),
        ),
    ):
        with Banco.abrir(BANCO_EM_MEMORIA, agora=relogio) as banco:
            banco.criar_schema()
            banco.gravar_regras(config.regras)
            ingerir(cliente_de(config), banco, config.regras, hoje=HOJE)
            resultados.append(
                banco.conexao.execute("SELECT * FROM raw_transacoes ORDER BY id").fetchall()
            )

    assert resultados[0] == resultados[1]


# ---------------------------------------------------------------------------
# Requisito 3: exclusão de pagamento de fatura (armadilha 1)
# ---------------------------------------------------------------------------


def test_pagamento_de_fatura_sai_dos_gastos_no_fluxo_completo(pipeline: Banco) -> None:
    em_gastos = ids(pipeline, "SELECT id_transacao FROM gastos")

    assert not em_gastos & {"tx-nu-b-01", "tx-sa-b-01", "tx-in-b-02"}
    # As compras que formaram a fatura continuam contando.
    assert {"tx-nu-c-01", "tx-nu-c-02", "tx-nu-c-03"} <= em_gastos


def test_dupla_contagem_evitada_em_reais(pipeline: Banco) -> None:
    (dobrado,) = uma(
        pipeline,
        "SELECT -sum(valor_assinado) FROM stg_transacoes "
        "WHERE e_pagamento_de_fatura AND valor_assinado < 0",
    )

    assert dobrado == Decimal("2500.30")


# ---------------------------------------------------------------------------
# Requisito 4: exclusão de transferência própria (armadilha 2)
# ---------------------------------------------------------------------------


def test_transferencia_propria_sai_dos_gastos_no_fluxo_completo(pipeline: Banco) -> None:
    em_gastos = ids(pipeline, "SELECT id_transacao FROM gastos")

    # Pix por CPF, Pix por telefone e TED pelo nome do titular.
    assert not em_gastos & {"tx-nu-b-02", "tx-sa-b-02", "tx-sa-b-03"}


def test_os_dois_lados_da_transferencia_saem(pipeline: Banco) -> None:
    """Uma transferência aparece duas vezes: saída numa conta, entrada na outra.

    A entrada nem entraria em `gastos` (é crédito), mas precisa estar marcada,
    senão contamina qualquer relatório de receita.
    """
    marcadas = ids(
        pipeline, "SELECT id_transacao FROM stg_transacoes WHERE e_transferencia_propria"
    )

    assert {"tx-nu-b-02", "tx-pp-b-01"} <= marcadas  # saída do Nubank, entrada no PicPay
    assert {"tx-sa-b-02", "tx-in-b-01"} <= marcadas  # saída do Santander, entrada no Inter


# ---------------------------------------------------------------------------
# Requisito 5: separação de investimento (armadilha 3)
# ---------------------------------------------------------------------------


def test_investimento_vive_em_tabela_propria(pipeline: Banco) -> None:
    de_investimento = ids(pipeline, "SELECT id FROM raw_investimentos")
    de_transacao = ids(pipeline, "SELECT id FROM raw_transacoes")

    assert de_investimento == {"inv-rico-cdb-01", "inv-rico-tesouro-01"}
    assert not de_investimento & de_transacao


def test_aporte_nao_conta_como_gasto(pipeline: Banco) -> None:
    """`Aplicacao CDB` sai da conta corrente como débito, mas o dinheiro
    continua sendo seu."""
    assert "tx-ri-b-02" not in ids(pipeline, "SELECT id_transacao FROM gastos")


def test_investimento_soma_no_patrimonio_e_nao_nos_gastos(pipeline: Banco) -> None:
    (investido,) = uma(
        pipeline,
        "SELECT investido FROM patrimonio WHERE instituicao = 'Rico Investimentos'",
    )
    (gastos_da_rico,) = uma(
        pipeline, "SELECT coalesce(sum(valor), 0) FROM gastos WHERE instituicao = 'Rico Investimentos'"
    )

    assert investido == Decimal("7192.79")
    assert gastos_da_rico == Decimal("120.00")  # só a compra na livraria


# ---------------------------------------------------------------------------
# Invariantes: nada se perde, nada conta duas vezes
# ---------------------------------------------------------------------------


def test_todo_debito_ou_e_gasto_ou_foi_excluido_por_um_motivo(pipeline: Banco) -> None:
    """Conservação: a soma dos débitos da camada limpa tem que fechar com
    gastos + excluídos. Sobrar significa dado perdido; faltar, dado contado
    duas vezes."""
    # Tudo em `valor_assinado`: é ele que significa "saída de dinheiro" nas
    # duas convenções de sinal da API. Com o valor cru, a conservação fecharia
    # por acaso na conta corrente e quebraria no cartão.
    (total,) = uma(
        pipeline,
        "SELECT -sum(valor_assinado) FROM stg_transacoes "
        "WHERE valor_assinado < 0 AND NOT e_futura",
    )
    (em_gastos,) = uma(pipeline, "SELECT sum(valor) FROM gastos")
    (excluidos,) = uma(
        pipeline,
        "SELECT -sum(valor_assinado) FROM stg_transacoes "
        "WHERE valor_assinado < 0 AND NOT e_futura AND "
        "(e_pagamento_de_fatura OR e_transferencia_propria OR e_aplicacao)",
    )

    assert em_gastos + excluidos == total


def test_transacao_com_duas_bandeiras_e_excluida_uma_vez_so(pipeline: Banco) -> None:
    """`tx-ri-b-02` combina aplicação com nome da corretora. Marcações
    sobrepostas não podem descontar o valor duas vezes."""
    marcadas = uma(
        pipeline,
        "SELECT count(*) FROM stg_transacoes WHERE id_transacao = 'tx-ri-b-02'",
    )

    assert marcadas == (1,)


def test_nenhuma_linha_de_gasto_e_duplicada(pipeline: Banco) -> None:
    total, distintas = uma(
        pipeline, "SELECT count(*), count(DISTINCT id_transacao) FROM gastos"
    )

    assert total == distintas == 15


# ---------------------------------------------------------------------------
# Filtros configuráveis: a promessa de mudar regra sem reingerir
# ---------------------------------------------------------------------------


def test_nenhum_sql_versionado_tem_filtro_hardcoded() -> None:
    """Guarda estrutural do princípio: todo LIKE das views compara com uma
    coluna de `cfg_*`, nunca com um literal.

    Um `LIKE '%fatura%'` escrito direto no .sql passaria em todos os testes de
    comportamento e ainda assim quebraria a promessa do projeto — só apareceria
    no dia em que o Santander mudasse a redação.
    """
    for arquivo in sorted(SQL.rglob("*.sql")):
        sem_comentarios = re.sub(r"--[^\n]*", "", arquivo.read_text(encoding="utf-8"))

        assert not re.search(r"\bLIKE\s+'", sem_comentarios, re.IGNORECASE), (
            f"{arquivo.name} compara LIKE com literal em vez de coluna cfg_*"
        )
        for instituicao in ("nubank", "santander", "picpay", "inter", "rico"):
            assert instituicao not in sem_comentarios.lower(), (
                f"{arquivo.name} cita '{instituicao}' fora de comentário"
            )


def test_mudar_o_toml_muda_a_view_sem_reingerir(
    pipeline: Banco, config_online: Configuracao
) -> None:
    """O fluxo prometido no README: editar o filtro e rodar `views`.

    A camada raw não é tocada — é exatamente por isso que a regra de negócio
    mora no SQL e não na ingestão.
    """
    from dataclasses import replace

    from financas.config import PadraoDeDescricao

    antes_raw = pipeline.contar("raw_transacoes")
    antes_gastos = uma(pipeline, "SELECT count(*) FROM gastos")[0]

    # Passa a tratar posto de gasolina como se fosse ruído a excluir.
    pipeline.gravar_regras(
        replace(
            config_online.regras,
            padroes_aplicacao=config_online.regras.padroes_aplicacao
            + (PadraoDeDescricao("%", "%posto%"),),
        )
    )
    aplicar_views(pipeline, SQL)

    assert pipeline.contar("raw_transacoes") == antes_raw  # nada reingerido
    assert uma(pipeline, "SELECT count(*) FROM gastos") == (antes_gastos - 1,)
    assert "tx-sa-b-04" not in ids(pipeline, "SELECT id_transacao FROM gastos")


def test_regra_removida_volta_a_valer_na_hora(
    pipeline: Banco, config_online: Configuracao
) -> None:
    """O caminho de volta também precisa funcionar, senão calibrar filtro vira
    uma via de mão única."""
    from dataclasses import replace

    pipeline.gravar_regras(replace(config_online.regras, padroes_fatura=()))
    aplicar_views(pipeline, SQL)

    assert {"tx-nu-b-01", "tx-sa-b-01"} <= ids(
        pipeline, "SELECT id_transacao FROM gastos"
    )


# ---------------------------------------------------------------------------
# A sequência real de uso, pela CLI
# ---------------------------------------------------------------------------


def test_sequencia_ingerir_views_frescor(
    projeto: Path, capsys
) -> None:
    """Como o pipeline vai ser usado de fato, com os códigos de saída que um
    `cron` enxerga."""
    ambiente = {
        "FINANCAS_FIXTURES": str(FIXTURES_PLUGGY),
        "FINANCAS_BANCO": str(projeto / "dados" / "e2e.duckdb"),
    }

    assert main(["ingerir", "--hoje", "2025-09-20"], ambiente=ambiente, raiz=projeto) == SAIDA_OK
    assert main(["views", "--sql", str(SQL)], ambiente=ambiente, raiz=projeto) == SAIDA_OK
    # PicPay parou em agosto: o consentimento vencido precisa gritar.
    assert (
        main(["frescor", "--hoje", "2025-09-20"], ambiente=ambiente, raiz=projeto)
        == SAIDA_DADOS_VELHOS
    )

    saida = capsys.readouterr().out
    assert "27 recebidas, 27 novas" in saida
    assert "marts/01_gastos" in saida
    assert "PicPay" in saida


def test_serie_de_patrimonio_cresce_a_cada_ingestao(
    projeto: Path, capsys
) -> None:
    """Duas execuções em dias diferentes: transação não duplica, patrimônio
    ganha um ponto na série."""
    ambiente = {
        "FINANCAS_FIXTURES": str(FIXTURES_PLUGGY),
        "FINANCAS_BANCO": str(projeto / "dados" / "serie.duckdb"),
    }

    for dia in ("2025-09-20", "2025-09-21"):
        main(["ingerir", "--hoje", dia], ambiente=ambiente, raiz=projeto)
    main(["views", "--sql", str(SQL)], ambiente=ambiente, raiz=projeto)
    capsys.readouterr()

    with Banco.abrir(ambiente["FINANCAS_BANCO"]) as banco:
        assert banco.contar("raw_transacoes") == 27
        serie = banco.conexao.execute(
            "SELECT data_posicao, sum(patrimonio_liquido) FROM patrimonio GROUP BY 1 ORDER BY 1"
        ).fetchall()

    assert [linha[0] for linha in serie] == [date(2025, 9, 20), date(2025, 9, 21)]
    assert serie[0][1] == serie[1][1]
