# Chicago Civic Data Assistant

Ask questions about Chicago in plain English. The service decides whether to answer from **city data tables** (Text-to-SQL over the Chicago Data Portal) or from **city documents** (hybrid RAG over the Municipal Code and budget PDFs), or both, and always cites its sources.

> 🚧 Work in progress: 2-week build, started November 2026.

## How it works

```
question ─► FastAPI /query ─► Router (LLM): SQL, documents, or both?
                                 │                      │
                         SQL agent (read-only)   Hybrid search (pgvector + BM25)
                                 │                      │
                         Postgres tables          Reranker → top 5 chunks
                                 └──────► LLM writes a cited answer ◄──┘
```

## Stack

FastAPI · Pydantic · PostgreSQL + pgvector · Gemini · Docker · Cloud Run · GitHub Actions · MCP

## Quickstart (local)

```bash
cp .env.example .env                      # add your keys
docker compose up -d db                   # Postgres + pgvector
pip install -r requirements.txt
python scripts/check_db.py                # Postgres up, pgvector on, read-only role works
python -m ingest.load_tables --check      # compare configured columns with the portal
python -m ingest.load_tables --since 2026-01-01
uvicorn app.main:app --reload             # http://localhost:8000/docs
```

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
