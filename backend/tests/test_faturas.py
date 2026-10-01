"""Faturas sintéticas: total oficial, vencimento e vínculo explícito por cartão."""
import json
from datetime import date
from decimal import Decimal

import httpx
from conftest import RAIZ
from financas.normalizacao import normalizar_conta
from financas.pluggy.cliente import ClienteHttp, ErroPluggy
from financas.pluggy.fixtures import ClienteFixtures
from financas.views import aplicar_views

HOJE = date(2026, 9, 18)


def conta(banco, identificador="cartao-a", instituicao="Banco Aurora", tipo="CREDIT"):
    banco.gravar_contas([normalizar_conta({
        "id": identificador, "name": "Cartão principal", "number": "4321",
        "type": tipo, "subtype": "CREDIT_CARD", "balance": 9876,
        "currencyCode": "BRL",
    }, id_item="item-" + identificador, instituicao=instituicao, data_posicao=HOJE)])


def fatura(identificador="fatura-a", **campos):
    return {"id": identificador, "dueDate": "2026-09-10T00:00:00.000Z",
            "billClosingDate": "2026-09-02T00:00:00.000Z", "totalAmount": 650.50,
            "totalAmountCurrencyCode": "BRL", "minimumPaymentAmount": 65.05,
            "allowsInstallments": True,
            "payments": [{"id": "pagamento-a", "amount": 400, "currencyCode": "BRL",
                          "valueType": "FULL_PAYMENT", "paymentMode": "PIX",
                          "paymentDate": "2026-08-10T00:00:00.000Z"}],
            "financeCharges": [{"id": "encargo-a", "type": "IOF", "amount": 0.50,
                                "currencyCode": "BRL"}], **campos}


def transacao(identificador="tx-a", id_conta="cartao-a", **campos):
    return {"id": identificador, "accountId": id_conta, "amount": 100,
            "currencyCode": "BRL", "type": "DEBIT", "status": "POSTED",
            "description": "Mercado de exemplo", "date": "2026-08-28",
            "creditCardMetadata": {"billId": "fatura-a"}, **campos}


def cliente_fixture(tmp_path, *, faturas=None, transacoes=None):
    for pasta, registros in (("bills", faturas or {}), ("transactions", transacoes or {})):
        (tmp_path / pasta).mkdir(exist_ok=True)
        for identificador, dados in registros.items():
            (tmp_path / pasta / f"{identificador}.json").write_text(json.dumps(dados), encoding="utf-8")
    return ClienteFixtures(tmp_path)


def coletar(cliente, banco, config):
    from financas.faturas import coletar_faturas
    banco.gravar_regras(config.regras)
    resultado = coletar_faturas(cliente, banco, config.regras, hoje=HOJE)
    aplicar_views(banco, RAIZ / "sql")
    return resultado


def test_cliente_faturas_pagina_ate_o_fim(config_online):
    chamadas = []
    def atender(req):
        if req.url.path == "/auth":
            return httpx.Response(200, json={"apiKey": "teste"})
        chamadas.append(req)
        pagina = int(req.url.params["page"])
        return httpx.Response(200, json={"page": pagina, "totalPages": 2,
                                        "results": [fatura(f"f-{pagina}")]})
    with ClienteHttp(config_online, transporte=httpx.MockTransport(atender)) as cliente:
        assert [f["id"] for f in cliente.listar_faturas("cartao-a")] == ["f-1", "f-2"]
    assert [r.url.path for r in chamadas] == ["/bills", "/bills"]
    assert all(r.url.params["accountId"] == "cartao-a" for r in chamadas)


