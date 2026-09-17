"""
Diagnóstico da conexão com a Pluggy.

Existe para um caso específico e desconcertante: `POST /auth` responde 200 e a
requisição seguinte responde 401. Credencial válida, chave recusada. Sem ver a
resposta crua não há como distinguir as causas possíveis, e o cliente normal
esconde tudo isso atrás de exceções — que é o comportamento certo dele, e o
errado para investigar.

Este módulo é deliberadamente burro: faz as requisições na mão, com `httpx`
direto, e mostra o que voltou. Não reaproveita `ClienteHttp` de propósito —
se o problema estiver no cliente, usar o cliente para investigar esconderia
justamente o que se quer ver.

**Nada de segredo é impresso.** Credenciais aparecem como comprimento e
prefixo, o suficiente para flagrar aspas sobrando, espaço no fim ou o campo
trocado, e insuficiente para vazar em print de tela ou em log colado num chat.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from financas.config import PADRAO_DE_UUID, Configuracao

# Candidatos a cabeçalho de autenticação. O primeiro é o documentado no
# OpenAPI da Pluggy; os outros existem porque um 401 logo depois de um /auth
# bem-sucedido é exatamente o sintoma de estar mandando a chave no lugar errado,
# e testar é mais barato que discutir.
CABECALHOS_CANDIDATOS = (
    ("X-API-KEY", lambda chave: chave),
    ("Authorization", lambda chave: f"Bearer {chave}"),
    ("authorization", lambda chave: chave),
)


@dataclass
class Achado:
    """Uma linha do relatório."""

    rotulo: str
    detalhe: str
    ok: bool | None = None  # None = informativo, sem juízo

    def __str__(self) -> str:
        marca = {True: "  OK  ", False: "FALHA ", None: "      "}[self.ok]
        return f"{marca} {self.rotulo:<34} {self.detalhe}"


def _mascarar(valor: str) -> str:
    """Mostra o suficiente para diagnosticar, nunca o suficiente para vazar."""
    if not valor:
        return "VAZIO"
    visivel = valor[:4]
    aviso = ""
    if valor != valor.strip():
        aviso = "  <-- TEM ESPAÇO OU QUEBRA DE LINHA NAS PONTAS"
    elif valor[0] in "\"'" or valor[-1] in "\"'":
        aviso = "  <-- TEM ASPAS SOBRANDO"
    return f"{len(valor)} caracteres, começa com {visivel!r}{aviso}"


def _claims_do_jwt(chave: str) -> dict[str, Any] | None:
    """Decodifica o payload de um JWT sem verificar assinatura.

    A `apiKey` da Pluggy é um JWT, e o payload dela é quem sabe responder por
    que a chave foi recusada: validade, escopo e plano vêm todos ali. Decodificar
    é leitura local — não valida nada, e não precisa validar: quem valida é a
    API, e a resposta dela já está no relatório.
    """
    import base64

    partes = chave.split(".")
    if len(partes) != 3:
        return None
    try:
        corpo = partes[1]
        corpo += "=" * (-len(corpo) % 4)  # base64url sem padding
        return json.loads(base64.urlsafe_b64decode(corpo))
    except Exception:
        return None


# Claims cujo valor é seguro mostrar: dizem respeito ao plano e à validade, não
# à identidade. O resto aparece só como nome, porque o relatório vai parar em
# print de tela e em chat de suporte.
CLAIMS_SEGUROS = {
    "exp", "iat", "nbf", "scope", "scopes", "role", "roles", "plan", "tier",
    "environment", "env", "type", "status", "products", "permissions",
    "isTrial", "trial", "active", "enabled",
}


def _achados_do_jwt(chave: str) -> list[Achado]:
    """Transforma o payload da apiKey em linhas do relatório."""
    claims = _claims_do_jwt(chave)
    if claims is None:
        return [Achado("apiKey", "não é um JWT decodificável (isso é normal)")]

    achados = [Achado("claims da apiKey", ", ".join(sorted(claims)))]
    achados.extend(_linhas_de_claims(claims, prefixo="  claim "))
    return achados


def _linhas_de_claims(claims: dict[str, Any], *, prefixo: str) -> list[Achado]:
    """Achata um nível de claims em linhas do relatório.

    A Pluggy aninha o contexto da aplicação num claim `data`, e é lá que moram
    plano, ambiente e escopo — justamente o que decide um 401. Mostrar só o nome
    do claim de fora esconderia a resposta um nível abaixo.
    """
    from datetime import datetime, timezone

    linhas: list[Achado] = []

    for nome in sorted(claims):
        valor = claims[nome]

        if isinstance(valor, dict):
            linhas.append(Achado(f"{prefixo}{nome}", ", ".join(sorted(valor)) or "vazio"))
            linhas.extend(_linhas_de_claims(valor, prefixo=f"{prefixo}{nome}."))
            continue

        if nome not in CLAIMS_SEGUROS:
            continue

        if nome in ("exp", "iat", "nbf") and isinstance(valor, (int, float)):
            quando = datetime.fromtimestamp(valor, tz=timezone.utc)
            vencida = nome == "exp" and quando < datetime.now(tz=timezone.utc)
            linhas.append(
                Achado(
                    f"{prefixo}{nome}",
                    quando.isoformat() + ("  <-- JÁ VENCIDA" if vencida else ""),
                    ok=False if vencida else None,
                )
            )
        else:
            linhas.append(
                Achado(f"{prefixo}{nome}", json.dumps(valor, ensure_ascii=False)[:160])
            )

    return linhas


def _corpo(resposta: httpx.Response, limite: int = 400) -> str:
    try:
        return json.dumps(resposta.json(), ensure_ascii=False)[:limite]
    except ValueError:
        return repr(resposta.text[:limite])


# Campos do item que dizem se a conexão está morrendo. Nenhum deles é
# segredo, e todos já vêm na resposta de /items/{id}.
CAMPOS_DE_SAUDE = (
    ("status", "status"),
    ("executionStatus", "execução"),
    ("statusDetail", "detalhe"),
    ("userAction", "AÇÃO NECESSÁRIA"),
    ("error", "erro"),
    ("consecutiveFailedLoginAttempts", "logins falhados seguidos"),
    ("lastUpdatedAt", "última atualização de dados"),
    ("nextAutoSyncAt", "próxima sincronização"),
    ("consentExpiresAt", "consentimento vence em"),
    ("createdAt", "criado em"),
)


def diagnosticar_item(config: Configuracao, id_item: str) -> list[Achado]:
    """Valida um `itemId` e mostra o estado da conexão.

    Existe porque listar items é bloqueado pela Pluggy, então os ids ficam no
    `regras.toml` escritos à mão — e id escrito à mão precisa de um jeito
    barato de conferir. Também serve para inspecionar a saúde de uma conexão
    sem rodar a ingestão inteira.

    Nada de dado financeiro é impresso: só o estado do item e a CONTAGEM de
    contas e investimentos.
    """
    achados: list[Achado] = []
    achados.append(Achado("host", config.url_api))
    achados.append(Achado("itemId consultado", id_item))

    if not PADRAO_DE_UUID.match(id_item):
        achados.append(
            Achado(
                "formato",
                "não é um UUID. Copie o id do item em dashboard.pluggy.ai.",
                ok=False,
            )
        )
        return achados

    if not config.client_id or not config.client_secret:
        achados.append(Achado("credenciais", "faltando; preencha o .env", ok=False))
        return achados

    with httpx.Client(base_url=config.url_api, timeout=config.timeout_http) as http:
        try:
            auth = http.post(
                "/auth",
                json={
                    "clientId": config.client_id,
                    "clientSecret": config.client_secret,
                },
            )
        except httpx.TransportError as erro:
            achados.append(Achado("POST /auth", f"não chegou: {erro!r}", ok=False))
            return achados

        if auth.status_code != 200:
            achados.append(
                Achado("POST /auth", f"HTTP {auth.status_code}", ok=False)
            )
            achados.append(Achado("resposta", _corpo(auth)))
            return achados

        chave = auth.json().get("apiKey")
        if not isinstance(chave, str) or not chave:
            achados.append(Achado("apiKey", "ausente na resposta do /auth", ok=False))
            return achados
        cabecalho = {"X-API-KEY": chave}

        r = http.get(f"/items/{id_item}", headers=cabecalho)
        achados.append(
            Achado(
                "GET /items/{id}",
                f"HTTP {r.status_code}"
                + ("" if r.status_code == 200 else f" — {_corpo(r, 200)}"),
                ok=r.status_code == 200,
            )
        )

        if r.status_code == 404:
            achados.append(
                Achado(
                    "conclusão",
                    "este id não existe nesta aplicação. Ou foi digitado errado, "
                    "ou a instituição foi reautorizada e ganhou um id novo "
                    "(armadilha 8). Pegue o atual em dashboard.pluggy.ai.",
                    ok=False,
                )
            )
            return achados
        if r.status_code != 200:
            return achados

        item = r.json()
        conector = item.get("connector") or {}
        achados.append(
            Achado(
                "instituição",
                f"{conector.get('name')} (conector {conector.get('id')})",
                ok=True,
            )
        )

        for campo, rotulo in CAMPOS_DE_SAUDE:
            if campo not in item:
                continue
            valor = item[campo]
            if valor is None or valor == "":
                continue
            if isinstance(valor, dict):
                valor = valor.get("message") or json.dumps(valor, ensure_ascii=False)
            juizo: bool | None = None
            if campo == "status":
                juizo = valor == "UPDATED"
            elif campo == "executionStatus":
                juizo = valor in ("SUCCESS", "PARTIAL_SUCCESS")
            elif campo in ("userAction", "error"):
                juizo = False
            elif campo == "consecutiveFailedLoginAttempts":
                juizo = not valor
            achados.append(Achado(f"  {rotulo}", str(valor)[:140], ok=juizo))

        # -- o que existe dentro, em contagem ---------------------------------
        for caminho, rotulo in (("/accounts", "contas"), ("/investments", "investimentos")):
            rc = http.get(caminho, headers=cabecalho, params={"itemId": id_item})
            if rc.status_code != 200:
                achados.append(
                    Achado(f"GET {caminho}", f"HTTP {rc.status_code}", ok=False)
                )
                continue
            try:
                quantos = len(rc.json().get("results") or [])
            except ValueError:
                quantos = 0
            achados.append(Achado(f"  {rotulo}", str(quantos), ok=None))

    return achados


def diagnosticar(config: Configuracao) -> list[Achado]:
    """Roda a bateria e devolve o relatório."""
    achados: list[Achado] = []

    achados.append(Achado("host", config.url_api))
    achados.append(Achado("modo", config.modo))
    achados.append(Achado("PLUGGY_CLIENT_ID", _mascarar(config.client_id or "")))
    achados.append(Achado("PLUGGY_CLIENT_SECRET", _mascarar(config.client_secret or "")))

    if not config.client_id or not config.client_secret:
        achados.append(
            Achado("credenciais", "faltando; preencha o .env", ok=False)
        )
        return achados

    with httpx.Client(base_url=config.url_api, timeout=config.timeout_http) as http:
        # --- 1. autenticação ------------------------------------------------
        try:
            auth = http.post(
                "/auth",
                json={
                    "clientId": config.client_id,
                    "clientSecret": config.client_secret,
                },
            )
        except httpx.TransportError as erro:
            achados.append(Achado("POST /auth", f"não chegou: {erro!r}", ok=False))
            return achados

        achados.append(
            Achado("POST /auth", f"HTTP {auth.status_code}", ok=auth.status_code == 200)
        )
        if auth.status_code != 200:
            achados.append(Achado("resposta", _corpo(auth)))
            return achados

        try:
            corpo: dict[str, Any] = auth.json()
        except ValueError:
            achados.append(Achado("resposta do /auth", "não é JSON", ok=False))
            return achados

        # Os NOMES dos campos, não os valores: se a API passar a devolver
        # `token` em vez de `apiKey`, isto mostra na hora.
        achados.append(Achado("campos devolvidos", ", ".join(sorted(corpo))))

        chave = corpo.get("apiKey")
        if not isinstance(chave, str) or not chave:
            achados.append(
                Achado(
                    "campo apiKey",
                    "ausente ou vazio — é o campo que o cliente lê",
                    ok=False,
                )
            )
            return achados
        achados.append(Achado("apiKey recebida", _mascarar(chave), ok=True))
        achados.extend(_achados_do_jwt(chave))

        # --- 1b. a chave vale para alguma coisa? ----------------------------
        #
        # Esta etapa existe porque a conclusão anterior estava errada. O
        # relatório dizia "a apiKey é recusada" ao ver um 401 em /items e
        # mandava investigar plano, ambiente e rotação de credencial. Só que
        # /connectors e /categories respondem 200 com a MESMA chave: ela vale,
        # e o que está bloqueado é um endpoint específico.
        #
        # Distinguir as duas coisas muda completamente o que fazer.
        for caminho, o_que_e in (
            ("/connectors", "conectores disponíveis"),
            ("/categories", "taxonomia de categorias"),
        ):
            try:
                r = http.get(caminho, headers={"X-API-KEY": chave}, params={"page": 1})
            except httpx.TransportError as erro:
                achados.append(Achado(f"GET {caminho}", f"{erro!r}", ok=False))
                continue
            quantos = ""
            if r.status_code == 200:
                try:
                    quantos = f" · {r.json().get('total', '?')} {o_que_e}"
                except ValueError:
                    pass
            achados.append(
                Achado(
                    f"GET {caminho}",
                    f"HTTP {r.status_code}{quantos}",
                    ok=r.status_code == 200,
                )
            )
            if caminho == "/categories" and r.status_code == 200:
                try:
                    total = int(r.json().get("total", 0))
                except (ValueError, TypeError):
                    total = 0
                achados.append(
                    Achado(
                        "categorização",
                        "disponível nesta conta" if total else
                        "indisponível — o de-para da fase 2 fica inerte",
                        ok=bool(total),
                    )
                )

        # --- 2. qual cabeçalho a API aceita ---------------------------------
        # É a pergunta central quando /auth dá 200 e o resto dá 401.
        aceito = None
        for nome, montar in CABECALHOS_CANDIDATOS:
            try:
                r = http.get("/items", headers={nome: montar(chave)}, params={"page": 1})
            except httpx.TransportError as erro:
                achados.append(Achado(f"GET /items via {nome}", f"{erro!r}", ok=False))
                continue

            achados.append(
                Achado(
                    f"GET /items via {nome}",
                    f"HTTP {r.status_code}"
                    + ("" if r.status_code == 200 else f" — {_corpo(r, 200)}"),
                    ok=r.status_code == 200,
                )
            )
            if r.status_code == 200 and aceito is None:
                aceito = (nome, r)

        if aceito is None:
            # A v1 responde um 401 pelado. A v2 do mesmo recurso responde 403
            # com `codeDescription`, e é ela que diz o motivo com todas as
            # letras — LIST_ITEMS_FEATURE_NOT_ENABLED, por exemplo. Perguntar
            # às duas troca três suposições por uma resposta.
            try:
                r = http.get("/v2/items", headers={"X-API-KEY": chave})
                motivo = ""
                try:
                    corpo_v2 = r.json()
                    motivo = str(
                        corpo_v2.get("codeDescription") or corpo_v2.get("message") or ""
                    )
                except ValueError:
                    motivo = r.text[:120]
                achados.append(
                    Achado(
                        "GET /v2/items (motivo)",
                        f"HTTP {r.status_code} — {motivo}",
                        ok=r.status_code == 200,
                    )
                )
                if "LIST_ITEMS_FEATURE_NOT_ENABLED" in motivo:
                    achados.append(
                        Achado(
                            "conclusão",
                            "a aplicação NÃO tem permissão para listar items. "
                            "A chave é válida (veja /connectors e /categories "
                            "acima) — o que falta é liberar esse recurso em "
                            "dashboard.pluggy.ai. Ver interpretação abaixo.",
                            ok=False,
                        )
                    )
                    return achados
            except httpx.TransportError:
                pass

            achados.append(
                Achado(
                    "conclusão",
                    "GET /items foi recusado por todos os cabeçalhos testados. "
                    "Ver interpretação abaixo.",
                    ok=False,
                )
            )
            return achados

        nome_aceito, resposta = aceito
        if nome_aceito != "X-API-KEY":
            achados.append(
                Achado(
                    "ATENÇÃO",
                    f"a API aceitou {nome_aceito}, não X-API-KEY. "
                    f"O cliente precisa mudar.",
                    ok=False,
                )
            )

        # --- 3. o que existe do outro lado ----------------------------------
        try:
            dados = resposta.json()
        except ValueError:
            dados = {}
        itens = dados.get("results", dados if isinstance(dados, list) else [])
        achados.append(Achado("itens (conexões) encontrados", str(len(itens)), ok=bool(itens)))

        for item in itens[:10]:
            conector = (item.get("connector") or {}).get("name", "?")
            achados.append(
                Achado(
                    f"  item {str(item.get('id'))[:8]}…",
                    f"{conector} · status={item.get('status')} "
                    f"· execução={item.get('executionStatus')}",
                    ok=item.get("status") == "UPDATED",
                )
            )

        if not itens:
            achados.append(
                Achado(
                    "conclusão",
                    "autenticação funciona, mas não há nenhuma conexão nesta "
                    "aplicação. Falta criar o item do conector MeuPluggy (id 200) "
                    "no dashboard.pluggy.ai.",
                    ok=False,
                )
            )

    return achados


INTERPRETACAO_401 = """\
COMO LER UM 401 EM /items LOGO DEPOIS DE UM /auth BEM-SUCEDIDO

