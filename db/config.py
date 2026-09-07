"""Database configuration and transition flags.

Transition workflow:
1. USE_DB=false, SYNC_TO_DB=true  -> Sheets primary; mirror writes to PostgreSQL.
2. USE_DB=true, SYNC_TO_SHEETS=true -> PostgreSQL primary; mirror writes to Sheets (parity testing).
3. USE_DB=true, SYNC_TO_SHEETS=false -> PostgreSQL only (final cutover).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any


def _read_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _get_settings_source() -> dict[str, Any]:
    """Prefer Streamlit secrets when available; fall back to environment variables."""
    try:
        import streamlit as st

        return dict(st.secrets.get("database", {}))
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_db_config() -> dict[str, Any]:
    """Return resolved database configuration."""
    secrets = _get_settings_source()
    return {
        # Final cutover: read/write PostgreSQL instead of Google Sheets.
        "use_db": _read_bool(
            secrets.get("use_db", os.getenv("USE_DB")),
            default=False,
        ),
        # While USE_DB=false, mirror app writes into PostgreSQL for parity testing.
        "sync_to_db": _read_bool(
            secrets.get("sync_to_db", os.getenv("SYNC_TO_DB")),
            default=False,
        ),
        # While USE_DB=true, keep Google Sheets updated in parallel during testing.
        "sync_to_sheets": _read_bool(
            secrets.get("sync_to_sheets", os.getenv("SYNC_TO_SHEETS")),
            default=False,
        ),
        "host": str(secrets.get("host", os.getenv("POSTGRES_HOST", "localhost"))),
        "port": int(secrets.get("port", os.getenv("POSTGRES_PORT", "5432"))),
        "database": str(
            secrets.get("database", os.getenv("POSTGRES_DB", "flyash_erp"))
        ),
        "user": str(secrets.get("user", os.getenv("POSTGRES_USER", "postgres"))),
        "password": str(
            secrets.get("password", os.getenv("POSTGRES_PASSWORD", ""))
        ),
        "url": str(
            secrets.get(
                "url",
                os.getenv(
                    "DATABASE_URL",
                    "",
                ),
            )
        ).strip(),
    }


def is_db_enabled() -> bool:
    return get_db_config()["use_db"]


def is_sync_to_db_enabled() -> bool:
    config = get_db_config()
    return config["sync_to_db"] and not config["use_db"]


def is_sync_to_sheets_enabled() -> bool:
    config = get_db_config()
    return config["sync_to_sheets"] and config["use_db"]


def get_connection_dsn() -> str:
    """Build a PostgreSQL DSN from config."""
    config = get_db_config()
    if config["url"]:
        return config["url"]
    password = config["password"]
    auth = f"{config['user']}:{password}" if password else config["user"]
    return (
        f"postgresql://{auth}@{config['host']}:{config['port']}/{config['database']}"
    )
