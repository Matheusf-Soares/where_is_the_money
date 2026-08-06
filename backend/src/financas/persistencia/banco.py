"""
Persistência em DuckDB: schema, upsert idempotente e carga da configuração.

O princípio que rege este módulo é a idempotência. Rodar a ingestão duas vezes
seguidas tem que deixar o banco byte a byte igual — não é preciosismo, é
consequência de o consentimento de Open Finance expirar, de a rede cair e de
ser natural rodar o mesmo comando duas vezes por insegurança.

Como isso é garantido:

1. **Upsert por chave natural**, nunca `INSERT` puro. Transação usa `id`; conta
   e investimento usam `(id, data_posicao)`, porque são estado e não evento.
2. **`ingerido_em` nunca é sobrescrito.** Ele marca quando o registro entrou.
3. **`atualizado_em` só se mexe quando o payload muda de verdade.** Se ele fosse
   carimbado a cada execução, a segunda rodada alteraria o banco e o teste de
   idempotência viraria teatro: passaria sem verificar nada.
4. **Deduplicação dentro do lote.** Páginas sobrepostas podem trazer a mesma
   transação duas vezes na mesma execução, e o `ON CONFLICT` do DuckDB recusa
   atualizar a mesma linha duas vezes na mesma instrução.

Nada de regra de negócio aqui. Este módulo grava o que recebe.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

from financas.config import Regras

registrador = logging.getLogger(__name__)

CAMINHO_DO_SCHEMA = Path(__file__).with_name("schema.sql")

BANCO_EM_MEMORIA = ":memory:"

# Chave natural de cada tabela raw. Ver o comentário no schema.sql para o
# porquê de conta e investimento carregarem a data.
CHAVES_NATURAIS: dict[str, tuple[str, ...]] = {
    "raw_transacoes": ("id",),
    "raw_contas": ("id", "data_posicao"),
    "raw_investimentos": ("id", "data_posicao"),
}

# Colunas de controle: preenchidas pelo banco, não por quem chama.
COLUNAS_DE_CONTROLE = ("ingerido_em", "atualizado_em")


@dataclass(frozen=True)
class ResultadoUpsert:
    """O que aconteceu numa gravação. Serve de relatório para a CLI e de
    asserção para os testes de idempotência."""

    tabela: str
    recebidas: int
    inseridas: int
    atualizadas: int
    inalteradas: int

    @property
    def houve_mudanca(self) -> bool:
        return self.inseridas > 0 or self.atualizadas > 0

    @classmethod
    def somar(cls, tabela: str, partes: Iterable[ResultadoUpsert]) -> ResultadoUpsert:
        """Consolida os resultados de várias gravações na mesma tabela.

        A ingestão grava por instituição, então o relatório final precisa somar.
        """
        total = cls(tabela, 0, 0, 0, 0)
        for parte in partes:
            total = cls(
                tabela,
                total.recebidas + parte.recebidas,
                total.inseridas + parte.inseridas,
                total.atualizadas + parte.atualizadas,
                total.inalteradas + parte.inalteradas,
            )
        return total

    def __str__(self) -> str:
        return (
            f"{self.tabela}: {self.recebidas} recebidas, {self.inseridas} novas, "
            f"{self.atualizadas} atualizadas, {self.inalteradas} sem mudança"
        )


class Banco:
    """Conexão com o DuckDB local.

    Args:
        conexao: conexão DuckDB já aberta.
        agora: substitui `datetime.now`, para os testes controlarem os
            timestamps de controle e conseguirem afirmar que uma segunda
            execução não mexeu neles.
    """

    def __init__(
        self,
        conexao: duckdb.DuckDBPyConnection,
        *,
        agora: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._conexao = conexao
        self._agora = agora

    # -- ciclo de vida ------------------------------------------------------

    @classmethod
    def abrir(
        cls, caminho: Path | str, *, agora: Callable[[], datetime] = datetime.now
    ) -> Banco:
        """Abre (e cria, se preciso) o banco no caminho indicado.

        Aceita `":memory:"`, que é o que os testes usam.
        """
        if str(caminho) != BANCO_EM_MEMORIA:
            caminho = Path(caminho)
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho = str(caminho)
        return cls(duckdb.connect(str(caminho)), agora=agora)

    def __enter__(self) -> Banco:
        return self

    def __exit__(self, *_excecao: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        self._conexao.close()

    @property
    def conexao(self) -> duckdb.DuckDBPyConnection:
        """Acesso direto, para consultas ad hoc e para as views da etapa (e)."""
        return self._conexao

    # -- schema -------------------------------------------------------------

    def criar_schema(self) -> None:
        """Aplica `schema.sql`. Idempotente: tudo é `CREATE TABLE IF NOT EXISTS`."""
        self._conexao.execute(CAMINHO_DO_SCHEMA.read_text(encoding="utf-8"))

    # -- gravação -----------------------------------------------------------

    def gravar_transacoes(self, linhas: Iterable[dict[str, Any]]) -> ResultadoUpsert:
        return self._gravar("raw_transacoes", linhas)

    def gravar_contas(self, linhas: Iterable[dict[str, Any]]) -> ResultadoUpsert:
        return self._gravar("raw_contas", linhas)

    def gravar_investimentos(self, linhas: Iterable[dict[str, Any]]) -> ResultadoUpsert:
        return self._gravar("raw_investimentos", linhas)

    def gravar_regras(self, regras: Regras) -> None:
        """Copia o `regras.toml` para as tabelas `cfg_*`.

        Reescreve tudo: a configuração é pequena e o arquivo é a fonte da
        verdade. Merge incremental só criaria a chance de sobrar no banco um
        padrão que já foi apagado do TOML.
        """
        self._conexao.execute("BEGIN TRANSACTION")
        try:
            self._reescrever(
                "cfg_padroes_fatura",
                [(p.instituicao, p.padrao, p.observacao) for p in regras.padroes_fatura],
            )
            self._reescrever(
                "cfg_padroes_aplicacao",
                [
                    (p.instituicao, p.padrao, p.observacao)
                    for p in regras.padroes_aplicacao
                ],
            )
            self._reescrever(
                "cfg_contrapartes_proprias",
                [(c.tipo, c.valor, c.observacao) for c in regras.contrapartes_proprias],
            )
            self._reescrever(
                "cfg_frescor",
                [
                    (l.instituicao, l.dias_maximos, l.observacao)
                    for l in regras.limites_frescor
                ],
            )
            self._reescrever(
                "cfg_categorias",
                [
                    (
                        c.prioridade,
                        c.instituicao,
                        c.padrao,
                        c.categoria,
                        c.grupo,
                        c.observacao,
                    )
                    for c in regras.categorias
                ],
            )
            self._reescrever(
                "cfg_mapa_categorias",
                [
                    (m.id_categoria, m.categoria, m.grupo, m.observacao)
                    for m in regras.mapa_categorias
                ],
            )
            self._reescrever(
                "cfg_geral",
                [
                    ("data_inicial", regras.data_inicial.isoformat()),
                    ("frescor_dias_padrao", str(regras.frescor_dias_padrao)),
                    ("recorrencia_meses_minimos", str(regras.recorrencia_meses_minimos)),
                    (
                        "recorrencia_variacao_maxima",
                        str(regras.recorrencia_variacao_maxima),
                    ),
                    # Rótulos de quem não casou com nada. Ficam aqui, e não como
                    # literal no .sql, para poderem ser renomeados sem editar view.
                    ("categoria_padrao", regras.categoria_padrao),
                    ("grupo_padrao", regras.grupo_padrao),
                ],
            )
        except Exception:
            self._conexao.execute("ROLLBACK")
            raise
        self._conexao.execute("COMMIT")

    def _reescrever(self, tabela: str, linhas: Sequence[tuple[Any, ...]]) -> None:
        """Apaga e regrava uma tabela `cfg_*`.

        Lista vazia é caso legítimo — um `regras.toml` pode não ter nenhum
        limite de frescor — e o `executemany` do DuckDB recusa lista vazia, daí
        a guarda.
        """
        self._conexao.execute(f"DELETE FROM {tabela}")
        if not linhas:
            return
        marcadores = ", ".join("?" * len(linhas[0]))
        self._conexao.executemany(f"INSERT INTO {tabela} VALUES ({marcadores})", linhas)

    # -- consulta -----------------------------------------------------------

    def contar(self, tabela: str) -> int:
        return int(self._conexao.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0])

    # -- interno ------------------------------------------------------------

    def _gravar(self, tabela: str, linhas: Iterable[dict[str, Any]]) -> ResultadoUpsert:
        chave = CHAVES_NATURAIS[tabela]
        colunas = self._colunas(tabela)
        recebidas = list(linhas)

        unicas = _deduplicar(recebidas, chave)
        if not unicas:
            return ResultadoUpsert(tabela, len(recebidas), 0, 0, 0)

        instante = self._agora()
        valores = [
            tuple(
                instante if coluna in COLUNAS_DE_CONTROLE else linha.get(coluna)
                for coluna in colunas
            )
            for linha in unicas
        ]

        entrada = f"entrada_{tabela}"
        self._conexao.execute("BEGIN TRANSACTION")
        try:
            self._conexao.execute(
                f"CREATE OR REPLACE TEMP TABLE {entrada} AS "
                f"SELECT * FROM {tabela} LIMIT 0"
            )
            self._conexao.executemany(
                f"INSERT INTO {entrada} VALUES ({', '.join('?' * len(colunas))})",
                valores,
            )

            juncao = " AND ".join(f"a.{c} = e.{c}" for c in chave)
            inseridas = self._contar_consulta(
                f"SELECT count(*) FROM {entrada} e "
                f"LEFT JOIN {tabela} a ON {juncao} WHERE a.{chave[0]} IS NULL"
            )
            atualizadas = self._contar_consulta(
                f"SELECT count(*) FROM {entrada} e "
                f"JOIN {tabela} a ON {juncao} "
                f"WHERE a.payload_json IS DISTINCT FROM e.payload_json"
            )

            self._conexao.execute(self._sql_de_upsert(tabela, chave, colunas))
            self._conexao.execute(f"DROP TABLE {entrada}")
        except Exception:
            self._conexao.execute("ROLLBACK")
            raise
        self._conexao.execute("COMMIT")

        resultado = ResultadoUpsert(
            tabela=tabela,
            recebidas=len(recebidas),
            inseridas=inseridas,
            atualizadas=atualizadas,
            inalteradas=len(unicas) - inseridas - atualizadas,
        )
        registrador.info("%s", resultado)
        return resultado

    def _sql_de_upsert(
        self, tabela: str, chave: Sequence[str], colunas: Sequence[str]
    ) -> str:
        """Monta o `INSERT ... ON CONFLICT` da tabela.

        Duas colunas ficam de fora do `SET`, e é aí que mora a idempotência:

        - `ingerido_em` não é atualizado, então guarda a primeira aparição.
        - `atualizado_em` só recebe o instante novo quando o payload difere.
        """
        atribuicoes = [
            f"{coluna} = excluded.{coluna}"
            for coluna in colunas
            if coluna not in chave and coluna not in COLUNAS_DE_CONTROLE
        ]
        atribuicoes.append(
            "atualizado_em = CASE "
            f"WHEN {tabela}.payload_json IS DISTINCT FROM excluded.payload_json "
            f"THEN excluded.atualizado_em ELSE {tabela}.atualizado_em END"
        )
        return (
            f"INSERT INTO {tabela} BY NAME SELECT * FROM entrada_{tabela} "
            f"ON CONFLICT ({', '.join(chave)}) DO UPDATE SET {', '.join(atribuicoes)}"
        )

    def _colunas(self, tabela: str) -> list[str]:
        linhas = self._conexao.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? AND table_schema = 'main' "
            "ORDER BY ordinal_position",
            [tabela],
        ).fetchall()
        if not linhas:
            raise ValueError(
                f"tabela {tabela!r} não existe. Rode criar_schema() antes de gravar."
            )
        return [linha[0] for linha in linhas]

    def _contar_consulta(self, sql: str) -> int:
        return int(self._conexao.execute(sql).fetchone()[0])


def _deduplicar(
    linhas: Sequence[dict[str, Any]], chave: Sequence[str]
) -> list[dict[str, Any]]:
    """Remove repetições de chave dentro do lote, mantendo a última ocorrência.

    Páginas sobrepostas trazem a mesma transação duas vezes, e o `ON CONFLICT`
    do DuckDB recusa atualizar a mesma linha duas vezes na mesma instrução. A
    última ocorrência vence porque, quando a API muda de opinião no meio de uma
    paginação, o dado mais recente é o que veio depois.
    """
    por_chave: dict[tuple[Any, ...], dict[str, Any]] = {}
    for linha in linhas:
        por_chave[tuple(linha.get(c) for c in chave)] = linha
    return list(por_chave.values())
