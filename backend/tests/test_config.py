"""Testes da camada de configuração.

O que importa aqui não é só que a configuração carrega, é que ela **falha bem**:
a mensagem precisa dizer qual variável faltou e onde arrumar.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from financas.config import (
    MODO_OFFLINE,
    MODO_ONLINE,
    ErroDeConfiguracao,
    carregar_configuracao,
    carregar_regras,
    ler_arquivo_env,
)


# ---------------------------------------------------------------------------
# Leitura do .env
# ---------------------------------------------------------------------------


def test_ler_env_ignora_comentario_e_linha_em_branco(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "# comentário\n\nPLUGGY_CLIENT_ID=abc\n\n# outro\nFINANCAS_MODO=online\n",
        encoding="utf-8",
    )

    assert ler_arquivo_env(arquivo) == {
        "PLUGGY_CLIENT_ID": "abc",
        "FINANCAS_MODO": "online",
    }


def test_ler_env_aceita_aspas_e_export(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        'export PLUGGY_CLIENT_SECRET="seg redo"\nFINANCAS_BANCO=\'dados/a.duckdb\'\n',
        encoding="utf-8",
    )

    valores = ler_arquivo_env(arquivo)

    assert valores["PLUGGY_CLIENT_SECRET"] == "seg redo"
    assert valores["FINANCAS_BANCO"] == "dados/a.duckdb"


def test_ler_env_preserva_igual_dentro_do_valor(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    arquivo.write_text("PLUGGY_CLIENT_SECRET=a=b=c\n", encoding="utf-8")

    assert ler_arquivo_env(arquivo)["PLUGGY_CLIENT_SECRET"] == "a=b=c"


def test_ler_env_inexistente_devolve_vazio(tmp_path: Path) -> None:
    assert ler_arquivo_env(tmp_path / "nao-existe") == {}


def test_ler_env_reclama_de_linha_sem_igual(tmp_path: Path) -> None:
    arquivo = tmp_path / ".env"
    arquivo.write_text("PLUGGY_CLIENT_ID=abc\nlixo\n", encoding="utf-8")

    with pytest.raises(ErroDeConfiguracao) as erro:
        ler_arquivo_env(arquivo)

    assert ":2:" in str(erro.value)


# ---------------------------------------------------------------------------
# Modo online x offline
# ---------------------------------------------------------------------------


def test_offline_e_o_padrao_e_nao_exige_credencial(projeto: Path) -> None:
    config = carregar_configuracao(ambiente={}, raiz=projeto)

    assert config.modo == MODO_OFFLINE
    assert config.offline is True
    assert config.client_id == ""


def test_online_sem_credencial_lista_as_duas_variaveis(projeto: Path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_configuracao(ambiente={"FINANCAS_MODO": "online"}, raiz=projeto)

    mensagem = str(erro.value)
    assert "PLUGGY_CLIENT_ID" in mensagem
    assert "PLUGGY_CLIENT_SECRET" in mensagem
    # A mensagem precisa dizer onde conseguir o valor, não só que ele falta.
    assert "dashboard.pluggy.ai" in mensagem


def test_online_com_credencial_carrega(projeto: Path) -> None:
    config = carregar_configuracao(
        ambiente={
            "FINANCAS_MODO": "online",
            "PLUGGY_CLIENT_ID": "id-de-teste",
            "PLUGGY_CLIENT_SECRET": "segredo-de-teste",
        },
        raiz=projeto,
    )

    assert config.modo == MODO_ONLINE
    assert config.offline is False
    assert config.client_secret == "segredo-de-teste"


def test_placeholder_do_env_example_e_recusado(projeto: Path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_configuracao(
            ambiente={
                "FINANCAS_MODO": "online",
                "PLUGGY_CLIENT_ID": "<seu-client-id>",
                "PLUGGY_CLIENT_SECRET": "segredo",
            },
            raiz=projeto,
        )

    assert "placeholder" in str(erro.value)


def test_modo_invalido_mostra_as_opcoes(projeto: Path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_configuracao(ambiente={"FINANCAS_MODO": "producao"}, raiz=projeto)

    assert "'offline'" in str(erro.value) and "'online'" in str(erro.value)


def test_offline_sem_diretorio_de_fixtures_falha(projeto: Path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_configuracao(
            ambiente={"FINANCAS_FIXTURES": "fixtures/que/nao/existem"}, raiz=projeto
        )

    assert "FINANCAS_FIXTURES" in str(erro.value)


def test_secret_nao_vaza_no_repr(projeto: Path) -> None:
    config = carregar_configuracao(
        ambiente={
            "FINANCAS_MODO": "online",
            "PLUGGY_CLIENT_ID": "id-de-teste",
            "PLUGGY_CLIENT_SECRET": "nao-me-mostre",
        },
        raiz=projeto,
    )

    assert "nao-me-mostre" not in repr(config)


# ---------------------------------------------------------------------------
# Precedência e caminhos
# ---------------------------------------------------------------------------


def test_ambiente_do_processo_vence_o_arquivo_env(projeto: Path) -> None:
    (projeto / ".env").write_text("FINANCAS_MODO=offline\n", encoding="utf-8")

    config = carregar_configuracao(
        ambiente={
            "FINANCAS_MODO": "online",
            "PLUGGY_CLIENT_ID": "id",
            "PLUGGY_CLIENT_SECRET": "segredo",
        },
        raiz=projeto,
    )

    assert config.modo == MODO_ONLINE


def test_valores_do_env_sao_usados_quando_o_processo_nao_define(projeto: Path) -> None:
    (projeto / ".env").write_text("FINANCAS_TIMEOUT=90\n", encoding="utf-8")

    config = carregar_configuracao(ambiente={}, raiz=projeto)

    assert config.timeout_http == 90.0


def test_caminho_relativo_resolve_a_partir_da_raiz(projeto: Path) -> None:
    config = carregar_configuracao(
        ambiente={"FINANCAS_BANCO": "dados/meu.duckdb"}, raiz=projeto
    )

    assert config.caminho_banco == (projeto / "dados" / "meu.duckdb").resolve()


def test_url_da_api_perde_a_barra_final(projeto: Path) -> None:
    config = carregar_configuracao(
        ambiente={"PLUGGY_API_URL": "https://api.pluggy.ai/"}, raiz=projeto
    )

    assert config.url_api == "https://api.pluggy.ai"


@pytest.mark.parametrize("valor", ["zero", "0", "-1"])
def test_timeout_invalido_e_reportado(projeto: Path, valor: str) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_configuracao(ambiente={"FINANCAS_TIMEOUT": valor}, raiz=projeto)

    assert "FINANCAS_TIMEOUT" in str(erro.value)


def test_erros_sao_acumulados_e_nao_reportados_um_por_vez(projeto: Path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_configuracao(
            ambiente={
                "FINANCAS_MODO": "online",
                "PLUGGY_API_URL": "api.pluggy.ai",
                "FINANCAS_TIMEOUT": "-5",
            },
            raiz=projeto,
        )

    # client_id, client_secret, url e timeout: quatro problemas de uma vez.
    assert len(erro.value.problemas) == 4


# ---------------------------------------------------------------------------
# Regras de negócio (regras.toml)
# ---------------------------------------------------------------------------


def test_regras_sao_carregadas_junto_da_configuracao(projeto: Path) -> None:
    regras = carregar_configuracao(ambiente={}, raiz=projeto).regras

    assert regras.data_inicial == date(2025, 8, 1)
    assert regras.frescor_dias_padrao == 5
    assert len(regras.padroes_fatura) == 5
    assert len(regras.contrapartes_proprias) == 4


def test_limite_de_frescor_por_instituicao_e_carregado(projeto: Path) -> None:
    """Quem decide o que está velho é o SQL de `financas.frescor`. Aqui só
    conferimos que o limite chegou íntegro do TOML."""
    regras = carregar_configuracao(ambiente={}, raiz=projeto).regras

    (limite,) = regras.limites_frescor
    assert limite.instituicao == "rico%"
    assert limite.dias_maximos == 10
    assert regras.frescor_dias_padrao == 5


def test_instituicao_em_maiuscula_e_recusada(projeto: Path) -> None:
    """`instituicao` é padrão LIKE comparado com lower(): maiúscula nunca casa,
    e um filtro que nunca casa falha em silêncio."""
    caminho = _escrever_regras(
        projeto,
        "[geral]\ndata_inicial = 2025-08-01\nfrescor_dias_padrao = 5\n"
        '\n[[frescor]]\ninstituicao = "Rico"\ndias_maximos = 10\n',
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "instituicao" in str(erro.value)


def test_regras_ausentes_dizem_como_criar(projeto: Path) -> None:
    (projeto / "config" / "regras.toml").unlink()

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_configuracao(ambiente={}, raiz=projeto)

    assert "regras.example.toml" in str(erro.value)


def _escrever_regras(projeto: Path, conteudo: str) -> Path:
    caminho = projeto / "config" / "regras.toml"
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def test_data_inicial_como_texto_e_recusada(projeto: Path) -> None:
    caminho = _escrever_regras(
        projeto,
        '[geral]\ndata_inicial = "2025-08-01"\nfrescor_dias_padrao = 5\n',
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "data_inicial" in str(erro.value)


def test_frescor_zero_e_recusado_por_causa_da_latencia(projeto: Path) -> None:
    caminho = _escrever_regras(
        projeto, "[geral]\ndata_inicial = 2025-08-01\nfrescor_dias_padrao = 0\n"
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "latência" in str(erro.value)


def test_padrao_de_fatura_em_maiuscula_e_recusado(projeto: Path) -> None:
    caminho = _escrever_regras(
        projeto,
        "[geral]\ndata_inicial = 2025-08-01\nfrescor_dias_padrao = 5\n"
        '\n[[pagamento_fatura]]\ninstituicao = "nubank"\npadrao = "%Pagamento de Fatura%"\n',
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert erro.value.problemas == [
        f"{caminho}: [[pagamento_fatura]] #1: padrao deve estar em minúsculas "
        "(a comparação usa lower(), então maiúscula nunca casaria), "
        "recebi '%Pagamento de Fatura%'"
    ]


def test_tipo_de_contraparte_desconhecido_e_recusado(projeto: Path) -> None:
    caminho = _escrever_regras(
        projeto,
        "[geral]\ndata_inicial = 2025-08-01\nfrescor_dias_padrao = 5\n"
        '\n[[transferencia_propria]]\ntipo = "apelido"\nvalor = "x"\n',
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "titular" in str(erro.value)


def test_toml_quebrado_diz_qual_arquivo(projeto: Path) -> None:
    caminho = _escrever_regras(projeto, "[geral\ndata_inicial = 2025-08-01\n")

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "TOML inválido" in str(erro.value)


def test_arquivo_de_regras_do_repositorio_e_valido() -> None:
    """O exemplo versionado precisa carregar sem erro, senão ele engana quem copiar."""
    exemplo = Path(__file__).resolve().parents[1] / "config" / "regras.example.toml"

    regras = carregar_regras(exemplo)

    assert regras.padroes_fatura, "o exemplo deve trazer padrões de fatura"
    assert regras.data_inicial == date(2025, 8, 1)


# ---------------------------------------------------------------------------
# [[item]]: os itemId, que não podem ser listados pela API
# ---------------------------------------------------------------------------

# O mínimo para o arquivo ser válido; o que se testa vem depois dele.
GERAL = """[geral]
data_inicial = 2025-08-01
frescor_dias_padrao = 5
"""


def test_item_com_id_que_nao_e_uuid_e_recusado(projeto: Path) -> None:
    """Falhar cedo: id torto descoberto aqui em vez de num 404 lá.

    O itemId é copiado à mão do Dashboard, porque listar items é bloqueado.
    Cópia manual erra, e a validação de formato é de graça.
    """
    caminho = _escrever_regras(
        projeto,
        GERAL + """