def test_total_oficial_vencimento_e_metadados_nao_dependem_do_saldo_ou_gastos(banco, config_offline, tmp_path):
    conta(banco)
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]},
                              transacoes={"cartao-a": [transacao()]})
    resumo = coletar(cliente, banco, config_offline)
    assert (resumo.contas, resumo.faturas, resumo.falhas) == (1, 1, ())
    row = banco.conexao.execute("SELECT valor_total, valor_brl, vencimento, mes_referencia, fechamento, pagamento_minimo, permite_parcelamento, numero_cartao FROM faturas").fetchone()
    assert row == (Decimal("650.50"), Decimal("650.50"), date(2026, 9, 10), "2026-09", date(2026, 9, 2), Decimal("65.05"), True, "4321")
    pagamentos, encargos = banco.conexao.execute("SELECT pagamentos_json, encargos_json FROM faturas").fetchone()
    assert json.loads(pagamentos)[0]["amount"] == 400
    assert json.loads(encargos)[0]["amount"] == 0.5
    assert banco.conexao.execute("SELECT data, id_fatura FROM transacoes_analiticas").fetchone() == (date(2026, 8, 28), "fatura-a")


def test_upsert_faturas_preserva_payload_e_timestamps_sem_mudanca(banco, config_offline, tmp_path, relogio):
    conta(banco)
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]})
    coletar(cliente, banco, config_offline)
    antes = banco.conexao.execute("SELECT * FROM raw_faturas").fetchone()
    relogio.avancar(hours=1)
    coletar(cliente, banco, config_offline)
    assert banco.conexao.execute("SELECT * FROM raw_faturas").fetchone() == antes
    cliente_fixture(tmp_path, faturas={"cartao-a": [fatura(totalAmount=710)]})
    coletar(cliente, banco, config_offline)
    assert banco.contar("raw_faturas") == 1
    valor, payload, inserido, atualizado = banco.conexao.execute("SELECT valor_total, payload_json, ingerido_em, atualizado_em FROM raw_faturas").fetchone()
    assert valor == Decimal("710.00")
    assert json.loads(payload) == fatura(totalAmount=710)
    assert atualizado > inserido


def test_falha_de_um_cartao_preserva_ultimo_sucesso_e_outro_cartao_continua(banco, config_offline, tmp_path):
    conta(banco)
    conta(banco, "cartao-b", "Banco Boreal")
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]})
    coletar(cliente, banco, config_offline)
    antes = banco.conexao.execute("SELECT coletado_em FROM cobertura_faturas WHERE id_conta='cartao-a'").fetchone()[0]
    class Interrompido(ClienteFixtures):
        def listar_faturas(self, id_conta):
            if id_conta == "cartao-a":
                raise ErroPluggy("conexão indisponível")
            return [fatura("fatura-b", totalAmount=50)]
    resumo = coletar(Interrompido(tmp_path), banco, config_offline)
    assert len(resumo.falhas) == 1
    assert resumo.falhas[0].instituicao == "Banco Aurora"
    assert banco.contar("faturas") == 2
    assert banco.conexao.execute("SELECT estado, coletado_em FROM cobertura_faturas WHERE id_conta='cartao-a'").fetchone() == ("falha", antes)
    assert banco.conexao.execute("SELECT estado FROM cobertura_faturas WHERE id_conta='cartao-b'").fetchone()[0] == "sucesso"


def test_cobertura_distingue_nao_coletado_sem_faturas_e_conta_corrente(banco, config_offline, tmp_path):
    conta(banco)
    conta(banco, "corrente", tipo="BANK")
    banco.gravar_regras(config_offline.regras)
    aplicar_views(banco, RAIZ / "sql")
    assert banco.conexao.execute("SELECT id_conta, estado, coletado_em FROM cobertura_faturas").fetchall() == [("cartao-a", "nao_coletado", None)]
    coletar(cliente_fixture(tmp_path), banco, config_offline)
    assert banco.conexao.execute("SELECT estado FROM cobertura_faturas").fetchone()[0] == "sem_faturas"
    assert banco.contar("faturas") == 0


def test_fatura_em_dolar_nao_entra_no_total_brl(banco, config_offline, tmp_path):
    conta(banco)
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura(totalAmount=40, totalAmountCurrencyCode="USD")]})
    coletar(cliente, banco, config_offline)
    assert banco.conexao.execute("SELECT moeda, valor_total, valor_brl FROM faturas").fetchone() == ("USD", Decimal("40.00"), None)


