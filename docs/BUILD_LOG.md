# Build log

One entry per commit, newest first. Each entry says what changed, why, how to check it yourself, and the concepts it introduces. New terms are in **bold** the first time they appear.

---

## No-heat 311 question becomes a refusal test

**Goal:** stop the eval set and the API docs from assuming data we don't have. 311 has no heat complaint type (checked across all 105 types in the full download).

### What changed

| File | Change |
| --- | --- |
| `evals/questions.jsonl` | q001 ("How many no-heat complaints were filed in Ward 25 ... ?") is now `answerable: false`; the reference SQL and answer placeholders are cleared |
| `app/schemas.py` | The sample question in the API docs is now "How many heat violations were recorded last winter, and what does the city code require landlords to provide?" |

### Step by step

1. Kept q001's wording and route (`sql`): the router should still send it to the SQL side, which should then refuse because no 311 type covers heat.
2. Replaced the sample question with one the data can answer: a count from `building_violations` (heat violations, filtered on the old number 13-196-410) plus the rule from the Municipal Code (14X-8-802.2.2). It's a "both" question, like the plan's original example.

### Check it yourself

```bash
head -1 evals/questions.jsonl     # q001 ... "answerable": false
pytest -q
```

Run the API and open `http://localhost:8000/docs`: the `/query` example shows the new question.

### Concepts

- **Unanswerable eval question:** a question with no correct answer in the data, used to measure the **correct refusal rate**. A system that answers it with a number is guessing. A plausible question that the data can't answer is the best test, because a model is tempted to make up a number.

---

## Correction: the heat rule is 14X-8-802.2.2, not 14X-8-803

**Goal:** fix a wrong section number before it reaches the prompts and the eval set.

### What happened

Earlier entries (Day 1, the CLAUDE.md entry and the TABLES.md entry) say the current heat rule is **14X-8-803**. Checked against the downloaded chapter `data/docs/code/14X-8.pdf`, the minimum heat landlords must provide is in **14X-8-802.2.2**; **14X-8-803 is the cooling rule**. Those entries are left as written, since this log records what was done at the time; this entry corrects them. The old number 13-196-410 is still right as the *old* number, and the violations data still cites it.

### What changed