[[item]]
id = "nao-e-uuid"
""",
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "UUID" in str(erro.value)


def test_item_repetido_e_recusado(projeto: Path) -> None:
    """Id duplicado ingeriria a mesma instituição duas vezes."""
    caminho = _escrever_regras(
        projeto,
        GERAL + """
[[item]]
id = "11111111-1111-4111-8111-111111111111"
instituicao = "Nubank"

[[item]]
id = "11111111-1111-4111-8111-111111111111"
instituicao = "Nubank de novo"
""",
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "mais de uma vez" in str(erro.value)


def test_sem_item_nao_e_erro(projeto: Path) -> None:
    """O modo offline não precisa de itemId nenhum.

    Cobrar isso aqui atrapalharia o desenvolvimento. Quem cobra é a ingestão
    online, que sabe dizer o que faltou e onde pegar.
    """
    regras = carregar_regras(_escrever_regras(projeto, GERAL))

    assert regras.itens == ()


def test_instituicao_do_item_e_obrigatoria(projeto: Path) -> None:
    """Sem ela, as instituições viram uma só.

    O conector MeuPluggy (200) é agregador: `connector.name` devolve
    "MeuPluggy" para TODOS os items. Contra os dados reais, isso fez as 656
    transações e as 8 contas ficarem com a mesma instituição — `patrimonio`
    colapsou numa linha e `frescor` deixou de saber quem tinha parado.
    """
    caminho = _escrever_regras(
        projeto,
        GERAL + """
[[item]]
id = "11111111-1111-4111-8111-111111111111"
""",
    )

    with pytest.raises(ErroDeConfiguracao) as erro:
        carregar_regras(caminho)

    assert "instituicao" in str(erro.value)


def test_rotulo_do_item_vem_da_instituicao(projeto: Path) -> None:
    """Sem connector (id morto) o rótulo é o que identifica a instituição."""
    regras = carregar_regras(
        _escrever_regras(
            projeto,
            GERAL + """
[[item]]
id = "11111111-1111-4111-8111-111111111111"
instituicao = "Nubank"
observacao = "conta corrente + cartão"
""",
        )
    )

    assert regras.itens[0].instituicao == "Nubank"
    assert regras.itens[0].rotulo == "Nubank"
