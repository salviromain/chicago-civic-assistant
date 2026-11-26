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

Results will be published here: router accuracy, SQL execution accuracy, recall@5, faithfulness, citation accuracy, correct refusals, latency and cost per query, against a baseline (Claude + [OpenGov MCP](https://github.com/srobbin/opengov-mcp-server)).

| System | Router | SQL | Recall@5 | Faithfulness | Correct refusals |
| --- | --- | --- | --- | --- | --- |
| Baseline | n/a | – | n/a | – | – |
| This project | – | – | – | – | – |

## Data sources

- [Chicago Data Portal](https://data.cityofchicago.org): 311 Service Requests, Building Violations, Building Permits
- [Municipal Code of Chicago](https://codelibrary.amlegal.com/codes/chicago/latest/chicago_il) chapters 14X-8, 5-12, 5-16 (American Legal Publishing; informational copy)
- City of Chicago 2027 Budget Recommendations (proposed)

Details, dataset ids and known data traps: [docs/SOURCES.md](docs/SOURCES.md).

*Not legal advice. Answers may be wrong; always check the cited source.*
