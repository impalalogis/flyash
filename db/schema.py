"""DDL generation and schema bootstrap for PostgreSQL tables."""

from __future__ import annotations

from pathlib import Path

from db.connection import get_connection
from db.schema_definitions import SYNC_METADATA_TABLE, TableDef, iter_table_definitions


def build_create_table_sql(table: TableDef) -> str:
    """Build CREATE TABLE IF NOT EXISTS for one sheet-backed table."""
    column_defs = ",\n    ".join(
        f"{column.db_name} {column.pg_type}" for column in table.columns
    )
    pk_columns = ", ".join(table.primary_key)
    return (
        f"CREATE TABLE IF NOT EXISTS {table.table_name} (\n"
        f"    {column_defs},\n"
        f"    PRIMARY KEY ({pk_columns})\n"
        f");"
    )


def build_sync_metadata_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS {SYNC_METADATA_TABLE} (
    table_name VARCHAR(128) PRIMARY KEY,
    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_count INTEGER NOT NULL DEFAULT 0
);
""".strip()


def build_full_schema_sql() -> str:
    statements = [build_sync_metadata_sql()]
    for table in iter_table_definitions():
        statements.append(build_create_table_sql(table))
    return "\n\n".join(statements) + "\n"


def write_schema_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_full_schema_sql(), encoding="utf-8")


def ensure_schema(table_names: list[str] | None = None) -> None:
    """Create all PostgreSQL tables if they do not exist."""
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(build_sync_metadata_sql())
            for table in iter_table_definitions(table_names):
                cursor.execute(build_create_table_sql(table))