| File | Change |
| --- | --- |
| `CLAUDE.md` | Heat rule trap now says 14X-8-802.2.2, and that 14X-8-803 is cooling |
| `docs/SOURCES.md` | 14X-8 row and the "trap worth an eval question" note now cite 14X-8-802.2.2 |
| `docs/TABLES.md` | Heat violation trap: cite 14X-8-802.2.2 in answers (this file goes into the SQL agent's prompt) |
| `app/schemas.py` | The example citation in the API docs is now `Municipal Code 14X-8-802.2.2` |
| `evals/questions.jsonl` | New question q004: "Which code section sets the minimum heat landlords must provide?", answer 14X-8-802.2.2, route docs |

### Step by step

1. Searched the repo for every mention of 14X-8-80x and 13-196-410.
2. Fixed the files that describe the project today; kept the old build log entries unchanged.
3. Added q004 so the eval set catches this exact mistake: a model citing from memory is likely to say 14X-8-803 or 13-196-410; only retrieval from the real chapter gives 14X-8-802.2.2.

### Check it yourself

```bash
grep -rn "14X-8-803" CLAUDE.md docs/SOURCES.md docs/TABLES.md app/   # only "803 is cooling" notes remain
tail -1 evals/questions.jsonl                                        # q004
pytest -q
```

### Concepts

- **Subsection number:** in `14X-8-802.2.2`, `14X` is the title, `8` the chapter, `802` the section, and `.2.2` the subsection inside it. Citations should point to the most specific part that supports the claim.
- **Correcting a log instead of rewriting it:** a build log is a history. Adding a correction keeps the record honest about what was believed when, and still points readers to the right answer.

---

## CLAUDE.md: the full 2-week build plan

**Goal:** every Claude Code session knows what each day of the plan covers and which day is next, instead of having to ask.

### What changed

| File | Change |
| --- | --- |
| `CLAUDE.md` | The build plan section now lists all 14 days (from the plan PDF of 2026-11-17), the metric targets, and one open issue |

### Step by step

1. Copied each day's tasks from the plan in short form; Days 1 and 2 marked done, Day 3 (load the documents) marked next.
2. Added the eval targets, so later work (Day 8 onward) aims at the same numbers.
3. Checked the plan's example question against the data. "How many no-heat complaints were filed in Ward 25 last winter" assumes 311 has a heat complaint type. It doesn't: none of the 105 types in the full download (excluded ones included) mentions heat, temperature, boiler or furnace. Recorded as an open issue.

### Check it yourself

Open `CLAUDE.md` and read the "Build plan" section. In a new Claude Code session, ask "what's next?": it should say Day 3, load the documents.

### Concepts

- **Checking an example against the data:** a plan written before looking at the data can assume things the data doesn't have. Testing the headline example early is cheaper than finding out on demo day.

---

## Day 2: table reference for the SQL agent (docs/TABLES.md)

**Goal:** write down, from the real data, what each table and column means and how to query it correctly, so the SQL agent's prompt (Day 5) starts from facts instead of guesses.

### What changed

| File | Change |
| --- | --- |
| `docs/TABLES.md` | New: for each table, what one row is, the row count and date range, every column (type, meaning, real values, % missing), traps, and example queries that were run on the database |
| `docs/SOURCES.md` | Records the load date, row counts and the 311 exclusion |
| `CLAUDE.md` | Points to `TABLES.md`; adds the traps found today; Day 2 marked done |
| `app/sql_agent.py` | Docstring now points to `TABLES.md` instead of repeating a partial list of traps |

### Step by step

1. Queried every short-text column for its distinct values and counts (`SELECT col, count(*) ... GROUP BY col`), and the share of missing values for the columns that matter.
2. Listed all 103 311 request types with their short code, department and duplicate rate. The agent needs exact names, because an enum column rejects a value that isn't in its list.
3. Looked for traps and found new ones:
   - **Heat violations cite the old number.** The violations data says "(13-196-410)"; no row cites 14X-8-803. So the agent filters on the old number but cites the new one.
   - **An en dash in one permit type.** `PERMIT – EXPRESS PERMIT PROGRAM`, the biggest type (64% of permits), uses `–`; the others use `-`.
   - **No heat type in 311.** None of the 103 types mentions heat.
   - **Duplicate rates vary by type**, from 0% (abandoned vehicles) to 44% (open hydrants). Counting duplicates would distort comparisons.
   - **`violation_status_date` is missing for 79% of rows**, so it can't measure time to fix.
   - **12% of permits have no `permit_status`.**
4. Checked a column meaning instead of assuming it: `processing_time` equals issue date minus application date on 60,419 of 60,420 permits.
5. Ran every example query in `TABLES.md` as `civic_reader` and wrote its result next to it.

### Check it yourself

```bash
docker compose up -d db
```

Open `docs/TABLES.md`, copy any example query into the PostgreSQL extension (connected as `civic_reader`), and compare with the result written under it. For instance, pothole complaints in ward 25 in 2026 should return 721.

### Concepts

- **Schema description for Text-to-SQL:** an LLM writing SQL only knows what the prompt tells it. Column names alone aren't enough: it also needs real values (`'Completed'`, not `'Closed'`), what a row means, and the rules a careful analyst would follow (drop duplicates, half-open date ranges).
- **Grain:** what one row represents (one request, one violation, one permit). Getting it wrong leads to double counting, for example counting violations when the question is about inspections.
- **Half-open date range:** `>= start AND < end`. It includes everything on the last day without having to write `23:59:59`.
- **Median vs. average:** the median is the middle value, so a few extreme values don't drag it. `percentile_cont(0.5)` computes it in Postgres.
- **En dash vs. hyphen:** `–` and `-` look almost the same but are different characters, so `=` treats them as different strings.

---

## Table size check against Neon's free tier

**Goal:** know, with one command, whether the data fits Neon's free 0.5 GB before we move the database there.

### What changed

| File | What it does |
| --- | --- |
| `scripts/table_sizes.py` | New: rows, data size, index size and total for each table; the sum against a 400 MB target and Neon's 500 MB limit; exits with an error if over the target |

### Step by step

1. Set the target at **400 MB**, not 500, to leave about 100 MB for the document chunks and their embeddings (Day 3 onward).
2. Measured each table with Postgres's own size functions, indexes included, since Neon counts them too.
3. Results along the way:

| Load | 311 | Violations | Permits | Total |
| --- | --- | --- | --- | --- |
| Everything since 2025-01-01 | 951 MB | 36 MB | 26 MB | 1,013 MB |
| Without info-only calls and aircraft noise | 460 MB | 36 MB | 26 MB | 522 MB |
| Plus compact 311 columns (enums, smallint) | 295 MB | 36 MB | 25 MB | **356 MB** |

### Check it yourself

```bash
python scripts/table_sizes.py    # prints the table above for your database; "OK: fits the target"
```

### Concepts

- **Table size vs. index size:** `pg_table_size` is the rows themselves; `pg_indexes_size` is the indexes built on them; `pg_total_relation_size` is both. A single index on a 1.8M-row table can take 40 MB.
- **Exit code:** a number a program returns when it ends; 0 means success. Returning 1 when over budget lets a script or CI job stop automatically.

---

## Loader: full download since 2025-01-01, resumable, compact 311 table

**Goal:** load every row since 2025-01-01 for all three tables (about 4M rows) without the download falling over, and store 311 compactly enough to fit Neon's free 0.5 GB.

### What happened

The first full download failed three times, each in a new way:

1. **A timeout at 100k rows.** The loader only retried HTTP error codes, so one slow answer crashed it and lost everything fetched so far.
2. **Skipping rows got too slow.** By 1.8M rows, a 1,000-row request took over 5 minutes. Asking for "skip 1.8M rows, then give me 50k" (`$offset`) makes the portal walk past every skipped row.
3. **A response cut off mid-way** (`ChunkedEncodingError`), a network error the retry didn't cover.

Once complete, the 311 table took 951 MB in Postgres; info-only calls and aircraft noise complaints, 53% of the rows, were 2,036,231 of them.

### What changed

| File | Change |
| --- | --- |
| `ingest/load_tables.py` | Retries every network error (timeouts, dropped and cut-off responses) with growing waits; a real request error like a bad column name still stops at once |
| `ingest/load_tables.py` | **Keyset paging**: asks for "the next 50,000 rows after row id X" instead of `$offset` |
| `ingest/load_tables.py` | Saves each page to `data/.pages/` as it arrives; rerunning the same command resumes. The folder is deleted when the table is complete |
| `ingest/load_tables.py` | Writes to Postgres with **COPY** instead of `INSERT` |
| `ingest/load_tables.py` | Leaves 311 info-only calls and aircraft noise complaints out of Postgres (kept in the parquet file). `--no-exclude` loads them |
| `ingest/load_tables.py` | Compact 311 columns: `sr_type`, `sr_short_code`, `owner_department`, `status`, `origin` are **enums**; `ward` and `community_area` are `smallint` |
| `ingest/load_tables.py` | Indexes after loading: each table's date column, 311 `sr_short_code`, permits `ward` |
| `ingest/load_tables.py` | `--from-parquet` re-applies the column types, so files from older runs load correctly |
| `tests/test_load_tables.py` | 8 new tests: exclusions, missing values for COPY, retries, resuming from saved pages, integer wards |

### Step by step

1. Tested the portal directly: 1,000 rows at offset 0 took 13 s, at offset 1.8M it timed out after 5 minutes. With keyset paging, 50,000 rows at the same point took 10 s.
2. Switched to keyset paging and kept the 36 pages already downloaded (converted to the new page names, with the last row's id looked up from the portal).
3. Finished the download: 3,855,259 rows of 311, 90,738 violations, 60,420 permits.
4. Checked it: no `sr_number` appears twice, and the 3,851,773 rows of 311 created before the download day match the portal's own `count(*)` exactly, so no page was skipped or repeated.
5. Measured (see the next entry for the script): 1,013 MB with everything, 522 MB with the two 311 types excluded. Still over the limit.
6. Looked for the space: `sr_type` (27 bytes per row) and `owner_department` (26) repeat the same few values millions of times. Checked that every short code has exactly one type name; one code (DBES) has two departments, so a lookup table keyed by code would have lost data. Used enums instead, which keep every value.
7. Reloaded from parquet in 18 s: 311 went from 460 MB to 295 MB; all three tables are 356 MB.

### Check it yourself

```bash
docker compose up -d db
python -m ingest.load_tables --from-parquet     # loads saved files (no download), about 30 s
python scripts/table_sizes.py                   # 356 MB, OK
pytest -q                                       # 23 tests pass
```

In the PostgreSQL extension or `psql`, as `civic_reader`:

```sql
SELECT count(*) FROM service_requests_311 WHERE sr_type = 'Pothole in Street Complaint' AND NOT duplicate;
SELECT count(*) FROM service_requests_311 WHERE sr_type::text ILIKE '%rat%';   -- ILIKE needs ::text
```

### Concepts

- **Offset paging vs. keyset paging:** offset says "skip N rows", and the server still has to step past all N, so pages get slower as N grows. Keyset says "rows after id X" and jumps straight there using the order, so every page costs the same.
- **Resumable download:** saving each piece as it arrives means a failure costs one page, not the whole run. Writing to a `.tmp` file and then renaming it means a crash never leaves a half-written page behind.
- **COPY:** Postgres's bulk-load command. Rows go over as one stream instead of one `INSERT` statement per batch; much faster, and it avoids the 65,535 parameter limit per statement.
- **Enum type:** a column type with a fixed list of allowed values. Each row stores a 4-byte reference, not the text, but you still write `sr_type = 'Graffiti Removal Request'`. Two catches: `LIKE`/`ILIKE` need `sr_type::text`, and comparing with a value not in the list is an error rather than 0 rows.
- **smallint:** a 2-byte whole number (up to 32,767), enough for wards (1 to 50) and community areas (1 to 77). The default `double precision` takes 8 bytes and shows `25.0`.
- **Index:** a sorted lookup structure that makes filtering on a column fast, at the cost of disk space. The `ward` index on 311 took 39 MB, so it was dropped; a full scan of 1.8M rows is still quick.

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
