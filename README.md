# Chicago Civic Data Assistant

Ask questions about Chicago in plain English. The service decides whether to answer from **city data tables** (Text-to-SQL over the Chicago Data Portal) or from **city documents** (hybrid RAG over the Municipal Code and budget PDFs), or both, and always cites its sources.

> 🚧 Work in progress: 2-week build, started November 2026.

## How it works

```
question ─► FastAPI /query ─► Router (LLM): SQL, documents, or both?
                                 │                      │
                         SQL agent (read-only)   Hybrid search (pgvector + BM25, RRF)
                                 │                      │
                         Postgres tables          top 5 chunks (reranker: optional)
                                 └──────► LLM writes a cited answer ◄──┘
```

## Stack

FastAPI · Pydantic · PostgreSQL + pgvector · Gemini · Docker · Cloud Run · GitHub Actions · MCP

## Quickstart (local)

Prerequisites: Python 3.12+ and Docker (macOS: `brew install --cask docker`, then open Docker once).

```bash
python3 -m venv .venv && source .venv/bin/activate   # once per terminal: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                      # add your keys
docker compose up -d db                   # Postgres + pgvector
python scripts/check_db.py                # Postgres up, pgvector on, read-only role works
python -m ingest.load_tables --check      # compare configured columns with the portal
python -m ingest.load_tables --since 2026-01-01
uvicorn app.main:app --reload             # http://localhost:8000/docs
```

Ask a question (the key is `SERVICE_API_KEY` from `.env`):

```bash
curl -s -X POST localhost:8000/query -H "X-API-Key: $SERVICE_API_KEY" -H "Content-Type: application/json" \
  -d '{"question": "How many heat violations were recorded last winter, and what heat must landlords provide?"}'
```

The response has the `answer` (with `[1]`, `[2]` markers), the `route` (sql, docs or both), the `citations` (the SQL that ran, or the code section / budget page with a link), `refused`, `latency_ms`, token `usage` and `cost_usd`. Errors: `401` bad key, `422` bad input, `502` the language model failed, `503` database down or daily quota used up, `504` no answer within 30 s.

## Evaluation

87 held-out questions (`evals/questions.jsonl`: 33 table, 34 document, 10 both, 10 unanswerable), with answers computed from the data and the documents (`evals/build_questions.py`). Run with `python -m evals.run_evals --label <name>`.

**Baseline** (2026-11-26, `gemini-3.1-flash-lite`, judge `gemini-3.5-flash-lite`):

| Metric | Result | Target |
| --- | --- | --- |
| Router accuracy | 100% (87/87) | 90%+ |
| SQL execution accuracy | 79.1% (34/43) | 85%+ |
| Recall@5 / MRR | 97.7% / 0.76 | 80%+ / 0.6+ |
| Answer correctness (checks) | 84.4% (65/77) | 80%+ |
| Answer correctness (LLM judge) | 89.6% | |
| Faithfulness (LLM judge) | 100% (77/77) | 90%+ |
| Citation accuracy | 98.7% | 90%+ |
| Correct refusals / false refusals | 100% (10/10) / 0% | 90%+ |
| Latency p50 / p95 | 16.7 s / 70.2 s (Gemini overloaded that day) | p95 under ~8 s |
| Cost per question | $0 (free tier), ~8,600 tokens | reported |

The judge agreed with a hand check on 18 of 20 correctness verdicts and 20 of 20 faithfulness verdicts, and caught 3 of 3 planted false claims. It is too lenient on near-miss numbers, so the table's correctness figure comes from deterministic checks.

| System | Router | SQL | Recall@5 | Faithfulness | Correct refusals |
| --- | --- | --- | --- | --- | --- |
| Comparison: Claude + OpenGov MCP (Day 10) | n/a | – | n/a | – | – |
| This project (first run, 2026-11-26) | 100% | 79.1% | 97.7% | 100% | 100% |

## Data sources

- [Chicago Data Portal](https://data.cityofchicago.org): 311 Service Requests, Building Violations, Building Permits
- [Municipal Code of Chicago](https://codelibrary.amlegal.com/codes/chicago/latest/chicago_il) chapters 14X-8, 5-12, 5-16 (American Legal Publishing; informational copy)
- City of Chicago 2027 Budget Recommendations (proposed)

Details, dataset ids and known data traps: [docs/SOURCES.md](docs/SOURCES.md).

*Not legal advice. Answers may be wrong; always check the cited source.*
