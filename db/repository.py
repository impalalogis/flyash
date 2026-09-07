"""PostgreSQL repository with parameterized queries."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from db.connection import get_connection
from db.schema_definitions import TableDef, get_table_definition


INTEGER_TYPES = {"INTEGER"}
NUMERIC_TYPES = {"NUMERIC", "NUMERIC(18, 4)"}
DATE_TYPES = {"DATE"}


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    text = str(value).strip()
    return not text or text.lower() in {"nan", "none", "nat"}


def _to_date(value: object) -> date | None:
    if _is_blank(value):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _to_int(value: object) -> int | None:
    if _is_blank(value):
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def _to_numeric(value: object) -> Decimal | None:
    if _is_blank(value):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _coerce_value(pg_type: str, value: object) -> object:
    if _is_blank(value):
        return None
    if pg_type in INTEGER_TYPES:
        return _to_int(value)
    if pg_type in NUMERIC_TYPES or pg_type.startswith("NUMERIC"):
        return _to_numeric(value)
    if pg_type in DATE_TYPES:
        return _to_date(value)
    return str(value).strip()


def _row_to_db_values(table: TableDef, row: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for column in table.columns:
        raw = row.get(column.sheet_name, row.get(column.db_name, ""))
        values[column.db_name] = _coerce_value(column.pg_type, raw)
    return values


def read_table(table_name: str) -> pd.DataFrame:
    """Read a sheet-backed table from PostgreSQL."""
    table = get_table_definition(table_name)
    columns_sql = ", ".join(table.db_columns)
    query = f"SELECT {columns_sql} FROM {table.table_name} ORDER BY 1"
    with get_connection() as conn:
        data_frame = pd.read_sql_query(query, conn)
    if data_frame.empty:
        return pd.DataFrame(columns=table.sheet_columns)
    rename_map = table.db_to_sheet_map()
    data_frame = data_frame.rename(columns=rename_map)
    for column in table.sheet_columns:
        if column not in data_frame.columns:
            data_frame[column] = ""
    return data_frame[table.sheet_columns].fillna("")


def upsert_row(table_name: str, data: dict[str, Any]) -> None:
    """Insert or update one row using the table primary key."""
    table = get_table_definition(table_name)
    values = _row_to_db_values(table, data)
    columns = table.db_columns
    placeholders = ", ".join(["%s"] * len(columns))
    column_list = ", ".join(columns)
    update_columns = [
        column for column in columns if column not in table.primary_key
    ]
    if not update_columns:
        conflict_sql = "DO NOTHING"
    else:
        assignments = ", ".join(
            f"{column} = EXCLUDED.{column}" for column in update_columns
        )
        conflict_sql = f"DO UPDATE SET {assignments}"
    pk_list = ", ".join(table.primary_key)
    query = (
        f"INSERT INTO {table.table_name} ({column_list}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT ({pk_list}) {conflict_sql}"
    )
    params = tuple(values[column] for column in columns)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params)


def delete_row(table_name: str, row_id: str) -> None:
    """Delete one row by its business ID column."""
    table = get_table_definition(table_name)
    if not table.id_column:
        raise ValueError(f"Table {table_name} does not support delete_row by ID")
    id_db_name = table.sheet_to_db_map()[table.id_column]
    query = f"DELETE FROM {table.table_name} WHERE {id_db_name} = %s"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (str(row_id).strip(),))


def replace_table(table_name: str, data_frame: pd.DataFrame) -> None:
    """Replace all rows in a PostgreSQL table (idempotent full refresh)."""
    table = get_table_definition(table_name)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"DELETE FROM {table.table_name}")
            if data_frame.empty:
                return
            columns = table.db_columns
            column_list = ", ".join(columns)
            placeholders = ", ".join(["%s"] * len(columns))
            query = (
                f"INSERT INTO {table.table_name} ({column_list}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT ({', '.join(table.primary_key)}) DO UPDATE SET "
                + ", ".join(
                    f"{column} = EXCLUDED.{column}"
                    for column in columns
                    if column not in table.primary_key
                )
            )
            rows = data_frame.to_dict(orient="records")
            for row in rows:
                values = _row_to_db_values(table, row)
                cursor.execute(query, tuple(values[column] for column in columns))


def update_sync_metadata(table_name: str, row_count: int) -> None:
    query = """
        INSERT INTO sync_metadata (table_name, last_synced_at, row_count)
        VALUES (%s, NOW(), %s)
        ON CONFLICT (table_name)
        DO UPDATE SET last_synced_at = EXCLUDED.last_synced_at,
                      row_count = EXCLUDED.row_count
    """
    table = get_table_definition(table_name)
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, (table.table_name, row_count))
