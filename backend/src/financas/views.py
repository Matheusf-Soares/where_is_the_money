"""
Aplicação das views SQL versionadas.

As views são o contrato público do backend: é o que o frontend da fase 3 vai
consumir. Elas vivem em arquivos `.sql` sob `sql/`, e este módulo só os lê e
executa — nenhuma regra de negócio em Python, nenhum templating de string.

A ordem importa e é dada pelos diretórios: `staging` antes de `marts`, porque
marts consulta staging. Dentro de cada diretório a ordem é alfabética, então
prefixo numérico (`01_...`) resolve dependência entre views do mesmo nível.

Aplicar é idempotente: os arquivos usam `CREATE OR REPLACE VIEW`, e reaplicar
depois de editar o `regras.toml` é justamente o fluxo esperado — as views leem
as tabelas `cfg_*`, então um filtro novo passa a valer sem reingestão.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from financas.persistencia import Banco

registrador = logging.getLogger(__name__)

# Ordem de aplicação. Marts depende de staging.
CAMADAS = ("staging", "marts")


class ErroDeView(Exception):
    """Um arquivo `.sql` falhou ao ser aplicado."""

    def __init__(self, caminho: Path, causa: Exception) -> None:
        self.caminho = caminho
        self.causa = causa
        super().__init__(f"{caminho}: {causa}")


@dataclass(frozen=True)
class ViewAplicada:
    camada: str
    nome: str

    def __str__(self) -> str:
        return f"{self.camada}/{self.nome}"


def listar_arquivos(raiz_sql: Path) -> list[tuple[str, Path]]:
    """Enumera os `.sql` na ordem em que devem ser aplicados."""
    arquivos: list[tuple[str, Path]] = []
    for camada in CAMADAS:
        diretorio = raiz_sql / camada
        if not diretorio.is_dir():
            continue
        arquivos.extend((camada, caminho) for caminho in sorted(diretorio.glob("*.sql")))
    return arquivos


def aplicar_views(banco: Banco, raiz_sql: Path) -> list[ViewAplicada]:
    """Executa todos os `.sql` de `staging` e depois de `marts`.

    Tudo dentro de uma transação: um arquivo quebrado deixaria as views num
    estado meio-aplicado, com marts apontando para um staging que mudou.
    """
    arquivos = listar_arquivos(raiz_sql)
    if not arquivos:
        registrador.warning("nenhum arquivo .sql encontrado em %s", raiz_sql)
        return []

    aplicadas: list[ViewAplicada] = []
    banco.conexao.execute("BEGIN TRANSACTION")
    try:
        for camada, caminho in arquivos:
            registrador.debug("aplicando %s/%s", camada, caminho.name)
            try:
                banco.conexao.execute(caminho.read_text(encoding="utf-8"))
            except Exception as erro:
                raise ErroDeView(caminho, erro) from erro
            aplicadas.append(ViewAplicada(camada, caminho.stem))
    except Exception:
        banco.conexao.execute("ROLLBACK")
        raise
    banco.conexao.execute("COMMIT")

    registrador.info("%d views aplicadas", len(aplicadas))
    return aplicadas
