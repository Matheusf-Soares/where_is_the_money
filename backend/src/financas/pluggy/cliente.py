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

# Trava contra paginação infinita se a API devolver `totalPages` inconsistente.
MAXIMO_DE_PAGINAS = 2000

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

    def listar_transacoes(
        self, id_conta: str, desde: date
    ) -> Iterator[dict[str, Any]]:
        """Extrato de uma conta, já percorrendo todas as páginas."""
        ...

    def listar_investimentos(self, id_item: str) -> list[dict[str, Any]]:
        """Posição de investimentos de um item."""
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
        return list(self._paginar("/items"))

    def listar_contas(self, id_item: str) -> list[dict[str, Any]]:
        return list(self._paginar("/accounts", {"itemId": id_item}))

    def listar_transacoes(
        self, id_conta: str, desde: date
    ) -> Iterator[dict[str, Any]]:
        return self._paginar(
            "/transactions", {"accountId": id_conta, "from": desde.isoformat()}
        )

    def listar_investimentos(self, id_item: str) -> list[dict[str, Any]]:
        return list(self._paginar("/investments", {"itemId": id_item}))

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

    # -- requisição ---------------------------------------------------------

    def _requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        autenticado: bool = True,
    ) -> dict[str, Any]:
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
                return _corpo_json(resposta, metodo, caminho)

            if resposta.status_code == 401 and autenticado and not reautenticou:
                registrador.info("apiKey recusada (401); autenticando de novo")
                reautenticou = True
                self._api_key = None
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
    resposta: httpx.Response, metodo: str, caminho: str
) -> dict[str, Any]:
    try:
        corpo = resposta.json()
    except ValueError as erro:
        raise ErroPluggy(
            f"{metodo} {caminho} respondeu {resposta.status_code} com corpo "
            f"que não é JSON: {resposta.text[:200]!r}"
        ) from erro
    if not isinstance(corpo, dict):
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
