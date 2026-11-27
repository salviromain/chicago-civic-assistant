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
- Python venv at `.venv` (`pip install -r requirements-dev.txt`). Always use `.venv/bin/python` (and `.venv/bin/pytest`), never the system Python.
- Postgres + pgvector in Docker: `docker compose up -d db`. Verify with `.venv/bin/python scripts/check_db.py`. Production database: Neon (`scripts/setup_neon.py`); `DATABASE_URL` stays local.
- Google Cloud: `gcloud` logged in, project `gen-lang-client-0110972456`. Read secrets only into variables or pipes, never print them.
- Settings in `.env`, loaded with python-dotenv via `load_dotenv(find_dotenv(usecwd=True))`. See `.env.example`.
- DB driver is **psycopg 3** (`import psycopg`), not psycopg2.
- LLM is **Gemini**, default `gemini-3.1-flash-lite`. Since 2026-11-27 the development key is on the **paid tier** (about $0.003 per question; one full eval run ≈ $0.30): run evals with `LLM_REQUESTS_PER_MINUTE=120 LLM_USD_PER_M_INPUT=0.25 LLM_USD_PER_M_OUTPUT=1.5`. The public demo will use a separate free-tier project (Day 12/13), so strangers can't spend money. Every call goes through `app/llm.generate`, which caches replies in `data/cache/llm/` (`LLM_CACHE_DIR` points it elsewhere, e.g. an empty folder to time cold runs). Embeddings are limited to 30,000 tokens per minute; `ingest/load_docs.py` paces requests and caches every embedding in `data/cache/embeddings/`.

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

Two weeks, about 3 to 4 hours a day. **All 14 days done (2026-11-27).** Week 1 makes it work end to end; week 2 makes it good, measured and live. Keep the scope small: 3 tables, 2 document sets.

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
- Day 11, fix failures: done. 15 held-out questions written first. Fixes: SQL review in code (`app/sql_review.py`: city-generated, duplicates, average/median, inspections, open fire hydrant, LIMIT 1 hiding ties → one repair), tidy numbers in the table source (3 decimals under 1,000, so the answer rounds once), refuse when the asked fact is missing, tie rule. Scorer false alarms fixed (cents, a department's own budget page); q012 left as a known one. Results (`evals/results/day11-ties-summary.json`): SQL execution 97.7%, answer checks 100%, judge correctness 98.7%, faithfulness 100%, citations 100%, refusals 10/10; cold latency p50/p95 2.3 s / 4.1 s (paid tier); $0.0029 per question. Held-out, scored once (`holdout-summary.json`): 15/15 on every metric. Model: kept `gemini-3.1-flash-lite` (3.5-flash-lite equal on accuracy, slipped once on rounding, and would need the less-checked 3.1 judge).
- Day 12, production pieces: done. Rate limits (`app/ratelimit.py`: per client 5/min and 50/day, service 500/day; 429 + `Retry-After`; days end at midnight Pacific; in memory, so one instance; client IP from `X-Forwarded-For` with `TRUSTED_PROXIES`). One JSON log line per `/query` (`app/logs.py`: status, latency, tokens, `cost_usd` at list price, salted client hash, `X-Request-ID`; question text only with `LOG_QUESTIONS=true`). Quota 503 says when it resets. Docker image 438 MB: pinned runtime-only `requirements.txt` (dev: `requirements-dev.txt`; reranker: `requirements-reranker.txt`), allow-list `.dockerignore`, non-root, includes `docs/TABLES.md`; checked against the local database. Not done (optional, Day 14): bake cached replies for example questions into the image.
- Day 13, deploy and CI: done. Neon (`aws-us-east-2`, 368 MB; `scripts/setup_neon.py` copies the local db, creates `civic_reader` with a random password, stores its URL in Secret Manager `readonly-database-url`; owner URL in `.env` as `NEON_DATABASE_URL`). Cloud Run `civic-api` in `us-east5`, project `gen-lang-client-0110972456` (`scripts/deploy.sh`; service accounts `civic-api` (reads the 3 secrets) and `civic-build` (Cloud Run Builder); `.gcloudignore` allow-list). Live: https://civic-api-408605137306.us-east5.run.app, checked (health, 401, 4 routes correct). Demo key: free tier, project `civic-demo-516006` (billing off), secret `gemini-demo-key`; service key in secret `service-api-key`. Free tier is slow (CI dry run p50 17 s / p95 35 s; paid 2.3 / 4.1 s). CI `eval` job (pull requests and Run workflow; 10 questions, `--fail-under 0.8`, errored questions retried once) uses GitHub secrets `GEMINI_API_KEY` (the **paid** key: the free tier's 504s failed the first run) and `READONLY_DATABASE_URL`; first green run 2026-11-27: 10/10, 0.6 min, p50 2.7 s, ~$0.04. `gh` is logged in. The demo stays on the free key until its daily cap survives restarts (in-memory counts reset on scale to zero).
- Day 14, show it: done. Web page at `/` (`app/static/index.html`: cited answer, sources with SQL/excerpt, key in localStorage, text-only DOM, strict CSP), deployed (revision civic-api-00002) and checked live. `docs/demo.gif` + `docs/screenshot.png` (recorded with headless Chrome over the DevTools protocol, fresh question). README rewritten for first-time readers. Résumé bullet given in chat. Possible next steps: a daily cap stored in the database, then the paid key for the demo (2–4 s instead of 15–35 s).

**Metric targets** (starting points; before/after matters more): router 90%+, SQL execution 85%+, recall@5 80%+, MRR 0.6+, faithfulness 90%+, citation accuracy 90%+, answer correctness 80%+, correct refusals 90%+, p95 latency under ~8 s, cost per query reported.

**Open issue:** the plan's example question counts "no-heat complaints" from 311, but 311 has no heat type (checked all 105 types in the full download). Heat questions use the heat violations in `building_violations` instead.