def test_detalhamento_exige_billid_e_conta_preserva_creditos(banco, config_offline, tmp_path):
    conta(banco)
    conta(banco, "cartao-b", "Banco Boreal")
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]}, transacoes={"cartao-a": [
        transacao(), transacao("credito", type="CREDIT", amount=-20),
        transacao("sem-vinculo", creditCardMetadata={}),
    ], "cartao-b": [transacao("outro-cartao", "cartao-b")]})
    coletar(cliente, banco, config_offline)
    rows = banco.conexao.execute("SELECT t.id_transacao, t.valor_assinado FROM transacoes_analiticas t JOIN faturas f ON f.id_fatura=t.id_fatura AND f.id_conta=t.id_conta ORDER BY t.id_transacao").fetchall()
    assert rows == [("credito", Decimal("20.00")), ("tx-a", Decimal("-100.00"))]


def test_falha_de_transacoes_preserva_fatura_oficial_e_detalhe_anterior(banco, config_offline, tmp_path):
    conta(banco)
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]}, transacoes={"cartao-a": [transacao()]})
    coletar(cliente, banco, config_offline)
    class SemExtrato(ClienteFixtures):
        def listar_transacoes(self, id_conta, desde):
            raise ErroPluggy("extrato indisponível")
    cliente_fixture(tmp_path, faturas={"cartao-a": [fatura(totalAmount=800)]})
    resumo = coletar(SemExtrato(tmp_path), banco, config_offline)
    assert len(resumo.falhas) == 1
    assert banco.conexao.execute("SELECT valor_total FROM faturas").fetchone()[0] == Decimal("800.00")
    assert banco.contar("transacoes_analiticas") == 1
    estado, mensagem = banco.conexao.execute("SELECT estado, mensagem FROM cobertura_faturas").fetchone()
    assert estado == "falha" and "extrato" in mensagem


def test_publicacao_inclui_faturas_e_cobertura_no_mesmo_manifesto(banco, config_offline, tmp_path):
    from financas.publicacao import publicar
    conta(banco)
    coletar(cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]}), banco, config_offline)
    destino = tmp_path / "publicacao"
    publicar(banco, destino)
    manifesto = json.loads((destino / "manifesto.json").read_text(encoding="utf-8"))
    for view in ("faturas", "cobertura_faturas"):
        caminho = destino / manifesto["arquivos"][view]
        assert banco.conexao.execute("SELECT count(*) FROM read_parquet(?)", [str(caminho)]).fetchone()[0] == 1


def preparar_ingestao(tmp_path):
    (tmp_path / "accounts").mkdir(exist_ok=True)
    (tmp_path / "items.json").write_text(json.dumps([{"id": "item-a", "status": "UPDATED", "connector": {"name": "Banco Aurora"}}]), encoding="utf-8")
    (tmp_path / "accounts" / "item-a.json").write_text(json.dumps([{
        "id": "cartao-a", "type": "CREDIT", "subtype": "CREDIT_CARD",
        "name": "Cartão principal", "number": "4321", "currencyCode": "BRL", "balance": 999,
    }]), encoding="utf-8")
    return cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]},
                           transacoes={"cartao-a": [transacao(), transacao("tx-set", date="2026-09-04")]})


def test_ingerir_coleta_faturas_sem_refazer_extrato_e_preserva_recorte_explicito(banco, config_offline, tmp_path):
    from financas.ingestao import ingerir
    preparar_ingestao(tmp_path)
    class SemRepeticao(ClienteFixtures):
        consultas = 0
        def listar_transacoes(self, id_conta, desde):
            self.consultas += 1
            if self.consultas > 1:
                raise AssertionError("O extrato já foi atualizado nesta ingestão")
            return super().listar_transacoes(id_conta, desde)
    cliente = SemRepeticao(tmp_path)
    resumo = ingerir(cliente, banco, config_offline.regras, hoje=HOJE, desde=date(2026, 9, 1))
    assert banco.contar("raw_faturas") == 1
    assert resumo.faturas == 1 and not resumo.houve_falha
    assert banco.conexao.execute("SELECT id FROM raw_transacoes").fetchall() == [("tx-set",)]
    assert banco.conexao.execute("SELECT transacoes_desde FROM log_faturas").fetchone()[0] == date(2026, 9, 1)


