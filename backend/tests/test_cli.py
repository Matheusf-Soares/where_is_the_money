"""
Testes da CLI.

O foco está nos **códigos de saída**, porque é assim que a CLI será usada: em
`cron` e em script, onde ninguém lê a saída na hora. Um `frescor` que devolve 0
com dado velho é uma armadilha 4 não detectada.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from financas.cli import (
    SAIDA_DADOS_VELHOS,
    SAIDA_ERRO,
    SAIDA_INGESTAO_PARCIAL,
    SAIDA_OK,
    SAIDA_SEM_DADOS,
    main,
)

from conftest import FIXTURES_PLUGGY, RAIZ


# ---------------------------------------------------------------------------
# Ingestão vazia e empacotamento
#
# Os dois blocos abaixo protegem coisas que a suíte não pegava: uma ingestão
# que não traz nada mas sai com código 0, e uma instalação que faz `python -m
# financas` morrer com "No module named financas" enquanto todos os testes
# passam (o `pythonpath` do pyproject vale só para o pytest).
# ---------------------------------------------------------------------------


def test_ingerir_sem_itens_falha_alto(tmp_path, projeto) -> None:
    """Ingestão vazia não pode sair com 0.

    O banco fica vazio, as views rodam sem erro, o dashboard abre mostrando
    R$ 0,00 — e nada em lugar nenhum diz que houve problema. É a falha
    silenciosa que este projeto existe para combater.
    """
    fixtures_vazias = tmp_path / "vazio"
    fixtures_vazias.mkdir()
    (fixtures_vazias / "items.json").write_text("[]", encoding="utf-8")

    codigo = main(
        ["--banco", str(tmp_path / "b.duckdb"), "ingerir", "--hoje", "2025-09-20"],
        ambiente={"FINANCAS_FIXTURES": str(fixtures_vazias)},
        raiz=projeto,
    )

    assert codigo == SAIDA_SEM_DADOS


def test_diagnostico_de_lista_vazia_explica_os_dois_portais(capsys, tmp_path, projeto) -> None:
    """A mensagem precisa apontar a causa real, não só constatar o vazio.

    Quase sempre é a confusão entre meu.pluggy.ai e dashboard.pluggy.ai: os
    bancos foram autorizados de um lado e a aplicação vive do outro, sem o item
    do conector MeuPluggy fazendo a ponte.
    """
    fixtures_vazias = tmp_path / "vazio"
    fixtures_vazias.mkdir()
    (fixtures_vazias / "items.json").write_text("[]", encoding="utf-8")

    main(
        ["--banco", str(tmp_path / "b.duckdb"), "ingerir", "--hoje", "2025-09-20"],
        ambiente={"FINANCAS_FIXTURES": str(fixtures_vazias)},
        raiz=projeto,
    )
    erro = capsys.readouterr().err

    assert "MeuPluggy" in erro
    assert "dashboard.pluggy.ai" in erro
    assert "meu.pluggy.ai" in erro


def test_pyproject_declara_como_instalar() -> None:
    """Sem `[build-system]`, `pip install -e .` fica a cargo do palpite do pip."""
    import tomllib

    pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["packages"]["find"]["where"] == ["src"]


def test_ponto_de_entrada_do_executavel_existe() -> None:
    """`[project.scripts]` aponta para uma string; um erro de digitação ali só
    apareceria na hora de rodar `financas`, fora de qualquer teste."""
    import tomllib

    pyproject = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    alvo = pyproject["project"]["scripts"]["financas"]
    modulo, _, funcao = alvo.partition(":")

    importado = __import__(modulo, fromlist=[funcao])

    assert callable(getattr(importado, funcao))


@pytest.fixture
def ambiente(projeto: Path) -> dict[str, str]:
    """Projeto temporário com banco próprio, apontando para as fixtures reais."""
    return {
        "FINANCAS_FIXTURES": str(FIXTURES_PLUGGY),
        "FINANCAS_BANCO": str(projeto / "dados" / "teste.duckdb"),
    }


def rodar(argv: list[str], ambiente: dict[str, str], projeto: Path) -> int:
    return main(argv, ambiente=ambiente, raiz=projeto)


# ---------------------------------------------------------------------------
# ingerir
# ---------------------------------------------------------------------------


def test_ingerir_sai_zero_e_grava(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    codigo = rodar(["ingerir", "--hoje", "2025-09-20"], ambiente, projeto)

    saida = capsys.readouterr().out
    assert codigo == SAIDA_OK
    assert "27 recebidas, 27 novas" in saida
    assert Path(ambiente["FINANCAS_BANCO"]).is_file()


def test_ingerir_duas_vezes_relata_zero_mudancas(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    rodar(["ingerir", "--hoje", "2025-09-20"], ambiente, projeto)
    capsys.readouterr()

    codigo = rodar(["ingerir", "--hoje", "2025-09-20"], ambiente, projeto)

    assert codigo == SAIDA_OK
    assert "0 novas, 0 atualizadas, 27 sem mudança" in capsys.readouterr().out


def test_ingerir_aceita_recorte_de_data(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    codigo = rodar(
        ["ingerir", "--hoje", "2025-09-20", "--desde", "2025-09-01"], ambiente, projeto
    )

    assert codigo == SAIDA_OK
    assert "20 recebidas" in capsys.readouterr().out


def test_data_malformada_e_recusada_pelo_argparse(
    ambiente: dict[str, str], projeto: Path
) -> None:
    with pytest.raises(SystemExit) as saida:
        rodar(["ingerir", "--desde", "20/09/2025"], ambiente, projeto)

    assert saida.value.code == 2  # convenção do argparse para uso errado


# ---------------------------------------------------------------------------
# frescor
# ---------------------------------------------------------------------------


def test_frescor_sai_dois_quando_ha_dado_velho(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    """O requisito da armadilha 4: código de saída não-zero."""
    rodar(["ingerir", "--hoje", "2025-09-20"], ambiente, projeto)
    capsys.readouterr()

    codigo = rodar(["frescor", "--hoje", "2025-09-20"], ambiente, projeto)

    capturado = capsys.readouterr()
    assert codigo == SAIDA_DADOS_VELHOS
    assert "PicPay" in capturado.out and "ATRASADA" in capturado.out
    assert "meu.pluggy.ai" in capturado.err


def test_frescor_sai_zero_quando_tudo_esta_em_dia(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    """Com data de referência logo após o último movimento do PicPay, nada está
    atrasado."""
    rodar(["ingerir", "--hoje", "2025-08-07"], ambiente, projeto)
    capsys.readouterr()

    codigo = rodar(["frescor", "--hoje", "2025-08-07"], ambiente, projeto)

    assert codigo == SAIDA_OK
    assert "ATRASADA" not in capsys.readouterr().out


def test_frescor_com_banco_vazio_nao_finge_que_esta_ok(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    codigo = rodar(["frescor"], ambiente, projeto)

    assert codigo == SAIDA_ERRO
    assert "Rode 'ingerir'" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# views
# ---------------------------------------------------------------------------


def test_views_recarrega_a_configuracao(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    codigo = rodar(["views"], ambiente, projeto)

    assert codigo == SAIDA_OK
    assert "configuração recarregada" in capsys.readouterr().out


def test_views_aplica_os_arquivos_sql(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    diretorio = projeto / "sql" / "marts"
    diretorio.mkdir(parents=True)
    (diretorio / "gastos.sql").write_text(
        "CREATE OR REPLACE VIEW gastos AS "
        "SELECT id, valor FROM raw_transacoes WHERE valor < 0",
        encoding="utf-8",
    )

    rodar(["ingerir", "--hoje", "2025-09-20"], ambiente, projeto)
    capsys.readouterr()
    codigo = rodar(["views", "--sql", str(projeto / "sql")], ambiente, projeto)

    assert codigo == SAIDA_OK
    assert "marts/gastos" in capsys.readouterr().out


def test_view_quebrada_reporta_o_arquivo(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    diretorio = projeto / "sql" / "marts"
    diretorio.mkdir(parents=True)
    (diretorio / "quebrada.sql").write_text("SELECT * FROM tabela_inexistente", encoding="utf-8")

    codigo = rodar(["views", "--sql", str(projeto / "sql")], ambiente, projeto)

    assert codigo == SAIDA_ERRO
    assert "quebrada.sql" in capsys.readouterr().err


def test_staging_e_aplicado_antes_de_marts(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    """Marts consulta staging, então a ordem não pode ser alfabética global."""
    (projeto / "sql" / "staging").mkdir(parents=True)
    (projeto / "sql" / "marts").mkdir(parents=True)
    (projeto / "sql" / "staging" / "zzz.sql").write_text(
        "CREATE OR REPLACE VIEW stg_teste AS SELECT 1 AS n", encoding="utf-8"
    )
    (projeto / "sql" / "marts" / "aaa.sql").write_text(
        "CREATE OR REPLACE VIEW mart_teste AS SELECT n FROM stg_teste", encoding="utf-8"
    )

    codigo = rodar(["views", "--sql", str(projeto / "sql")], ambiente, projeto)

    assert codigo == SAIDA_OK
    assert "staging/zzz" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_com_banco_inexistente_orienta(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    codigo = rodar(["status"], ambiente, projeto)

    assert codigo == SAIDA_OK
    assert "Rode 'ingerir'" in capsys.readouterr().out


def test_status_mostra_contagens_e_periodo(
    ambiente: dict[str, str], projeto: Path, capsys
) -> None:
    rodar(["ingerir", "--hoje", "2025-09-20"], ambiente, projeto)
    capsys.readouterr()

    codigo = rodar(["status"], ambiente, projeto)

    saida = capsys.readouterr().out
    assert codigo == SAIDA_OK
    assert "raw_transacoes                   27" in saida
    assert "2025-08-02 a 2025-09-16" in saida


# ---------------------------------------------------------------------------
# Erros e overrides
# ---------------------------------------------------------------------------


def test_configuracao_invalida_sai_um_com_mensagem_util(
    projeto: Path, capsys
) -> None:
    codigo = main(["status"], ambiente={"FINANCAS_MODO": "online"}, raiz=projeto)

    assert codigo == SAIDA_ERRO
    assert "PLUGGY_CLIENT_ID" in capsys.readouterr().err


def test_banco_da_linha_de_comando_vence_o_ambiente(
    ambiente: dict[str, str], projeto: Path
) -> None:
    outro = projeto / "outro.duckdb"

    main(
        ["--banco", str(outro), "ingerir", "--hoje", "2025-09-20"],
        ambiente=ambiente,
        raiz=projeto,
    )

    assert outro.is_file()
    assert not Path(ambiente["FINANCAS_BANCO"]).exists()


def test_ingestao_parcial_tem_codigo_proprio(
    ambiente: dict[str, str], projeto: Path, monkeypatch, capsys
) -> None:
    """Falha de uma instituição não é sucesso nem erro total: tem código só dela."""
    from financas.pluggy import ClienteFixtures, ConsentimentoExpirado

    original = ClienteFixtures.listar_contas

    def falhar(self, id_item):
        if id_item == "item-nubank":
            raise ConsentimentoExpirado("HTTP 403: consentimento vencido")
        return original(self, id_item)

    monkeypatch.setattr(ClienteFixtures, "listar_contas", falhar)

    codigo = rodar(["ingerir", "--hoje", "2025-09-20"], ambiente, projeto)

    assert codigo == SAIDA_INGESTAO_PARCIAL
    assert "FALHOU  Nubank" in capsys.readouterr().err


def test_comando_ausente_e_erro_de_uso(projeto: Path) -> None:
    with pytest.raises(SystemExit) as saida:
        main([], ambiente={}, raiz=projeto)

    assert saida.value.code == 2
