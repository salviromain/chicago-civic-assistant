# Build log

One entry per commit, newest first. Each entry says what changed, why, how to check it yourself, and the concepts it introduces. New terms are in **bold** the first time they appear.

---

## Setup fixes: virtual environment and Docker prerequisites

**Goal:** make the quickstart work on a fresh Mac. The first real run failed in two places.

### What happened

1. `pip install` refused to run: **"externally-managed-environment"**. Homebrew's Python blocks installing packages globally (a rule called PEP 668), so a package for one project can't break Homebrew's own tools.
2. `docker` was not found: Docker wasn't installed yet.

### What changed

| File | Change |
| --- | --- |
| `README.md` | Quickstart now lists Python and Docker as prerequisites and creates a virtual environment before installing |
| `docs/BUILD_LOG.md` | This log (it missed the previous push, so it's added here) |

### Check it yourself

```bash
python3 -m venv .venv
source .venv/bin/activate      # prompt starts with (.venv)
pip install -r requirements.txt
docker --version
```

### Concepts

- **Virtual environment (venv):** a private folder (`.venv/`) with its own Python packages for this project only. Activate it in each new terminal with `source .venv/bin/activate`; `deactivate` leaves it. It's in `.gitignore` because each machine builds its own.
- **Docker Desktop:** the app that runs **containers** on a Mac. `docker compose up -d db` then starts our Postgres + pgvector container in the background (`-d` = detached).

---

## Day 1: three datasets, document sources, verified local database

**Goal:** know exactly which data the assistant will use, and have a working local database to put it in.

### What changed

| File | Change |
| --- | --- |
| `ingest/load_tables.py` | Rewritten to handle three datasets instead of one |
| `docs/SOURCES.md` | New: which tables and documents we use, where they come from, and their traps |
| `scripts/check_db.py` | New: a script that proves the database is set up correctly |
| `requirements.txt` | Database driver changed from `psycopg2-binary` to `psycopg[binary]` |
| `tests/test_load_tables.py` | New tests for the loader |
| `README.md` | Quickstart now includes the check steps |

### Step by step

1. **Picked the three tables** on the Chicago Data Portal and recorded their **dataset ids** (the 9-character code in each dataset's URL): 311 `v6vf-nfxy`, Building Violations `22u3-xenr`, Building Permits `ydr8-5enu`.
2. **Made the loader configurable.** Each dataset is now described by a small `Dataset` record: its id, the Postgres table name, which date column to filter on, which columns to keep, and which columns are dates, numbers or yes/no values. Adding a fourth table later means adding one record, not a new script.
3. **Added a `--check` mode.** The column lists for violations and permits are guesses (the portal's column list couldn't be read from the build machine). `--check` downloads 5 rows, compares the real column names with the configured ones, and prints what's missing. During a real download, missing columns are dropped automatically instead of crashing.
4. **Kept the paging rules from the 311 loader** for all three tables: 50,000 rows per request, moving `$offset` forward, and always sorting by `:id` so pages don't overlap or skip rows.
5. **Chose the documents** and wrote them into `docs/SOURCES.md`: Municipal Code chapters 14X-8 (heat), 5-12 (landlord–tenant) and 5-16 (heating cost disclosure), plus the 2027 proposed budget. They are downloaded by hand, not by script, to respect the code website.
6. **Recorded the data traps** we found while researching. Each one becomes an eval question later:
   - The heat rule is now section **14X-8-803**; many websites still cite the old number **13-196-410**.
   - The 2027 budget is **proposed**, not adopted; last year the City Council passed a different version.
   - 311 has **duplicate** reports; counts should usually exclude them.
7. **Wrote `scripts/check_db.py`**, which connects to the database and checks five things: Postgres answers, **pgvector** is installed, vector math works, the read-only user can read, and the read-only user *cannot* create tables.
8. **Ran everything against a real Postgres 16 + pgvector** on the build machine. This caught a bug: the newest **SQLAlchemy** (the Python library that talks to databases) now expects the `psycopg` (version 3) driver for `postgresql://` addresses. With the old `psycopg2` package, the first connection would fail. Fixed in `requirements.txt`.
9. **Loaded two sample 311 rows** and read them back as the read-only user, confirming that tables created by the loader are automatically readable by the SQL agent, and that dates, numbers and yes/no columns get the right types.

### Check it yourself

```bash
docker compose up -d db
python scripts/check_db.py            # five OK lines, then "Database ready."
python -m ingest.load_tables --check  # lists any wrong column names
pytest -q                             # 14 tests pass
```

### Concepts

- **Dataset id (Socrata 4x4):** the portal's name for a dataset, used in API URLs: `data.cityofchicago.org/resource/<id>.json`.
- **Database driver:** the low-level package that actually speaks Postgres' network protocol. SQLAlchemy sits on top of it.
- **Read-only role:** a database user that is only allowed to `SELECT`. Even if the LLM writes a harmful query, the database refuses it. This is a **guardrail enforced by the database, not by the prompt**.
- **Default privileges:** a Postgres rule saying "any table created in the future is readable by this user." That's why new tables from the loader work for the SQL agent without extra steps.

---

## Initial scaffold: FastAPI service, pgvector setup, 311 loader, eval harness, CI

**Goal:** an empty-but-working project skeleton, so each later day only fills in one piece.

### What changed

Everything is new. The folders follow the pipeline: `ingest/` gets data in, `app/` answers questions, `evals/` measures quality, `tests/` checks the code.

| File | What it does |
| --- | --- |
| `app/main.py` | The **FastAPI** app. `GET /health` says the service is alive; `POST /query` will answer questions (returns "not implemented" for now) and requires an **API key** in the `X-API-Key` header |
| `app/schemas.py` | **Pydantic** models: the exact shape of a request (`question`) and a response (`answer`, `route`, `citations`, `refused`, `latency_ms`, `cost_usd`) |
| `app/config.py` | Reads settings (database URL, keys, model names) from **environment variables** or a `.env` file |
| `app/sql_agent.py` | `is_safe_select()`: rejects anything that isn't a single `SELECT`. Notes on data traps for the prompt |
| `app/retrieval.py` | `reciprocal_rank_fusion()`: merges keyword and embedding search results |
| `app/router.py`, `app/answer.py` | Placeholders with the plan for Day 6 |
| `ingest/load_tables.py` | The 311 loader |
| `ingest/load_docs.py` | Placeholder for Day 3 |
| `db/init.sql` | Runs once when the database is created: turns on pgvector, creates the read-only `civic_reader` user, sets a 15-second query timeout |
| `docker-compose.yml` | Starts Postgres with pgvector (and later the API) with one command |
| `Dockerfile` | Recipe for packaging the API into a **container** for Cloud Run |
| `evals/questions.jsonl` | 3 starter eval questions, including one the data cannot answer |
| `evals/run_evals.py` | `recall_at_k()` and `reciprocal_rank()` metrics; the full harness comes on Day 9 |
| `tests/` | 12 tests: health check, API key required, input validation, SQL guardrail, RRF, metrics, eval file format |
| `.github/workflows/ci.yml` | **CI**: GitHub runs the tests on every push and pull request |
| `.env.example` | Template for secrets; the real `.env` is never committed |
| `.gitignore` | Keeps secrets, downloaded data and caches out of git |
| `README.md` | Project summary, quickstart, results table to fill |

### Step by step

1. Created the folder layout from the build plan.
2. Wrote the API first (`/health`, `/query` with key check) so there is something to deploy and test from day one.
3. Wrote the two pieces of logic that don't need an LLM, the SQL guardrail and RRF, and tested them.
4. Set up the database recipe (`docker-compose.yml` + `db/init.sql`) with the read-only user built in from the start.
5. Added CI so every future change is tested automatically.
6. Ran the tests locally (12 passed) before committing.
7. When pushing, GitHub already had a `LICENSE` commit (MIT, created with the repo), so the scaffold was **rebased** on top of it: `git pull --rebase origin main`, then `git push`.

### Check it yourself

```bash
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload    # open http://localhost:8000/docs
```

### Concepts

- **Endpoint:** one URL of the API that does one thing.
- **HTTP status codes used here:** 200 OK, 401 missing/wrong API key, 422 invalid input, 501 not built yet.
- **Rebase:** replaying your commits on top of someone else's, so history stays a straight line.
- **CI (continuous integration):** automatic checks on every change; a red X on GitHub means something broke.
