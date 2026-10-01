"""
Cliente HTTP da API da Pluggy.

Responsabilidade única: falar com a API e devolver o JSON como veio. Nenhuma
regra de negócio, nenhuma normalização — quem transforma é a camada de cima.

Três coisas que este módulo garante, porque são armadilhas conhecidas do
domínio:

- **Autentica a cada execução e nunca persiste o token.** A `apiKey` vive ~2h.
  Guardá-la em disco só troca um problema barato (autenticar de novo) por um
  caro (falhar no meio da ingestão).
- **Sempre pagina.** Todo endpoint de listagem é percorrido até o fim. Assumir
  que a primeira página é tudo perde histórico em silêncio, que é o pior modo
  de falha possível aqui.
- **Distingue os erros.** Credencial errada, consentimento caído e API fora do ar
  exigem ações diferentes de quem está lendo o log.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any, Protocol

import httpx

from financas.config import Configuracao

registrador = logging.getLogger(__name__)

# A Pluggy aceita até 500 por página. Menos páginas, menos chance de o
# consentimento vencer no meio de uma ingestão longa.
TAMANHO_DE_PAGINA = 500

# Trava contra paginação infinita se a API devolver `totalPages` inconsistente,
# ou um cursor que nunca muda.
MAXIMO_DE_PAGINAS = 2000

# Extrato mudou de endereço: `GET /transactions` responde HTTP 410
# ENDPOINT_DEPRECATED e manda usar a v2, que pagina por cursor em vez de por
# número de página. Os demais endpoints (`/items`, `/accounts`, `/investments`,
# `/categories`) continuam na v1 com paginação por página — por isso o cliente
# tem as duas formas de paginar, e não uma só.
CAMINHO_TRANSACOES = "/v2/transactions"

# A v2 recusa qualquer parâmetro fora da lista dela ("property X should not
# exist"), então o recorte de data mudou de nome: `from` virou `dateFrom`, e
# `page`/`pageSize` deixaram de existir.
PARAMETRO_DATA_INICIAL = "dateFrom"

# Status que valem uma nova tentativa: throttling e falha do lado deles.
STATUS_RETENTAVEIS = frozenset({408, 429, 500, 502, 503, 504})

ESPERA_MAXIMA_SEGUNDOS = 30.0


# ---------------------------------------------------------------------------
# Erros
# ---------------------------------------------------------------------------


class ErroPluggy(Exception):
    """Base de todos os erros deste módulo."""


class ErroDeAutenticacao(ErroPluggy):
    """`POST /auth` recusou as credenciais."""


class ConsentimentoExpirado(ErroPluggy):
    """A API recusou o acesso aos dados de um item.

    Quase sempre significa que a autorização de Open Finance venceu e precisa
    ser renovada no `meu.pluggy.ai`. É a armadilha 4 se manifestando de forma
    barulhenta — o caso silencioso, em que a API responde 200 com dados velhos,
    é problema do comando `frescor`.
    """


class ErroDaApi(ErroPluggy):
    """Resposta HTTP de erro que não se encaixa nos casos acima."""

    def __init__(self, status: int, metodo: str, caminho: str, corpo: str) -> None:
        self.status = status
        self.metodo = metodo
        self.caminho = caminho
        self.corpo = corpo
        super().__init__(f"{metodo} {caminho} devolveu HTTP {status}: {corpo[:400]}")


class ErroDeRede(ErroPluggy):
    """A requisição não chegou a ter resposta, mesmo depois das tentativas."""


class EndpointAposentado(ErroPluggy):
    """A API respondeu 410: o endereço que o cliente usa não existe mais.

    Vale uma exceção própria porque a ação é diferente de todas as outras: não
    adianta tentar de novo, renovar consentimento nem conferir credencial — é o
    código deste projeto que precisa mudar. Já aconteceu uma vez, quando
    `GET /transactions` virou `GET /v2/transactions`.
    """


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------


class Cliente(Protocol):
    """Contrato que `ClienteHttp` e `ClienteFixtures` cumprem.

    O resto do pipeline depende só disto, e é por isso que dá para desenvolver
    e testar tudo sem rede.
    """

    def listar_itens(self) -> list[dict[str, Any]]:
        """Conexões autorizadas."""
        ...

    def listar_contas(self, id_item: str) -> list[dict[str, Any]]:
        """Contas de um item, de qualquer tipo (`BANK` ou `CREDIT`)."""
        ...

    def listar_faturas(self, id_conta: str) -> list[dict[str, Any]]:
        """Faturas oficiais do cartão, percorrendo todas as páginas."""
        ...

    def listar_transacoes(
        self, id_conta: str, desde: date
    ) -> Iterator[dict[str, Any]]:
        """Extrato de uma conta, já percorrendo todas as páginas."""
        ...

    def listar_investimentos(self, id_item: str) -> list[dict[str, Any]]:
        """Posição de investimentos de um item."""
        ...

    def listar_categorias(self) -> list[dict[str, Any]]:
        """Taxonomia de categorias da Pluggy.

        Diferente dos outros, este endpoint não devolve dado seu: é uma lista de
        referência, igual para todo mundo. Serve para gerar o de-para da fase 2
        com os ids reais, em vez de adivinhá-los.
        """
        ...

    # O ciclo de vida faz parte do contrato, e não é detalhe do cliente HTTP:
    # quem chama não sabe qual implementação recebeu, então precisa poder
    # fechar as duas do mesmo jeito. Sem isto, a CLI abria um `httpx.Client`
    # por execução e nunca o fechava.

    def fechar(self) -> None:
        """Libera os recursos do cliente. Sem efeito no cliente de fixtures."""
        ...

    def __enter__(self) -> "Cliente":
        ...

    def __exit__(self, *excecao: object) -> None:
        ...


# ---------------------------------------------------------------------------
# Implementação HTTP
# ---------------------------------------------------------------------------


class ClienteHttp:
    """Cliente da API real.

    Args:
        config: credenciais, host, timeout e número de tentativas.
        transporte: substitui o transporte do httpx. Existe para os testes
            usarem `httpx.MockTransport` — nenhum teste deste projeto abre
            socket.
        dormir: substitui `time.sleep`, para os testes não esperarem de verdade
            o backoff.
    """

    def __init__(
        self,
        config: Configuracao,
        *,
        transporte: httpx.BaseTransport | None = None,
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._dormir = dormir
        self._api_key: str | None = None
        self._http = httpx.Client(
            base_url=config.url_api,
            timeout=config.timeout_http,
            transport=transporte,
            headers={"User-Agent": "where-is-the-money/0.1"},
        )

    # -- ciclo de vida ------------------------------------------------------

    def __enter__(self) -> ClienteHttp:
        return self

    def __exit__(self, *_excecao: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        self._http.close()

    # -- autenticação -------------------------------------------------------

    def autenticar(self) -> str:
        """Troca client_id/secret por uma `apiKey`.

        Chamado sob demanda na primeira requisição e de novo se a chave expirar
        no meio da execução. O valor fica só em memória, nunca em disco.
        """
        registrador.debug("autenticando em %s", self._config.url_api)
        corpo = self._requisitar(
            "POST",
            "/auth",
            json={
                "clientId": self._config.client_id,
                "clientSecret": self._config.client_secret,
            },
            autenticado=False,
        )
        chave = corpo.get("apiKey")
        if not isinstance(chave, str) or not chave:
            raise ErroDeAutenticacao(
                "POST /auth respondeu sem 'apiKey'. Resposta: " + repr(corpo)[:200]
            )
        self._api_key = chave
        return chave

    def _garantir_api_key(self) -> str:
        if self._api_key is None:
            self.autenticar()
        assert self._api_key is not None  # garantido por autenticar()
        return self._api_key

    # -- endpoints ----------------------------------------------------------

    def listar_itens(self) -> list[dict[str, Any]]:
        """Conexões autorizadas, uma requisição por `itemId` configurado.

        `GET /items` (listar) é bloqueado pela Pluggy por design: a FAQ diz que
        listar items "is not available for security reasons, so that no data
        can leak across clients". Não é permissão a pedir — é assim para todo
        cliente. Por isso os ids vêm de `[[item]]` no regras.toml e cada um é
        buscado em `/items/{id}`.

        Sem `[[item]]` configurado, cai na listagem. Não é por otimismo: é para
        a mensagem de erro vir da API, e não deste método, se algum dia a
        Pluggy liberar o recurso ou alguém apontar o cliente para um mock.

        Um id que não existe mais NÃO derruba a execução. Ele volta como um
        item de status `NOT_FOUND`, e a ingestão trata isso como instituição
        que falhou — do mesmo jeito que trataria um consentimento vencido.
        Reautorizar gera itemId novo (armadilha 8), então id morto é rotina, e
        rotina não pode abortar as outras instituições.
        """
        configurados = self._config.regras.itens
        if not configurados:
            return list(self._paginar("/items"))

        itens: list[dict[str, Any]] = []
        for configurado in configurados:
            try:
                itens.append(self._requisitar("GET", f"/items/{configurado.id}"))
            except ErroDaApi as erro:
                if erro.status != 404:
                    raise
                registrador.error(
                    "itemId %s não existe mais (404). Reautorizar gera um id "
                    "novo: pegue o atual em dashboard.pluggy.ai e troque no "
                    "regras.toml.",
                    configurado.id,
                )
                itens.append(
                    {
                        "id": configurado.id,
                        "status": "NOT_FOUND",
                        "statusDetail": "o id não existe nesta aplicação",
                        # Sem connector não há nome, então o rótulo do TOML é o
                        # que sobra para o relatório dizer QUAL instituição caiu.
                        "connector": {"name": configurado.rotulo or configurado.id},
                    }
                )
        return itens

    def listar_contas(self, id_item: str) -> list[dict[str, Any]]:
        return list(self._paginar("/accounts", {"itemId": id_item}))

    def listar_faturas(self, id_conta: str) -> list[dict[str, Any]]:
        return list(self._paginar("/bills", {"accountId": id_conta}))

    def listar_transacoes(
        self, id_conta: str, desde: date
    ) -> Iterator[dict[str, Any]]:
        """Extrato de uma conta, pela v2 e por cursor.

        A v1 (`GET /transactions`) responde 410 desde que a Pluggy a aposentou.
        Como ela devolvia 410 para QUALQUER chamada, a ingestão inteira falhava
        conta por conta — barulhento, ao menos, e não silencioso.
        """
        return self._paginar_por_cursor(
            CAMINHO_TRANSACOES,
            {"accountId": id_conta, PARAMETRO_DATA_INICIAL: desde.isoformat()},
        )

    def listar_investimentos(self, id_item: str) -> list[dict[str, Any]]:
        return list(self._paginar("/investments", {"itemId": id_item}))

    def listar_categorias(self) -> list[dict[str, Any]]:
        """`GET /categories`: a taxonomia inteira, sem paginação.

        Este endpoint foge do padrão dos outros: devolve um array puro, e não o
        envelope `{"results": [...]}`. Aceitar as duas formas evita depender de
        um detalhe que a documentação não promete manter.
        """
        corpo = self._requisitar("GET", "/categories", exigir_objeto=False)

        if isinstance(corpo, dict):
            corpo = corpo.get("results", [])
        if not isinstance(corpo, list):
            raise ErroPluggy(
                f"GET /categories devolveu {type(corpo).__name__}, "
                f"esperava uma lista: {repr(corpo)[:200]}"
            )
        return [item for item in corpo if isinstance(item, dict)]

    # -- paginação ----------------------------------------------------------

    def _paginar(
        self, caminho: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Percorre um endpoint de listagem até a última página.

        A parada é por `totalPages` quando a API informa, e por página vazia
        quando não informa. As duas condições valem juntas: se `totalPages`
        disser 10 mas a página 3 vier vazia, para na 3 — confiar cegamente no
        contador já rendeu laço infinito em outros projetos.
        """
        pagina = 1
        while pagina <= MAXIMO_DE_PAGINAS:
            consulta = dict(params or {})
            consulta.update({"page": pagina, "pageSize": TAMANHO_DE_PAGINA})
            corpo = self._requisitar("GET", caminho, params=consulta)

            resultados = corpo.get("results")
            if not isinstance(resultados, list):
                raise ErroPluggy(
                    f"GET {caminho} devolveu um corpo sem a lista 'results': "
                    f"{repr(corpo)[:200]}"
                )

            yield from resultados

            total_paginas = _inteiro_ou_nulo(corpo.get("totalPages"))
            ultima = total_paginas is not None and pagina >= total_paginas
            if ultima or not resultados:
                return
            pagina += 1

        raise ErroPluggy(
            f"GET {caminho} passou de {MAXIMO_DE_PAGINAS} páginas. "
            f"Provável laço infinito por 'totalPages' inconsistente."
        )

    def _paginar_por_cursor(
        self, caminho: str, params: dict[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Percorre um endpoint v2, que pagina por cursor.

        O corpo é `{"results": [...], "next": <query string ou null>}`. O
        `next` NÃO é um valor de cursor solto: é a query string inteira da
        próxima página, com `?` na frente, para ser concatenada ao caminho —
        `GET /v2/transactions{next}`. A parada é `next` nulo.

        Duas travas, pelo mesmo motivo da paginação por página: um cursor que
        se repete ou uma contagem que não acaba viraria laço infinito, e o
        sintoma seria uma ingestão que nunca termina em vez de um erro.
        """
        alvo = caminho
        consulta: dict[str, Any] | None = dict(params or {})
        vistos: set[str] = set()

        for _ in range(MAXIMO_DE_PAGINAS):
            corpo = self._requisitar("GET", alvo, params=consulta)

            resultados = corpo.get("results")
            if not isinstance(resultados, list):
                raise ErroPluggy(
                    f"GET {caminho} devolveu um corpo sem a lista 'results': "
                    f"{repr(corpo)[:200]}"
                )

            yield from resultados

            proximo = corpo.get("next")
            if not isinstance(proximo, str) or not proximo:
                return
            if proximo in vistos:
                raise ErroPluggy(
                    f"GET {caminho} repetiu o cursor {proximo[:40]!r}. "
                    f"Parando para não entrar em laço infinito."
                )
            vistos.add(proximo)

            # `next` já vem como query string completa — accountId, dateFrom e
            # after, todos dentro dele. Concatena-se ao caminho e NÃO se manda
            # `params` de novo, senão o httpx sobrescreve a query e o cursor
            # some. Mandar o `next` dentro de `after=` devolve 400
            # INVALID_CURSOR.
            alvo = caminho + proximo
            consulta = None

        raise ErroPluggy(
            f"GET {caminho} passou de {MAXIMO_DE_PAGINAS} páginas de cursor. "
            f"Provável laço infinito."
        )

    # -- requisição ---------------------------------------------------------

    def _requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        autenticado: bool = True,
        exigir_objeto: bool = True,
    ) -> Any:
        """Executa uma requisição com retry e tradução de erro.

        Reautentica uma única vez diante de um 401 em requisição autenticada:
        numa ingestão longa a `apiKey` de ~2h pode vencer no meio, e refazer o
        login é mais barato do que abortar tudo.
        """
        reautenticou = False
        ultimo_erro_de_rede: Exception | None = None

        for tentativa in range(1, self._config.tentativas_http + 1):
            cabecalhos = {}
            if autenticado:
                cabecalhos["X-API-KEY"] = self._garantir_api_key()

            try:
                resposta = self._http.request(
                    metodo, caminho, params=params, json=json, headers=cabecalhos
                )
            except httpx.TransportError as erro:
                ultimo_erro_de_rede = erro
                if tentativa == self._config.tentativas_http:
                    break
                self._esperar(tentativa, motivo=f"falha de rede ({erro!r})")
                continue

            if resposta.status_code < 400:
                return _corpo_json(
                    resposta, metodo, caminho, exigir_objeto=exigir_objeto
                )

            if resposta.status_code == 401 and autenticado and not reautenticou:
                registrador.info("apiKey recusada (401); autenticando de novo")
                reautenticou = True
                self._api_key = None
                # A reautenticação consome uma tentativa. Com FINANCAS_TENTATIVAS=1
                # o laço acabaria aqui e o 401 sairia como ErroDeRede("última
                # falha: None") — mensagem que manda investigar a rede quando o
                # problema é a credencial. Traduzir aqui mantém o diagnóstico
                # honesto.
                if tentativa == self._config.tentativas_http:
                    raise _traduzir_erro(resposta, metodo, caminho)
                continue

            if (
                resposta.status_code in STATUS_RETENTAVEIS
                and tentativa < self._config.tentativas_http
            ):
                self._esperar(
                    tentativa,
                    motivo=f"HTTP {resposta.status_code}",
                    retry_after=resposta.headers.get("Retry-After"),
                )
                continue

            raise _traduzir_erro(resposta, metodo, caminho)

        raise ErroDeRede(
            f"{metodo} {caminho} falhou em {self._config.tentativas_http} tentativas. "
            f"Última falha: {ultimo_erro_de_rede!r}"
        ) from ultimo_erro_de_rede

    def _esperar(
        self, tentativa: int, *, motivo: str, retry_after: str | None = None
    ) -> None:
        """Backoff exponencial, respeitando `Retry-After` quando a API manda um."""
        espera = min(2.0**(tentativa - 1), ESPERA_MAXIMA_SEGUNDOS)
        if retry_after:
            try:
                espera = min(float(retry_after), ESPERA_MAXIMA_SEGUNDOS)
            except ValueError:
                # Retry-After também pode vir como data HTTP; nesse caso o
                # backoff exponencial já serve.
                pass
        registrador.warning(
            "tentativa %d falhou (%s); nova tentativa em %.1fs", tentativa, motivo, espera
        )
        self._dormir(espera)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------


def _corpo_json(
    resposta: httpx.Response,
    metodo: str,
    caminho: str,
    *,
    exigir_objeto: bool = True,
) -> Any:
    """Interpreta o corpo da resposta.

    `exigir_objeto` existe porque `GET /categories` devolve um array puro, e não
    o envelope `{"results": [...]}` de todos os outros endpoints.
    """
    try:
        corpo = resposta.json()
    except ValueError as erro:
        raise ErroPluggy(
            f"{metodo} {caminho} respondeu {resposta.status_code} com corpo "
            f"que não é JSON: {resposta.text[:200]!r}"
        ) from erro
    if exigir_objeto and not isinstance(corpo, dict):
        raise ErroPluggy(
            f"{metodo} {caminho} respondeu com {type(corpo).__name__}, esperava objeto JSON"
        )
    return corpo


def _traduzir_erro(
    resposta: httpx.Response, metodo: str, caminho: str
) -> ErroPluggy:
    """Converte um status HTTP na exceção que diz o que fazer a respeito."""
    status = resposta.status_code
    corpo = resposta.text

    if caminho == "/auth" and status in (400, 401, 403):
        return ErroDeAutenticacao(
            "A Pluggy recusou as credenciais (HTTP "
            f"{status}). Confira PLUGGY_CLIENT_ID e PLUGGY_CLIENT_SECRET no .env "
            "contra dashboard.pluggy.ai > sua aplicação > credenciais. "
            f"Resposta: {corpo[:200]}"
        )

    if status == 410:
        return EndpointAposentado(
            f"{metodo} {caminho} devolveu HTTP 410: a Pluggy aposentou este "
            "endpoint. Não é problema de credencial nem de consentimento — o "
            "cliente precisa ser atualizado para o endereço novo. "
            f"Resposta: {corpo[:300]}"
        )

    if status == 403:
        return ConsentimentoExpirado(
            f"{metodo} {caminho} devolveu HTTP 403. O consentimento de Open "
            "Finance provavelmente venceu: entre em meu.pluggy.ai e reautorize "
            "a instituição. Lembre que reautorizar gera um itemId novo. "
            f"Resposta: {corpo[:200]}"
        )

    return ErroDaApi(status, metodo, caminho, corpo)


def _inteiro_ou_nulo(valor: object) -> int | None:
    """Lê `totalPages` sem confiar no tipo — a API já mandou string nesse campo."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, int):
        return valor
    try:
        return int(str(valor))
    except (TypeError, ValueError):
        return None
