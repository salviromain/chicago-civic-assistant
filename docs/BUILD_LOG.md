# Build log

One entry per commit, newest first. Each entry says what changed, why, how to check it yourself, and the concepts it introduces. New terms are in **bold** the first time they appear.

---

## CLAUDE.md: project memory for Claude Code

**Goal:** every new Claude Code session starts out knowing what this project is, how the machine is set up, and the rules to follow, without being told again.

### What changed

| File | What it does |
| --- | --- |
| `CLAUDE.md` | New: project summary, environment (venv, Docker, `.env`, psycopg 3, Gemini free tier), working rules, data traps, and where we are in the build plan |
| `docs/BUILD_LOG.md` | This entry |

### Step by step

1. Wrote down what the service does: a router that sends questions to Text-to-SQL (311, violations, permits) and/or hybrid RAG (Municipal Code chapters 14X-8, 5-12, 5-16 and the 2027 proposed budget), with citations and refusals.
2. Recorded the environment details that are easy to get wrong: always `.venv/bin/python`, `find_dotenv(usecwd=True)`, psycopg 3 rather than psycopg2, and keeping Gemini calls cached and few.
3. Listed the working rules: a build log entry per commit, `pytest -q` before committing, test data and SQL changes on the real database, never commit `.env` or `data/`, ask before pushing.
4. Listed the data traps the SQL agent and answers must respect (311 duplicates, city-generated origins, no ward in violations, heat rule 14X-8-803, budget is proposed).
5. Noted the build plan status: Day 1 done, Day 2 is loading tables and writing table descriptions.

### Check it yourself

```bash
cat CLAUDE.md
pytest -q        # still passes; no code changed
```

Start a new Claude Code session in this folder and ask "what is this project?": it should answer from `CLAUDE.md`.

### Concepts

- **CLAUDE.md:** a Markdown file at the repo root that Claude Code reads automatically at the start of every session. It works like a briefing note: anything written there doesn't need repeating in each chat. Keep it short and current; update it when a rule or the plan changes.

---

## VS Code setup: interpreter, tasks, debugging

**Goal:** do all the work inside VS Code: run every command from a menu, debug with breakpoints, and run tests from the sidebar.

### What changed

| File | What it does |
| --- | --- |
| `.vscode/settings.json` | Uses `.venv` as the Python interpreter, activates it in every new terminal, loads `.env`, turns on pytest in the Testing sidebar |
| `.vscode/extensions.json` | Recommends Python, Pylance, Python Debugger, Container Tools (Docker) and PostgreSQL; VS Code offers to install them when you open the folder |
| `.vscode/tasks.json` | Named commands: create venv, start/stop/check DB, check columns, load tables (asks which table and start date), load saved files, run API, run tests |
| `.vscode/launch.json` | Debug configurations: the API, the column check, a small one-table load, and the current file |
| `.gitignore` | Shares these four files; other `.vscode/` files stay private |

### Step by step

1. Chose to commit the VS Code setup so it works the same on any machine that clones the repo.
2. Pointed the interpreter at `.venv/bin/python`, so imports resolve and the terminal auto-activates the venv.
3. Wrote one task per command used so far, so nothing needs to be remembered or retyped. "DB: check" starts the database first.
4. Added debug configurations that run modules (`-m ingest.load_tables`, `uvicorn`) exactly as the terminal does, with `.env` loaded.
5. Validated all four files as JSON.

### How to use it

- **Run a task:** `Cmd+Shift+P` → "Tasks: Run Task" → pick one.
- **Debug:** set a breakpoint (click left of a line number), then Run and Debug sidebar (`Cmd+Shift+D`) → pick a configuration → green arrow.
- **Tests:** the flask icon in the left sidebar; click ▶ next to any test.
- **Database:** the PostgreSQL extension can connect to `localhost:5432`, database `civic`, user `postgres`, to browse tables and run SQL.

### Concepts

- **Interpreter:** which Python VS Code uses. It must be the venv's, or imports like `pandas` show as missing.
- **Task:** a saved shell command with a name.
- **Launch configuration:** how to start a program under the debugger, so it pauses at breakpoints and you can inspect variables.

---

## Loader fixes: reliable column check, .env support, load saved files

**Goal:** fix three problems found on the first real run of the loader.

### What happened

Running `--check` against the live portal showed all 311 and permits columns exist, but flagged `violation_status_date` in violations as missing. That flag might have been false: the check looked at 5 sample rows, and **the API leaves a field out of a row when it's empty**. A column that's often blank can look like it doesn't exist. The run also showed that the loader ignored `.env`, and that without a database, downloaded files had no way into Postgres later except downloading again.

### What changed

| File | Change |
| --- | --- |
| `ingest/load_tables.py` | `--check` now reads the portal's official column list (`/api/views/<id>.json`) instead of sample rows |
| `ingest/load_tables.py` | Reads `.env` from the folder you run it in, so `DATABASE_URL` and `SODA_APP_TOKEN` work without `export` |
| `ingest/load_tables.py` | New `--from-parquet` flag: loads files already in `data/` into Postgres, no download |
| `ingest/load_tables.py` | Says "downloading to files only" when no database is configured, instead of staying silent |
| `scripts/check_db.py` | Also reads `.env` |
| `requirements.txt` | Lists `python-dotenv` explicitly (it was only installed indirectly) |
| `docs/SOURCES.md` | Columns marked as confirmed; noted that violations has **no ward column** |
| `tests/test_load_tables.py` | Test for reading the official column list |

### Step by step

1. Replaced the sample-row check with a metadata request. The dataset's metadata lists every column's `fieldName`, empty or not.
2. Added `load_dotenv(find_dotenv(usecwd=True))`. The `usecwd=True` part matters: by default `python-dotenv` searches for `.env` starting from the *script's* folder, not the folder you're in. Caught by testing from a different folder.
3. Added `--from-parquet`, which reads `data/<table>.parquet` and writes it to Postgres.
4. Tested against Postgres 16 + pgvector: a saved violations file loaded with only `.env` configured, then `check_db.py` passed.

### Check it yourself

```bash
python -m ingest.load_tables --check          # violation_status_date should now resolve correctly
python -m ingest.load_tables --from-parquet   # after Docker is running: loads what you already downloaded
pytest -q                                     # 15 tests pass
```

### Concepts

- **Metadata vs. data:** the column list describes the dataset; rows only show values that exist. To ask "what columns are there?", ask the metadata.
- **Sparse field:** a column that is empty for most rows. JSON APIs often omit it rather than send `null`.
- **`.env` file:** a local, untracked file of settings (`NAME=value` lines). `python-dotenv` copies them into environment variables when the script starts.
- **Missing ward in violations:** a schema gap the SQL agent must know about. "Violations in Ward 25" can't be a simple filter; it needs a join on location (a good harder eval question).

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
