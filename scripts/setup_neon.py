"""Copy the local database to Neon and create the read-only role there (Day 13).

    .venv/bin/python -m scripts.setup_neon            # copy + role + secret + check
    .venv/bin/python -m scripts.setup_neon --check    # only compare row counts

Needs NEON_DATABASE_URL in .env (Neon's owner connection string, direct, not pooled)
and the local database running (docker compose up -d db).

1. pg_dump the local `civic` database (inside the db container, so the dump tool
   matches the server version) and pg_restore it into Neon.
2. Create `civic_reader` on Neon with a random password: SELECT on the tables, a
   15 s statement timeout, as db/init.sql does locally.
3. Store its connection URL in Google Secret Manager as `readonly-database-url`,
   for Cloud Run and CI. The password is never printed or written to disk.
4. Compare row counts, local vs. Neon, as civic_reader.

Running it again replaces Neon's tables and gives civic_reader a new password
(a new secret version); redeploy Cloud Run afterwards to pick it up.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from urllib.parse import quote, urlsplit, urlunsplit

TABLES = ["service_requests_311", "building_violations", "building_permits", "doc_chunks"]
SECRET = "readonly-database-url"
LOCAL = "postgresql://postgres:postgres@localhost:5432/civic"


def neon_url() -> str:
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    url = os.getenv("NEON_DATABASE_URL")
    if not url:
        sys.exit("NEON_DATABASE_URL is not set in .env")
    if "-pooler" in (urlsplit(url).hostname or ""):
        sys.exit("Use Neon's direct connection string (no -pooler): pg_restore needs a session")
    return url


def copy_database(url: str) -> None:
    """Local dump piped straight into Neon; both tools run in the db container."""
    print("copying the local database to Neon (a few minutes)...", flush=True)
    dump = subprocess.Popen(
        ["docker", "compose", "exec", "-T", "db", "pg_dump", "-U", "postgres", "-d", "civic",
         "--format=custom", "--no-owner", "--no-privileges", "--no-comments"],
        stdout=subprocess.PIPE)
    # The URL goes in through the environment, not the command line, so it doesn't
    # show up in the process list
    restore = subprocess.run(
        ["docker", "compose", "exec", "-T", "-e", "NEON_URL", "db", "sh", "-c",
         'pg_restore --clean --if-exists --no-owner --no-privileges --no-comments -d "$NEON_URL"'],
        stdin=dump.stdout, env={**os.environ, "NEON_URL": url})
    dump.stdout.close()
    if dump.wait() != 0 or restore.returncode != 0:
        sys.exit("copy failed (see the messages above)")


def reader_url(owner_url: str, password: str) -> str:
    """The owner's URL with civic_reader and its password instead."""
    u = urlsplit(owner_url)
    netloc = f"civic_reader:{quote(password, safe='')}@{u.hostname}" + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, netloc, u.path, u.query, ""))


def create_reader(url: str) -> str:
    import psycopg
    from psycopg import sql
    password = secrets.token_urlsafe(32)  # 256 random bits; Neon requires strong passwords
    dbname = urlsplit(url).path.lstrip("/")
    with psycopg.connect(url, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'civic_reader'").fetchone()
        verb = "ALTER" if exists else "CREATE"
        # A password can't be a query parameter in CREATE ROLE; quote it as a literal
        lit = sql.Literal(password).as_string(conn)
        conn.execute(f"{verb} ROLE civic_reader LOGIN PASSWORD {lit}")
        for stmt in (f'GRANT CONNECT ON DATABASE "{dbname}" TO civic_reader',
                     "GRANT USAGE ON SCHEMA public TO civic_reader",
                     "GRANT SELECT ON ALL TABLES IN SCHEMA public TO civic_reader",
                     "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO civic_reader",
                     "ALTER ROLE civic_reader SET statement_timeout = '15s'"):
            conn.execute(stmt)
    print(f"civic_reader {'password reset' if exists else 'created'}, SELECT only, 15 s timeout")
    return reader_url(url, password)


def store_secret(value: str) -> None:
    have = subprocess.run(["gcloud", "secrets", "describe", SECRET], capture_output=True).returncode == 0
    cmd = (["gcloud", "secrets", "versions", "add", SECRET, "--data-file=-"] if have else
           ["gcloud", "secrets", "create", SECRET, "--data-file=-"])
    subprocess.run(cmd, input=value.encode(), check=True, capture_output=True)
    print(f"stored in Secret Manager: {SECRET} ({'new version' if have else 'created'})")


def secret_value() -> str:
    return subprocess.run(["gcloud", "secrets", "versions", "access", "latest", f"--secret={SECRET}"],
                          capture_output=True, text=True, check=True).stdout


def compare(neon_reader: str) -> bool:
    import psycopg
    ok = True
    with psycopg.connect(LOCAL) as local, psycopg.connect(neon_reader) as neon:
        print(f"{'table':22} {'local':>10} {'neon':>10}")
        for t in TABLES:
            a = local.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            b = neon.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            ok &= a == b
            print(f"{t:22} {a:>10,} {b:>10,} {'' if a == b else 'DIFFERENT'}")
        user = neon.execute("SELECT current_user").fetchone()[0]
        try:
            neon.execute("CREATE TABLE should_fail (x int)")
            ok = False
            print("civic_reader could create a table: NOT read-only")
        except psycopg.errors.InsufficientPrivilege:
            neon.rollback()  # the failed statement aborts the transaction
            print(f"connected as {user}: writes are refused (read-only)")
        size = neon.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
        print(f"Neon database size: {size} (free plan: 1 GB)")
    return ok


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true", help="only compare row counts")
    args = p.parse_args()
    if not args.check:
        url = neon_url()
        copy_database(url)
        store_secret(create_reader(url))
    sys.exit(0 if compare(secret_value()) else 1)


if __name__ == "__main__":
    main()