def test_cli_faturas_coleta_e_publica_no_destino_sem_outros_produtos(projeto, tmp_path):
    from financas.cli import main
    from financas.persistencia import Banco
    fixtures = tmp_path / "fonte"
    fixtures.mkdir()
    cliente_fixture(fixtures, faturas={"cartao-a": [fatura()]}, transacoes={"cartao-a": [transacao()]})
    caminho = tmp_path / "faturas.duckdb"
    with Banco.abrir(caminho) as banco:
        banco.criar_schema()
        conta(banco)
    destino = tmp_path / "publicado"
    codigo = main(["--banco", str(caminho), "faturas", "--destino", str(destino), "--hoje", HOJE.isoformat()],
                  ambiente={"FINANCAS_FIXTURES": str(fixtures)}, raiz=projeto)
    assert codigo == 0
    manifesto = json.loads((destino / "manifesto.json").read_text(encoding="utf-8"))
    assert manifesto["linhas"]["faturas"] == 1
    with Banco.abrir(caminho) as banco:
        assert banco.conexao.execute("SELECT id_fatura FROM transacoes_analiticas").fetchall() == [("fatura-a",)]


def test_cli_faturas_sem_cartoes_retorna_codigo_explicito(projeto, tmp_path):
    from financas.cli import main
    codigo = main(["--banco", str(tmp_path / "vazio.duckdb"), "faturas", "--destino", str(tmp_path / "publicado")],
                  ambiente={}, raiz=projeto)
    assert codigo == 5


def test_cli_faturas_falha_parcial_publica_cartoes_que_responderam(projeto, tmp_path, monkeypatch):
    from financas.cli import main
    from financas.persistencia import Banco
    caminho = tmp_path / "faturas.duckdb"
    with Banco.abrir(caminho) as banco:
        banco.criar_schema()
        conta(banco)
        conta(banco, "cartao-b", "Banco Boreal")
    class Parcial(ClienteFixtures):
        def listar_faturas(self, id_conta):
            if id_conta == "cartao-a":
                raise ErroPluggy("API indisponível")
            return [fatura("fatura-b")]
    monkeypatch.setattr("financas.cli.criar_cliente", lambda config: Parcial(tmp_path))
    destino = tmp_path / "publicado"
    codigo = main(["--banco", str(caminho), "faturas", "--destino", str(destino), "--hoje", HOJE.isoformat()], ambiente={}, raiz=projeto)
    assert codigo == 3
    assert json.loads((destino / "manifesto.json").read_text(encoding="utf-8"))["linhas"]["faturas"] == 1


def test_payload_de_fatura_invalido_preserva_coleta_anterior(banco, config_offline, tmp_path):
    conta(banco)
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()]})
    coletar(cliente, banco, config_offline)
    cliente_fixture(tmp_path, faturas={"cartao-a": [fatura(totalAmount=800), {"id": " "}]})
    resumo = coletar(cliente, banco, config_offline)
    assert len(resumo.falhas) == 1
    assert banco.conexao.execute("SELECT valor_total FROM raw_faturas").fetchall() == [(Decimal("650.50"),)]


def test_payload_de_transacao_invalido_nao_aborta_outros_cartoes(banco, config_offline, tmp_path):
    conta(banco)
    conta(banco, "cartao-b", "Banco Boreal")
    cliente = cliente_fixture(tmp_path, faturas={"cartao-a": [fatura()], "cartao-b": [fatura("fatura-b")]})
    class Invalido(ClienteFixtures):
        def listar_transacoes(self, id_conta, desde):
            return iter([None]) if id_conta == "cartao-a" else iter([])
    resumo = coletar(Invalido(tmp_path), banco, config_offline)
    assert len(resumo.falhas) == 1
    assert banco.contar("faturas") == 2
