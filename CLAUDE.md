# CLAUDE.md

## Project

**Chicago Civic Data Assistant**: a FastAPI service that answers questions about Chicago. A router sends each question to one or both of:

- **Text-to-SQL** over Chicago Data Portal tables: 311 service requests, building violations, building permits.
- **Hybrid RAG** (pgvector + BM25, merged with RRF; reranker optional) over Municipal Code chapters 14X-8, 5-12, 5-16 and the 2027 proposed budget.

Answers must cite their sources and refuse when the data doesn't support an answer.

For details, read `README.md`, `docs/SOURCES.md` (datasets, documents, traps), `docs/TABLES.md` (table and column reference for the SQL agent) and `docs/BUILD_LOG.md` (what was built and why, newest first).

Layout: `app/` (API, router, SQL agent, retrieval, answer), `ingest/` (table and document loaders), `db/init.sql`, `scripts/check_db.py`, `evals/`, `tests/`.

## Environment

- macOS, VS Code (`.vscode/` has tasks and debug configs).
- Python venv at `.venv`. Always use `.venv/bin/python` (and `.venv/bin/pytest`), never the system Python.
- Postgres + pgvector in Docker: `docker compose up -d db`. Verify with `.venv/bin/python scripts/check_db.py`.
- Settings in `.env`, loaded with python-dotenv via `load_dotenv(find_dotenv(usecwd=True))`. See `.env.example`.
- DB driver is **psycopg 3** (`import psycopg`), not psycopg2.
- LLM is the **Gemini free tier**, default `gemini-3.1-flash-lite` (free quota: a few hundred requests per model per day; one full eval run ≈ 260 answer-model calls + 87 judge calls) (2.5 models are retired for new keys; the bigger 3.x Flash models took 23 to 268 s per call). Every call goes through `app/llm.generate`, which caches replies in `data/cache/llm/`; keep eval runs small. Embeddings are limited to 30,000 tokens per minute; `ingest/load_docs.py` paces requests and caches every embedding in `data/cache/embeddings/`.

## Rules

- **Build log:** every commit adds an entry at the top of `docs/BUILD_LOG.md` in the existing format: Goal, What changed (table), Step by step, Check it yourself, Concepts. The user is learning these technologies, so explain new terms plainly and bold them the first time.
- **Tests:** run `.venv/bin/pytest -q` before every commit; tests must pass.
- **Real database:** when touching data loading or SQL, test against the real local database, not just unit tests.
- **Secrets:** never commit `.env`, anything in `data/`, or secrets. The SQL agent connects only as the read-only `civic_reader` role.
- **Commits:** small, one topic each, clear messages. Ask before pushing.

## Data traps

