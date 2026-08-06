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

from financas.config import Configuracao

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
            achados.append(
                Achado(
                    "conclusão",
                    "a apiKey é recusada por todos os cabeçalhos testados. "
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
COMO LER UM 401 LOGO DEPOIS DE UM /auth BEM-SUCEDIDO

As credenciais são válidas — o /auth as aceitou e devolveu uma apiKey bem
formada. O que foi recusado foi essa chave, na requisição seguinte.

Repare na diferença entre os erros acima, porque ela é informativa:

  X-API-KEY      -> 401 "Unauthorized"
  Authorization  -> 403 "API_KEY_MISSING_OR_INVALID"

O 403 diz "não achei chave nenhuma aqui" — é o esperado, já que a Pluggy lê a
chave só do X-API-KEY. O 401 é diferente: a chave FOI lida, reconhecida como
bem formada, e ainda assim negada. Isso descarta erro de cabeçalho, de formato
e de credencial, e deixa três causas:

1. CONTA SEM ACESSO À API (mais provável em plano gratuito)
   A aplicação existe e autentica, mas o acesso aos dados foi cortado — trial
   encerrado, ou plano que não inclui consumo de API.
   Onde conferir: dashboard.pluggy.ai, aba de plano ou billing da aplicação.

2. CREDENCIAL DE OUTRO AMBIENTE
   Cada aplicação tem um par por ambiente. Autenticar com o par de um e
   consultar dados de outro devolve exatamente este 401.
   Onde conferir: dashboard.pluggy.ai > sua aplicação > credenciais; confirme
   que está copiando as de Desenvolvimento.

3. APLICAÇÃO DESATIVADA OU PAR ROTACIONADO PELA METADE
   Se só o secret foi atualizado no .env, o /auth pode passar e a chave sair
   sem escopo.
   Onde conferir: gere um par novo e substitua os DOIS valores.

Os claims da apiKey aparecem no relatório acima. Se houver algum indicando
plano, escopo ou validade, é ele que responde qual dos três casos é o seu.

O `errorId` de cada resposta é rastreável pelo suporte da Pluggy — é o que
vale mandar para eles, junto do horário, se nada acima resolver.\
"""
