"""
Achatamento do JSON da Pluggy em linhas de colunas planas.

A API devolve estruturas aninhadas (`paymentData.receiver.documentNumber.value`)
que não cabem numa tabela. Este módulo extrai os campos que a análise usa e
guarda o JSON original inteiro em `payload_json`.

O que este módulo **não** faz: decidir se algo é gasto, se é transferência
própria ou se é aporte. Isso é regra de negócio e vive no SQL. Aqui só há
tradução de formato — e é por isso que a camada raw continua sendo um retrato
fiel do que a API respondeu.

Duas escolhas que merecem explicação:

- **`Decimal`, nunca `float`.** Somar centavos em ponto flutuante acumula erro,
  e o total do mês precisa fechar com o extrato.
- **`payload_json` com chaves ordenadas.** A serialização é determinística, então
  duas ingestões do mesmo dado geram exatamente a mesma string. É isso que
  permite detectar "mudou de verdade" comparando texto, sem falso positivo por
  ordem de chave.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

INSTITUICAO_DESCONHECIDA = "Desconhecida"


def nome_da_instituicao(item: dict[str, Any], configurado: str = "") -> str:
    """Nome da instituição de um item.

    Propagada na travessia `item → conta → transação` e gravada em cada linha,
    porque a API não devolve instituição junto da transação. Não é regra de
    negócio, é procedência: sem ela, a armadilha 1 não teria como aplicar um
    padrão de fatura por instituição.

    `configurado` vence o conector, e precisa vencer: com o conector MeuPluggy
    (200), que é agregador, `connector.name` devolve "MeuPluggy" para todos os
    items. Confiar nele faria as cinco instituições virarem uma só.
    """
    if configurado.strip():
        return configurado.strip()

    conector = item.get("connector")
    if isinstance(conector, dict):
        nome = conector.get("name")
        if isinstance(nome, str) and nome.strip():
            return nome.strip()
    return INSTITUICAO_DESCONHECIDA


def normalizar_transacao(
    bruto: dict[str, Any], *, id_item: str, instituicao: str
) -> dict[str, Any]:
    """Converte uma transação da API em uma linha de `raw_transacoes`.

    Não há chave Pix aqui, e a ausência é deliberada: `paymentData` não tem
    campo `pixKey`. A contraparte de um Pix é identificada por `name` e por
    `documentNumber.value` — que são os campos lidos abaixo — ou pelo texto da
    descrição. Uma versão anterior lia `paymentData.receiver.pixKey`, que só
    existia nas fixtures; contra a API real a coluna vinha sempre nula, e os
    testes de transferência própria passavam sem exercitar nada.
    """
    return {
        "id": _texto(bruto.get("id")),
        "id_conta": _texto(bruto.get("accountId")),
        "id_item": id_item,
        "instituicao": instituicao,
        "descricao": _texto(bruto.get("description")),
        "descricao_original": _texto(bruto.get("descriptionRaw")),
        "valor": _decimal(bruto.get("amount")),
        "moeda": _texto(bruto.get("currencyCode")),
        "data": _data(bruto.get("date")),
        "tipo": _texto(bruto.get("type")),
        "situacao": _texto(bruto.get("status")),
        "categoria": _texto(bruto.get("category")),
        "id_categoria": _texto(bruto.get("categoryId")),
        "saldo": _decimal(bruto.get("balance")),
        "metodo_pagamento": _texto(_em(bruto, "paymentData", "paymentMethod")),
        "pagador_nome": _texto(_em(bruto, "paymentData", "payer", "name")),
        "pagador_documento": _texto(
            _em(bruto, "paymentData", "payer", "documentNumber", "value")
        ),
        "recebedor_nome": _texto(_em(bruto, "paymentData", "receiver", "name")),
        "recebedor_documento": _texto(
            _em(bruto, "paymentData", "receiver", "documentNumber", "value")
        ),
        "estabelecimento_nome": _texto(_em(bruto, "merchant", "name")),
        "estabelecimento_cnpj": _texto(_em(bruto, "merchant", "cnpj")),
        "cartao_final": _texto(_em(bruto, "creditCardMetadata", "cardNumber")),
        "parcela_numero": _inteiro(_em(bruto, "creditCardMetadata", "installmentNumber")),
        "parcela_total": _inteiro(_em(bruto, "creditCardMetadata", "totalInstallments")),
        "payload_json": serializar(bruto),
    }


def normalizar_conta(
    bruto: dict[str, Any], *, id_item: str, instituicao: str, data_posicao: date
) -> dict[str, Any]:
    """Converte uma conta da API em uma linha de `raw_contas`.

    `data_posicao` é a data da ingestão: conta é estado, não evento, e cada
    execução grava um retrato novo. Sem isso não existe série de patrimônio.
    """
    return {
        "id": _texto(bruto.get("id")),
        "data_posicao": data_posicao,
        "id_item": id_item,
        "instituicao": instituicao,
        "tipo": _texto(bruto.get("type")),
        "subtipo": _texto(bruto.get("subtype")),
        "nome": _texto(bruto.get("name")),
        "nome_comercial": _texto(bruto.get("marketingName")),
        "numero": _texto(bruto.get("number")),
        "saldo": _decimal(bruto.get("balance")),
        "moeda": _texto(bruto.get("currencyCode")),
        "titular": _texto(bruto.get("owner")),
        "limite_credito": _decimal(_em(bruto, "creditData", "creditLimit")),
        "limite_disponivel": _decimal(_em(bruto, "creditData", "availableCreditLimit")),
        "fechamento_fatura": _data(_em(bruto, "creditData", "balanceCloseDate")),
        "vencimento_fatura": _data(_em(bruto, "creditData", "balanceDueDate")),
        "payload_json": serializar(bruto),
    }


def normalizar_investimento(
    bruto: dict[str, Any], *, id_item: str, instituicao: str, data_posicao: date
) -> dict[str, Any]:
    """Converte um investimento da API em uma linha de `raw_investimentos`.

    `data_posicao` é sempre a data da ingestão, igual a `raw_contas`. Isso é o
    que mantém as duas séries alinhadas: `patrimonio` soma saldo de conta com
    posição de investimento no mesmo dia, e se cada tabela usasse um calendário
    diferente o join não fecharia.

    A data que a corretora informa fica em `data_referencia`, como informação.
    Ela costuma ser o fechamento do mês, e não o dia da consulta.
    """
    return {
        "id": _texto(bruto.get("id")),
        "data_posicao": data_posicao,
        "data_referencia": _data(bruto.get("date")),
        "id_item": id_item,
        "instituicao": instituicao,
        "nome": _texto(bruto.get("name")),
        "numero": _texto(bruto.get("number")),
        "tipo": _texto(bruto.get("type")),
        "subtipo": _texto(bruto.get("subtype")),
        "emissor": _texto(bruto.get("issuer")),
        "moeda": _texto(bruto.get("currencyCode")),
        "data_aplicacao": _data(bruto.get("issueDate")),
        "data_vencimento": _data(bruto.get("dueDate")),
        "taxa": _decimal(bruto.get("rate"), casas=6),
        "tipo_taxa": _texto(bruto.get("rateType")),
        "quantidade": _decimal(bruto.get("quantity"), casas=8),
        "valor_aplicado": _decimal(
            bruto.get("amountOriginal") if bruto.get("amountOriginal") is not None
            else bruto.get("amount")
        ),
        "saldo": _decimal(bruto.get("balance")),
        "rendimento": _decimal(bruto.get("amountProfit")),
        "situacao": _texto(bruto.get("status")),
        "payload_json": serializar(bruto),
    }


def serializar(bruto: dict[str, Any]) -> str:
    """Serializa o payload de forma determinística.

    `sort_keys` é o que faz a comparação de mudança funcionar: sem ele, a mesma
    transação devolvida com as chaves em outra ordem pareceria alterada e o
    upsert marcaria uma atualização que não existiu.
    """
    return json.dumps(bruto, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------


def _em(bruto: dict[str, Any], *caminho: str) -> Any:
    """Lê um campo aninhado, devolvendo None em qualquer buraco do caminho."""
    atual: Any = bruto
    for chave in caminho:
        if not isinstance(atual, dict):
            return None
        atual = atual.get(chave)
    return atual


def _texto(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _decimal(valor: Any, *, casas: int = 2) -> Decimal | None:
    """Converte para Decimal via string, para não herdar imprecisão de float."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None
    return numero.quantize(Decimal(1).scaleb(-casas))


def _inteiro(valor: Any) -> int | None:
    if valor is None or isinstance(valor, bool):
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _data(valor: Any) -> date | None:
    """Lê a data de um timestamp ISO, ignorando hora e fuso.

    A Pluggy manda `2025-09-10T00:00:00.000Z`. Para análise de gasto a hora não
    interessa, e carregar fuso junto só criaria confusão de virada de dia.
    """
    if not isinstance(valor, str) or len(valor) < 10:
        return None
    try:
        return date.fromisoformat(valor[:10])
    except ValueError:
        return None
