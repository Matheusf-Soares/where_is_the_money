"""
Testes da categorização própria (fase 2).

A resolução tem três camadas, e o que estes testes protegem é a ordem entre
elas e a garantia de cobertura total:

    1. cfg_categorias       regra por texto        vence
    2. cfg_mapa_categorias  de-para do categoryId  cobre o resto
    3. cfg_geral            rótulo padrão          nunca deixa NULL

As regras do `conftest` cobrem de propósito só uma parte das fixtures: Netflix
e Uber têm regra, Spotify e Supermercado só têm de-para, e Restaurante/Amazon
não têm nada. Sem essa assimetria, um teste que passasse não provaria em qual
camada a resposta foi decidida.

Casos-chave nas fixtures:

    tx-nu-b-05  Netflix.com     05070000  regra E mapa -> a regra tem que vencer
    tx-nu-c-02  Spotify         05070000  só mapa
    tx-nu-c-01  Uber *Trip      04000000  só regra
    tx-in-b-03  Academia        05060000  só mapa
    tx-sa-c-01  Restaurante Xis 05020000  nenhum  -> rótulo padrão
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from financas.config import (
    CATEGORIA_PADRAO,
    GRUPO_PADRAO,
    ErroDeConfiguracao,
    carregar_regras,
)
from financas.persistencia import Banco
from financas.views import aplicar_views

from conftest import RAIZ, REGRAS_MINIMAS

SQL = RAIZ / "sql"


def uma(banco: Banco, consulta: str):
    return banco.conexao.execute(consulta).fetchone()


def categoria_de(banco: Banco, id_transacao: str) -> tuple[str, str, str]:
    """Devolve (categoria_propria, grupo, origem) de uma transação."""
    return uma(
        banco,
        "SELECT categoria_propria, grupo, origem_da_categoria FROM stg_transacoes "
        f"WHERE id_transacao = '{id_transacao}'",
    )


def regras_com(extra: str, tmp_path):
    """Escreve um regras.toml sintético e o carrega."""
    caminho = tmp_path / "regras.toml"
    caminho.write_text(REGRAS_MINIMAS + extra, encoding="utf-8")
    return carregar_regras(caminho)


# ---------------------------------------------------------------------------
# Precedência entre as camadas
# ---------------------------------------------------------------------------


def test_regra_por_texto_vence_o_de_para(banco_com_views: Banco) -> None:
    """O caso que justifica a camada 1 existir.

    Netflix casa a regra `%netflix%` e também o de-para de 05070000. Se o
    de-para vencesse, a categorização fina não teria como sobrescrever a
    grosseira — que é o motivo inteiro da fase 2.
    """
    categoria, grupo, origem = categoria_de(banco_com_views, "tx-nu-b-05")

    assert (categoria, grupo, origem) == ("Streaming", "Lazer", "regra")


def test_de_para_pega_o_que_nenhuma_regra_pegou(banco_com_views: Banco) -> None:
    """Spotify tem o mesmo categoryId da Netflix, mas nenhuma regra de texto."""
    categoria, grupo, origem = categoria_de(banco_com_views, "tx-nu-c-02")

    assert (categoria, grupo, origem) == ("Streaming (mapa)", "Lazer", "mapa")


def test_regra_vale_mesmo_sem_de_para_para_o_id(banco_com_views: Banco) -> None:
    """Uber: 04000000 não está no de-para do conftest, mas a regra casa."""
    categoria, grupo, origem = categoria_de(banco_com_views, "tx-nu-c-01")

    assert (categoria, grupo, origem) == ("Transporte", "Variável", "regra")


def test_sem_regra_e_sem_de_para_cai_no_rotulo_padrao(banco_com_views: Banco) -> None:
    categoria, grupo, origem = categoria_de(banco_com_views, "tx-sa-c-01")

    assert (categoria, grupo, origem) == (CATEGORIA_PADRAO, GRUPO_PADRAO, "padrao")


def test_prioridade_menor_vence(banco: Banco, tmp_path) -> None:
    """Duas regras casam a mesma transação; decide a prioridade, não a ordem."""
    regras = regras_com(
        """
[[categoria]]
prioridade = 90
padrao = "%mercado%"
categoria = "Genérica"
grupo = "Variável"

