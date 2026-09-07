#!/usr/bin/env python3
"""Migrate Google Sheets data into PostgreSQL.

First run copies all configured tabs into PostgreSQL using idempotent upserts.
Re-running the script is safe: existing primary keys are updated, not duplicated.

Usage:
    python scripts/migrate_sheets_to_postgres.py
    python scripts/migrate_sheets_to_postgres.py --tables Sales_Log Payments
    python scripts/migrate_sheets_to_postgres.py --full-refresh

Environment variables (or [database] in .streamlit/secrets.toml):
    DATABASE_URL / POSTGRES_*  -> PostgreSQL connection
    USE_DB=false (default)     -> migration does not switch the app backend
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_dotenv_into_env() -> None:
    """Load DB_* variables from a local .env file when present."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in __import__("os").environ:
            __import__("os").environ[key] = value


def _load_secrets_into_env() -> None:
    """Load database settings from Streamlit secrets when running standalone."""
    _load_dotenv_into_env()
    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    secrets = tomllib.loads(secrets_path.read_text(encoding="utf-8"))
    database = secrets.get("database", {})
    env_map = {
        "host": "DB_HOST",
        "port": "DB_PORT",
        "database": "DB_NAME",
        "user": "DB_USER",
        "password": "DB_PASSWORD",
        "url": "DATABASE_URL",
    }
    for key, value in database.items():
        env_key = env_map.get(key, key.upper())
        if env_key not in __import__("os").environ and value not in ("", None):
            __import__("os").environ[env_key] = str(value)


def _build_sheets_reader():
    import database

    return database.read_table


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Google Sheets tabs to PostgreSQL")
    parser.add_argument(
        "--tables",
        nargs="*",
        help="Optional subset of sheet names to migrate",
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Delete and reload each table before upserting rows",
    )
    parser.add_argument(
        "--schema-only",
        action="store_true",
        help="Create PostgreSQL tables without copying data",
    )
    args = parser.parse_args()

    _load_secrets_into_env()

    from db.connection import test_connection
    from db.schema import ensure_schema, write_schema_file
    from db.sync import migrate_all_from_sheets, migrate_table_from_sheets

    if not test_connection():
        print("ERROR: Could not connect to PostgreSQL. Check DATABASE_URL / [database] secrets.")
        return 1

    write_schema_file(ROOT / "postgres" / "schema.sql")
    table_names = args.tables
    ensure_schema(table_names)

    if args.schema_only:
        print("Schema created successfully.")
        return 0

    sheets_reader = _build_sheets_reader()
    if table_names:
        summary = {
            name: migrate_table_from_sheets(
                name,
                sheets_reader,
                full_refresh=args.full_refresh,
            )
            for name in table_names
        }
    else:
        summary = migrate_all_from_sheets(sheets_reader)

    print("Migration complete:")
    for table_name, row_count in summary.items():
        print(f"  {table_name}: {row_count} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
