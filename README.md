# Chicago Civic Data Assistant

Ask questions about Chicago in plain English. The service decides whether to answer from **city data tables** (Text-to-SQL over the Chicago Data Portal) or from **city documents** (RAG over the Municipal Code and budget PDFs), or both, and always cites its sources.

> 🚧 Work in progress: 2-week build, started November 2026.

## How it works

```
question ─► FastAPI /query ─► Router (LLM): SQL, documents, or both?
                                 │                      │
                         SQL agent (read-only)   Vector search (pgvector) + section lookup
                                 │                      │
                         Postgres tables          top 5 chunks (BM25, RRF, reranker: optional)
                                 └──────► LLM writes a cited answer ◄──┘
```

## Stack

FastAPI · Pydantic · PostgreSQL + pgvector · Gemini · Docker · Cloud Run · GitHub Actions · MCP

## Quickstart (local)

Prerequisites: Python 3.12+ and Docker (macOS: `brew install --cask docker`, then open Docker once).

```bash
python3 -m venv .venv && source .venv/bin/activate   # once per terminal: source .venv/bin/activate
pip install -r requirements-dev.txt           # requirements.txt = what the API image installs
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

The response has the `answer` (with `[1]`, `[2]` markers), the `route` (sql, docs or both), the `citations` (the SQL that ran, or the code section / budget page with a link), `refused`, `latency_ms`, token `usage` and `cost_usd`. Errors: `401` bad key, `422` bad input, `429` too many questions (per client: 5 a minute, 50 a day; the service: 500 a day; `Retry-After` says when to try again), `502` the language model failed, `503` database down or daily quota used up, `504` no answer within 30 s. Each response has an `X-Request-ID` header that matches its line in the server log.

**With Docker** (the image the deployment uses; reads `.env`):

```bash
docker compose up -d db
docker compose up --build api              # http://localhost:8000/docs
```

## Deployment

Live at `https://civic-api-408605137306.us-east5.run.app` (`/docs` for the API page; `/query` needs an API key).

| Piece | Where |
| --- | --- |
| API | Cloud Run, `us-east5` (Ohio), one instance, scales to zero (`scripts/deploy.sh`) |
| Database | Neon free plan, `aws-us-east-2` (Ohio), copied from the local one by `scripts/setup_neon.py`; the API connects as the read-only `civic_reader` |
| Secrets | Google Secret Manager: Gemini key, the service's API key, the read-only database URL; read at startup, never in the image |
| Gemini | The demo uses a free-tier key from a project with billing off, so strangers can't spend money; development uses a paid key |
| CI | GitHub Actions: tests on every push; on pull requests, a live 10-question eval against Neon that fails below 80% |

## Evaluation

87 eval questions (`evals/questions.jsonl`: 33 table, 34 document, 10 both, 10 unanswerable), with answers computed from the data and the documents (`evals/build_questions.py`), plus 15 **held-out** questions (`evals/questions_holdout.jsonl`) written before the Day 11 fixes and scored once at the end. Run with `python -m evals.run_evals --label <name>`.

Answer model `gemini-3.1-flash-lite`, judge `gemini-3.5-flash-lite`:

| Metric | Baseline (Day 9) | After Day 11 fixes | Held-out (15, scored once) | Target |
| --- | --- | --- | --- | --- |
| Router accuracy | 100% (87/87) | 100% | 100% (15/15) | 90%+ |
| SQL execution accuracy | 79.1% (34/43) | 97.7% (42/43)* | 100% (9/9) | 85%+ |
| Recall@5 / MRR | 97.7% / 0.76 | 100% / 0.86 | 100% / 0.71 | 80%+ / 0.6+ |
| Answer correctness (checks) | 84.4% (65/77) | 100% (77/77) | 100% (13/13) | 80%+ |
| Answer correctness (LLM judge) | 89.6% | 98.7% | 100% | |
| Faithfulness (LLM judge) | 100% (77/77) | 100% | 100% | 90%+ |
| Citation accuracy | 98.7% | 100% | 100% | 90%+ |
| Correct refusals / false refusals | 100% (10/10) / 0% | 100% / 0% | 100% (2/2) / 0% | 90%+ |
| Latency p50 / p95, every call live | 16.7 s / 70.2 s (free tier, overloaded) | 2.3 s / 4.1 s (paid tier) | 2.7 s / 4.5 s | p95 under ~8 s |
| Cost per question | $0 (free tier) | $0.0029 (~10,400 tokens) | $0.0030 | reported |

\* The one miss (q012) is a scorer false alarm: the answer is right, but the query returns the month as a date and the reference as a name.

**Read with care:** the 87 questions were used to find and fix failures from Day 9 on, so "after Day 11" partly measures fitting to them. The held-out set is the honest check, but 15 questions is small, and the same person wrote the questions and the fixes. Costs use the list prices of $0.25 / $1.50 per million input / output tokens.

The judge agreed with a hand check on 18 of 20 correctness verdicts and 20 of 20 faithfulness verdicts, and caught 3 of 3 planted false claims. It is too lenient on near-miss numbers, so the headline correctness figure comes from deterministic checks.

| System | Router | SQL | Recall@5 | Faithfulness | Correct refusals |
| --- | --- | --- | --- | --- | --- |
| This project (first run, 2026-11-26) | 100% | 79.1% | 97.7% | 100% | 100% |
| This project (after Day 11, 2026-11-27) | 100% | 97.7% | 100% | 100% | 100% |

The planned outside comparison (Claude + [OpenGov MCP](https://github.com/srobbin/opengov-mcp-server) on the same questions) was skipped: it needs a paid Anthropic API key or a manual Claude Desktop run.

**Experiments** (Day 10, one change at a time on the same questions; details in `docs/BUILD_LOG.md`):

| Change | SQL execution | Recall@5 | Answer checks | Decision |
| --- | --- | --- | --- | --- |
| Baseline (hybrid search, `gemini-3.1-flash-lite`) | 79.1% | 97.7% | 84.4% | |
| Vector search instead of hybrid | 79.1% | **100%** | **87.0%** | **adopted** |
| Reranker on (retrieval only) | | 72.7%* | | rejected |
| Fixed 500-token chunks (retrieval only) | | 95.5%* | | rejected (no gain) |
| Answer model `gemini-3.5-flash-lite` | **93.0%** | 97.7% | **90.9%** | not adopted: equal after Day 11 (both 100% checks) |

\* key-phrase relevance; hybrid scores 95.5% on the same measure.

## Data sources

- [Chicago Data Portal](https://data.cityofchicago.org): 311 Service Requests, Building Violations, Building Permits
- [Municipal Code of Chicago](https://codelibrary.amlegal.com/codes/chicago/latest/chicago_il) chapters 14X-8, 5-12, 5-16 (American Legal Publishing; informational copy)
- City of Chicago 2027 Budget Recommendations (proposed)

Details, dataset ids and known data traps: [docs/SOURCES.md](docs/SOURCES.md).

*Not legal advice. Answers may be wrong; always check the cited source.*