- **311 duplicates:** exclude `duplicate = true` unless the question asks for duplicates.
- **311 origin:** `'Generated In House'` and `'Mass Entry'` requests are city-generated. Keep them by default; exclude them only when the question is about residents ("complaint" alone doesn't count: many types are named "… Complaint").
- **311 info-only calls and aircraft noise are not loaded** (space): refuse those questions.
- **311 enum columns** (`sr_type`, `sr_short_code`, `owner_department`, `status`, `origin`): `ILIKE` needs `::text`; an unknown value is an error.
- **Match codes, not words:** `ILIKE '%tree%'` also matches "Street", `'%rat%'` "Inaccurate", `'%sign%'` "Signal". Use `sr_short_code` lists, and `~* '\mword'` (word start) on free text. Full list: `docs/TABLES.md`, "Matching values and text".
- **building_violations has no ward column.** Ward questions can't be answered from it.
- **Heat rule** is **14X-8-802.2.2** (14X-8-803 is cooling), not the old 13-196-410. The violations data still cites 13-196-410: filter on the old number, cite 14X-8-802.2.2. It's the only old number mapped (`OLD_SECTIONS` in `app/retrieval.py`); violations cite 210. Don't name a current section for the others unless checked (hot water, 13-196-430, isn't in the loaded chapters).
- **En dashes:** permit type `PERMIT – EXPRESS PERMIT PROGRAM` and 311 type `Snow – Uncleared Sidewalk Complaint`; the others a hyphen. `Café` has an accent.
- **Data ends 2026-11-18** (311) / 2026-11-17: the SQL agent adds a code-written note when a period runs past it.
- **The 2027 budget is proposed, not adopted.** Say so in answers.

## Build plan

Two weeks, about 3 to 4 hours a day. Week 1 makes it work end to end; week 2 makes it good, measured and live. Keep the scope small: 3 tables, 2 document sets.

**Week 1: make it work**

- Day 1, setup and scope: done.
- Day 2, load the tables (from 2025-01-01) + `docs/TABLES.md`: done. Tables total 356 MB (`scripts/table_sizes.py`).
- Day 3, load the documents: done. `doc_chunks` has 351 chunks (code: one per section, id = section number; budget: ~500 tokens per page), Gemini embeddings (768 numbers) and a full-text index.
- Day 4, search: done. `app/retrieval.search(question, mode, rerank)`: vector + real BM25 + exact section lookup, merged with RRF. On 10 hand-checked questions (`python -m scripts.try_search`): hybrid 10/10 in the top 5, MRR 0.88. The bge-reranker-base cross-encoder lowered MRR to 0.62, so `use_reranker = False`; Day 10 compares rerankers on the full eval set.
- Day 5, SQL agent: done. `app/sql_agent.query_tables(question)`: prompt = `docs/TABLES.md` + refusal examples, structured `SqlPlan`, one repair on a fixable Postgres error. Guardrails: `app/sql_guard.check_sql` (sqlglot: one SELECT, the 3 tables, row limit), civic_reader, READ ONLY transaction, 15 s timeout (`app/db.py`). `python -m scripts.try_sql`: 34/34 (16 + 17 harder trap questions from the Day 5 audit + 1 from Day 7), stable on two uncached runs, median 2.5 s. Known risks for later days: the latest "Audit (5/5)" entry in `docs/BUILD_LOG.md`.
- Day 6, router and answer: done. `app/answer.run(question)` → `Trace`, `answer(question)` → `QueryResponse`. Router (`app/router.py`) picks sql / docs / both and splits both-questions; single-route questions pass unchanged (rewording hurt search). Sources run in parallel, are numbered [T1] / [D1..D5]; code builds the citations and refuses an uncited answer. `python -m scripts.try_answer`: 19/19, routes 19/19 (first run 15/19). Gemini calls are cut off after 12 s and retried (free-tier calls sometimes stall ~1 min).
- Day 7, FastAPI: done. `POST /query` (X-API-Key) runs `answer()` with a 30 s limit; failures map to 502 (Gemini unusable), 503 (database down, daily quota), 504 (too slow) instead of 500. Responses carry `usage` (calls, tokens) and `cost_usd` (0 on the free tier; prices in settings). `GET /health` reports the database. Milestone reached: checked on a real server, including with the database unreachable.

**Week 2: make it good and live**

- Day 8, eval set: done. 87 questions in `evals/questions.jsonl` (33 sql, 34 docs, 10 both, 10 unanswerable), built by `python -m evals.build_questions` (reference SQL run as civic_reader; each expected chunk checked for its key phrase; `--check` reports drift). q001–q004 are tagged `seen-in-tuning`. Answers are matched with `evals.run_evals.must_contain_ok` (numbers as whole numbers).
- Day 9, eval harness: done. `python -m evals.run_evals --label X` (judge `gemini-3.5-flash-lite`; `--timing-from` keeps live timings when re-scoring from cache); `evals.review_judge` (`--score`, `--canary`). Baseline 2026-11-26 (`evals/results/baseline-summary.json`): router 100%, SQL execution 79.1%, recall@5 97.7%, MRR 0.76, answer checks 84.4%, judge correctness 89.6%, faithfulness 100%, citations 98.7%, refusals 10/10, p50/p95 16.7 s / 70.2 s (Gemini overloaded). Judge vs. hand check: 18/20 correctness, 20/20 faithfulness, 3/3 canaries; lenient on near-miss numbers, so headline correctness = deterministic checks. Biggest failure group: city-generated requests excluded by default (5 answers).
- Day 10, experiments: mostly done (`evals/experiments.py`, `run_evals --model/--search-mode/--sql-thinking`). Adopted: **vector search** (+ exact section lookup), `search_mode = "vector"`: recall@5 100% vs hybrid 95.5%, answer checks 87.0% vs 84.4%. Rejected: reranker (72.7%), fixed 500-token chunks (no gain). `gemini-3.5-flash-lite` answering: SQL execution 93.0%, answer checks 90.9%, but not adopted until a combined run (new model + vector search) with a judge other than itself. Still to run (daily quotas used up 2026-11-26): that combined run, SQL agent thinking `low`, a fresh latency measurement. Outside comparison (Claude + OpenGov MCP): skipped by the user (needs a paid API key).
- **Day 11 (next), fix failures:** group wrong answers by cause, fix the biggest group, re-run, record the gain.
- Day 12, production pieces: API key and rate limiting; log latency, tokens and cost per request; Dockerfile.
- Day 13, deploy and CI: move the database to Neon; deploy to Cloud Run; CI runs tests and a small eval subset on every PR.
- Day 14, show it: README (problem, diagram, how to run, results table), demo video/GIF, resume bullet with real numbers.

**Metric targets** (starting points; before/after matters more): router 90%+, SQL execution 85%+, recall@5 80%+, MRR 0.6+, faithfulness 90%+, citation accuracy 90%+, answer correctness 80%+, correct refusals 90%+, p95 latency under ~8 s, cost per query reported.

**Open issue:** the plan's example question counts "no-heat complaints" from 311, but 311 has no heat type (checked all 105 types in the full download). Heat questions use the heat violations in `building_violations` instead.
