"""
Testes da publicação para o frontend.

O frontend é estático: ele lê exatamente o que este módulo escreveu, e não tem
como perguntar nada de volta. Isso muda o que precisa ser testado — não basta
"o arquivo foi criado". Três coisas importam:

1. **Os Parquet reproduzem as views.** Se `gastos.parquet` tiver contagem ou
   total diferente de `gastos`, a tela mostra um número que não existe em lugar
   nenhum do backend, e nenhum teste do backend acusaria.
2. **Não sobra arquivo de publicação anterior.** Parquet órfão apareceria na
   tela como dado atual.
3. **Os avisos disparam.** Um dashboard mostrando R$ 0,00 sem explicar por quê
   é pior que um erro: parece resposta.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import pytest

from financas.persistencia import Banco
from financas.publicacao import (
    NOME_DO_MANIFESTO,
    TABELAS_PUBLICADAS,
    ErroDePublicacao,
    publicar,
)


def ler_parquet(caminho, consulta: str):
    return duckdb.connect().execute(consulta.format(arquivo=caminho.as_posix())).fetchone()


def arquivo_publicado(destino, tabela):
    manifesto = json.loads((destino / NOME_DO_MANIFESTO).read_text(encoding="utf-8"))
    return destino / manifesto["arquivos"][tabela]


# ---------------------------------------------------------------------------
# Fidelidade: o que está no disco é o que a view diz
# ---------------------------------------------------------------------------


def test_publica_todas_as_tabelas(banco_com_views: Banco, tmp_path) -> None:
    resultado = publicar(banco_com_views, tmp_path / "dados")

    for tabela in TABELAS_PUBLICADAS:
        assert arquivo_publicado(tmp_path / "dados", tabela).is_file()
    assert set(resultado.linhas) == set(TABELAS_PUBLICADAS)


def test_parquet_de_gastos_bate_com_a_view(banco_com_views: Banco, tmp_path) -> None:
    """A asserção que impede a tela de inventar número.

    Conferir contagem **e** soma: um erro de tipo no COPY poderia preservar o
    número de linhas e estragar o DECIMAL, e só o total acusaria.
    """
    destino = tmp_path / "dados"
    publicar(banco_com_views, destino)

    do_banco = banco_com_views.conexao.execute(
        "SELECT count(*), sum(valor) FROM gastos"
    ).fetchone()
    do_disco = ler_parquet(
        arquivo_publicado(destino, "gastos"),
        "SELECT count(*), sum(valor) FROM read_parquet('{arquivo}')",
    )

    assert do_disco == do_banco


def test_parquet_preserva_as_bandeiras_de_auditoria(
    banco_com_views: Banco, tmp_path
) -> None:
    """Sem elas a aba Auditoria não responde 'por que esse gasto sumiu?'."""
    destino = tmp_path / "dados"
    publicar(banco_com_views, destino)

    colunas = {
        linha[0]
        for linha in duckdb.connect()
        .execute(
            f"DESCRIBE SELECT * FROM read_parquet("
            f"'{arquivo_publicado(destino, 'stg_transacoes').as_posix()}')"
        )
        .fetchall()
    }

    assert {
        "e_pagamento_de_fatura",
        "e_transferencia_propria",
        "e_aplicacao",
        "origem_da_categoria",
        "categoria",
        "categoria_pluggy",
        "grupo",
    } <= colunas


def test_publicar_e_idempotente(banco_com_views: Banco, tmp_path) -> None:
    destino = tmp_path / "dados"

    primeira = publicar(banco_com_views, destino)
    segunda = publicar(banco_com_views, destino)

    assert primeira.linhas == segunda.linhas


def test_parquet_orfao_nao_e_publicado(banco_com_views: Banco, tmp_path) -> None:
    """Só os caminhos do manifesto são publicados; arquivos avulsos são preservados."""
    destino = tmp_path / "dados"
    destino.mkdir()
    (destino / "tabela_que_nao_existe_mais.parquet").write_bytes(b"lixo")

    publicar(banco_com_views, destino)

    manifesto = json.loads((destino / NOME_DO_MANIFESTO).read_text(encoding="utf-8"))
    assert "tabela_que_nao_existe_mais" not in manifesto["arquivos"]
    assert (destino / "tabela_que_nao_existe_mais.parquet").read_bytes() == b"lixo"


def test_nao_apaga_arquivo_que_nao_e_nosso(banco_com_views: Banco, tmp_path) -> None:
    """A limpeza é seletiva de propósito: o destino pode ser um diretório que o
    usuário usa para outra coisa, e `rmtree` seria um jeito caro de descobrir."""
    destino = tmp_path / "dados"
    destino.mkdir()
    (destino / "anotacoes.txt").write_text("não me apague", encoding="utf-8")

    publicar(banco_com_views, destino)

    assert (destino / "anotacoes.txt").read_text(encoding="utf-8") == "não me apague"


# ---------------------------------------------------------------------------
# Manifesto
# ---------------------------------------------------------------------------


def test_manifesto_carimba_quando_e_de_quando(banco_com_views: Banco, tmp_path) -> None:
    """A tela mostra um retrato, não tempo real. Sem a data, quem olha não tem
    como saber se está vendo dado de hoje ou de três semanas atrás."""
    destino = tmp_path / "dados"
    momento = datetime(2025, 9, 20, 12, 0, tzinfo=timezone.utc)

    publicar(banco_com_views, destino, agora=momento)
    manifesto = json.loads((destino / NOME_DO_MANIFESTO).read_text(encoding="utf-8"))

    assert manifesto["gerado_em"].startswith("2025-09-20T12:00")
    assert manifesto["periodo"]["primeira_transacao"] == "2025-08-02"
    assert manifesto["periodo"]["ultima_transacao"] == "2025-09-16"
    assert manifesto["linhas"]["stg_transacoes"] == 27


def test_manifesto_e_json_valido_e_legivel(banco_com_views: Banco, tmp_path) -> None:
    destino = tmp_path / "dados"
    publicar(banco_com_views, destino)

    texto = (destino / NOME_DO_MANIFESTO).read_text(encoding="utf-8")

    assert json.loads(texto)["tabelas"] == list(TABELAS_PUBLICADAS)


# ---------------------------------------------------------------------------
# Avisos: o que a tela precisa dizer em voz alta
# ---------------------------------------------------------------------------


def test_avisa_quando_a_pluggy_nao_categorizou_nada(banco: Banco, tmp_path) -> None:
    """O caso da conta gratuita.

    Categorização é premium: sem ela `category` vem nulo em tudo, o de-para não
    resolve nada e só as regras por texto atuam. A tela precisa dizer isso, e
    não exibir um gráfico vazio que parece resposta.
    """
    from financas.config import carregar_regras
    from financas.views import aplicar_views

    from conftest import RAIZ, REGRAS_MINIMAS

    caminho = tmp_path / "regras.toml"
    caminho.write_text(REGRAS_MINIMAS, encoding="utf-8")
    banco.gravar_regras(carregar_regras(caminho))
    banco.conexao.execute(
        """
        INSERT INTO raw_transacoes (id, id_conta, instituicao, descricao, valor,
            data, tipo, situacao, categoria, payload_json, ingerido_em, atualizado_em)
        VALUES ('tx-sem-cat', 'c1', 'Nubank', 'Padaria', -10.00, DATE '2025-09-01',
                'DEBIT', 'POSTED', NULL, '{}', now(), now())
        """
    )
    aplicar_views(banco, RAIZ / "sql")

    resultado = publicar(banco, tmp_path / "dados")

    assert any("premium" in aviso for aviso in resultado.avisos)


def test_avisa_sobre_cobertura_baixa(banco_com_views: Banco, tmp_path) -> None:
    """As regras do conftest cobrem só parte das fixtures, de propósito — é
    assim que as três camadas de resolução ficam exercitadas. O efeito colateral
    é cobertura de 60%, e a tela precisa avisar: um gráfico "por categoria" com
    40% em 'Sem categoria' induz a conclusão errada se não disser isso."""
    resultado = publicar(banco_com_views, tmp_path / "dados")

    assert any("sem categoria" in aviso for aviso in resultado.avisos)


def test_nao_avisa_de_premium_quando_a_categoria_veio(
    banco_com_views: Banco, tmp_path
) -> None:
    """As fixtures trazem `category` preenchido, então o aviso da conta gratuita
    não pode disparar — senão ele viraria ruído e ninguém leria nenhum aviso."""
    resultado = publicar(banco_com_views, tmp_path / "dados")

    assert not any("premium" in aviso for aviso in resultado.avisos)


# ---------------------------------------------------------------------------
# Falhas
# ---------------------------------------------------------------------------


def test_publicar_sem_views_falha_dizendo_o_que_fazer(banco: Banco, tmp_path) -> None:
    """Mesmo padrão do config.py: a mensagem aponta o comando que resolve."""
    with pytest.raises(ErroDePublicacao) as erro:
        publicar(banco, tmp_path / "dados")

    assert "financas views" in str(erro.value)


def test_cria_o_destino_se_nao_existir(banco_com_views: Banco, tmp_path) -> None:
    destino = tmp_path / "fundo" / "do" / "poco"

    publicar(banco_com_views, destino)

    assert arquivo_publicado(destino, "gastos").is_file()
