"""Publica um retrato consistente das views, sem invalidar a versão anterior."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from financas.persistencia import Banco

registrador = logging.getLogger(__name__)
TABELAS_PUBLICADAS = (
    "gastos", "stg_transacoes", "recorrencias", "patrimonio", "stg_contas",
    "stg_investimentos", "transacoes_analiticas", "gastos_analiticos", "compras",
    "recorrencias_analiticas", "qualidade_dados",
)
NOME_DO_MANIFESTO = "manifesto.json"


class ErroDePublicacao(Exception):
    """Faltou uma view, ou não foi possível publicar o retrato completo."""


@dataclass(frozen=True)
class Publicacao:
    destino: Path
    linhas: dict[str, int]
    avisos: tuple[str, ...]
    versao: str = ""

    @property
    def total(self) -> int:
        return sum(self.linhas.values())


def serializar_json(valor: object) -> str:
    """Preserva precisão monetária e datas no contrato HTTP/manifesto."""
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    raise TypeError(f"tipo não serializável: {type(valor).__name__}")


def publicar(banco: Banco, destino: Path, *, agora: datetime | None = None) -> Publicacao:
    """Troca o manifesto somente após exportar todas as views numa transação.

    Cada manifesto aponta para uma geração imutável. Leitores que abriram a
    versão anterior podem terminar suas consultas. Só o manifesto define o
    conjunto ativo; arquivos avulsos no destino não são publicados nem apagados.
    """
    momento = agora or datetime.now(timezone.utc)
    existentes = _views_existentes(banco)
    faltando = [t for t in TABELAS_PUBLICADAS if t not in existentes]
    if faltando:
        raise ErroDePublicacao(
            f"estas views não existem no banco: {', '.join(faltando)}. "
            "Rode 'python -m financas views' antes de publicar."
        )
    versao = uuid4().hex
    pasta = destino / "versoes" / versao
    temporario = destino / f".manifesto-{versao}.tmp"
    linhas: dict[str, int] = {}
    em_transacao = False
    try:
        pasta.mkdir(parents=True)
        banco.conexao.execute("BEGIN TRANSACTION")
        em_transacao = True
        for tabela in TABELAS_PUBLICADAS:
            _exportar_tabela(banco, tabela, pasta / f"{tabela}.parquet")
            linhas[tabela] = int(banco.conexao.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0])
        avisos = _avisos(banco, linhas)
        cursor = banco.conexao.execute("SELECT * FROM qualidade_dados ORDER BY instituicao")
        colunas = [d[0] for d in cursor.description]
        instituicoes = [dict(zip(colunas, r)) for r in cursor.fetchall()]
        manifesto = {
            "versao_schema": 2, "versao": versao, "gerado_em": momento.isoformat(),
            "revisao": banco.conexao.execute("SELECT revisao FROM usr_estado WHERE id=1").fetchone()[0],
            "data_referencia": date.today().isoformat(), "linhas": linhas,
            "periodo": _periodo(banco), "avisos": list(avisos),
            "instituicoes": instituicoes, "tabelas": list(TABELAS_PUBLICADAS),
            "arquivos": {t: f"versoes/{versao}/{t}.parquet" for t in TABELAS_PUBLICADAS},
        }
        banco.conexao.execute("COMMIT")
        em_transacao = False
        temporario.write_text(json.dumps(manifesto, indent=2, ensure_ascii=False, default=serializar_json), encoding="utf-8")
        temporario.replace(destino / NOME_DO_MANIFESTO)
    except Exception as erro:
        if em_transacao:
            banco.conexao.execute("ROLLBACK")
        # Remove apenas caminhos criados nesta chamada, nunca versões anteriores.
        try:
            temporario.unlink(missing_ok=True)
            for tabela in TABELAS_PUBLICADAS:
                (pasta / f"{tabela}.parquet").unlink(missing_ok=True)
            if pasta.is_dir():
                pasta.rmdir()
        except OSError:
            registrador.warning("Geração incompleta não publicada ficou no disco: %s", versao)
        raise ErroDePublicacao(f"a publicação anterior foi preservada: {erro}") from erro
    registrador.info("publicadas %d tabelas, versão %s", len(linhas), versao)
    return Publicacao(destino, linhas, avisos, versao)


def _exportar_tabela(banco: Banco, tabela: str, arquivo: Path) -> None:
    banco.conexao.execute(f"COPY (SELECT * FROM {tabela}) TO ? (FORMAT PARQUET)", [arquivo.as_posix()])


def _avisos(banco: Banco, linhas: dict[str, int]) -> tuple[str, ...]:
    avisos: list[str] = []
    if not linhas.get("gastos_analiticos"):
        avisos.append("Nenhum gasto encontrado. Confira o período e as exclusões em Revisão.")
    (com_categoria,) = banco.conexao.execute(
        "SELECT count(*) FROM stg_transacoes WHERE coalesce(categoria_pluggy, '') <> ''"
    ).fetchone()
    if linhas.get("stg_transacoes") and not com_categoria:
        avisos.append("A Pluggy não devolveu categorias (recurso premium). Classifique pela interface ou por regras.")
    consideradas, sem_categoria, sem_conversao = banco.conexao.execute(
        "SELECT count(*), count(*) FILTER (WHERE categoria = 'Sem categoria'), "
        "count(*) FILTER (WHERE valor_brl IS NULL) FROM gastos_analiticos"
    ).fetchone()
    if consideradas and sem_categoria / consideradas > 0.3:
        avisos.append(f"{sem_categoria} de {consideradas} gastos ({sem_categoria / consideradas:.0%}) estão sem categoria.")
    if sem_conversao:
        avisos.append(f"{sem_conversao} gastos sem conversão comprovada. O consolidado em BRL é parcial.")
    return tuple(avisos)


def _periodo(banco: Banco) -> dict[str, str | None]:
    minimo, maximo, futura = banco.conexao.execute(
        "SELECT min(data) FILTER (WHERE NOT e_futura), max(data) FILTER (WHERE NOT e_futura), "
        "max(data) FILTER (WHERE e_futura) FROM stg_transacoes"
    ).fetchone()
    return dict(zip(("primeira_transacao", "ultima_transacao", "ultima_futura"),
                    (d.isoformat() if d else None for d in (minimo, maximo, futura))))


def _views_existentes(banco: Banco) -> set[str]:
    return {r[0] for r in banco.conexao.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
    ).fetchall()}


def servir(diretorio: Path, porta: int) -> None:
    """Servidor estático compatível; edição usa o novo comando financas servir."""
    import functools
    import http.server

    manipulador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(diretorio))
    with http.server.ThreadingHTTPServer(("127.0.0.1", porta), manipulador) as servidor:
        print(f"servindo {diretorio} em http://127.0.0.1:{servidor.server_port}")
        print("Somente leitura. Para editar: python -m financas servir. Ctrl+C para parar.")
        try:
            servidor.serve_forever()
        except KeyboardInterrupt:
            print("\nparado.")

