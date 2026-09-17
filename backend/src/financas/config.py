"""
Configuração do pipeline.

Duas fontes, propositalmente separadas:

- **Variáveis de ambiente** (`.env`): segredos e caminhos. Dependem da máquina,
  nunca entram no repositório.
- **`config/regras.toml`**: filtros de negócio. Mudam a resposta das views sem
  exigir reingestão.

Este módulo só lê, valida e falha cedo. Nenhuma regra é aplicada aqui — quem
aplica é o SQL. O objetivo é que um erro de configuração apareça antes de a
primeira requisição sair, com uma mensagem que diga o que fazer.
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

MODO_ONLINE = "online"
MODO_OFFLINE = "offline"
MODOS_VALIDOS = (MODO_OFFLINE, MODO_ONLINE)

TIPOS_DE_CONTRAPARTE = ("titular", "chave_pix", "contraparte")

# O itemId da Pluggy é um UUID. Validar o formato aqui é barato e evita a
# viagem até a API só para descobrir que faltou um caractere na cópia — e
# `config.py` falha cedo por princípio.
PADRAO_DE_UUID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# As três bandeiras de ruído de `stg_transacoes`, na ordem das armadilhas 1, 2
# e 3. A categoria da Pluggy pode reforçar qualquer uma delas.
BANDEIRAS_DE_RUIDO = ("fatura", "transferencia_propria", "aplicacao")

# Rótulos de quem não casou com nenhuma regra nem com o de-para. São rótulo, e
# não NULL, de propósito: NULL some de JOIN e de filtro sem avisar, e gasto que
# desaparece em silêncio é o modo de falha que este projeto combate. Ficam em
# `cfg_geral`, então dá para renomeá-los sem tocar em SQL.
CATEGORIA_PADRAO = "Sem categoria"
GRUPO_PADRAO = "Sem grupo"


class ErroDeConfiguracao(Exception):
    """Configuração ausente, mal formada ou inconsistente.

    Carrega a lista completa de problemas encontrados, e não só o primeiro:
    corrigir um `.env` de cada vez, uma variável por execução, é irritante.
    """

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = problemas
        corpo = "\n".join(f"  - {p}" for p in problemas)
        super().__init__(f"Configuração inválida:\n{corpo}")


# ---------------------------------------------------------------------------
# Regras de negócio (config/regras.toml)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PadraoDeDescricao:
    """Padrão que reconhece um tipo de lançamento pela descrição.

    Usado tanto para pagamento de fatura (armadilha 1) quanto para aplicação em
    investimento (armadilha 3).

    Os dois campos são padrões LIKE comparados em minúsculas. `instituicao`
    também é padrão, e não igualdade, porque o `connector.name` da API nem
    sempre é o nome curto: a Rico vem como "Rico Investimentos", então só
    `"rico%"` casa. `"%"` vale para todas.
    """

    instituicao: str
    padrao: str
    observacao: str = ""


@dataclass(frozen=True)
class ItemConfigurado:
    """Um `itemId` autorizado, guardado à mão.

    Existe porque `GET /items` é bloqueado pela Pluggy por design — a FAQ diz
    que listar items "is not available for security reasons, so that no data
    can leak across clients". Não há o que habilitar: o cliente precisa saber
    de antemão quais items consultar.

    `instituicao` é o nome curto que vai para TODAS as linhas ingeridas por
    este item, e não é enfeite: com o conector MeuPluggy (200), que é
    agregador, `connector.name` devolve "MeuPluggy" para todo item. Sem este
    campo, as cinco instituições viram uma só — `patrimonio` colapsa numa
    linha, `frescor` deixa de saber quem parou, e todo padrão escopado por
    instituição para de casar.

    Ele também resolve o caso do id morto: quando `/items/{id}` devolve 404 não
    há connector nenhum, e "o item a1b2c3d4… morreu" é pior que "o PicPay
    morreu".
    """

    id: str
    instituicao: str = ""
    observacao: str = ""

    @property
    def rotulo(self) -> str:
        """Como esta conexão aparece em relatório."""
        return self.instituicao or self.observacao or self.id


@dataclass(frozen=True)
class ContrapartePropria:
    """Identificador de uma conta do próprio titular.

    `tipo` diz em qual campo da transação procurar; ver `TIPOS_DE_CONTRAPARTE`.
    """

    tipo: str
    valor: str
    observacao: str = ""


@dataclass(frozen=True)
class LimiteFrescor:
    """Tolerância de atraso, em dias, para uma instituição específica.

    `instituicao` é padrão LIKE, pelo mesmo motivo de `PadraoFatura`.
    """

    instituicao: str
    dias_maximos: int
    observacao: str = ""


@dataclass(frozen=True)
class RegraDeCategoria:
    """Regra que atribui categoria própria pelo texto do lançamento (fase 2).

    É a primeira das três camadas de resolução, e a única precisa: casa contra a
    descrição **ou** o estabelecimento, porque a Pluggy preenche um ou outro
    conforme a instituição.

    `prioridade` é obrigatória e única no arquivo inteiro. Sem isso, duas regras
    que casassem a mesma transação decidiriam pela ordem das linhas no TOML —
    resultado que muda sozinho quando alguém reordena o arquivo, e que ninguém
    percebe. Menor número vence.

    `padrao` e `instituicao` são padrões LIKE em minúsculas. `categoria` e
    `grupo` não são: são rótulo de saída, e aparecem no relatório como escritos.
    """

    prioridade: int
    instituicao: str
    padrao: str
    categoria: str
    grupo: str
    observacao: str = ""


@dataclass(frozen=True)
class MapaDeCategoria:
    """De-para da categoria da Pluggy para a sua (fase 2).

    Segunda camada: cobre o que nenhuma regra de texto pegou. O casamento é por
    igualdade no `categoryId` (ex.: `"05070000"`), não por LIKE — o conjunto de
    categorias da Pluggy é finito e conhecido, então exigir igualdade elimina
    por construção a chance de duas linhas casarem a mesma transação.
    """

    id_categoria: str
    categoria: str
    grupo: str
    observacao: str = ""


@dataclass(frozen=True)
class CategoriaDeRuido:
    """Categoria da Pluggy que reforça uma das bandeiras de ruído.

    A Pluggy já classifica nativamente `Credit card payment`,
    `Same person transfer` e `Investments` — exatamente as armadilhas 1, 2 e 3.
    Usar isso como sinal **complementar** ao texto cobre a redação que nenhum
    padrão previu, sem abrir mão do filtro por texto: categorização por ML erra,
    e o texto pega o que ela errar. Marcar é um OR, nunca uma substituição.

    `padrao` casa contra `lower(categoria)`, e `bandeira` diz qual das três
    reforçar (ver `BANDEIRAS_DE_RUIDO`).
    """

    bandeira: str
    padrao: str
    observacao: str = ""


@dataclass(frozen=True)
class Regras:
    """Conteúdo validado de `config/regras.toml`."""

    data_inicial: date
    frescor_dias_padrao: int
    itens: tuple[ItemConfigurado, ...] = ()
    recorrencia_meses_minimos: int = 2
    recorrencia_variacao_maxima: float = 0.15
    categoria_padrao: str = CATEGORIA_PADRAO
    grupo_padrao: str = GRUPO_PADRAO
    padroes_fatura: tuple[PadraoDeDescricao, ...] = ()
    padroes_aplicacao: tuple[PadraoDeDescricao, ...] = ()
    contrapartes_proprias: tuple[ContrapartePropria, ...] = ()
    limites_frescor: tuple[LimiteFrescor, ...] = ()
    categorias: tuple[RegraDeCategoria, ...] = ()
    mapa_categorias: tuple[MapaDeCategoria, ...] = ()
    categorias_de_ruido: tuple[CategoriaDeRuido, ...] = ()

    # Não há um `dias_de_frescor()` aqui de propósito. Decidir o que está velho é
    # regra de negócio, e regra de negócio mora no SQL — neste caso na consulta
    # de `financas.frescor`, que casa `cfg_frescor` com `cfg_geral`. Uma versão
    # em Python inevitavelmente divergiria da versão em SQL.


# ---------------------------------------------------------------------------
# Configuração de execução (.env)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Configuracao:
    """Tudo que o pipeline precisa saber para rodar."""

    modo: str
    url_api: str
    caminho_banco: Path
    caminho_regras: Path
    diretorio_fixtures: Path
    timeout_http: float
    tentativas_http: int
    regras: Regras
    client_id: str = ""
    client_secret: str = field(default="", repr=False)

    @property
    def offline(self) -> bool:
        return self.modo == MODO_OFFLINE

    def __repr__(self) -> str:  # pragma: no cover - conveniência de depuração
        # O secret nunca aparece: esta classe acaba em log e em traceback.
        return (
            f"Configuracao(modo={self.modo!r}, url_api={self.url_api!r}, "
            f"caminho_banco={str(self.caminho_banco)!r}, "
            f"client_id={'definido' if self.client_id else 'ausente'}, "
            f"client_secret={'definido' if self.client_secret else 'ausente'})"
        )


def raiz_do_projeto() -> Path:
    """Diretório raiz do repositório, deduzido da posição deste arquivo."""
    return Path(__file__).resolve().parents[2]


def ler_arquivo_env(caminho: Path) -> dict[str, str]:
    """Lê um `.env` simples em `CHAVE=valor`.

    Feito à mão para evitar uma dependência a mais. Suporta comentários com `#`,
    linhas em branco, o prefixo `export` e aspas ao redor do valor. Não suporta
    interpolação de variáveis nem valores em múltiplas linhas — se um dia for
    preciso, aí sim vale trocar por `python-dotenv`.
    """
    if not caminho.is_file():
        return {}

    valores: dict[str, str] = {}
    for numero, linha_bruta in enumerate(
        caminho.read_text(encoding="utf-8").splitlines(), start=1
    ):
        linha = linha_bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if linha.startswith("export "):
            linha = linha[len("export ") :].lstrip()
        if "=" not in linha:
            raise ErroDeConfiguracao(
                [f"{caminho}:{numero}: linha sem '=': {linha_bruta!r}"]
            )
        chave, _, valor = linha.partition("=")
        chave = chave.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[chave] = valor
    return valores


def carregar_regras(caminho: Path) -> Regras:
    """Lê e valida `config/regras.toml`.

    Acumula todos os problemas antes de levantar, pelo mesmo motivo do `.env`.
    """
    problemas: list[str] = []

    if not caminho.is_file():
        raise ErroDeConfiguracao(
            [
                f"arquivo de regras não encontrado em {caminho}. "
                f"Copie config/regras.example.toml para {caminho.name} e preencha."
            ]
        )

    try:
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as erro:
        raise ErroDeConfiguracao([f"{caminho}: TOML inválido ({erro})"]) from erro

    geral = dados.get("geral", {})
    if not isinstance(geral, dict):
        raise ErroDeConfiguracao([f"{caminho}: [geral] deve ser uma tabela"])

    data_inicial = geral.get("data_inicial")
    if data_inicial is None:
        problemas.append(f"{caminho}: falta geral.data_inicial (ex.: 2025-08-01)")
    elif not isinstance(data_inicial, date):
        problemas.append(
            f"{caminho}: geral.data_inicial deve ser uma data TOML sem aspas "
            f"(ex.: 2025-08-01), recebi {data_inicial!r}"
        )

    frescor_padrao = geral.get("frescor_dias_padrao")
    if frescor_padrao is None:
        problemas.append(f"{caminho}: falta geral.frescor_dias_padrao (ex.: 5)")
    elif not isinstance(frescor_padrao, int) or isinstance(frescor_padrao, bool):
        problemas.append(
            f"{caminho}: geral.frescor_dias_padrao deve ser inteiro, "
            f"recebi {frescor_padrao!r}"
        )
    elif frescor_padrao < 1:
        problemas.append(
            f"{caminho}: geral.frescor_dias_padrao deve ser >= 1 "
            f"(a API tem latência de até 24h), recebi {frescor_padrao}"
        )

    meses_minimos = _inteiro_de_geral(
        geral, "recorrencia_meses_minimos", 2, caminho, problemas
    )
    variacao_maxima = _fracao_de_geral(
        geral, "recorrencia_variacao_maxima", 0.15, caminho, problemas
    )

    itens = _itens_configurados(dados, caminho, problemas)

    padroes = _padroes_de_descricao(dados, "pagamento_fatura", caminho, problemas)
    aplicacoes = _padroes_de_descricao(dados, "aplicacao", caminho, problemas)

    contrapartes: list[ContrapartePropria] = []
    for indice, bruto in enumerate(
        _lista_de_tabelas(dados, "transferencia_propria", caminho, problemas)
    ):
        rotulo = f"{caminho}: [[transferencia_propria]] #{indice + 1}"
        tipo = _texto(bruto, "tipo", rotulo, problemas)
        valor = _texto(bruto, "valor", rotulo, problemas)
        if tipo and tipo not in TIPOS_DE_CONTRAPARTE:
            problemas.append(
                f"{rotulo}: tipo deve ser um de {list(TIPOS_DE_CONTRAPARTE)}, "
                f"recebi {tipo!r}"
            )
            continue
        if tipo and valor:
            contrapartes.append(
                ContrapartePropria(tipo, valor.lower(), str(bruto.get("observacao", "")))
            )

    limites: list[LimiteFrescor] = []
    for indice, bruto in enumerate(_lista_de_tabelas(dados, "frescor", caminho, problemas)):
        rotulo = f"{caminho}: [[frescor]] #{indice + 1}"
        instituicao = _texto(bruto, "instituicao", rotulo, problemas)
        _exigir_minusculas(instituicao, "instituicao", rotulo, problemas)
        dias = bruto.get("dias_maximos")
        if not isinstance(dias, int) or isinstance(dias, bool) or dias < 1:
            problemas.append(f"{rotulo}: dias_maximos deve ser inteiro >= 1, recebi {dias!r}")
            continue
        if instituicao:
            limites.append(
                LimiteFrescor(instituicao, dias, str(bruto.get("observacao", "")))
            )

    categorias = _regras_de_categoria(dados, caminho, problemas)
    mapa = _mapa_de_categorias(dados, caminho, problemas)
    ruido = _categorias_de_ruido(dados, caminho, problemas)

    categoria_padrao = _rotulo_de_geral(
        geral, "categoria_padrao", CATEGORIA_PADRAO, caminho, problemas
    )
    grupo_padrao = _rotulo_de_geral(
        geral, "grupo_padrao", GRUPO_PADRAO, caminho, problemas
    )

    if problemas:
        raise ErroDeConfiguracao(problemas)

    return Regras(
        data_inicial=data_inicial,  # type: ignore[arg-type]
        frescor_dias_padrao=frescor_padrao,  # type: ignore[arg-type]
        itens=tuple(itens),
        recorrencia_meses_minimos=meses_minimos,
        recorrencia_variacao_maxima=variacao_maxima,
        categoria_padrao=categoria_padrao,
        grupo_padrao=grupo_padrao,
        padroes_fatura=tuple(padroes),
        padroes_aplicacao=tuple(aplicacoes),
        contrapartes_proprias=tuple(contrapartes),
        limites_frescor=tuple(limites),
        categorias=tuple(categorias),
        mapa_categorias=tuple(mapa),
        categorias_de_ruido=tuple(ruido),
    )


def carregar_configuracao(
    ambiente: Mapping[str, str] | None = None,
    raiz: Path | None = None,
) -> Configuracao:
    """Monta a configuração a partir do ambiente e do arquivo de regras.

    Precedência: variável de ambiente de verdade > `.env` > padrão embutido.
    Assim dá para sobrescrever qualquer coisa numa execução pontual sem editar
    arquivo.

    Args:
        ambiente: substitui `os.environ`. Existe para os testes não dependerem
            do ambiente da máquina.
        raiz: substitui a raiz do projeto, usada para resolver caminhos
            relativos e localizar o `.env`.
    """
    raiz = (raiz or raiz_do_projeto()).resolve()
    do_processo = dict(os.environ if ambiente is None else ambiente)
    do_arquivo = ler_arquivo_env(raiz / ".env")
    valores = {**do_arquivo, **do_processo}

    problemas: list[str] = []

    modo = valores.get("FINANCAS_MODO", MODO_OFFLINE).strip().lower()
    if modo not in MODOS_VALIDOS:
        problemas.append(
            f"FINANCAS_MODO deve ser um de {list(MODOS_VALIDOS)}, recebi {modo!r}"
        )

    client_id = valores.get("PLUGGY_CLIENT_ID", "").strip()
    client_secret = valores.get("PLUGGY_CLIENT_SECRET", "").strip()

    # No modo offline nada de rede acontece, então cobrar credencial só atrapalha
    # quem está desenvolvendo. No modo online elas são obrigatórias.
    if modo == MODO_ONLINE:
        for nome, valor in (
            ("PLUGGY_CLIENT_ID", client_id),
            ("PLUGGY_CLIENT_SECRET", client_secret),
        ):
            if not valor:
                problemas.append(
                    f"{nome} é obrigatória com FINANCAS_MODO=online. "
                    f"Pegue em dashboard.pluggy.ai > sua aplicação > credenciais "
                    f"e coloque no .env (veja env.example)."
                )
            elif valor.startswith("<") and valor.endswith(">"):
                problemas.append(
                    f"{nome} ainda está com o placeholder {valor!r} do env.example."
                )

    url_api = valores.get("PLUGGY_API_URL", "https://api.pluggy.ai").strip().rstrip("/")
    if not url_api.startswith(("http://", "https://")):
        problemas.append(
            f"PLUGGY_API_URL deve começar com http:// ou https://, recebi {url_api!r}"
        )

    timeout = _numero(valores, "FINANCAS_TIMEOUT", 30.0, problemas)
    tentativas = int(_numero(valores, "FINANCAS_TENTATIVAS", 3.0, problemas, inteiro=True))

    caminho_banco = _resolver(raiz, valores.get("FINANCAS_BANCO", "dados/financas.duckdb"))
    caminho_regras = _resolver(raiz, valores.get("FINANCAS_REGRAS", "config/regras.toml"))
    diretorio_fixtures = _resolver(
        raiz, valores.get("FINANCAS_FIXTURES", "tests/fixtures/pluggy")
    )

    if modo == MODO_OFFLINE and not diretorio_fixtures.is_dir():
        problemas.append(
            f"FINANCAS_MODO=offline exige fixtures, mas {diretorio_fixtures} não existe. "
            f"Aponte FINANCAS_FIXTURES para o diretório certo."
        )

    if problemas:
        raise ErroDeConfiguracao(problemas)

    regras = carregar_regras(caminho_regras)

    return Configuracao(
        modo=modo,
        url_api=url_api,
        caminho_banco=caminho_banco,
        caminho_regras=caminho_regras,
        diretorio_fixtures=diretorio_fixtures,
        timeout_http=timeout,
        tentativas_http=tentativas,
        regras=regras,
        client_id=client_id,
        client_secret=client_secret,
    )


# ---------------------------------------------------------------------------
# Auxiliares de validação
# ---------------------------------------------------------------------------


def _resolver(raiz: Path, valor: str) -> Path:
    """Resolve um caminho do `.env` relativo à raiz do projeto."""
    caminho = Path(valor.strip()).expanduser()
    return caminho if caminho.is_absolute() else (raiz / caminho).resolve()


def _numero(
    valores: Mapping[str, str],
    nome: str,
    padrao: float,
    problemas: list[str],
    *,
    inteiro: bool = False,
) -> float:
    bruto = valores.get(nome, "").strip()
    if not bruto:
        return padrao
    try:
        numero = float(bruto)
    except ValueError:
        problemas.append(f"{nome} deve ser numérico, recebi {bruto!r}")
        return padrao
    if numero <= 0:
        problemas.append(f"{nome} deve ser maior que zero, recebi {bruto!r}")
        return padrao
    if inteiro and numero != int(numero):
        problemas.append(f"{nome} deve ser inteiro, recebi {bruto!r}")
        return padrao
    return numero


def _lista_de_tabelas(
    dados: dict, chave: str, caminho: Path, problemas: list[str]
) -> list[dict]:
    """Extrai `[[chave]]` do TOML, tolerando ausência e reclamando de formato."""
    bruto = dados.get(chave, [])
    if not isinstance(bruto, list):
        problemas.append(f"{caminho}: {chave} deve ser uma lista de tabelas [[{chave}]]")
        return []
    limpo = []
    for item in bruto:
        if isinstance(item, dict):
            limpo.append(item)
        else:
            problemas.append(f"{caminho}: cada [[{chave}]] deve ser uma tabela, recebi {item!r}")
    return limpo


def _itens_configurados(
    dados: dict, caminho: Path, problemas: list[str]
) -> list[ItemConfigurado]:
    """Lê `[[item]]`: os itemId que a ingestão vai percorrer.

    Recusa id repetido e id que não é UUID. Ausência NÃO é erro aqui: o modo
    offline não precisa de itemId nenhum, e cobrar isso atrapalharia o
    desenvolvimento. Quem cobra é a ingestão online, que sabe o que faltou.
    """
    itens: list[ItemConfigurado] = []
    vistos: set[str] = set()

    for indice, bruto in enumerate(_lista_de_tabelas(dados, "item", caminho, problemas)):
        rotulo_erro = f"{caminho}: [[item]] #{indice + 1}"
        id_item = _texto(bruto, "id", rotulo_erro, problemas)
        if not id_item:
            continue

        if not PADRAO_DE_UUID.match(id_item):
            problemas.append(
                f"{rotulo_erro}: id deve ser um UUID "
                f"(xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx), recebi {id_item!r}. "
                f"Copie o id do item em dashboard.pluggy.ai."
            )
            continue

        if id_item.lower() in vistos:
            problemas.append(f"{rotulo_erro}: id {id_item!r} aparece mais de uma vez.")
            continue

        instituicao = str(bruto.get("instituicao", "")).strip()
        if not instituicao:
            problemas.append(
                f"{rotulo_erro}: falta `instituicao`. Com o conector MeuPluggy "
                f"o campo connector.name devolve 'MeuPluggy' para todos os "
                f"items, então sem este nome as instituições viram uma só e "
                f"`patrimonio` e `frescor` param de distinguir quem é quem. "
                f"Escreva o nome curto, ex.: instituicao = \"Nubank\"."
            )
            continue

        vistos.add(id_item.lower())
        itens.append(
            ItemConfigurado(
                id=id_item,
                instituicao=instituicao,
                observacao=str(bruto.get("observacao", "")).strip(),
            )
        )

    return itens


def _padroes_de_descricao(
    dados: dict, chave: str, caminho: Path, problemas: list[str]
) -> list[PadraoDeDescricao]:
    """Lê uma seção `[[chave]]` no formato instituicao + padrao.

    Serve para `pagamento_fatura` e `aplicacao`, que têm a mesma forma e a mesma
    função: reconhecer um lançamento pela descrição para tirá-lo dos gastos.
    """
    padroes: list[PadraoDeDescricao] = []
    for indice, bruto in enumerate(_lista_de_tabelas(dados, chave, caminho, problemas)):
        rotulo = f"{caminho}: [[{chave}]] #{indice + 1}"
        instituicao = _texto(bruto, "instituicao", rotulo, problemas)
        padrao = _texto(bruto, "padrao", rotulo, problemas)
        _exigir_minusculas(instituicao, "instituicao", rotulo, problemas)
        _exigir_minusculas(padrao, "padrao", rotulo, problemas)
        if instituicao and padrao:
            padroes.append(
                PadraoDeDescricao(instituicao, padrao, str(bruto.get("observacao", "")))
            )
    return padroes


def _regras_de_categoria(
    dados: dict, caminho: Path, problemas: list[str]
) -> list[RegraDeCategoria]:
    """Lê `[[categoria]]`: a camada de regra por texto da fase 2.

    Recusa prioridade repetida. Duas regras com a mesma prioridade que casassem
    a mesma transação teriam desempate arbitrário, e o resultado passaria a
    depender da ordem das linhas no arquivo — falha que não aparece em teste
    nenhum e muda o relatório quando alguém reordena o TOML.
    """
    regras: list[RegraDeCategoria] = []
    vistas: dict[int, str] = {}

    for indice, bruto in enumerate(
        _lista_de_tabelas(dados, "categoria", caminho, problemas)
    ):
        rotulo = f"{caminho}: [[categoria]] #{indice + 1}"

        padrao = _texto(bruto, "padrao", rotulo, problemas)
        categoria = _texto(bruto, "categoria", rotulo, problemas)
        grupo = _texto(bruto, "grupo", rotulo, problemas)

        # Ausente vale para todas, igual às outras seções.
        instituicao = str(bruto.get("instituicao", "%")).strip() or "%"

        _exigir_minusculas(padrao, "padrao", rotulo, problemas)
        _exigir_minusculas(instituicao, "instituicao", rotulo, problemas)

        prioridade = bruto.get("prioridade")
        if not isinstance(prioridade, int) or isinstance(prioridade, bool):
            problemas.append(
                f"{rotulo}: prioridade é obrigatória e deve ser inteiro "
                f"(menor vence), recebi {prioridade!r}"
            )
            continue
        if prioridade in vistas:
            problemas.append(
                f"{rotulo}: prioridade {prioridade} já é usada por {vistas[prioridade]!r}. "
                f"Prioridade precisa ser única, senão o desempate entre duas regras "
                f"que casam a mesma transação vira a ordem das linhas do arquivo."
            )
            continue

        if padrao and categoria and grupo:
            vistas[prioridade] = padrao
            regras.append(
                RegraDeCategoria(
                    prioridade=prioridade,
                    instituicao=instituicao,
                    padrao=padrao,
                    categoria=categoria,
                    grupo=grupo,
                    observacao=str(bruto.get("observacao", "")),
                )
            )

    return sorted(regras, key=lambda r: r.prioridade)


def _mapa_de_categorias(
    dados: dict, caminho: Path, problemas: list[str]
) -> list[MapaDeCategoria]:
    """Lê `[[mapa_categoria]]`: o de-para da categoria da Pluggy.

    Recusa `id_categoria` repetido pelo mesmo motivo da prioridade — só que
    aqui a unicidade também é o que permite casar por igualdade em vez de LIKE.
    """
    mapa: list[MapaDeCategoria] = []
    vistos: set[str] = set()

    for indice, bruto in enumerate(
        _lista_de_tabelas(dados, "mapa_categoria", caminho, problemas)
    ):
        rotulo = f"{caminho}: [[mapa_categoria]] #{indice + 1}"

        id_categoria = _texto(bruto, "id_categoria", rotulo, problemas)
        categoria = _texto(bruto, "categoria", rotulo, problemas)
        grupo = _texto(bruto, "grupo", rotulo, problemas)

        if id_categoria and id_categoria in vistos:
            problemas.append(
                f"{rotulo}: id_categoria {id_categoria!r} aparece mais de uma vez. "
                f"O de-para casa por igualdade, então cada id só pode ter um destino."
            )
            continue

        if id_categoria and categoria and grupo:
            vistos.add(id_categoria)
            mapa.append(
                MapaDeCategoria(
                    id_categoria=id_categoria,
                    categoria=categoria,
                    grupo=grupo,
                    observacao=str(bruto.get("observacao", "")),
                )
            )

    return mapa


def _categorias_de_ruido(
    dados: dict, caminho: Path, problemas: list[str]
) -> list[CategoriaDeRuido]:
    """Lê `[[categoria_ruido]]`: a categoria da Pluggy reforçando uma bandeira."""
    lista: list[CategoriaDeRuido] = []

    for indice, bruto in enumerate(
        _lista_de_tabelas(dados, "categoria_ruido", caminho, problemas)
    ):
        rotulo = f"{caminho}: [[categoria_ruido]] #{indice + 1}"

        bandeira = _texto(bruto, "bandeira", rotulo, problemas)
        padrao = _texto(bruto, "padrao", rotulo, problemas)
        _exigir_minusculas(padrao, "padrao", rotulo, problemas)

        if bandeira and bandeira not in BANDEIRAS_DE_RUIDO:
            problemas.append(
                f"{rotulo}: bandeira deve ser uma de {list(BANDEIRAS_DE_RUIDO)}, "
                f"recebi {bandeira!r}"
            )
            continue

        if bandeira and padrao:
            lista.append(
                CategoriaDeRuido(bandeira, padrao, str(bruto.get("observacao", "")))
            )

    return lista


def _rotulo_de_geral(
    geral: dict, campo: str, padrao: str, caminho: Path, problemas: list[str]
) -> str:
    """Lê um rótulo de saída de `[geral]`, tolerando ausência.

    Diferente dos padrões LIKE, rótulo não é normalizado para minúsculas: ele
    aparece no relatório exatamente como foi escrito.
    """
    valor = geral.get(campo, padrao)
    if not isinstance(valor, str) or not valor.strip():
        problemas.append(
            f"{caminho}: geral.{campo} deve ser um texto não vazio, recebi {valor!r}"
        )
        return padrao
    return valor.strip()


def _inteiro_de_geral(
    geral: dict, campo: str, padrao: int, caminho: Path, problemas: list[str]
) -> int:
    valor = geral.get(campo, padrao)
    if not isinstance(valor, int) or isinstance(valor, bool) or valor < 1:
        problemas.append(f"{caminho}: geral.{campo} deve ser inteiro >= 1, recebi {valor!r}")
        return padrao
    return valor


def _fracao_de_geral(
    geral: dict, campo: str, padrao: float, caminho: Path, problemas: list[str]
) -> float:
    valor = geral.get(campo, padrao)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not 0 <= valor <= 1:
        problemas.append(
            f"{caminho}: geral.{campo} deve ser um número entre 0 e 1 "
            f"(fração, não porcentagem), recebi {valor!r}"
        )
        return padrao
    return float(valor)


def _exigir_minusculas(
    valor: str, campo: str, rotulo: str, problemas: list[str]
) -> None:
    """Padrão LIKE precisa estar em minúsculas.

    A comparação no SQL é `lower(coluna) LIKE padrao`. Um padrão com maiúscula
    simplesmente nunca casa — e falha silenciosa em filtro de gasto é
    exatamente o que este projeto não pode ter.
    """
    if valor and valor != valor.lower():
        problemas.append(
            f"{rotulo}: {campo} deve estar em minúsculas (a comparação usa "
            f"lower(), então maiúscula nunca casaria), recebi {valor!r}"
        )


def _texto(bruto: dict, campo: str, rotulo: str, problemas: list[str]) -> str:
    valor = bruto.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        problemas.append(f"{rotulo}: campo {campo!r} obrigatório e não vazio")
        return ""
    return valor.strip()
