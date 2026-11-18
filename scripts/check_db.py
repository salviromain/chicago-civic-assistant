"""Check the local database is ready: Postgres up, pgvector on, read-only role works.

Usage:
    docker compose up -d db
    python scripts/check_db.py
"""

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, OperationalError

ADMIN_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/civic")
READER_URL = os.getenv("READONLY_DATABASE_URL",
                       "postgresql://civic_reader:change-me@localhost:5432/civic")


def ok(msg: str) -> None:
    print(f"  OK   {msg}")


def fail(msg: str) -> None:
    print(f"  FAIL {msg}")
    sys.exit(1)


def main() -> None:
    print("Checking the database...")
    try:
        admin = create_engine(ADMIN_URL)
        with admin.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar()
            ok(f"connected to Postgres {version}")

            ext = conn.execute(text(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
            if not ext:
                fail("pgvector is not enabled. Run: CREATE EXTENSION vector;")
            ok(f"pgvector {ext} enabled")

            dist = conn.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")).scalar()
            ok(f"vector math works (distance = {dist})")
    except OperationalError as e:
        fail(f"cannot connect as admin: {e.orig}. Is `docker compose up -d db` running?")

    try:
        reader = create_engine(READER_URL)
        with reader.connect() as conn:
            conn.execute(text("SELECT 1"))
            ok("read-only role civic_reader can connect and SELECT")
            try:
                conn.execute(text("CREATE TABLE should_fail (x int)"))
                conn.rollback()
                fail("civic_reader was able to CREATE a table; check db/init.sql grants")
            except DBAPIError:
                conn.rollback()
                ok("civic_reader cannot create tables (guardrail works)")
    except OperationalError as e:
        fail(f"cannot connect as civic_reader: {e.orig}")

    print("Database ready.")


if __name__ == "__main__":
    main()
