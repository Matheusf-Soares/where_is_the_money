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

    tx-nu-b-05  Netflix.com     09020000  (Video streaming)  regra E mapa -> a regra tem que vencer
    tx-nu-c-02  Spotify         09020000  só mapa
    tx-nu-c-01  Uber *Trip      04000000  só regra
    tx-in-b-03  Academia        05060000  só mapa
    tx-sa-c-01  Restaurante Xis 05020000  nenhum  -> rótulo padrão
"""

from __future__ import annotations

import tomllib
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest

from financas.categorias import GRUPO_A_DEFINIR, auditar, gerar_de_para
from financas.config import (
    CATEGORIA_PADRAO,
    GRUPO_PADRAO,
    Configuracao,
    ErroDeConfiguracao,
    carregar_regras,
)
from financas.persistencia import Banco
from financas.pluggy import ClienteFixtures, ClienteHttp
from financas.views import aplicar_views

from conftest import FIXTURES_PLUGGY, RAIZ, REGRAS_MINIMAS

SQL = RAIZ / "sql"


def uma(banco: Banco, consulta: str):
    return banco.conexao.execute(consulta).fetchone()


def categoria_de(banco: Banco, id_transacao: str) -> tuple[str, str, str]:
    """Devolve (categoria, grupo, origem) de uma transação."""
    return uma(
        banco,
        "SELECT categoria, grupo, origem_da_categoria FROM stg_transacoes "
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

    Netflix casa a regra `%netflix%` e também o de-para de 09020000. Se o
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
    _inserir(banco, "tx-1", "Supermercado Big Centro", "10000000")
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
        "WHERE categoria IS NULL OR grupo IS NULL",
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
        "SELECT categoria_pluggy, id_categoria FROM stg_transacoes "
        "WHERE id_transacao = 'tx-nu-b-05'",
    )

    assert (categoria_pluggy, id_categoria) == ("Video streaming", "09020000")


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
id_categoria = "09020000"
categoria = "Streaming"
grupo = "Lazer"

[[mapa_categoria]]
id_categoria = "09020000"
categoria = "Assinaturas"
grupo = "Fixo"
""",
            tmp_path,
        )

    assert "09020000" in str(erro.value)


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
# Sincronização da taxonomia (GET /categories)
# ---------------------------------------------------------------------------

TAXONOMIA = [
    {"id": "05000000", "description": "Transfers", "descriptionTranslated": "Transferências"},
    {
        "id": "05080000",
        "description": "Transfer - TED",
        "descriptionTranslated": "Transferência - TED",
        "parentId": "05000000",
        "parentDescription": "Transfers",
    },
]


def test_de_para_gerado_e_toml_valido() -> None:
    """O bloco gerado vai ser colado num arquivo que o tomllib relê.

    Uma aspa solta num nome de categoria quebraria o parse com erro que não
    aponta para a causa — daí o escape e daí este teste.
    """
    texto = gerar_de_para(TAXONOMIA)

    lido = tomllib.loads(texto)

    assert [m["id_categoria"] for m in lido["mapa_categoria"]] == [
        "05000000",
        "05080000",
    ]
    assert all(m["grupo"] == GRUPO_A_DEFINIR for m in lido["mapa_categoria"])


def test_de_para_usa_a_traducao_como_rotulo() -> None:
    lido = tomllib.loads(gerar_de_para(TAXONOMIA))

    assert lido["mapa_categoria"][0]["categoria"] == "Transferências"


def test_de_para_escapa_aspas_no_nome() -> None:
    texto = gerar_de_para(
        [{"id": "01000000", "description": 'Categoria "estranha"'}]
    )

    assert tomllib.loads(texto)["mapa_categoria"][0]["categoria"] == (
        'Categoria "estranha"'
    )


def test_de_para_comenta_o_que_ja_esta_mapeado(tmp_path) -> None:
    """Colar o bloco duas vezes geraria id repetido, que a validação recusa."""
    regras = regras_com(
        """
[[mapa_categoria]]
id_categoria = "05000000"
categoria = "Transferências"
grupo = "Neutro"
""",
        tmp_path,
    )

    lido = tomllib.loads(gerar_de_para(TAXONOMIA, existentes=regras))

    assert [m["id_categoria"] for m in lido["mapa_categoria"]] == ["05080000"]


def test_taxonomia_vazia_avisa_sobre_a_feature_premium() -> None:
    """Categorização é opt-in pago na Pluggy. Sem ela, `category` vem nulo em
    todas as transações e esta camada inteira não tem o que fazer — o gerador
    precisa dizer isso, não devolver um arquivo vazio sem explicação."""
    texto = gerar_de_para([])

    assert "premium" in texto
    assert tomllib.loads(texto) == {}


def test_cliente_offline_le_a_taxonomia() -> None:
    categorias = ClienteFixtures(FIXTURES_PLUGGY).listar_categorias()

    # Ids REAIS de GET /categories: Video streaming e Credit card payment.
    # Os anteriores (05070000, 07000000) eram inventados e significam outra
    # coisa na taxonomia de verdade.
    assert {c["id"] for c in categorias} >= {"09020000", "05100000"}


