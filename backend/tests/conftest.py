"""Fixtures compartilhadas. Tudo sintético: nenhum teste toca rede ou credencial real.

Os valores aqui espelham `tests/fixtures/pluggy/`: titular "Fulano de Tal", CPF
`12345678909` e telefone `31900001111`, todos inventados. Nada de dado real
entra no repositório — nem em fixture, nem em teste.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from financas.config import Configuracao, carregar_configuracao
from financas.normalizacao import (
    nome_da_instituicao,
    normalizar_conta,
    normalizar_investimento,
    normalizar_transacao,
)
from financas.persistencia import BANCO_EM_MEMORIA, Banco
from financas.pluggy import criar_cliente

RAIZ = Path(__file__).resolve().parents[1]
FIXTURES_PLUGGY = RAIZ / "tests" / "fixtures" / "pluggy"

REGRAS_MINIMAS = """
[geral]
data_inicial = 2025-08-01
frescor_dias_padrao = 5
recorrencia_meses_minimos = 2
recorrencia_variacao_maxima = 0.15

[[pagamento_fatura]]
instituicao = "nubank"
padrao = "%pagamento de fatura%"

[[pagamento_fatura]]
instituicao = "nubank"
padrao = "%pagamento recebido%"

[[pagamento_fatura]]
instituicao = "santander"
padrao = "%pagto%cartao%"

[[pagamento_fatura]]
instituicao = "inter"
padrao = "%pagamento fatura%"

[[pagamento_fatura]]
instituicao = "%"
padrao = "%fatura cartao%"

[[aplicacao]]
instituicao = "%"
padrao = "%aplicacao%"

[[transferencia_propria]]
tipo = "titular"
valor = "%fulano de tal%"

[[transferencia_propria]]
tipo = "chave_pix"
valor = "%12345678909%"

[[transferencia_propria]]
tipo = "chave_pix"
valor = "%123.456.789-09%"

[[transferencia_propria]]
tipo = "chave_pix"
valor = "%31900001111%"

[[frescor]]
instituicao = "rico%"
dias_maximos = 10

# Fase 2. Cobre de propósito só uma parte das fixtures: o resto tem que cair no
# de-para, e alguma coisa tem que sobrar para o rótulo padrão — é assim que as
# três camadas ficam exercitadas de verdade.
[[categoria]]
prioridade = 10
padrao = "%netflix%"
categoria = "Streaming"
grupo = "Lazer"

[[categoria]]
prioridade = 20
padrao = "%uber%"
categoria = "Transporte"
grupo = "Variável"

[[mapa_categoria]]
id_categoria = "09020000"
categoria = "Streaming (mapa)"
grupo = "Lazer"

[[mapa_categoria]]
id_categoria = "10000000"
categoria = "Mercado"
grupo = "Essencial"

[[mapa_categoria]]
id_categoria = "07030001"
categoria = "Academia"
grupo = "Fixo"
"""


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    """Raiz de projeto sintética, com o mínimo para `carregar_configuracao` passar."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "regras.toml").write_text(REGRAS_MINIMAS, encoding="utf-8")
    (tmp_path / "tests" / "fixtures" / "pluggy").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def config_offline(projeto: Path) -> Configuracao:
    """Configuração em modo offline apontando para as fixtures reais do repositório."""
    return carregar_configuracao(
        ambiente={"FINANCAS_FIXTURES": str(FIXTURES_PLUGGY)}, raiz=projeto
    )


@pytest.fixture
def config_online(projeto: Path) -> Configuracao:
    """Configuração em modo online com credenciais falsas.

    Serve para exercitar `ClienteHttp` com `httpx.MockTransport`: as credenciais
    nunca saem da máquina porque nenhuma requisição chega a existir.
    """
    return carregar_configuracao(
        ambiente={
            "FINANCAS_MODO": "online",
            "PLUGGY_CLIENT_ID": "id-falso",
            "PLUGGY_CLIENT_SECRET": "segredo-falso",
            "PLUGGY_API_URL": "https://api.pluggy.test",
            "FINANCAS_TENTATIVAS": "3",
        },
        raiz=projeto,
    )


class RelogioFalso:
    """Relógio controlável.

    Sem ele não dá para testar idempotência de verdade: a asserção que importa é
    que uma segunda execução, num instante diferente, não mexeu em
    `atualizado_em`.
    """

    def __init__(self, inicio: datetime) -> None:
        self.instante = inicio

    def __call__(self) -> datetime:
        return self.instante

    def avancar(self, **intervalo: float) -> None:
        self.instante += timedelta(**intervalo)


@pytest.fixture
def relogio() -> RelogioFalso:
    return RelogioFalso(datetime(2025, 9, 20, 10, 0, 0))


@pytest.fixture
def banco(relogio: RelogioFalso) -> Banco:
    """Banco DuckDB em memória, com o schema já aplicado."""
    with Banco.abrir(BANCO_EM_MEMORIA, agora=relogio) as instancia:
        instancia.criar_schema()
        yield instancia


@pytest.fixture
def banco_com_views(banco: Banco, config_offline: Configuracao) -> Banco:
    """Banco com fixtures ingeridas, cfg_* carregadas e views aplicadas.

    A data de posição é 2025-09-20, a mesma usada nos testes de frescor.
    """
    from datetime import date as _date

    from financas.ingestao import ingerir
    from financas.views import aplicar_views

    banco.gravar_regras(config_offline.regras)
    ingerir(
        criar_cliente(config_offline),
        banco,
        config_offline.regras,
        hoje=_date(2025, 9, 20),
    )
    aplicar_views(banco, RAIZ / "sql")
    return banco


@pytest.fixture
def dados_normalizados(
    config_offline: Configuracao,
) -> dict[str, list[dict[str, Any]]]:
    """As fixtures inteiras, já achatadas em linhas prontas para gravar.

    É a travessia `item → conta → transação` que a ingestão da etapa (d) vai
    fazer, reduzida ao mínimo para os testes de persistência não dependerem
    dela.
    """
    cliente = criar_cliente(config_offline)
    data_posicao = date(2025, 9, 20)
    transacoes: list[dict[str, Any]] = []
    contas: list[dict[str, Any]] = []
    investimentos: list[dict[str, Any]] = []

    for item in cliente.listar_itens():
        id_item = item["id"]
        instituicao = nome_da_instituicao(item)

        for bruta in cliente.listar_contas(id_item):
            contas.append(
                normalizar_conta(
                    bruta,
                    id_item=id_item,
                    instituicao=instituicao,
                    data_posicao=data_posicao,
                )
            )
            for transacao in cliente.listar_transacoes(bruta["id"], date(2025, 8, 1)):
                transacoes.append(
                    normalizar_transacao(
                        transacao, id_item=id_item, instituicao=instituicao
                    )
                )

        for bruto in cliente.listar_investimentos(id_item):
            investimentos.append(
                normalizar_investimento(
                    bruto,
                    id_item=id_item,
                    instituicao=instituicao,
                    data_posicao=data_posicao,
                )
            )

    return {
        "transacoes": transacoes,
        "contas": contas,
        "investimentos": investimentos,
    }
