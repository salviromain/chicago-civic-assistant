"""
Download Chicago Data Portal tables in pages and load them into Postgres.

Usage:
    export SODA_APP_TOKEN=...            # free token from data.cityofchicago.org (recommended)
    export DATABASE_URL=postgresql://... # optional: load into Postgres after download

    python -m ingest.load_tables --since 2025-01-01                 # all three tables
    python -m ingest.load_tables --table violations --since 2026-11-01
    python -m ingest.load_tables --table permits --check            # compare columns, download nothing
    python -m ingest.load_tables --from-parquet                     # load saved files into Postgres, no download
    python -m ingest.load_tables --from-parquet --no-exclude        # load every row, ignoring Dataset.exclude

Settings are read from the environment or from .env in the repo root.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from dataclasses import dataclass, field

import pandas as pd
import requests
from dotenv import find_dotenv, load_dotenv

PORTAL = "https://data.cityofchicago.org/resource/{id}.json"
METADATA = "https://data.cityofchicago.org/api/views/{id}.json"
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
    # Whole numbers stored as smallint (2 bytes) instead of double precision (8)
    smallints: list[str] = field(default_factory=list)
    # Text columns with few distinct values, stored as a Postgres enum (4 bytes
    # per row instead of the full text). Queries still compare them like text.
    categories: list[str] = field(default_factory=list)
    # Rows left out of Postgres (kept in the parquet file): {column: [values]}
    exclude: dict[str, list[str]] = field(default_factory=dict)
    # Columns to index after loading (the date column is always indexed)
    indexes: list[str] = field(default_factory=list)


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
        smallints=["ward", "community_area"],
        categories=["sr_type", "sr_short_code", "owner_department", "status", "origin"],
        # Not service requests, and together 56% of rows: dropped to fit Neon's
        # 0.5 GB free tier. See docs/TABLES.md.
        exclude={"sr_type": ["311 INFORMATION ONLY CALL", "Aircraft Noise Complaint"]},
        indexes=["sr_short_code"],
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
        indexes=["ward"],
    ),
}


def _get(url: str, params: dict, token: str | None, attempts: int = 6) -> list[dict]:
    """GET with retries. Retries throttling (429), server errors (5xx) and any
    network failure; other HTTP errors (a bad column name) are raised at once."""
    headers = {"X-App-Token": token} if token else {}
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=300)
            if r.status_code == 200:
                return r.json()
            if r.status_code < 500 and r.status_code != 429:
                r.raise_for_status()  # a 4xx like a bad column name won't fix itself
            problem = f"HTTP {r.status_code}"
        except requests.HTTPError:
            raise
        except (requests.RequestException, ValueError) as e:
            # timeouts, dropped connections, a response cut off mid-way
            # (ChunkedEncodingError) or one that isn't valid JSON
            problem = type(e).__name__
        if attempt == attempts - 1:
            raise RuntimeError(f"giving up after {attempts} attempts ({problem})")
        wait = min(2 ** attempt * 5, 120)
        print(f"  {problem}, retrying in {wait}s")
        time.sleep(wait)
    return []


def portal_columns(metadata: dict) -> set[str]:
    """Field names from the portal's dataset metadata (the official column list)."""
    return {c["fieldName"] for c in metadata.get("columns", []) if "fieldName" in c}


def check_columns(ds: Dataset, token: str | None) -> list[str]:
    """Report configured columns the dataset doesn't have.

    Uses the official column list. Sample rows are NOT reliable for this:
    the API leaves out fields that are empty in a row, so a sparse column
    can look missing.
    """
    headers = {"X-App-Token": token} if token else {}
    r = requests.get(METADATA.format(id=ds.id), headers=headers, timeout=60)
    r.raise_for_status()
    available = portal_columns(r.json())
    missing = [c for c in ds.columns if c not in available]
    extra = sorted(c for c in available - set(ds.columns) if not c.startswith(":@"))
    print(f"\n[{ds.key}] {ds.id} -> {ds.table}")
    print(f"  missing (will be dropped): {missing or 'none'}")
    print(f"  available but not kept:   {extra}")
    return missing


def download(ds: Dataset, since: str, token: str | None, outdir: str = "data") -> pd.DataFrame:
    """Download all rows since `since`, one page at a time, using keyset paging.

    Keyset paging asks for "the next PAGE_SIZE rows after row id X" instead of
    "skip N rows" ($offset). The portal must walk past every skipped row, so
    large offsets get slower and time out (seen at offset 1.8M); with keyset
    paging every page costs about the same.

    Each page is saved to <outdir>/.pages/<table>-since-<date>/ as it arrives,
    so running the same command again after a failure resumes instead of
    starting over. The folder is deleted once the full table is saved.
    """
    missing = check_columns(ds, token)
    columns = [c for c in ds.columns if c not in missing]
    pagedir = os.path.join(outdir, ".pages", f"{ds.table}-since-{since}")
    os.makedirs(pagedir, exist_ok=True)
    rows, page_no, last_id = [], 0, None
    while True:
        cached = os.path.join(pagedir, f"{page_no:06d}.json")
        if os.path.exists(cached):
            with open(cached) as f:
                page = json.load(f)
            note = "cached"
        else:
            where = f"{ds.date_column} >= '{since}T00:00:00'"
            if page_no > 0:
                if not last_id:
                    raise SystemExit(f"saved page {page_no - 1} in {pagedir} has no :id; "
                                     "delete that folder to start the download over")
                where += f" AND :id > '{last_id}'"
            params = {
                "$select": ",".join([":id", *columns]),  # :id is the portal's row id
                "$where": where,
                "$order": ":id",  # keyset paging needs rows in id order
                "$limit": PAGE_SIZE,
            }
            page = _get(PORTAL.format(id=ds.id), params, token)
            with open(cached + ".tmp", "w") as f:
                json.dump(page, f)
            os.replace(cached + ".tmp", cached)  # never leave a half-written page
            note = "downloaded"
        rows.extend(page)
        print(f"  page {page_no:>4}: {len(page):,} rows {note} (total {len(rows):,})")
        if len(page) < PAGE_SIZE:
            break
        last_id = page[-1].get(":id")
        page_no += 1
    return clean(pd.DataFrame(rows, columns=columns), ds)  # columns= drops :id


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
    for col in ds.smallints:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int16")  # nullable integer
    return df


