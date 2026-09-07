"""PostgreSQL connection helpers."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.extensions import connection as PgConnection

from db.config import get_connection_kwargs


@contextmanager
def get_connection() -> Generator[PgConnection, None, None]:
    """Open a PostgreSQL connection and always close it."""
    conn = psycopg2.connect(**get_connection_kwargs())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def test_connection() -> bool:
    """Return True when PostgreSQL is reachable."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        return True
    except Exception:
        return False