[[categoria]]
prioridade = 5
padrao = "%supermercado big%"
categoria = "Específica"
grupo = "Essencial"
""",
        tmp_path,
    )
    banco.gravar_regras(regras)
    _inserir(banco, "tx-1", "Supermercado Big Centro", "05010000")
    aplicar_views(banco, SQL)

    assert categoria_de(banco, "tx-1") == ("Específica", "Essencial", "regra")


def test_regra_casa_pelo_estabelecimento_e_nao_so_pela_descricao(
    banco: Banco, tmp_path
) -> None:
    """A Pluggy preenche descrição ou estabelecimento conforme a instituição.

    Olhar só a descrição perderia silenciosamente todas as transações em que a
    única pista está no `merchant.name`.
    """
    regras = regras_com(
        """
[[categoria]]
prioridade = 1
padrao = "%padaria bela vista%"
categoria = "Padaria"
grupo = "Essencial"
""",
        tmp_path,
    )
    banco.gravar_regras(regras)
    _inserir(
        banco,
        "tx-2",
        descricao="COMPRA CARTAO 4321",
        id_categoria="05020000",
        estabelecimento="Padaria Bela Vista",
    )
    aplicar_views(banco, SQL)

    assert categoria_de(banco, "tx-2") == ("Padaria", "Essencial", "regra")


# ---------------------------------------------------------------------------
# Cobertura: nada pode ficar sem categoria
# ---------------------------------------------------------------------------


def test_nenhuma_transacao_fica_sem_categoria(banco_com_views: Banco) -> None:
    """A garantia que torna a coluna utilizável em GROUP BY.

    Categoria nula sai de JOIN e de filtro sem avisar, e gasto que some do
    relatório em silêncio é o modo de falha que este projeto combate.
    """
    (nulas,) = uma(
        banco_com_views,
        "SELECT count(*) FROM stg_transacoes "
        "WHERE categoria_propria IS NULL OR grupo IS NULL",
    )

    assert nulas == 0


def test_toda_transacao_tem_origem_declarada(banco_com_views: Banco) -> None:
    origens = {
        linha[0]
        for linha in banco_com_views.conexao.execute(
            "SELECT DISTINCT origem_da_categoria FROM stg_transacoes"
        ).fetchall()
    }

    assert origens <= {"regra", "mapa", "padrao"}
    # As três camadas precisam estar de fato exercitadas pelas fixtures, senão
    # este arquivo de teste estaria medindo menos do que promete.
    assert origens == {"regra", "mapa", "padrao"}


def test_categorizar_nao_muda_o_total_de_gastos(banco_com_views: Banco) -> None:
    """Categoria é rótulo, não filtro.

    Se a resolução duplicasse linha — um LEFT JOIN a mais casando duas vezes —
    o total de gastos subiria sem nenhum outro teste acusar.
    """
    (linhas_stg,) = uma(banco_com_views, "SELECT count(*) FROM stg_transacoes")
    (linhas_raw,) = uma(
        banco_com_views,
        "SELECT count(*) FROM raw_transacoes WHERE coalesce(situacao, '') <> 'CANCELLED'",
    )

    assert linhas_stg == linhas_raw


def test_categoria_da_pluggy_continua_disponivel(banco_com_views: Banco) -> None:
    """Sem ela não dá para auditar o de-para nem descobrir id que falta."""
    categoria_pluggy, id_categoria = uma(
        banco_com_views,
        "SELECT categoria, id_categoria FROM stg_transacoes "
        "WHERE id_transacao = 'tx-nu-b-05'",
    )

    assert (categoria_pluggy, id_categoria) == ("Streaming", "05070000")


# ---------------------------------------------------------------------------
# Validação da configuração
# ---------------------------------------------------------------------------


def test_prioridade_repetida_e_recusada(tmp_path) -> None:
    """Empate deixaria o desempate por conta da ordem das linhas do arquivo."""
    with pytest.raises(ErroDeConfiguracao) as erro:
        regras_com(
            """
[[categoria]]
prioridade = 10
padrao = "%netflix%"
categoria = "Streaming"
grupo = "Lazer"

[[categoria]]
prioridade = 10
padrao = "%spotify%"
categoria = "Streaming"
grupo = "Lazer"
""",
            tmp_path,
        )

    assert "prioridade 10" in str(erro.value)


def test_prioridade_ausente_e_recusada(tmp_path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        regras_com(
            """
[[categoria]]
padrao = "%netflix%"
categoria = "Streaming"
grupo = "Lazer"
""",
            tmp_path,
        )

    assert "prioridade" in str(erro.value)


def test_id_categoria_repetido_no_de_para_e_recusado(tmp_path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        regras_com(
            """
[[mapa_categoria]]
id_categoria = "05070000"
categoria = "Streaming"
grupo = "Lazer"