def apply_exclusions(df: pd.DataFrame, ds: Dataset) -> pd.DataFrame:
    """Drop the rows listed in ds.exclude."""
    keep = pd.Series(True, index=df.index)
    for col, values in ds.exclude.items():
        if col in df:
            keep &= ~df[col].isin(values)
    return df[keep]


def to_rows(df: pd.DataFrame):
    """Yield rows as tuples with missing values (NaN, NaT, None) as None, for COPY."""
    obj = df.astype(object).where(df.notna(), None)
    yield from obj.itertuples(index=False, name=None)


def write_table(df: pd.DataFrame, ds: Dataset, engine) -> None:
    """Replace the table: create it from the DataFrame's types, then stream rows with COPY.

    COPY sends rows as one stream, much faster than INSERT, and has no
    per-statement limit on parameters (INSERT is capped at 65,535).
    """
    from sqlalchemy import text
    df.head(0).to_sql(ds.table, engine, if_exists="replace", index=False)
    with engine.begin() as conn:  # change column types while the table is still empty
        for col in ds.smallints:
            if col in df:
                conn.execute(text(f'ALTER TABLE "{ds.table}" ALTER COLUMN "{col}" TYPE smallint'))
        for col in ds.categories:
            if col in df:
                typ = f"{ds.table}_{col}"
                values = sorted(df[col].dropna().unique())  # alphabetical, so ORDER BY matches text
                labels = ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)
                conn.execute(text(f'DROP TYPE IF EXISTS "{typ}"'))
                conn.execute(text(f'CREATE TYPE "{typ}" AS ENUM ({labels})'))
                conn.execute(text(f'ALTER TABLE "{ds.table}" ALTER COLUMN "{col}" '
                                  f'TYPE "{typ}" USING "{col}"::text::"{typ}"'))
    cols = ", ".join(f'"{c}"' for c in df.columns)
    raw = engine.raw_connection()
    try:
        with raw.driver_connection.cursor() as cur:  # the psycopg 3 connection underneath
            with cur.copy(f'COPY "{ds.table}" ({cols}) FROM STDIN') as copy:
                for row in to_rows(df):
                    copy.write_row(row)
        raw.commit()
    finally:
        raw.close()


def create_indexes(ds: Dataset, engine) -> None:
    from sqlalchemy import text
    with engine.begin() as conn:
        for col in [ds.date_column, *ds.indexes]:
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "{ds.table}_{col}_idx" ON "{ds.table}" ("{col}")'))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--table", choices=[*DATASETS, "all"], default="all")
    p.add_argument("--since", default="2025-01-01", help="YYYY-MM-DD")
    p.add_argument("--check", action="store_true", help="only compare columns with the API")
    p.add_argument("--from-parquet", action="store_true",
                   help="load previously downloaded files into Postgres, no download")
    p.add_argument("--no-exclude", action="store_true",
                   help="load every row into Postgres, ignoring each dataset's exclusions")
    p.add_argument("--outdir", default="data")
    args = p.parse_args()

    load_dotenv(find_dotenv(usecwd=True))  # read .env so DATABASE_URL and SODA_APP_TOKEN work without `export`
    token = os.getenv("SODA_APP_TOKEN") or None
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
    elif args.from_parquet:
        raise SystemExit("--from-parquet needs DATABASE_URL (set it in .env)")
    else:
        print("DATABASE_URL not set: downloading to files only")

    os.makedirs(args.outdir, exist_ok=True)
    for ds in selected:
        out = os.path.join(args.outdir, f"{ds.table}.parquet")
        if args.from_parquet:
            if not os.path.exists(out):
                print(f"\n[{ds.key}] no file at {out}, skipping")
                continue
            df = clean(pd.read_parquet(out), ds)  # re-apply types: files from older runs predate smallints
            print(f"\n[{ds.key}] read {len(df):,} rows from {out}")
        else:
            df = download(ds, args.since, token, args.outdir)
            df.to_parquet(out, index=False)  # local copy: reload without re-downloading
            shutil.rmtree(os.path.join(args.outdir, ".pages", f"{ds.table}-since-{args.since}"))
            print(f"  saved {len(df):,} rows to {out}")
        if engine is not None:
            if ds.exclude and not args.no_exclude:
                before = len(df)
                df = apply_exclusions(df, ds)
                print(f"  excluded {before - len(df):,} rows ({ds.exclude})")
            write_table(df, ds, engine)
            create_indexes(ds, engine)
            print(f"  loaded {len(df):,} rows into Postgres table {ds.table}")


if __name__ == "__main__":
    main()