def test_cliente_offline_tolera_taxonomia_ausente(tmp_path) -> None:
    """Ausência é legítima: quem não tem a feature não recebe categoria."""
    assert ClienteFixtures(tmp_path).listar_categorias() == []


def test_cliente_http_aceita_array_puro(config_online: Configuracao) -> None:
    """`GET /categories` foge do padrão: devolve array, não {'results': [...]}."""

    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "chave"})
        return httpx.Response(200, json=TAXONOMIA)

    with ClienteHttp(
        config_online, transporte=httpx.MockTransport(atender), dormir=lambda _s: None
    ) as cliente:
        assert [c["id"] for c in cliente.listar_categorias()] == [
            "05000000",
            "05080000",
        ]


def test_cliente_http_aceita_envelope_results(config_online: Configuracao) -> None:
    def atender(requisicao: httpx.Request) -> httpx.Response:
        if requisicao.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "chave"})
        return httpx.Response(200, json={"results": TAXONOMIA})

    with ClienteHttp(
        config_online, transporte=httpx.MockTransport(atender), dormir=lambda _s: None
    ) as cliente:
        assert len(cliente.listar_categorias()) == 2


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


def test_auditoria_acusa_regra_que_nunca_casou(banco: Banco, tmp_path) -> None:
    """O ponto inteiro do comando. Regra que não casa é filtro que não filtra,
    e sem isso ela fica lá para sempre sem ninguém perceber."""
    regras = regras_com(
        """
[[categoria]]
prioridade = 99
padrao = "%estabelecimento que nao existe%"
categoria = "Fantasma"
grupo = "Lazer"
""",
        tmp_path,
    )
    banco.gravar_regras(regras)
    _inserir(banco, "tx-9", "Supermercado Big", "10000000")
    aplicar_views(banco, SQL)

    resultado = auditar(banco)

    assert 99 in {prioridade for prioridade, _ in resultado.regras_mortas}
    assert resultado.tem_alerta


def test_auditoria_nao_acusa_regra_viva(banco_com_views: Banco) -> None:
    resultado = auditar(banco_com_views)

    assert resultado.regras_mortas == ()
    assert not resultado.tem_alerta


def test_auditoria_mede_a_cobertura(banco_com_views: Banco) -> None:
    resultado = auditar(banco_com_views)

    assert resultado.total_transacoes > 0
    assert 0 < resultado.fracao_sem_categoria < 1


def test_auditoria_ignora_o_que_ja_e_excluido(banco_com_views: Banco) -> None:
    """A lista de trabalho não pode mandar você categorizar pagamento de fatura:
    ele nunca chega em `gastos`, então o de-para não mudaria nada."""
    pendentes = {
        id_categoria
        for id_categoria, _, _ in auditar(banco_com_views).ids_sem_de_para
    }

    excluidas = {
        linha[0]
        for linha in banco_com_views.conexao.execute(
            "SELECT DISTINCT id_categoria FROM stg_transacoes "
            "WHERE e_pagamento_de_fatura OR e_transferencia_propria OR e_aplicacao"
        ).fetchall()
        if linha[0]
    }

    assert not (pendentes & excluidas)


# ---------------------------------------------------------------------------
# Categoria reforçando as armadilhas 1, 2 e 3
# ---------------------------------------------------------------------------


def test_categoria_marca_fatura_que_o_texto_nao_pegou(banco: Banco, tmp_path) -> None:
    """O caso que justifica o reforço: redação que nenhum padrão previu."""
    regras = regras_com(
        """
[[categoria_ruido]]
bandeira = "fatura"
padrao = "credit card payment"
""",
        tmp_path,
    )
    banco.gravar_regras(regras)
    _inserir(banco, "tx-f", "QUITACAO MENSAL PLASTICO", "05100000", categoria="Credit card payment")
    aplicar_views(banco, SQL)

    (marcado,) = uma(
        banco,
        "SELECT e_pagamento_de_fatura FROM stg_transacoes WHERE id_transacao = 'tx-f'",
    )

    assert marcado


def test_categoria_marca_transferencia_propria_sem_lista_de_chaves(
    banco: Banco, tmp_path
) -> None:
    """`Same person transfer` não depende de você ter escrito cada chave Pix."""
    regras = regras_com(
        """
[[categoria_ruido]]
bandeira = "transferencia_propria"
padrao = "same person transfer%"
""",
        tmp_path,
    )
    banco.gravar_regras(regras)
    _inserir(
        banco,
        "tx-t",
        "TRANSF ENTRE CONTAS 998877",
        "04000000",
        categoria="Same person transfer - PIX",
    )
    aplicar_views(banco, SQL)

    (marcado,) = uma(
        banco,
        "SELECT e_transferencia_propria FROM stg_transacoes WHERE id_transacao = 'tx-t'",
    )

    assert marcado


