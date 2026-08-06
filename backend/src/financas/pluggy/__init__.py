"""Acesso à API da Pluggy, em duas implementações intercambiáveis."""

from __future__ import annotations

from financas.config import Configuracao
from financas.pluggy.cliente import (
    Cliente,
    ClienteHttp,
    ConsentimentoExpirado,
    ErroDaApi,
    ErroDeAutenticacao,
    ErroDeRede,
    ErroPluggy,
)
from financas.pluggy.fixtures import ClienteFixtures, ErroDeFixture

__all__ = [
    "Cliente",
    "ClienteFixtures",
    "ClienteHttp",
    "ConsentimentoExpirado",
    "ErroDaApi",
    "ErroDeAutenticacao",
    "ErroDeFixture",
    "ErroDeRede",
    "ErroPluggy",
    "criar_cliente",
]


def criar_cliente(config: Configuracao, **extras: object) -> Cliente:
    """Devolve o cliente correspondente ao `FINANCAS_MODO`.

    Único ponto do projeto que decide entre rede e disco. Todo o resto recebe um
    `Cliente` pronto e não pergunta de onde vieram os dados.
    """
    if config.offline:
        return ClienteFixtures(config.diretorio_fixtures)
    return ClienteHttp(config, **extras)  # type: ignore[arg-type]