Primeiro, o que já está descartado. Se /connectors e /categories responderam
200 no relatório acima, então:

  - as credenciais são válidas;
  - a apiKey foi aceita;
  - o cabeçalho X-API-KEY é o certo;
  - o ambiente e o plano dão acesso à API.

Nada disso é o problema. O que está bloqueado é UM recurso: listar items.

POR QUE O ERRO É TÃO POUCO INFORMATIVO

  GET /items      -> 401 "Unauthorized"                    (não explica nada)
  GET /v2/items   -> 403 "LIST_ITEMS_FEATURE_NOT_ENABLED"  (explica tudo)

São o mesmo recurso. A v1 responde um 401 pelado; a v2 diz o motivo por
extenso. É por isso que o diagnóstico pergunta às duas.

O QUE FAZER, NA ORDEM

1. CONFIRMAR QUE É ISSO
   Se o relatório acima mostra LIST_ITEMS_FEATURE_NOT_ENABLED, é isso. Pule
   para o passo 2. Se mostra outra coisa, leia a mensagem: ela é específica.

2. PEDIR A LIBERAÇÃO DO RECURSO
   "Listar items" não vem habilitado por padrão em toda aplicação. Entre em
   dashboard.pluggy.ai, abra a sua aplicação e procure a configuração de
   recursos/permissões da API. Não havendo a opção, é pedido para o suporte
   da Pluggy — mande o errorId que aparece no relatório, ele é rastreável.

3. ENQUANTO ISSO, O CAMINHO ALTERNATIVO
   A ingestão só usa /items para descobrir os itemId. Com os itemId em mãos,
   /accounts, /v2/transactions e /investments funcionam normalmente — eles
   NÃO dependem de listar items. Os ids aparecem em meu.pluggy.ai, na conexão
   de cada instituição.

   Lembre da armadilha 8: reautorizar gera um itemId novo, então id anotado
   à mão vence. É contorno, não solução.

O que NÃO adianta fazer: rotacionar a credencial, trocar de ambiente, mudar o
cabeçalho ou mexer no .env. Os quatro já estão descartados pelo relatório.\
"""
