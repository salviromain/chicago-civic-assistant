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
- LLM is the **Gemini free tier**: cache LLM calls and keep eval runs small. Embeddings are limited to 30,000 tokens per minute; `ingest/load_docs.py` paces requests and caches every embedding in `data/cache/embeddings/`.

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
- **Heat rule** is **14X-8-802.2.2** (14X-8-803 is cooling), not the old 13-196-410. The violations data still cites 13-196-410: filter on the old number, cite 14X-8-802.2.2.
- **Permit type `PERMIT – EXPRESS PERMIT PROGRAM` uses an en dash**; the others a hyphen.
- **The 2027 budget is proposed, not adopted.** Say so in answers.

## Build plan

Two weeks, about 3 to 4 hours a day. Week 1 makes it work end to end; week 2 makes it good, measured and live. Keep the scope small: 3 tables, 2 document sets.

**Week 1: make it work**

- Day 1, setup and scope: done.
- Day 2, load the tables (from 2025-01-01) + `docs/TABLES.md`: done. Tables total 356 MB (`scripts/table_sizes.py`).
- Day 3, load the documents: done. `doc_chunks` has 351 chunks (code: one per section, id = section number; budget: ~500 tokens per page), Gemini embeddings (768 numbers) and a full-text index.
- **Day 4 (next), search:** embedding search and keyword search functions, merged with RRF (hybrid); try 10 questions by hand. Keyword search must match *any* word (`websearch_to_tsquery` requires all of them); embed questions with `task_type="RETRIEVAL_QUERY"`.
- Day 5, SQL agent: table descriptions (`docs/TABLES.md`) + few-shot examples in the prompt; guardrails (SELECT-only check, read-only role, row limit).
- Day 6, router and answer: router returns SQL / docs / both as Pydantic structured output; answer prompt uses only the sources, cites them, refuses otherwise; one `answer(question)` function.
- Day 7, FastAPI: `POST /query`, `GET /health`; Pydantic request/response (answer, route, citations, latency, cost). Milestone: question in through the API, cited answer out.

**Week 2: make it good and live**

- Day 8, eval set: ~80 questions (~30 SQL, ~30 docs, ~10 both, ~10 unanswerable) with answers, routes, SQL and source chunks, in `evals/questions.jsonl`.
- Day 9, eval harness: compute every metric; LLM judge, hand-check 20 verdicts; record the baseline.
- Day 10, experiments, one change at a time: chunking (500 tokens vs. by section), search (embeddings vs. keyword vs. hybrid), reranker off/on, Gemini Flash vs. Pro. Then score the baseline (Claude + OpenGov MCP) on the same set.
- Day 11, fix failures: group wrong answers by cause, fix the biggest group, re-run, record the gain.
- Day 12, production pieces: API key and rate limiting; log latency, tokens and cost per request; Dockerfile.
- Day 13, deploy and CI: move the database to Neon; deploy to Cloud Run; CI runs tests and a small eval subset on every PR.
- Day 14, show it: README (problem, diagram, how to run, results table), demo video/GIF, resume bullet with real numbers.

**Metric targets** (starting points; before/after matters more): router 90%+, SQL execution 85%+, recall@5 80%+, MRR 0.6+, faithfulness 90%+, citation accuracy 90%+, answer correctness 80%+, correct refusals 90%+, p95 latency under ~8 s, cost per query reported.

**Open issue:** the plan's example question counts "no-heat complaints" from 311, but 311 has no heat type (checked all 105 types in the full download). Heat questions use the heat violations in `building_violations` instead.