[[mapa_categoria]]
id_categoria = "05070000"
categoria = "Assinaturas"
grupo = "Fixo"
""",
            tmp_path,
        )

    assert "05070000" in str(erro.value)


def test_padrao_com_maiuscula_e_recusado(tmp_path) -> None:
    """Mesma guarda das outras seções: a comparação usa lower(), então um
    padrão com maiúscula nunca casaria — e falharia calado."""
    with pytest.raises(ErroDeConfiguracao) as erro:
        regras_com(
            """
[[categoria]]
prioridade = 1
padrao = "%Netflix%"
categoria = "Streaming"
grupo = "Lazer"
""",
            tmp_path,
        )

    assert "minúsculas" in str(erro.value)


def test_rotulo_de_saida_aceita_maiuscula(tmp_path) -> None:
    """`categoria` e `grupo` não são padrão LIKE: aparecem como escritos."""
    regras = regras_com(
        """
[[categoria]]
prioridade = 1
padrao = "%netflix%"
categoria = "Streaming de Vídeo"
grupo = "Lazer"
""",
        tmp_path,
    )

    assert regras.categorias[0].categoria == "Streaming de Vídeo"


def test_grupo_obrigatorio(tmp_path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        regras_com(
            """
[[categoria]]
prioridade = 1
padrao = "%netflix%"
categoria = "Streaming"
""",
            tmp_path,
        )

    assert "grupo" in str(erro.value)


def test_secoes_de_categoria_sao_opcionais(tmp_path) -> None:
    """Quem ainda não escreveu nenhuma regra continua com o pipeline rodando —
    tudo cai no rótulo padrão, que é um resultado honesto e visível."""
    caminho = tmp_path / "regras.toml"
    caminho.write_text(
        """
[geral]
data_inicial = 2025-08-01
frescor_dias_padrao = 5
""",
        encoding="utf-8",
    )
    regras = carregar_regras(caminho)

    assert regras.categorias == ()
    assert regras.mapa_categorias == ()
    assert regras.categoria_padrao == CATEGORIA_PADRAO


def test_rotulo_padrao_e_configuravel(tmp_path, banco: Banco) -> None:
    caminho = tmp_path / "regras.toml"
    caminho.write_text(
        REGRAS_MINIMAS.replace(
            "recorrencia_variacao_maxima = 0.15",
            'recorrencia_variacao_maxima = 0.15\ncategoria_padrao = "A classificar"\n'
            'grupo_padrao = "A classificar"',
        ),
        encoding="utf-8",
    )
    regras = carregar_regras(caminho)
    banco.gravar_regras(regras)
    _inserir(banco, "tx-3", "Loja Desconhecida", "99999999")
    aplicar_views(banco, SQL)

    assert categoria_de(banco, "tx-3") == ("A classificar", "A classificar", "padrao")


def test_regras_vao_para_as_tabelas_cfg(banco: Banco, tmp_path) -> None:
    """As views fazem JOIN contra elas; se a carga não acontecer, todo filtro
    silenciosamente não casa nada."""
    regras = regras_com(
        """
[[categoria]]
prioridade = 7
padrao = "%padaria%"
categoria = "Padaria"
grupo = "Essencial"
""",
        tmp_path,
    )
    banco.gravar_regras(regras)

    assert uma(banco, "SELECT count(*) FROM cfg_categorias WHERE prioridade = 7") == (1,)
    assert uma(
        banco, "SELECT count(*) FROM cfg_mapa_categorias"
    ) == (len(regras.mapa_categorias),)


# ---------------------------------------------------------------------------
# Auxiliar
# ---------------------------------------------------------------------------


def _inserir(
    banco: Banco,
    id_transacao: str,
    descricao: str,
    id_categoria: str,
    estabelecimento: str | None = None,
) -> None:
    """Insere uma transação sintética direto na raw.

    Vai direto ao banco de propósito: o que está sendo testado é a resolução em
    SQL, e passar pela ingestão só acrescentaria partes móveis irrelevantes.
    """
    banco.conexao.execute(
        """
        INSERT INTO raw_transacoes (
            id, id_conta, id_item, instituicao, descricao, valor, moeda, data,
            tipo, situacao, categoria, id_categoria, estabelecimento_nome,
            payload_json, ingerido_em, atualizado_em
        ) VALUES (?, 'conta-x', 'item-x', 'Nubank', ?, -10.00, 'BRL', ?,
                  'DEBIT', 'POSTED', 'Qualquer', ?, ?, '{}', ?, ?)
        """,
        [
            id_transacao,
            descricao,
            date(2025, 9, 1),
            id_categoria,
            estabelecimento,
            datetime(2025, 9, 20, 10, 0, 0),
            datetime(2025, 9, 20, 10, 0, 0),
        ],
    )
