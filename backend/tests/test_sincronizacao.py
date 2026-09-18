"""Sincronização não é inferida a partir da última compra."""
from datetime import date

from financas.ingestao import ingerir
from financas.pluggy import criar_cliente
from test_ingestao import ClienteComFalha, ClienteComItemDoente


def test_reingestao_sem_mudancas_atualiza_sucesso_mas_nao_raw(banco, config_offline):
    cliente = criar_cliente(config_offline)
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 20))
    raw_antes = banco.conexao.execute("SELECT id, atualizado_em FROM raw_transacoes ORDER BY id").fetchall()
    banco.conexao.execute("UPDATE log_sincronizacoes SET sucesso_em = TIMESTAMP '2000-01-01'")
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 21))
    registros = banco.conexao.execute("SELECT estado, sucesso_em, desde, ate FROM log_sincronizacoes").fetchall()
    assert len(registros) == 5
    assert all(estado == "sucesso" and sucesso.year > 2000 and ate == date(2025, 9, 21)
               for estado, sucesso, desde, ate in registros)
    assert banco.conexao.execute("SELECT id, atualizado_em FROM raw_transacoes ORDER BY id").fetchall() == raw_antes


def test_falha_preserva_ultima_cobertura_completa(banco, config_offline):
    cliente = criar_cliente(config_offline)
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 20))
    anterior = banco.conexao.execute("SELECT sucesso_em, desde, ate FROM log_sincronizacoes WHERE instituicao='Nubank'").fetchone()
    ingerir(ClienteComFalha(cliente, "item-nubank"), banco, config_offline.regras, hoje=date(2025, 9, 21))
    estado, sucesso, desde, ate = banco.conexao.execute("SELECT estado, sucesso_em, desde, ate FROM log_sincronizacoes WHERE instituicao='Nubank'").fetchone()
    assert estado == "falha"
    assert (sucesso, desde, ate) == anterior


def test_coleta_com_acao_pendente_nao_afirma_sincronizacao_saudavel(banco, config_offline):
    cliente = ClienteComItemDoente(criar_cliente(config_offline), status="WAITING_USER_INPUT", userAction="INPUT_MFA")
    ingerir(cliente, banco, config_offline.regras, hoje=date(2025, 9, 20))
    assert banco.conexao.execute("SELECT count(*) FROM log_sincronizacoes WHERE estado='acao_necessaria'").fetchone()[0] == 1
