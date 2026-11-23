"""Report how much space the city tables use, against Neon's free-tier limit.

Usage:
    python scripts/table_sizes.py

Exits with status 1 if the tables (with their indexes) are over TARGET_MB.
"""

import os
import sys

from dotenv import find_dotenv, load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(find_dotenv(usecwd=True))  # read .env if present

ADMIN_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/civic")
TABLES = ["service_requests_311", "building_violations", "building_permits", "doc_chunks"]
NEON_LIMIT_MB = 500  # Neon free tier storage
TARGET_MB = 400      # leaves ~100 MB for document chunks and embeddings

MB = 1024 * 1024


def main() -> None:
    engine = create_engine(ADMIN_URL)
    total = 0
    with engine.connect() as conn:
        print(f"{'table':<24}{'rows':>12}{'data MB':>10}{'index MB':>10}{'total MB':>10}")
        for t in TABLES:
            exists = conn.execute(text("SELECT to_regclass(:t)"), {"t": t}).scalar()
            if not exists:
                print(f"{t:<24}{'(missing)':>12}")
                continue
            rows = conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
            data, idx, tot = conn.execute(text(
                "SELECT pg_table_size(:t), pg_indexes_size(:t), pg_total_relation_size(:t)"),
                {"t": t}).one()
            total += tot
            print(f"{t:<24}{rows:>12,}{data / MB:>10.1f}{idx / MB:>10.1f}{tot / MB:>10.1f}")
        db = conn.execute(text("SELECT pg_database_size(current_database())")).scalar()

    print(f"\nTables total: {total / MB:.1f} MB   target {TARGET_MB} MB   Neon limit {NEON_LIMIT_MB} MB")
    print(f"Whole database (includes system catalogs): {db / MB:.1f} MB")
    if total / MB > TARGET_MB:
        print("OVER TARGET")
        sys.exit(1)
    print("OK: fits the target")


if __name__ == "__main__":
    main()
