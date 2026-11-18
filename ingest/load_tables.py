"""
Download Chicago Data Portal tables in pages and load them into Postgres.

Usage:
    export SODA_APP_TOKEN=...            # free token from data.cityofchicago.org (recommended)
    export DATABASE_URL=postgresql://... # optional: load into Postgres after download

    python -m ingest.load_tables --since 2025-01-01                 # all three tables
    python -m ingest.load_tables --table violations --since 2026-11-01
    python -m ingest.load_tables --table permits --check            # compare columns, download nothing
"""

from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass, field

import pandas as pd
import requests

PORTAL = "https://data.cityofchicago.org/resource/{id}.json"
PAGE_SIZE = 50_000  # max per request on SODA 2.0 endpoints


@dataclass
class Dataset:
    key: str              # short name used on the command line
    id: str               # Socrata 4x4 id
    table: str            # Postgres table name
    date_column: str      # used for --since filtering
    columns: list[str]    # columns to keep (validated against the API with --check)
    dates: list[str] = field(default_factory=list)
    numbers: list[str] = field(default_factory=list)
    booleans: list[str] = field(default_factory=list)


DATASETS: dict[str, Dataset] = {
    "311": Dataset(
        key="311",
        id="v6vf-nfxy",
        table="service_requests_311",
        date_column="created_date",
        columns=[
            "sr_number", "sr_type", "sr_short_code", "owner_department",
            "status", "origin", "created_date", "closed_date",
            "street_address", "ward", "community_area", "zip_code",
            "duplicate", "parent_sr_number", "latitude", "longitude",
        ],
        dates=["created_date", "closed_date"],
        numbers=["ward", "community_area", "latitude", "longitude"],
        booleans=["duplicate"],
    ),
    # Columns below are best guesses until confirmed with --check (the portal's
    # column metadata could not be read from the build environment).
    "violations": Dataset(
        key="violations",
        id="22u3-xenr",
        table="building_violations",
        date_column="violation_date",
        columns=[
            "id", "violation_date", "violation_code", "violation_status",
            "violation_status_date", "violation_description", "violation_ordinance",
            "violation_inspector_comments", "inspection_number", "inspection_status",
            "inspection_category", "department_bureau", "address",
            "latitude", "longitude",
        ],
        dates=["violation_date", "violation_status_date"],
        numbers=["latitude", "longitude"],
    ),
    "permits": Dataset(
        key="permits",
        id="ydr8-5enu",
        table="building_permits",
        date_column="issue_date",
        columns=[
            "id", "permit_", "permit_type", "review_type", "permit_status",
            "application_start_date", "issue_date", "processing_time",
            "street_number", "street_direction", "street_name",
            "work_description", "reported_cost", "total_fee",
            "community_area", "ward", "latitude", "longitude",
        ],
        dates=["application_start_date", "issue_date"],
        numbers=["processing_time", "reported_cost", "total_fee",
                 "community_area", "ward", "latitude", "longitude"],
    ),
}


def _get(url: str, params: dict, token: str | None) -> list[dict]:
    headers = {"X-App-Token": token} if token else {}
    for attempt in range(5):
        r = requests.get(url, params=params, headers=headers, timeout=120)
        if r.status_code == 200:
            return r.json()
        wait = 2 ** attempt  # 429 throttled or 5xx hiccup: back off
        print(f"  HTTP {r.status_code}, retrying in {wait}s")
        time.sleep(wait)
    r.raise_for_status()
    return []


def check_columns(ds: Dataset, token: str | None) -> list[str]:
    """Fetch one row and report configured columns the API doesn't have."""
    sample = _get(PORTAL.format(id=ds.id), {"$limit": 5}, token)
    available = set().union(*(row.keys() for row in sample)) if sample else set()
    missing = [c for c in ds.columns if c not in available]
    extra = sorted(c for c in available - set(ds.columns) if not c.startswith(":@"))
    print(f"\n[{ds.key}] {ds.id} -> {ds.table}")
    print(f"  missing (will be dropped): {missing or 'none'}")
    print(f"  available but not kept:   {extra}")
    return missing


def download(ds: Dataset, since: str, token: str | None) -> pd.DataFrame:
    missing = check_columns(ds, token)
    columns = [c for c in ds.columns if c not in missing]
    rows, offset = [], 0
    while True:
        params = {
            "$select": ",".join(columns),
            "$where": f"{ds.date_column} >= '{since}T00:00:00'",
            # A stable order is REQUIRED for offset paging; otherwise pages can
            # overlap or skip rows.
            "$order": ":id",
            "$limit": PAGE_SIZE,
            "$offset": offset,
        }
        page = _get(PORTAL.format(id=ds.id), params, token)
        rows.extend(page)
        print(f"  offset {offset:>9,}: {len(page):,} rows (total {len(rows):,})")
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return clean(pd.DataFrame(rows, columns=columns), ds)


def clean(df: pd.DataFrame, ds: Dataset) -> pd.DataFrame:
    for col in ds.dates:
        if col in df:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ds.numbers:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ds.booleans:
        if col in df:
            # Checkbox columns arrive as true/false or missing; missing = false
            df[col] = df[col].map({True: True, "true": True}).fillna(False).astype(bool)
    return df


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--table", choices=[*DATASETS, "all"], default="all")
    p.add_argument("--since", default="2025-01-01", help="YYYY-MM-DD")
    p.add_argument("--check", action="store_true", help="only compare columns with the API")
    p.add_argument("--outdir", default="data")
    args = p.parse_args()

    token = os.getenv("SODA_APP_TOKEN")
    selected = DATASETS.values() if args.table == "all" else [DATASETS[args.table]]

    if args.check:
        for ds in selected:
            check_columns(ds, token)
        return

    db = os.getenv("DATABASE_URL")
    engine = None
    if db:
        from sqlalchemy import create_engine
        engine = create_engine(db)

    os.makedirs(args.outdir, exist_ok=True)
    for ds in selected:
        df = download(ds, args.since, token)
        out = os.path.join(args.outdir, f"{ds.table}.parquet")
        df.to_parquet(out, index=False)  # local copy: reload without re-downloading
        print(f"  saved {len(df):,} rows to {out}")
        if engine is not None:
            df.to_sql(ds.table, engine, if_exists="replace", index=False,
                      chunksize=10_000, method="multi")
            print(f"  loaded into Postgres table {ds.table}")


if __name__ == "__main__":
    main()
