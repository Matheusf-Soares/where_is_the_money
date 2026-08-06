"""
Cliente offline: lê fixtures JSON do disco em vez de chamar a API.

Cumpre o mesmo contrato de `ClienteHttp`, então o resto do pipeline não sabe
qual dos dois está em uso. É o que permite desenvolver e testar ingestão,
persistência e views inteiras sem rede, sem credencial e sem dado real.

Layout esperado do diretório de fixtures:

    <fixtures>/
    ├─ items.json                        {"results": [...]}
    ├─ categories.json                   taxonomia (array puro na API real)
    ├─ accounts/<id_item>.json
    ├─ transactions/<id_conta>.json
    └─ investments/<id_item>.json

Cada arquivo aceita tanto o envelope `{"results": [...]}` que a API devolve
quanto uma lista pura, para quem escrever fixture à mão não precisar do
boilerplate.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

registrador = logging.getLogger(__name__)


class ErroDeFixture(Exception):
    """Fixture ausente onde é obrigatória, ou malformada."""


class ClienteFixtures:
    """Implementação de `Cliente` que lê JSON do disco.

    Args:
        diretorio: raiz das fixtures, normalmente `config.diretorio_fixtures`.
    """

    def __init__(self, diretorio: Path) -> None:
        self._diretorio = Path(diretorio)

    def listar_itens(self) -> list[dict[str, Any]]:
        # Sem items.json não há por onde começar: isso é erro de configuração,
        # não ausência legítima de dado.
        return self._ler("items.json", obrigatorio=True)

    def listar_contas(self, id_item: str) -> list[dict[str, Any]]:
        return self._ler(f"accounts/{id_item}.json")

    def listar_transacoes(
        self, id_conta: str, desde: date
    ) -> Iterator[dict[str, Any]]:
        """Aplica o mesmo recorte de data que o `from=` faria na API real."""
        for transacao in self._ler(f"transactions/{id_conta}.json"):
            data = _data_da_transacao(transacao)
            if data is None or data >= desde:
                yield transacao

    def listar_investimentos(self, id_item: str) -> list[dict[str, Any]]:
        return self._ler(f"investments/{id_item}.json")

    def listar_categorias(self) -> list[dict[str, Any]]:
        """Taxonomia de categorias.

        Ausência é legítima: quem não tem a feature de categorização habilitada
        na Pluggy não recebe categoria nenhuma, e o de-para simplesmente fica
        vazio. Não é erro de configuração.
        """
        return self._ler("categories.json")

    # -- leitura ------------------------------------------------------------

    def _ler(self, relativo: str, *, obrigatorio: bool = False) -> list[dict[str, Any]]:
        caminho = self._diretorio / relativo
        if not caminho.is_file():
            if obrigatorio:
                raise ErroDeFixture(
                    f"fixture obrigatória não encontrada: {caminho}. "
                    f"Confira FINANCAS_FIXTURES no .env."
                )
            # Item sem investimento, conta sem extrato: ausência é resposta
            # legítima. Fica no log porque também pode ser id digitado errado.
            registrador.debug("fixture ausente, tratando como vazia: %s", caminho)
            return []

        try:
            conteudo = json.loads(caminho.read_text(encoding="utf-8"))
        except json.JSONDecodeError as erro:
            raise ErroDeFixture(f"{caminho}: JSON inválido ({erro})") from erro

        if isinstance(conteudo, dict):
            conteudo = conteudo.get("results", [])
        if not isinstance(conteudo, list):
            raise ErroDeFixture(
                f"{caminho}: esperava uma lista ou {{'results': [...]}}, "
                f"recebi {type(conteudo).__name__}"
            )
        return conteudo


def _data_da_transacao(transacao: dict[str, Any]) -> date | None:
    """Extrai a data de uma transação, tolerando o formato ISO com hora e `Z`."""
    bruto = transacao.get("date")
    if not isinstance(bruto, str) or len(bruto) < 10:
        return None
    try:
        return date.fromisoformat(bruto[:10])
    except ValueError:
        return None
