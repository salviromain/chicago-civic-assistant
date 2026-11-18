"""
Download Chicago 311 Service Requests (v6vf-nfxy) from the Data Portal
in pages, then optionally load them into Postgres.

Usage:
    pip install requests pandas sqlalchemy psycopg2-binary
    export SODA_APP_TOKEN=...            # free token from data.cityofchicago.org (optional but recommended)
    export DATABASE_URL=postgresql://... # optional: Neon or local Postgres
    python -m ingest.load_tables --since 2025-01-01
"""

import argparse
import os
import time

import pandas as pd
import requests

URL = "https://data.cityofchicago.org/resource/v6vf-nfxy.json"
PAGE_SIZE = 50_000  # safe max per request on SODA 2.0 endpoints

# Keep only what the SQL agent needs (smaller DB, fits Neon's free 0.5 GB).
# Check exact column names on the dataset page before running.
COLUMNS = [
    "sr_number", "sr_type", "sr_short_code", "owner_department",
    "status", "origin",
    "created_date", "closed_date",
    "street_address", "ward", "community_area", "zip_code",
    "duplicate", "parent_sr_number",
    "latitude", "longitude",
]


def fetch_page(since: str, offset: int, token: str | None) -> list[dict]:
    params = {
        "$select": ",".join(COLUMNS),
        "$where": f"created_date >= '{since}T00:00:00'",
        # Stable order is REQUIRED for offset paging; without it, pages can
        # overlap or skip rows because the API makes no ordering promise.
        "$order": ":id",
        "$limit": PAGE_SIZE,
        "$offset": offset,
    }
    headers = {"X-App-Token": token} if token else {}
    for attempt in range(5):
        r = requests.get(URL, params=params, headers=headers, timeout=120)
        if r.status_code == 200:
            return r.json()
        # 429 = throttled, 5xx = server hiccup: back off and retry
        wait = 2 ** attempt
        print(f"  HTTP {r.status_code}, retrying in {wait}s")
        time.sleep(wait)
    r.raise_for_status()
    return []


def download(since: str) -> pd.DataFrame:
    token = os.getenv("SODA_APP_TOKEN")
    rows, offset = [], 0
    while True:
        page = fetch_page(since, offset, token)
        rows.extend(page)
        print(f"offset {offset:>9,}: got {len(page):,} rows (total {len(rows):,})")
        if len(page) < PAGE_SIZE:  # last page
            break
        offset += PAGE_SIZE
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in ("created_date", "closed_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ("ward", "community_area", "latitude", "longitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Checkbox columns arrive as true/false (or missing); missing = not a duplicate
    df["duplicate"] = df["duplicate"].map({True: True, "true": True}).fillna(False).astype(bool)
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2025-01-01", help="YYYY-MM-DD")
    p.add_argument("--out", default="data/311.parquet")
    args = p.parse_args()

    df = download(args.since)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df.to_parquet(args.out, index=False)  # local copy: re-load without re-downloading
    print(f"Saved {len(df):,} rows to {args.out}")

    db = os.getenv("DATABASE_URL")
    if db:
        from sqlalchemy import create_engine
        engine = create_engine(db)
        df.to_sql("service_requests_311", engine, if_exists="replace",
                  index=False, chunksize=10_000, method="multi")
        print("Loaded into Postgres table service_requests_311")


if __name__ == "__main__":
    main()
