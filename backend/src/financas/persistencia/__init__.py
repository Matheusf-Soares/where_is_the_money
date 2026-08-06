"""Camada de persistência: DuckDB, schema raw e upsert idempotente."""

from __future__ import annotations

from financas.persistencia.banco import (
    BANCO_EM_MEMORIA,
    CHAVES_NATURAIS,
    Banco,
    ResultadoUpsert,
)

__all__ = ["BANCO_EM_MEMORIA", "CHAVES_NATURAIS", "Banco", "ResultadoUpsert"]