def test_reforco_e_or_e_nao_substituicao(banco: Banco, tmp_path) -> None:
    """Com a categorização desligada na conta, `categoria` vem nula — e o filtro
    por texto tem que continuar sendo tudo que existe."""
    regras = regras_com(
        """
[[categoria_ruido]]
bandeira = "fatura"
padrao = "credit card payment"
""",
        tmp_path,
    )
    banco.gravar_regras(regras)
    # Sem categoria nenhuma, mas com a redação que o texto reconhece.
    _inserir(banco, "tx-s", "Pagamento de fatura", "", categoria=None)
    aplicar_views(banco, SQL)

    (marcado,) = uma(
        banco,
        "SELECT e_pagamento_de_fatura FROM stg_transacoes WHERE id_transacao = 'tx-s'",
    )

    assert marcado


def test_sem_categoria_ruido_o_comportamento_nao_muda(banco_com_views: Banco) -> None:
    """As regras do conftest não têm `[[categoria_ruido]]`.

    Se o reforço marcasse alguma coisa por conta própria, os testes das
    armadilhas passariam a medir outra coisa sem ninguém perceber — e o total
    do contrato mudaria em silêncio. Esta é a asserção que amarra as duas
    pontas: tabela vazia, total idêntico ao de `test_views`.
    """
    assert uma(banco_com_views, "SELECT count(*) FROM cfg_categorias_ruido") == (0,)
    assert uma(banco_com_views, "SELECT count(*), sum(valor) FROM gastos") == (
        15,
        Decimal("1434.75"),
    )


def test_bandeira_invalida_e_recusada(tmp_path) -> None:
    with pytest.raises(ErroDeConfiguracao) as erro:
        regras_com(
            """
[[categoria_ruido]]
bandeira = "inventada"
padrao = "qualquer coisa"
""",
            tmp_path,
        )

    assert "bandeira" in str(erro.value)


# ---------------------------------------------------------------------------
# Auxiliar
# ---------------------------------------------------------------------------


def test_categoria_pega_transferencia_que_o_texto_nao_pegaria(
    banco_com_views: Banco,
) -> None:
    """A segunda rede da armadilha 2, sozinha.

    Descrição opaca: nenhum padrão de contraparte casa, porque não há nome,
    documento nem chave no texto. O que marca é a categoria nativa da Pluggy.

    Este é o caso que justifica `cfg_categorias_ruido` existir. A lista de
    contrapartes depende de você ter escrito seu nome e cada chave, em cada
    formato; `Same person transfer` não depende de nada disso.
    """
    banco_com_views.conexao.execute(
        "INSERT INTO cfg_categorias_ruido VALUES "
        "('transferencia_propria', 'same person transfer%', '')"
    )
    _inserir(
        banco_com_views,
        "tx-opaca",
        "TRANSFERENCIA 000123456",
        "04020000",
        categoria="Same person transfer - PIX",
    )

    (marcada,) = banco_com_views.conexao.execute(
        "SELECT e_transferencia_propria FROM stg_transacoes "
        "WHERE id_transacao = 'tx-opaca'"
    ).fetchone()

    assert marcada is True

    # E, marcada, não pode chegar em `gastos`.
    (quantas,) = banco_com_views.conexao.execute(
        "SELECT count(*) FROM gastos WHERE id_transacao = 'tx-opaca'"
    ).fetchone()
    assert quantas == 0


def test_categoria_ruido_reforca_o_texto_em_vez_de_substituir(
    banco_com_views: Banco,
) -> None:
    """Sem categoria da Pluggy, o texto continua sendo tudo que existe.

    Se a feature de categorização estiver desligada na conta, `category` vem
    nulo em toda transação. A bandeira tem que continuar subindo pelo texto —
    senão trocar uma rede pela outra teria só mudado o tipo de falso negativo.
    """
    banco_com_views.conexao.execute(
        "INSERT INTO cfg_categorias_ruido VALUES "
        "('fatura', 'credit card payment', '')"
    )
    _inserir(
        banco_com_views,
        "tx-sem-categoria",
        "PAGAMENTO DE FATURA CARTAO",
        "",
        categoria=None,
    )

    (marcada,) = banco_com_views.conexao.execute(
        "SELECT e_pagamento_de_fatura FROM stg_transacoes "
        "WHERE id_transacao = 'tx-sem-categoria'"
    ).fetchone()

    assert marcada is True


def _inserir(
    banco: Banco,
    id_transacao: str,
    descricao: str,
    id_categoria: str,
    estabelecimento: str | None = None,
    categoria: str | None = "Qualquer",
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
                  'DEBIT', 'POSTED', ?, ?, ?, '{}', ?, ?)
        """,
        [
            id_transacao,
            descricao,
            date(2025, 9, 1),
            categoria,
            id_categoria,
            estabelecimento,
            datetime(2025, 9, 20, 10, 0, 0),
            datetime(2025, 9, 20, 10, 0, 0),
        ],
    )
