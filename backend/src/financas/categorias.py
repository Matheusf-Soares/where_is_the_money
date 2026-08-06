"""
Apoio à categorização própria (fase 2).

Duas funções, uma para cada metade do problema:

- `gerar_de_para` transforma a taxonomia devolvida por `GET /categories` num
  bloco `[[mapa_categoria]]` pronto para colar no `regras.toml`. Existe porque
  os ids da Pluggy (`05080000` e afins) não estão publicados em lugar nenhum:
  só saem da API. Adivinhá-los produz um de-para que não casa nada — e que
  falha em silêncio, que é o modo de falha que este projeto combate.

- `auditar` responde as duas perguntas que dizem se a configuração está viva:
  qual regra nunca casou com nada, e quanto do gasto ficou sem categoria. Uma
  regra morta é um filtro que não filtra.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from financas.config import Regras
from financas.persistencia import Banco

# Os grupos são decisão do titular, não da Pluggy. O gerador escreve este
# placeholder para que o arquivo saia sintaticamente válido e obviamente
# incompleto — melhor do que chutar um grupo que ninguém revisou.
GRUPO_A_DEFINIR = "A definir"


# ---------------------------------------------------------------------------
# Geração do de-para
# ---------------------------------------------------------------------------


def gerar_de_para(
    categorias: list[dict[str, Any]], *, existentes: Regras | None = None
) -> str:
    """Monta o bloco `[[mapa_categoria]]` a partir da taxonomia da API.

    Args:
        categorias: resposta de `GET /categories`.
        existentes: regras já carregadas. Quando passadas, as categorias que já
            têm destino são comentadas em vez de repetidas — colar o bloco duas
            vezes geraria `id_categoria` duplicado, que a validação recusa.

    O texto sai ordenado por id, que é o mesmo que dizer agrupado por ramo da
    árvore: as filhas ficam logo abaixo da mãe, e decidir o grupo de um ramo
    inteiro vira uma passada só.
    """
    ja_mapeadas = (
        {m.id_categoria for m in existentes.mapa_categorias} if existentes else set()
    )

    linhas = [
        "# Gerado por `python -m financas categorias --sincronizar`.",
        "# Os ids vêm de GET /categories, então não há chute aqui.",
        "#",
        f"# Preencha o grupo de cada linha: {GRUPO_A_DEFINIR!r} é placeholder.",
        "# Apague as categorias que você nunca vai usar — o de-para é rede de",
        "# segurança, não precisa cobrir o que nunca vai aparecer no seu extrato.",
        "",
    ]

    limpas = sorted(
        (c for c in categorias if _texto(c.get("id"))),
        key=lambda c: str(c.get("id")),
    )

    if not limpas:
        linhas.append("# A API não devolveu categoria nenhuma.")
        linhas.append("# Categorização é feature premium na Pluggy: se não estiver")
        linhas.append("# habilitada, `category` vem nulo em todas as transações e")
        linhas.append("# esta camada não tem o que fazer.")
        return "\n".join(linhas) + "\n"

    for categoria in limpas:
        id_categoria = _texto(categoria.get("id"))
        descricao = _texto(categoria.get("description"))
        traduzida = _texto(categoria.get("descriptionTranslated"))
        mae = _texto(categoria.get("parentDescription"))

        rotulo = traduzida or descricao or id_categoria
        comentario = f"  # {descricao}" if descricao and traduzida else ""
        if mae:
            comentario += f" (dentro de {mae})" if comentario else f"  # em {mae}"

        prefixo = "# " if id_categoria in ja_mapeadas else ""
        if prefixo:
            comentario += "  <- já mapeada no seu regras.toml"

        linhas.extend(
            [
                f"{prefixo}[[mapa_categoria]]{comentario}",
                f'{prefixo}id_categoria = "{id_categoria}"',
                f'{prefixo}categoria = "{_escapar(rotulo)}"',
                f'{prefixo}grupo = "{GRUPO_A_DEFINIR}"',
                "",
            ]
        )

    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Auditoria:
    """Retrato de quão viva está a configuração de categorias."""

    regras_mortas: tuple[tuple[int, str], ...]
    ids_sem_de_para: tuple[tuple[str, str, int], ...]
    total_transacoes: int
    sem_categoria: int
    valor_sem_categoria: Decimal

    @property
    def fracao_sem_categoria(self) -> float:
        if not self.total_transacoes:
            return 0.0
        return self.sem_categoria / self.total_transacoes

    @property
    def tem_alerta(self) -> bool:
        """Regra que nunca casou é sempre suspeita; buraco de cobertura, não.

        Ficar sem categoria é estado normal de quem ainda não terminou de
        escrever o de-para. Regra morta, não: alguém escreveu com uma intenção
        que não se realizou.
        """
        return bool(self.regras_mortas)


def auditar(banco: Banco) -> Auditoria:
    """Confere a configuração de categorias contra o que existe no banco.

    Depende de `stg_transacoes`, ou seja, de `views` já ter rodado.
    """
    mortas = banco.conexao.execute(
        """
        SELECT r.prioridade, r.padrao
        FROM cfg_categorias r
        WHERE NOT EXISTS (
            SELECT 1 FROM stg_transacoes t
            WHERE lower(coalesce(t.instituicao, '')) LIKE r.instituicao
              AND (
                    lower(coalesce(t.descricao, ''))       LIKE r.padrao
                 OR lower(coalesce(t.estabelecimento, '')) LIKE r.padrao
              )
        )
        ORDER BY r.prioridade
        """
    ).fetchall()

    sem_de_para = banco.conexao.execute(
        """
        SELECT t.id_categoria, max(t.categoria), count(*)
        FROM stg_transacoes t
        WHERE t.origem_da_categoria = 'padrao'
          AND t.id_categoria IS NOT NULL
          -- As mesmas exclusões do total. Sem elas, a lista mandaria você
          -- escrever de-para para pagamento de fatura e transferência própria,
          -- que nunca chegam em `gastos`: trabalho que não muda nada.
          AND NOT t.e_pagamento_de_fatura
          AND NOT t.e_transferencia_propria
          AND NOT t.e_aplicacao
        GROUP BY t.id_categoria
        ORDER BY count(*) DESC
        """
    ).fetchall()

    total, sem_categoria, valor = banco.conexao.execute(
        """
        SELECT
            count(*),
            count(*) FILTER (WHERE origem_da_categoria = 'padrao'),
            coalesce(sum(CASE WHEN origem_da_categoria = 'padrao' AND valor < 0
                              THEN -valor ELSE 0 END), 0)
        FROM stg_transacoes
        WHERE NOT e_pagamento_de_fatura
          AND NOT e_transferencia_propria
          AND NOT e_aplicacao
        """
    ).fetchone()

    return Auditoria(
        regras_mortas=tuple((int(p), str(t)) for p, t in mortas),
        ids_sem_de_para=tuple(
            (str(i), str(d or ""), int(n)) for i, d, n in sem_de_para
        ),
        total_transacoes=int(total or 0),
        sem_categoria=int(sem_categoria or 0),
        valor_sem_categoria=Decimal(str(valor or 0)),
    )


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------


def _texto(valor: Any) -> str:
    return valor.strip() if isinstance(valor, str) else ""


def _escapar(valor: str) -> str:
    """Escapa para string TOML básica.

    O gerador escreve um arquivo que o `tomllib` vai reler; uma aspa solta num
    nome de categoria quebraria o parse com erro que não aponta para a causa.
    """
    return valor.replace("\\", "\\\\").replace('"', '\\"')
