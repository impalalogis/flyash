"""Dual-write synchronization between Google Sheets and PostgreSQL."""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

import app_logging
from db import config as db_config
from db.repository import delete_row as db_delete_row
from db.repository import read_table as db_read_table
from db.repository import replace_table as db_replace_table
from db.repository import update_sync_metadata
from db.repository import upsert_row as db_upsert_row
from db.schema import ensure_schema
from db.schema_definitions import MIGRATION_TABLE_ORDER, TABLE_DEFINITIONS, get_table_definition

logger = app_logging.get_logger("db.sync")

WriteOperation = Literal["insert", "update", "delete", "replace"]


def _is_postgres_active() -> bool:
    return db_config.is_db_enabled() or db_config.is_sync_to_db_enabled()


def _log_sync(event: str, **kwargs: object) -> None:
    app_logging.log_event(logger, event, **kwargs)


def read_table_from_backend(table_name: str, sheets_reader) -> pd.DataFrame:
    """Route reads to PostgreSQL when USE_DB=true, otherwise Google Sheets."""
    if db_config.is_db_enabled():
        _log_sync("read_table_from_postgres", table=table_name)
        return db_read_table(table_name)
    return sheets_reader(table_name)


def after_sheets_write(
    table_name: str,
    operation: WriteOperation,
    *,
    data: dict[str, Any] | None = None,
    row_id: str | None = None,
    data_frame: pd.DataFrame | None = None,
) -> None:
    """Mirror a Google Sheets write into PostgreSQL when SYNC_TO_DB=true."""
    if table_name not in TABLE_DEFINITIONS:
        return
    if not db_config.is_sync_to_db_enabled():
        return
    try:
        ensure_schema([table_name])
        if operation == "insert" and data is not None:
            db_upsert_row(table_name, data)
        elif operation == "update" and data is not None and row_id is not None:
            payload = dict(data)
            id_column = get_table_definition(table_name).id_column
            if id_column:
                payload[id_column] = row_id
            db_upsert_row(table_name, payload)
        elif operation == "delete" and row_id is not None:
            db_delete_row(table_name, row_id)
        elif operation == "replace" and data_frame is not None:
            db_replace_table(table_name, data_frame)
        update_sync_metadata(table_name, len(data_frame or []))
        _log_sync(
            "synced_sheets_write_to_postgres",
            table=table_name,
            operation=operation,
        )
    except Exception as exc:
        _log_sync(
            "sync_sheets_to_postgres_failed",
            table=table_name,
            operation=operation,
            error=str(exc),
        )


def after_postgres_write(
    table_name: str,
    operation: WriteOperation,
    *,
    data: dict[str, Any] | None = None,
    row_id: str | None = None,
    data_frame: pd.DataFrame | None = None,
    sheets_inserter=None,
    sheets_updater=None,
    sheets_deleter=None,
    sheets_replacer=None,
) -> None:
    """Mirror a PostgreSQL write into Google Sheets when SYNC_TO_SHEETS=true."""
    if not db_config.is_sync_to_sheets_enabled():
        return
    try:
        if operation == "insert" and data is not None and sheets_inserter:
            sheets_inserter(table_name, data, recompute_stock=False)
        elif (
            operation == "update"
            and data is not None
            and row_id is not None
            and sheets_updater
        ):
            sheets_updater(table_name, row_id, data, recompute_stock=False)
        elif operation == "delete" and row_id is not None and sheets_deleter:
            sheets_deleter(table_name, row_id, recompute_stock=False)
        elif operation == "replace" and data_frame is not None and sheets_replacer:
            sheets_replacer(table_name, data_frame, recompute_stock=False)
        _log_sync(
            "synced_postgres_write_to_sheets",
            table=table_name,
            operation=operation,
        )
    except Exception as exc:
        _log_sync(
            "sync_postgres_to_sheets_failed",
            table=table_name,
            operation=operation,
            error=str(exc),
        )


def migrate_table_from_sheets(
    table_name: str,
    sheets_reader,
    *,
    full_refresh: bool = False,
) -> int:
    """Copy one Google Sheet tab into PostgreSQL using idempotent upserts."""
    ensure_schema([table_name])
    data_frame = sheets_reader(table_name)
    if full_refresh:
        db_replace_table(table_name, data_frame)
    else:
        for row in data_frame.to_dict(orient="records"):
            db_upsert_row(table_name, row)
    row_count = len(data_frame)
    update_sync_metadata(table_name, row_count)
    _log_sync("migrated_table_to_postgres", table=table_name, rows=row_count)
    return row_count


def migrate_all_from_sheets(sheets_reader, table_names: list[str] | None = None) -> dict[str, int]:
    """Migrate all configured tables from Google Sheets to PostgreSQL."""
    names = table_names or list(MIGRATION_TABLE_ORDER)
    ensure_schema(names)
    summary: dict[str, int] = {}
    for table_name in names:
        summary[table_name] = migrate_table_from_sheets(
            table_name,
            sheets_reader,
            full_refresh=False,
        )
    return summary
