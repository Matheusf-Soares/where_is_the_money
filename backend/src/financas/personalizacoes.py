"""Ajustes locais atômicos; a resolução analítica continua nas views SQL."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import json
from uuid import uuid4

import duckdb

from financas.persistencia import Banco


class ConflitoDeRevisao(Exception):
    """Uma correção concorrente exige reler os dados antes de gravar."""


def _linhas(conexao, sql, parametros=None):
    cursor = conexao.execute(sql, parametros or [])
    nomes = [coluna[0] for coluna in cursor.description]
    return [dict(zip(nomes, linha)) for linha in cursor.fetchall()]


def _texto(ajuste, campo, padrao=None):
    valor = ajuste.get(campo, padrao)
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError(f"Informe {campo} como texto não vazio.")
    return valor.strip()


def _opcao(ajuste, campo, opcoes, padrao=None):
    valor = _texto(ajuste, campo, padrao)
    if valor not in opcoes:
        raise ValueError(f"{campo} deve ser um de: {', '.join(sorted(opcoes))}.")
    return valor


def _categoria(conexao, ajuste):
    id = _texto(ajuste, "id_categoria")
    if not conexao.execute("SELECT 1 FROM usr_categorias WHERE id = ?", [id]).fetchone():
        raise ValueError("A categoria informada não existe.")
    return id


def _ids(conexao, ajuste):
    ids = ajuste.get("ids_transacoes")
    if not isinstance(ids, list) or not ids or any(not isinstance(id, str) or not id.strip() for id in ids):
        raise ValueError("Selecione uma lista não vazia de transações válidas.")
    if len(set(ids)) != len(ids):
        raise ValueError("A lista contém transações repetidas.")
    linhas = _linhas(conexao, "SELECT * FROM transacoes_analiticas WHERE id_transacao IN (SELECT unnest(?))", [ids])
    if len(linhas) != len(ids):
        raise ValueError("Uma ou mais transações não existem no extrato.")
    return ids, linhas


def obter_catalogo(banco: Banco) -> dict:
    """Catálogos editáveis; não inclui payloads bancários nem credenciais."""
    consultas = {
        "categorias": "SELECT * FROM usr_categorias ORDER BY macro_categoria, nome, id",
        "regras": "SELECT * FROM usr_regras ORDER BY prioridade",
        "mapas": "SELECT * FROM usr_mapas ORDER BY id_categoria_pluggy",
        "aliases": "SELECT * FROM usr_aliases ORDER BY instituicao, descricao_original",
        "recorrencias": "SELECT * FROM usr_recorrencias ORDER BY instituicao, estabelecimento",
        "compras": "SELECT c.*, list(t.id_transacao ORDER BY t.id_transacao) AS ids_transacoes FROM usr_compras c LEFT JOIN usr_compra_transacoes t ON c.id=t.id_compra GROUP BY ALL ORDER BY c.data_compra, c.id",
    }
    return {nome: _linhas(banco.conexao, sql) for nome, sql in consultas.items()}


def _regra(conexao, ajuste):
    id = _texto(ajuste, "id", str(uuid4()))
    prioridade = ajuste.get("prioridade")
    if isinstance(prioridade, bool) or not isinstance(prioridade, int):
        raise ValueError("A prioridade da regra deve ser um número inteiro.")
    if conexao.execute("SELECT 1 FROM usr_regras WHERE prioridade = ? AND id <> ?", [prioridade, id]).fetchone():
        raise ValueError("Esta prioridade já é usada por outra regra.")
    ativa = ajuste.get("ativa", True)
    if not isinstance(ativa, bool):
        raise ValueError("ativa deve ser verdadeiro ou falso.")
    valores = [id, prioridade, _texto(ajuste, "padrao"), _texto(ajuste, "instituicao", "%"), _categoria(conexao, ajuste), ativa]
    conexao.execute("INSERT INTO usr_regras VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET prioridade=excluded.prioridade, padrao=excluded.padrao, instituicao=excluded.instituicao, id_categoria=excluded.id_categoria, ativa=excluded.ativa", valores)
    return {"id": id}


def _compra(conexao, ajuste):
    id = _texto(ajuste, "id", str(uuid4()))
    ids, linhas = _ids(conexao, ajuste)
    try:
        data = date.fromisoformat(_texto(ajuste, "data_compra"))
    except ValueError as erro:
        raise ValueError("Informe uma data de compra válida no formato AAAA-MM-DD.") from erro
    if data > date.today():
        raise ValueError("A data da compra não pode estar no futuro.")
    try:
        valor = Decimal(_texto(ajuste, "valor_total_brl"))
    except InvalidOperation as erro:
        raise ValueError("Informe o valor integral em BRL como decimal textual.") from erro
    if not valor.is_finite() or valor <= 0 or valor >= Decimal("10000000000000000") or valor != valor.quantize(Decimal("0.01")):
        raise ValueError("O valor integral deve ser positivo e ter até duas casas decimais.")
    if any(not t["e_parcelado"] or t["valor_assinado"] is None or t["valor_assinado"] >= 0 or t["e_pagamento_de_fatura"] or t["e_transferencia_propria"] or t["e_aplicacao"] or t["e_saldo_anterior"] or t["e_pendente_substituida"] for t in linhas):
        raise ValueError("Selecione apenas parcelas de consumo, sem transferências, aplicações ou faturas.")
    if len({(t["id_conta"], t["instituicao"]) for t in linhas}) != 1:
        raise ValueError("Todas as parcelas devem pertencer à mesma conta e instituição.")
    numeros = [t["parcela_numero"] for t in linhas]
    totais = {t["parcela_total"] for t in linhas}
    if len(totais) != 1 or any(n is None or n < 1 or n > max(totais) for n in numeros) or len(set(numeros)) != len(numeros):
        raise ValueError("As parcelas devem ter números válidos, distintos e o mesmo total.")
    parcial = ajuste.get("grupo_parcial", False)
    if not isinstance(parcial, bool):
        raise ValueError("grupo_parcial deve ser verdadeiro ou falso.")
    if len(linhas) < max(totais) and not parcial:
        raise ValueError("Confirme grupo_parcial para associar apenas parte das parcelas.")
    if valor < sum((t["valor_brl"] or Decimal(0) for t in linhas), Decimal(0)):
        raise ValueError("O valor integral não pode ser menor que a soma conhecida em BRL.")
    if any(t["id_compra"] is not None and t["id_compra"] != id for t in linhas):
        raise ValueError("Uma parcela já pertence a outra compra. Desfaça a associação anterior.")
    descricao = _texto(ajuste, "descricao")
    conexao.execute("INSERT INTO usr_compras VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET data_compra=excluded.data_compra, valor_total_brl=excluded.valor_total_brl, descricao=excluded.descricao, grupo_parcial=excluded.grupo_parcial", [id, data, valor, descricao, parcial])
    conexao.execute("DELETE FROM usr_compra_transacoes WHERE id_compra = ?", [id])
    conexao.executemany("INSERT INTO usr_compra_transacoes VALUES (?, ?)", [(t, id) for t in ids])
    return {"id": id, "grupo_parcial": parcial}


def _aplicar(conexao, ajuste):
    tipo = _texto(ajuste, "tipo")
    if tipo == "categoria":
        id = _texto(ajuste, "id", str(uuid4()))
        valores = [id, _texto(ajuste, "nome"), _texto(ajuste, "macro_categoria"),
            _opcao(ajuste, "essencialidade", {"essencial", "discricionario", "nao_definido"}, "nao_definido"),
            _opcao(ajuste, "comportamento", {"fixo", "variavel", "nao_definido"}, "nao_definido")]
        conexao.execute("INSERT INTO usr_categorias VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET nome=excluded.nome, macro_categoria=excluded.macro_categoria, essencialidade=excluded.essencialidade, comportamento=excluded.comportamento", valores)
        return {"id": id}
    if tipo in {"classificacao", "desfazer"}:
        ids, _ = _ids(conexao, ajuste)
        categoria = _categoria(conexao, ajuste) if tipo == "classificacao" else None
        for id in ids:
            if tipo == "classificacao":
                anterior = conexao.execute("SELECT id_categoria FROM usr_classificacoes WHERE id_transacao = ?", [id]).fetchone()
                conexao.execute("INSERT INTO usr_historico_classificacoes(id_transacao, id_categoria_anterior, id_categoria_nova) VALUES (?, ?, ?)", [id, anterior[0] if anterior else None, categoria])
                conexao.execute("INSERT INTO usr_classificacoes VALUES (?, ?) ON CONFLICT(id_transacao) DO UPDATE SET id_categoria=excluded.id_categoria", [id, categoria])
            else:
                anterior = conexao.execute("SELECT id, id_categoria_anterior FROM usr_historico_classificacoes WHERE id_transacao = ? AND desfeito_em IS NULL ORDER BY id DESC LIMIT 1", [id]).fetchone()
                if anterior:
                    conexao.execute("DELETE FROM usr_classificacoes WHERE id_transacao = ?", [id])
                    if anterior[1] is not None:
                        conexao.execute("INSERT INTO usr_classificacoes VALUES (?, ?)", [id, anterior[1]])
                    conexao.execute("UPDATE usr_historico_classificacoes SET desfeito_em=current_timestamp WHERE id = ?", [anterior[0]])
        return {"quantidade": len(ids)}
    if tipo in {"atributos", "desfazer_atributos"}:
        ids, _ = _ids(conexao, ajuste)
        if tipo == "atributos":
            novos = [_opcao(ajuste, "essencialidade", {"essencial", "discricionario", "nao_definido"}),
                     _opcao(ajuste, "comportamento", {"fixo", "variavel", "nao_definido"})]
            for id in ids:
                anterior = conexao.execute("SELECT essencialidade, comportamento FROM usr_atributos WHERE id_transacao=?", [id]).fetchone()
                conexao.execute("INSERT INTO usr_historico_atributos(id_transacao, anterior, novos) VALUES (?, ?, ?)", [id, json.dumps(anterior) if anterior else None, json.dumps(novos)])
                conexao.execute("INSERT INTO usr_atributos VALUES (?, ?, ?) ON CONFLICT(id_transacao) DO UPDATE SET essencialidade=excluded.essencialidade, comportamento=excluded.comportamento", [id, *novos])
        else:
            for id in ids:
                anterior = conexao.execute("SELECT id, anterior FROM usr_historico_atributos WHERE id_transacao=? AND desfeito_em IS NULL ORDER BY id DESC LIMIT 1", [id]).fetchone()
                if anterior:
                    conexao.execute("DELETE FROM usr_atributos WHERE id_transacao=?", [id])
                    if anterior[1] is not None:
                        conexao.execute("INSERT INTO usr_atributos VALUES (?, ?, ?)", [id, *json.loads(anterior[1])])
                    conexao.execute("UPDATE usr_historico_atributos SET desfeito_em=current_timestamp WHERE id=?", [anterior[0]])
        return {"quantidade": len(ids)}
    if tipo == "regra":
        return _regra(conexao, ajuste)
    if tipo == "mapa":
        fonte, categoria = _texto(ajuste, "id_categoria_pluggy"), _categoria(conexao, ajuste)
        conexao.execute("INSERT INTO usr_mapas VALUES (?, ?) ON CONFLICT(id_categoria_pluggy) DO UPDATE SET id_categoria=excluded.id_categoria", [fonte, categoria])
        return {"id_categoria_pluggy": fonte}
    if tipo == "alias":
        descricao = _texto(ajuste, "descricao_original").lower()
        instituicao = _texto(ajuste, "instituicao", "%").lower()
        estabelecimento = _texto(ajuste, "estabelecimento")
        conexao.execute("INSERT INTO usr_aliases VALUES (?, ?, ?) ON CONFLICT(descricao_original, instituicao) DO UPDATE SET estabelecimento=excluded.estabelecimento", [descricao, instituicao, estabelecimento])
        return {"estabelecimento": estabelecimento}
    if tipo == "recorrencia":
        instituicao, estabelecimento = _texto(ajuste, "instituicao"), _texto(ajuste, "estabelecimento")
        estado = _opcao(ajuste, "estado", {"sugestao", "ativa", "encerrada", "ignorada"})
        conexao.execute("DELETE FROM usr_recorrencias WHERE lower(instituicao)=lower(?) AND lower(estabelecimento)=lower(?)", [instituicao, estabelecimento])
        conexao.execute("INSERT INTO usr_recorrencias VALUES (?, ?, ?)", [instituicao, estabelecimento, estado])
        return {"estado": estado}
    if tipo == "compra":
        return _compra(conexao, ajuste)
    if tipo == "desfazer_compra":
        id = _texto(ajuste, "id_compra")
        if not conexao.execute("SELECT 1 FROM usr_compras WHERE id=?", [id]).fetchone():
            raise ValueError("A compra informada não existe.")
        conexao.execute("DELETE FROM usr_compra_transacoes WHERE id_compra=?", [id])
        conexao.execute("DELETE FROM usr_compras WHERE id=?", [id])
        return {"id": id}
    raise ValueError("Tipo de ajuste desconhecido.")


def aplicar_ajuste(banco: Banco, ajuste: dict, *, revisao_esperada: str | int | None = None) -> dict:
    """Valida e grava um ajuste inteiro ou desfaz todas as suas alterações."""
    if not isinstance(ajuste, dict):
        raise ValueError("Envie um objeto de ajuste.")
    c = banco.conexao
    c.execute("BEGIN TRANSACTION")
    try:
        revisao = c.execute("SELECT revisao FROM usr_estado WHERE id=1").fetchone()[0]
        if revisao_esperada is not None and str(revisao_esperada) != str(revisao):
            raise ConflitoDeRevisao("Outra aba ou instância alterou os dados. Atualize a tela e revise antes de salvar.")
        resultado = _aplicar(c, ajuste)
        c.execute("UPDATE usr_estado SET revisao=revisao+1 WHERE id=1")
        c.execute("COMMIT")
        return {"tipo": ajuste["tipo"], "revisao": revisao + 1, **resultado}
    except Exception as erro:
        c.execute("ROLLBACK")
        if isinstance(erro, duckdb.TransactionException):
            raise ConflitoDeRevisao("Outra operação está alterando os dados. Atualize antes de tentar novamente.") from erro
        if isinstance(erro, duckdb.Error):
            raise ValueError("Não foi possível gravar o ajuste; verifique referências e valores duplicados.") from erro
        raise


def prever_regra(banco: Banco, regra: dict) -> dict:
    """Simula a regra na mesma view e reverte tudo, inclusive em caso de erro."""
    if not isinstance(regra, dict):
        raise ValueError("Envie um objeto de regra.")
    c = banco.conexao
    c.execute("BEGIN TRANSACTION")
    try:
        c.execute("CREATE TEMP TABLE previa_categorias AS SELECT id_transacao, categoria, id_categoria_propria, origem_da_categoria FROM transacoes_analiticas")
        _regra(c, regra)
        protegidas = c.execute("""SELECT count(*) FROM stg_transacoes t
            JOIN raw_transacoes raw ON raw.id=t.id_transacao
            JOIN usr_classificacoes m ON m.id_transacao=t.id_transacao
            WHERE lower(coalesce(t.instituicao, '')) LIKE lower(?) AND
            (lower(t.descricao) LIKE lower(?) OR lower(coalesce(raw.descricao_original, '')) LIKE lower(?)
             OR lower(coalesce(t.estabelecimento, '')) LIKE lower(?))""",
            [_texto(regra, "instituicao", "%"), *[_texto(regra, "padrao")] * 3]).fetchone()[0] if regra.get("ativa", True) else 0
        c.execute("""CREATE TEMP TABLE previa_resultado AS SELECT t.id_transacao, t.descricao,
            p.categoria AS categoria_anterior, t.categoria AS categoria_nova, t.valor_brl
            FROM transacoes_analiticas t JOIN previa_categorias p USING(id_transacao)
            WHERE t.id_categoria_propria IS DISTINCT FROM p.id_categoria_propria
               OR t.categoria IS DISTINCT FROM p.categoria""")
        resumo = c.execute("SELECT count(*), coalesce(sum(valor_brl), 0), count(*) FILTER (WHERE valor_brl IS NULL) FROM previa_resultado").fetchone()
        return dict(quantidade=resumo[0], valor_brl=resumo[1], sem_conversao=resumo[2], protegidas_manualmente=protegidas,
                    linhas=_linhas(c, "SELECT * FROM previa_resultado ORDER BY id_transacao LIMIT 30"))
    except duckdb.Error as erro:
        raise ValueError("Não foi possível prever a regra; verifique os valores informados.") from erro
    finally:
        c.execute("ROLLBACK")
