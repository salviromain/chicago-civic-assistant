"""Read-only database access for the app (search and the SQL agent).

Always the civic_reader role (SELECT only), and every query runs in a
READ ONLY transaction with a statement timeout. Those hold even if a bad
query slipped past app/sql_guard.py.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal


def connect_readonly():
    import psycopg

    from app.config import get_settings
    url = os.getenv("READONLY_DATABASE_URL") or get_settings().readonly_database_url
    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://"))


def _plain(value):
    """Database values -> JSON-friendly ones (for the answer prompt and the API)."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return round(value.total_seconds() / 86400, 2)  # as days
    return value


def run_select(sql: str, max_rows: int, timeout_s: int | None = None) -> tuple[list[str], list[list], bool]:
    """Run a checked SELECT. Returns (column names, rows, truncated)."""
    from app.config import get_settings
    timeout_s = timeout_s or get_settings().sql_timeout_s
    with connect_readonly() as conn:
        conn.read_only = True  # the transaction itself refuses writes
        with conn.cursor() as cur:
            cur.execute(f"SET LOCAL statement_timeout = '{int(timeout_s)}s'")
            cur.execute(sql)
            columns = [c.name for c in cur.description or []]
            rows = cur.fetchmany(max_rows + 1)
        conn.rollback()  # nothing to keep
    truncated = len(rows) > max_rows
    return columns, [[_plain(v) for v in r] for r in rows[:max_rows]], truncated
