# CLAUDE.md

## Project

**Chicago Civic Data Assistant**: a FastAPI service that answers questions about Chicago. A router sends each question to one or both of:

- **Text-to-SQL** over Chicago Data Portal tables: 311 service requests, building violations, building permits.
- **Hybrid RAG** (pgvector + BM25 + reranker) over Municipal Code chapters 14X-8, 5-12, 5-16 and the 2027 proposed budget.

Answers must cite their sources and refuse when the data doesn't support an answer.

For details, read `README.md`, `docs/SOURCES.md` (datasets, documents, traps), `docs/TABLES.md` (table and column reference for the SQL agent) and `docs/BUILD_LOG.md` (what was built and why, newest first).

Layout: `app/` (API, router, SQL agent, retrieval, answer), `ingest/` (table and document loaders), `db/init.sql`, `scripts/check_db.py`, `evals/`, `tests/`.

## Environment

- macOS, VS Code (`.vscode/` has tasks and debug configs).
- Python venv at `.venv`. Always use `.venv/bin/python` (and `.venv/bin/pytest`), never the system Python.
- Postgres + pgvector in Docker: `docker compose up -d db`. Verify with `.venv/bin/python scripts/check_db.py`.
- Settings in `.env`, loaded with python-dotenv via `load_dotenv(find_dotenv(usecwd=True))`. See `.env.example`.
- DB driver is **psycopg 3** (`import psycopg`), not psycopg2.
- LLM is the **Gemini free tier**: cache LLM calls and keep eval runs small.

## Rules

- **Build log:** every commit adds an entry at the top of `docs/BUILD_LOG.md` in the existing format: Goal, What changed (table), Step by step, Check it yourself, Concepts. The user is learning these technologies, so explain new terms plainly and bold them the first time.
- **Tests:** run `.venv/bin/pytest -q` before every commit; tests must pass.
- **Real database:** when touching data loading or SQL, test against the real local database, not just unit tests.
- **Secrets:** never commit `.env`, anything in `data/`, or secrets. The SQL agent connects only as the read-only `civic_reader` role.
- **Commits:** small, one topic each, clear messages. Ask before pushing.

## Data traps

- **311 duplicates:** exclude `duplicate = true` unless the question asks for duplicates.
- **311 origin:** `'Generated In House'` and `'Mass Entry'` requests are city-generated, not resident complaints.
- **311 info-only calls and aircraft noise are not loaded** (space): refuse those questions.
- **311 enum columns** (`sr_type`, `sr_short_code`, `owner_department`, `status`, `origin`): `ILIKE` needs `::text`; an unknown value is an error.
- **building_violations has no ward column.** Ward questions can't be answered from it.
- **Heat rule** is **14X-8-803**, not the old 13-196-410. The violations data still cites 13-196-410: filter on the old number, cite the new one.
- **Permit type `PERMIT – EXPRESS PERMIT PROGRAM` uses an en dash**; the others a hyphen.
- **The 2027 budget is proposed, not adopted.** Say so in answers.

## Build plan

Two weeks.

- Day 1 (data choice + local DB): done.
- Day 2 (load tables from 2025-01-01, fit Neon's 0.5 GB, `docs/TABLES.md`): done. Tables total 356 MB (`scripts/table_sizes.py`).
- Day 3 onward: not written down yet; ask. (`app/sql_agent.py` marks the Text-to-SQL agent as Day 5.)
