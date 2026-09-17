"""
Testes do cliente da API.

`ClienteHttp` é exercitado com `httpx.MockTransport`: as requisições são
construídas e roteadas de verdade, mas nenhum socket é aberto. Isso permite
testar paginação, retry e tradução de erro sem rede e sem credencial.

O foco está nas armadilhas 6 (token de ~2h), 7 (paginação obrigatória) e 4
(consentimento vencido).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest

from financas.config import Configuracao
from financas.pluggy import EndpointAposentado, criar_cliente
from financas.pluggy.cliente import (
    MAXIMO_DE_PAGINAS,
    ClienteHttp,
    ConsentimentoExpirado,
    ErroDaApi,
    ErroDeAutenticacao,
    ErroDeRede,
    ErroPluggy,
)
from financas.pluggy.fixtures import ClienteFixtures, ErroDeFixture


# ---------------------------------------------------------------------------
# Andaime
# ---------------------------------------------------------------------------


class ApiFalsa:
    """Servidor de mentira que registra o que recebeu.

    Cada teste monta as respostas que quer e depois inspeciona `chamadas` para
    conferir se o cliente pediu o que devia.
    """

    def __init__(self) -> None:
        self.chamadas: list[httpx.Request] = []
        self.respostas: dict[str, list[httpx.Response]] = {}
        self.autenticacoes = 0

    def responder(self, caminho: str, *respostas: httpx.Response) -> None:
        self.respostas.setdefault(caminho, []).extend(respostas)

    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._atender)

    def _atender(self, requisicao: httpx.Request) -> httpx.Response:
        self.chamadas.append(requisicao)
        caminho = requisicao.url.path

        if caminho == "/auth" and caminho not in self.respostas:
            self.autenticacoes += 1
            return httpx.Response(200, json={"apiKey": f"chave-{self.autenticacoes}"})

        fila = self.respostas.get(caminho)
        if not fila:
            return httpx.Response(404, json={"message": f"sem resposta para {caminho}"})
        if caminho == "/auth":
            self.autenticacoes += 1
        return fila.pop(0) if len(fila) > 1 else fila[0]

    def chamadas_em(self, caminho: str) -> list[httpx.Request]:
        return [c for c in self.chamadas if c.url.path == caminho]


def pagina(resultados: list[dict[str, Any]], numero: int, total: int) -> httpx.Response:
    """Uma página de listagem no formato que a Pluggy devolve."""
    return httpx.Response(
        200,
        json={
            "results": resultados,
            "page": numero,
            "total": len(resultados) * total,
            "totalPages": total,
        },
    )


def cursor(resultados: list[dict[str, Any]], proximo: str | None) -> httpx.Response:
    """Uma página de `GET /v2/transactions`, que pagina por cursor.

    `proximo` é a QUERY STRING da próxima página, com `?` na frente, como a
    Pluggy responde de verdade — e não um valor de cursor solto. O cliente tem
    que concatená-la ao caminho sem interpretar. A v1 (`page`/`totalPages`) foi
    aposentada com HTTP 410.
    """
    return httpx.Response(200, json={"results": resultados, "next": proximo})


@pytest.fixture
def api() -> ApiFalsa:
    return ApiFalsa()


@pytest.fixture
def cliente(config_online: Configuracao, api: ApiFalsa) -> ClienteHttp:
    """Cliente HTTP com transporte falso e sem espera real entre tentativas."""
    with ClienteHttp(
        config_online, transporte=api.transporte(), dormir=lambda _s: None
    ) as instancia:
        yield instancia


# ---------------------------------------------------------------------------
# Autenticação (armadilha 6)
# ---------------------------------------------------------------------------


def test_autentica_antes_da_primeira_requisicao(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder("/items", pagina([{"id": "item-1"}], 1, 1))

    cliente.listar_itens()

    assert api.autenticacoes == 1
    assert api.chamadas[0].url.path == "/auth"


def test_autentica_uma_vez_so_para_varias_requisicoes(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    api.responder("/items", pagina([{"id": "item-1"}], 1, 1))
    api.responder("/accounts", pagina([{"id": "conta-1"}], 1, 1))

    cliente.listar_itens()
    cliente.listar_contas("item-1")

    assert api.autenticacoes == 1


def test_api_key_vai_no_cabecalho(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder("/items", pagina([], 1, 1))

    cliente.listar_itens()

    assert api.chamadas_em("/items")[0].headers["X-API-KEY"] == "chave-1"


def test_credencial_recusada_diz_onde_conferir(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder("/auth", httpx.Response(403, json={"message": "invalid client"}))

    with pytest.raises(ErroDeAutenticacao) as erro:
        cliente.listar_itens()

    assert "dashboard.pluggy.ai" in str(erro.value)
    assert "PLUGGY_CLIENT_SECRET" in str(erro.value)


def test_auth_sem_api_key_no_corpo_e_erro(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder("/auth", httpx.Response(200, json={"mensagem": "ok"}))

    with pytest.raises(ErroDeAutenticacao):
        cliente.listar_itens()


def test_chave_expirada_no_meio_da_execucao_reautentica(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    """Armadilha 6: numa ingestão longa a apiKey de ~2h pode vencer no meio."""
    api.responder(
        "/items",
        httpx.Response(401, json={"message": "expired"}),
        pagina([{"id": "item-1"}], 1, 1),
    )

    itens = cliente.listar_itens()

    assert itens == [{"id": "item-1"}]
    assert api.autenticacoes == 2
    assert api.chamadas_em("/items")[-1].headers["X-API-KEY"] == "chave-2"


def test_401_persistente_nao_vira_laco_infinito(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder("/items", httpx.Response(401, json={"message": "expired"}))

    with pytest.raises(ErroDaApi) as erro:
        cliente.listar_itens()

    assert erro.value.status == 401
    assert api.autenticacoes == 2  # a inicial e exatamente uma renovação


def test_token_nunca_e_escrito_em_disco(
    cliente: ClienteHttp, api: ApiFalsa, projeto: Path
) -> None:
    api.responder("/items", pagina([], 1, 1))

    cliente.listar_itens()

    escritos = [c for c in projeto.rglob("*") if c.is_file()]
    assert not any("chave-1" in c.read_text(encoding="utf-8", errors="ignore") for c in escritos)


# ---------------------------------------------------------------------------
# Paginação (armadilha 7)
# ---------------------------------------------------------------------------


def test_percorre_todas_as_paginas(cliente: ClienteHttp, api: ApiFalsa) -> None:
    """Extrato: o cliente segue o cursor até `next` vir nulo."""
    api.responder(
        "/v2/transactions",
        cursor([{"id": "tx-1"}, {"id": "tx-2"}], "?accountId=conta-1&after=c2"),
        cursor([{"id": "tx-3"}, {"id": "tx-4"}], "?accountId=conta-1&after=c3"),
        cursor([{"id": "tx-5"}], None),
    )

    transacoes = list(cliente.listar_transacoes("conta-1", date(2025, 8, 1)))

    assert [t["id"] for t in transacoes] == ["tx-1", "tx-2", "tx-3", "tx-4", "tx-5"]
    assert len(api.chamadas_em("/v2/transactions")) == 3


def test_cursor_volta_para_a_api_como_veio(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    """O cursor é opaco: o cliente devolve o que recebeu, sem interpretar."""
    api.responder(
        "/v2/transactions",
        cursor([{"id": "tx-1"}], "?accountId=conta-1&after=eyJvZmZzZXQiOjF9"),
        cursor([{"id": "tx-2"}], None),
    )

    list(cliente.listar_transacoes("conta-1", date(2025, 8, 1)))

    chamadas = api.chamadas_em("/v2/transactions")
    assert "after" not in chamadas[0].url.params
    # O `next` volta INTEIRO como query string, não embrulhado em `after=`.
    # Mandar `after=?accountId=...` devolve 400 INVALID_CURSOR na API real.
    assert chamadas[1].url.params["after"] == "eyJvZmZzZXQiOjF9"
    assert chamadas[1].url.params["accountId"] == "conta-1"


def test_cursor_repetido_nao_vira_laco_infinito(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    """API que devolve sempre o mesmo cursor faria o cliente rodar para sempre.

    Falhar alto é melhor que uma ingestão que nunca termina: a segunda parece
    lentidão e ninguém investiga.
    """
    api.responder(
        "/v2/transactions",
        cursor([{"id": "tx-1"}], "?accountId=conta-1&after=mesmo"),
        cursor([{"id": "tx-2"}], "?accountId=conta-1&after=mesmo"),
    )

    with pytest.raises(ErroPluggy, match="repetiu o cursor"):
        list(cliente.listar_transacoes("conta-1", date(2025, 8, 1)))


def test_v1_do_extrato_nao_e_mais_usada(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    """A Pluggy aposentou `GET /transactions` com HTTP 410.

    Se alguém reverter o cliente para a v1, este teste acusa — a rota v1 nem
    é chamada, então a API falsa não registra nada nela.
    """
    api.responder("/v2/transactions", cursor([{"id": "tx-1"}], None))

    list(cliente.listar_transacoes("conta-1", date(2025, 8, 1)))

    assert api.chamadas_em("/transactions") == []
    assert len(api.chamadas_em("/v2/transactions")) == 1


def test_410_vira_erro_que_diz_para_atualizar_o_cliente(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    """410 não é credencial nem consentimento: é endereço que sumiu."""
    api.responder(
        "/v2/transactions",
        httpx.Response(
            410,
            json={"message": "deprecated", "codeDescription": "ENDPOINT_DEPRECATED"},
        ),
    )

    with pytest.raises(EndpointAposentado, match="aposentou"):
        list(cliente.listar_transacoes("conta-1", date(2025, 8, 1)))


def test_numero_da_pagina_avanca(cliente: ClienteHttp, api: ApiFalsa) -> None:
    """Paginação por página continua valendo para /items e /accounts."""
    api.responder(
        "/items",
        pagina([{"id": "item-1"}], 1, 2),
        pagina([{"id": "item-2"}], 2, 2),
    )

    cliente.listar_itens()

    paginas = [c.url.params["page"] for c in api.chamadas_em("/items")]
    assert paginas == ["1", "2"]


def test_para_em_pagina_vazia_mesmo_com_totalpages_mentindo(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    """`totalPages` inconsistente não pode virar laço infinito."""
    api.responder(
        "/items",
        pagina([{"id": "item-1"}], 1, 99),
        pagina([], 2, 99),
    )

    itens = cliente.listar_itens()

    assert [i["id"] for i in itens] == ["item-1"]
    assert len(api.chamadas_em("/items")) == 2


def test_pagina_sem_totalpages_continua_ate_esvaziar(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    api.responder(
        "/items",
        httpx.Response(200, json={"results": [{"id": "item-1"}]}),
        httpx.Response(200, json={"results": []}),
    )

    assert [i["id"] for i in cliente.listar_itens()] == ["item-1"]


def test_totalpages_como_texto_e_aceito(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder(
        "/items",
        httpx.Response(200, json={"results": [{"id": "item-1"}], "totalPages": "1"}),
    )

    assert len(cliente.listar_itens()) == 1
    assert len(api.chamadas_em("/items")) == 1


def test_itens_vem_da_configuracao_um_por_um(
    config_online: Configuracao, api: ApiFalsa
) -> None:
    """`GET /items` (listar) é bloqueado pela Pluggy por design.

    A FAQ diz que não está disponível "for security reasons, so that no data
    can leak across clients". Por isso os ids vêm do regras.toml e cada um é
    buscado em `/items/{id}` — a rota de listagem não deve nem ser tocada.
    """
    from dataclasses import replace

    from financas.config import ItemConfigurado

    regras = replace(
        config_online.regras,
        itens=(
            ItemConfigurado("11111111-1111-4111-8111-111111111111", "Nubank"),
            ItemConfigurado("22222222-2222-4222-8222-222222222222", "Inter"),
        ),
    )
    config = replace(config_online, regras=regras)

    api.responder(
        "/items/11111111-1111-4111-8111-111111111111",
        httpx.Response(200, json={"id": "11111111-1111-4111-8111-111111111111"}),
    )
    api.responder(
        "/items/22222222-2222-4222-8222-222222222222",
        httpx.Response(200, json={"id": "22222222-2222-4222-8222-222222222222"}),
    )

    with ClienteHttp(
        config, transporte=api.transporte(), dormir=lambda _s: None
    ) as cliente:
        itens = cliente.listar_itens()

    assert [i["id"] for i in itens] == [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    # A rota de listagem não foi usada.
    assert api.chamadas_em("/items") == []


def test_item_com_404_volta_como_not_found_em_vez_de_explodir(
    config_online: Configuracao, api: ApiFalsa
) -> None:
    """Um id morto não pode derrubar as outras instituições.

    Reautorizar gera um itemId novo (armadilha 8), então 404 é rotina. Ele
    volta como item de status NOT_FOUND, carregando o rótulo do TOML para o
    relatório poder dizer QUAL instituição caiu — sem connector não há nome.
    """
    from dataclasses import replace

    from financas.config import ItemConfigurado

    regras = replace(
        config_online.regras,
        itens=(ItemConfigurado("33333333-3333-4333-8333-333333333333", "PicPay"),),
    )
    config = replace(config_online, regras=regras)

    api.responder(
        "/items/33333333-3333-4333-8333-333333333333",
        httpx.Response(404, json={"message": "item not found", "code": 404}),
    )

    with ClienteHttp(
        config, transporte=api.transporte(), dormir=lambda _s: None
    ) as cliente:
        itens = cliente.listar_itens()

    assert len(itens) == 1
    assert itens[0]["status"] == "NOT_FOUND"
    assert itens[0]["connector"]["name"] == "PicPay"


def test_paginacao_vale_para_itens_e_contas_tambem(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    """Não é só transação que pagina — assumir isso perde conta e item."""
    api.responder(
        "/items",
        pagina([{"id": "item-1"}], 1, 2),
        pagina([{"id": "item-2"}], 2, 2),
    )
    api.responder(
        "/accounts",
        pagina([{"id": "conta-1"}], 1, 2),
        pagina([{"id": "conta-2"}], 2, 2),
    )

    assert len(cliente.listar_itens()) == 2
    assert len(cliente.listar_contas("item-1")) == 2


def test_recorte_de_data_vai_na_query(cliente: ClienteHttp, api: ApiFalsa) -> None:
    """Armadilha 9: não adianta pedir histórico anterior a agosto de 2025."""
    api.responder("/v2/transactions", cursor([], None))

    list(cliente.listar_transacoes("conta-1", date(2025, 8, 1)))

    consulta = api.chamadas_em("/v2/transactions")[0].url.params
    # Na v2 o parâmetro chama `dateFrom`; a v2 recusa `from` com HTTP 400
    # ("property from should not exist"), então o nome não é detalhe.
    assert consulta["dateFrom"] == "2025-08-01"
    assert consulta["accountId"] == "conta-1"


def test_corpo_sem_results_e_erro_explicito(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder("/items", httpx.Response(200, json={"mensagem": "sem results"}))

    with pytest.raises(ErroPluggy, match="results"):
        cliente.listar_itens()


def test_trava_de_paginas_existe() -> None:
    """A trava é a última linha de defesa contra laço infinito."""
    assert MAXIMO_DE_PAGINAS > 0


# ---------------------------------------------------------------------------
# Erros (armadilha 4)
# ---------------------------------------------------------------------------


def test_403_vira_consentimento_expirado_com_instrucao(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    api.responder("/accounts", httpx.Response(403, json={"message": "forbidden"}))

    with pytest.raises(ConsentimentoExpirado) as erro:
        cliente.listar_contas("item-1")

    assert "meu.pluggy.ai" in str(erro.value)
    assert "itemId novo" in str(erro.value)


def test_404_vira_erro_da_api_com_status(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder("/accounts", httpx.Response(404, json={"message": "nao existe"}))

    with pytest.raises(ErroDaApi) as erro:
        cliente.listar_contas("item-inexistente")

    assert erro.value.status == 404
    assert "/accounts" in str(erro.value)


def test_resposta_que_nao_e_json_nao_estoura_feio(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    api.responder("/items", httpx.Response(200, text="<html>manutenção</html>"))

    with pytest.raises(ErroPluggy, match="não é JSON"):
        cliente.listar_itens()


# ---------------------------------------------------------------------------
# Retry
# ---------------------------------------------------------------------------


def test_429_e_retentado(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder(
        "/items",
        httpx.Response(429, json={"message": "slow down"}),
        pagina([{"id": "item-1"}], 1, 1),
    )

    assert cliente.listar_itens() == [{"id": "item-1"}]
    assert len(api.chamadas_em("/items")) == 2


def test_500_e_retentado(cliente: ClienteHttp, api: ApiFalsa) -> None:
    api.responder(
        "/items",
        httpx.Response(500, json={"message": "boom"}),
        pagina([{"id": "item-1"}], 1, 1),
    )

    assert cliente.listar_itens() == [{"id": "item-1"}]


def test_400_nao_e_retentado(cliente: ClienteHttp, api: ApiFalsa) -> None:
    """Requisição malformada não melhora sozinha; insistir só gasta tempo."""
    api.responder("/items", httpx.Response(400, json={"message": "invalid"}))

    with pytest.raises(ErroDaApi):
        cliente.listar_itens()

    assert len(api.chamadas_em("/items")) == 1


def test_erro_persistente_desiste_apos_as_tentativas(
    cliente: ClienteHttp, api: ApiFalsa
) -> None:
    api.responder("/items", httpx.Response(503, json={"message": "indisponivel"}))

    with pytest.raises(ErroDaApi) as erro:
        cliente.listar_itens()

    assert erro.value.status == 503
    assert len(api.chamadas_em("/items")) == 3  # FINANCAS_TENTATIVAS=3


def test_retry_after_e_respeitado(config_online: Configuracao, api: ApiFalsa) -> None:
    esperas: list[float] = []
    api.responder(
        "/items",
        httpx.Response(429, headers={"Retry-After": "7"}, json={}),
        pagina([{"id": "item-1"}], 1, 1),
    )

    with ClienteHttp(
        config_online, transporte=api.transporte(), dormir=esperas.append
    ) as cliente:
        cliente.listar_itens()

    assert esperas == [7.0]


def test_backoff_cresce_entre_tentativas(config_online: Configuracao, api: ApiFalsa) -> None:
    esperas: list[float] = []
    api.responder("/items", httpx.Response(503, json={}))

    with ClienteHttp(
        config_online, transporte=api.transporte(), dormir=esperas.append
    ) as cliente:
        with pytest.raises(ErroDaApi):
            cliente.listar_itens()

    assert esperas == [1.0, 2.0]


def test_falha_de_rede_vira_erro_de_rede(config_online: Configuracao) -> None:
    def cair(_requisicao: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sem rota para o host")

    with ClienteHttp(
        config_online, transporte=httpx.MockTransport(cair), dormir=lambda _s: None
    ) as cliente:
        with pytest.raises(ErroDeRede, match="3 tentativas"):
            cliente.listar_itens()


# ---------------------------------------------------------------------------
# Cliente offline
# ---------------------------------------------------------------------------


def test_fixtures_leem_os_cinco_itens(config_offline: Configuracao) -> None:
    itens = criar_cliente(config_offline).listar_itens()

    nomes = sorted(item["connector"]["name"] for item in itens)
    assert nomes == ["Inter", "Nubank", "PicPay", "Rico Investimentos", "Santander"]


def test_fixtures_trazem_exatamente_tres_cartoes(config_offline: Configuracao) -> None:
    """O CLAUDE.md fala em 3 cartões; a fixture precisa refletir isso."""
    cliente = criar_cliente(config_offline)

    cartoes = [
        conta
        for item in cliente.listar_itens()
        for conta in cliente.listar_contas(item["id"])
        if conta["type"] == "CREDIT"
    ]

    assert len(cartoes) == 3


def test_fixtures_aplicam_o_recorte_de_data(config_offline: Configuracao) -> None:
    cliente = criar_cliente(config_offline)

    todas = list(cliente.listar_transacoes("conta-nubank-bank", date(2025, 8, 1)))
    de_setembro = list(cliente.listar_transacoes("conta-nubank-bank", date(2025, 9, 1)))

    assert len(todas) == 7
    assert len(de_setembro) == 4
    assert "tx-nu-b-02" not in {t["id"] for t in de_setembro}  # é de agosto


def test_fixture_ausente_e_lista_vazia_e_nao_erro(config_offline: Configuracao) -> None:
    """Conta sem extrato e item sem investimento são respostas legítimas."""
    cliente = criar_cliente(config_offline)

    assert cliente.listar_investimentos("item-nubank") == []
    assert list(cliente.listar_transacoes("conta-que-nao-existe", date(2025, 8, 1))) == []


def test_items_json_ausente_e_erro_de_configuracao(tmp_path: Path) -> None:
    with pytest.raises(ErroDeFixture, match="FINANCAS_FIXTURES"):
        ClienteFixtures(tmp_path).listar_itens()


def test_fixture_aceita_lista_pura_sem_envelope(tmp_path: Path) -> None:
    (tmp_path / "items.json").write_text('[{"id": "item-1"}]', encoding="utf-8")

    assert ClienteFixtures(tmp_path).listar_itens() == [{"id": "item-1"}]


def test_fixture_com_json_quebrado_diz_qual_arquivo(tmp_path: Path) -> None:
    (tmp_path / "items.json").write_text("{quebrado", encoding="utf-8")

    with pytest.raises(ErroDeFixture, match="JSON inválido"):
        ClienteFixtures(tmp_path).listar_itens()


def test_investimentos_da_rico_estao_separados(config_offline: Configuracao) -> None:
    """Armadilha 3: aporte não é despesa e não pode encostar em transação."""
    cliente = criar_cliente(config_offline)

    investimentos = cliente.listar_investimentos("item-rico")
    ids_de_transacao = {
        t["id"]
        for conta in ("conta-rico-bank", "conta-rico-credit")
        for t in cliente.listar_transacoes(conta, date(2025, 8, 1))
    }

    assert len(investimentos) == 2
    assert not {i["id"] for i in investimentos} & ids_de_transacao


# ---------------------------------------------------------------------------
# Fábrica e integridade das fixtures
# ---------------------------------------------------------------------------


def test_fabrica_escolhe_o_cliente_pelo_modo(
    config_offline: Configuracao, config_online: Configuracao
) -> None:
    assert isinstance(criar_cliente(config_offline), ClienteFixtures)

    cliente = criar_cliente(config_online, transporte=httpx.MockTransport(lambda _r: httpx.Response(200, json={})))
    assert isinstance(cliente, ClienteHttp)
    cliente.fechar()


def test_toda_conta_das_fixtures_aponta_para_um_item_existente(
    config_offline: Configuracao,
) -> None:
    cliente = criar_cliente(config_offline)
    ids_de_item = {item["id"] for item in cliente.listar_itens()}

    for id_item in ids_de_item:
        for conta in cliente.listar_contas(id_item):
            assert conta["itemId"] in ids_de_item


def test_toda_transacao_das_fixtures_aponta_para_a_propria_conta(
    config_offline: Configuracao,
) -> None:
    cliente = criar_cliente(config_offline)

    for item in cliente.listar_itens():
        for conta in cliente.listar_contas(item["id"]):
            for transacao in cliente.listar_transacoes(conta["id"], date(2025, 1, 1)):
                assert transacao["accountId"] == conta["id"]


def test_ids_de_transacao_das_fixtures_sao_unicos(config_offline: Configuracao) -> None:
    """A chave natural do upsert é o id da transação; fixture com id repetido
    mascararia um bug de idempotência na etapa seguinte."""
    cliente = criar_cliente(config_offline)

    ids = [
        transacao["id"]
        for item in cliente.listar_itens()
        for conta in cliente.listar_contas(item["id"])
        for transacao in cliente.listar_transacoes(conta["id"], date(2025, 1, 1))
    ]

    assert len(ids) == len(set(ids))


def test_fixtures_nao_contem_dado_pessoal_real() -> None:
    """Guarda-corpo: fixture é versionada, então não pode ter dado de verdade."""
    proibidos = ("15357432635", "153.574.326-35", "31989791159", "matheusfps27")
    diretorio = Path(__file__).resolve().parent / "fixtures" / "pluggy"

    for arquivo in diretorio.rglob("*.json"):
        conteudo = arquivo.read_text(encoding="utf-8")
        json.loads(conteudo)  # de quebra, garante que todo JSON é válido
        for proibido in proibidos:
            assert proibido not in conteudo, f"{arquivo.name} contém dado real"
