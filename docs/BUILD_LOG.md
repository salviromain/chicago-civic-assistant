# Build log

One entry per commit, newest first. Each entry says what changed, why, how to check it yourself, and the concepts it introduces. New terms are in **bold** the first time they appear.

---

## Day 5 done: CLAUDE.md updated

**Goal:** keep the project briefing in step with Day 5.

### What changed

| File | Change |
| --- | --- |
| `CLAUDE.md` | Environment: default model `gemini-3.1-flash-lite`, all calls through `app/llm.generate`. Data traps: the precise city-generated rule. Build plan: Day 5 done with its results; Day 6 next; Day 10 compares Gemini models |

### Check it yourself

Read "Environment", "Data traps" and "Build plan" in `CLAUDE.md`; the numbers match the previous entry.

### Concepts

- **One source of truth per rule:** the city-generated rule now says the same thing in `CLAUDE.md` and `docs/TABLES.md`. Two different wordings are how the ambiguity crept in.

---

## Day 5 (3/3): the SQL agent, checked on 16 questions against the real database

**Goal:** turn a question into a safe SQL query, run it, and return the rows with the filters the answer must mention, or refuse when the tables can't answer.

### What happened

- **First run: 14/16, no repairs needed.** It got the en dash, the old heat ordinance, duplicates and all 6 refusals right. Both failures had one cause: it removed city-generated requests from "pothole complaints" (718 instead of 721) and "tree-related requests" (80,528 instead of 123,441).
- **The cause was my reference, not the model.** `docs/TABLES.md` said to exclude city-generated requests "for questions about what residents report or **complain** about". But many 311 types are *named* "… Complaint", so the rule was ambiguous. Fixed: keep them by default; exclude them only when the question is about *residents*. The graffiti example and question now say "residents".
- **Second run: 16/16.** These 16 questions shaped that fix, so they're a check, not a score: the honest number comes from the Day 8 eval set.
- **Repair, tried for real:** given a broken first query, Gemini fixed both enum traps from the real Postgres error in one try: `sr_short_code = 'POTHOLE'` (*invalid input value for enum*) and `sr_type ILIKE` without `::text` (*operator does not exist*). Both repaired queries return 35,832, the hand-computed count.
- **New trap found** while computing the expected answers: `sr_type::text ILIKE '%tree%'` also matches "S**tree**t …" types (potholes, street lights): 202,905 rows in 2025 instead of 123,441. Added to TABLES.md. The agent had picked the 5 tree codes correctly anyway.
- **Notes can be wrong.** In the first run, the open-rats note said "reported by residents" though the SQL had no such filter. In the second run every note matched its SQL. Day 6: cite the SQL itself, so a reader can check the notes.

### What changed

| File | Change |
| --- | --- |
| `app/sql_agent.py` | `query_tables(question, today)` → `SqlResult` (sql, columns, rows, notes, refusal_reason, error, attempts, tokens, latency). System prompt = rules + 5 refusal examples + all of `docs/TABLES.md` |
| `docs/TABLES.md` | City-generated rule made precise (keep by default); "Street" contains "tree" trap |
| `scripts/try_sql.py` | 16 questions with hand-computed answers (10 to answer, 6 to refuse); prints SQL, rows and notes; summary |
| `tests/test_sql_agent.py` | 7 tests with a fake LLM and database: SQL is checked before it runs, refusals never touch the database, one repair then stop, database down isn't "repaired" |

### Step by step

1. **Prompt:** the system prompt is the rules, five refusal examples and the whole of `docs/TABLES.md` (~8,000 tokens; its example queries are the **few-shot** examples). The question comes with today's date, so "last winter" has a meaning.
2. **Structured output:** Gemini returns a `SqlPlan`: `approach` (written first, so it thinks about tables and traps before the SQL), `answerable`, `sql`, `notes`, `refusal_reason`.
3. **Refusal:** if `answerable` is false, stop. The database is never touched.
4. **Guard and run:** `check_sql` (Day 5, 2/3), then `run_select` as `civic_reader`.
5. **One repair:** if the guard or Postgres rejects the query with an error a better query could fix, the question, the failed SQL and the error go back to Gemini once. Which errors count is decided by the Postgres error code (**SQLSTATE**): `42…` (syntax, unknown column, missing cast), `22…` (bad value, e.g. an unknown enum value), `57014` (timeout). A connection failure is raised instead: no query can fix it.

### Results

| Run | Correct | Repairs | Median time per question (uncached) | Median tokens |
| --- | --- | --- | --- | --- |
| First (ambiguous rule) | 14/16 | 0 | 1.8 s | 8,474 |
| After the rule fix | **16/16** | 0 | 1.3 s | 8,636 |
| Re-run | 16/16 | 0 | cached (0 API calls) | |

Model: `gemini-3.1-flash-lite`, temperature 0.

### Check it yourself

```bash
.venv/bin/python -m scripts.try_sql            # SQL, rows and notes for each question (cached: instant)
.venv/bin/python -m scripts.try_sql --quiet
.venv/bin/python -c "
from dotenv import load_dotenv; load_dotenv()
from app.sql_agent import query_tables
r = query_tables('How many rat complaints were made in ward 1 in 2026?')
print(r.sql); print(r.rows, r.notes)"
```

Compare any answer with your own query: `docker compose exec db psql -U civic_reader -d civic`.

### Concepts

- **Text-to-SQL:** an LLM writes the database query instead of a person. It works when the model sees the real schema, real values and the traps, which is what `docs/TABLES.md` is for.
- **Few-shot examples:** a handful of solved examples (question → SQL) in the prompt. The model copies their patterns: half-open date ranges, `NOT duplicate`, `sr_short_code`.
- **Self-repair:** feeding a database error back to the model so it can fix its own query. Limited to one try, so a confused model can't loop.
- **SQLSTATE:** the five-character code Postgres attaches to every error (`42703` = unknown column). The first two characters give the class of error.

---

## Day 5 (2/3): SQL guardrails with a real parser, and a read-only executor

**Goal:** make sure SQL written by the LLM can only read, only from the three city tables, and only a bounded number of rows, before the agent itself exists.

### What changed

| File | Change |
| --- | --- |
| `app/sql_guard.py` | `check_sql(sql, row_limit)` → safe SQL with a `LIMIT`, or `UnsafeSQL` with the reason. Replaces the regex check that was in `app/sql_agent.py` |
| `app/db.py` | `connect_readonly()` (civic_reader) and `run_select(sql, max_rows)`: READ ONLY transaction, statement timeout, at most `max_rows` rows fetched, values made JSON-friendly |
| `app/retrieval.py` | Uses `connect_readonly()` instead of its own copy |
| `app/config.py` | `sql_timeout_s = 15` |
| `requirements.txt` | `sqlglot` |
| `tests/test_sql_guard.py`, `tests/test_db.py` | 24 tests: what's allowed, what's rejected and why, the row limit, the en dash survives, every TABLES.md example passes |

### Three layers

1. **The guard (`app/sql_guard.py`)** parses the SQL with **sqlglot** and rejects:
   - anything but one `SELECT` (or `WITH … SELECT`, `UNION`): no `INSERT`, `UPDATE`, `DROP`, `COPY`, `SET`, …, including a `DELETE` hidden inside a `WITH`;
   - `SELECT … INTO` (which creates a table) and `FOR UPDATE` (which locks rows);
   - functions that sleep, read files or change settings (`pg_sleep`, `pg_read_file`, `set_config`, …);
   - any table other than the three city tables (so not `doc_chunks`, not `pg_catalog`).
   It adds `LIMIT 500` when there's none and lowers a bigger one. Comments are dropped, so `-- ; DROP TABLE` can't hide anything.
2. **The role:** `civic_reader` can only `SELECT`.
3. **The transaction:** `run_select` opens it `READ ONLY` with a 15 s `statement_timeout`. The role has a timeout too, but setting it per query keeps it when the database moves to Neon (Day 13), where `db/init.sql` won't have run.

### Checked against the real database

- All 7 example queries in `docs/TABLES.md` give **exactly the same rows** before and after the guard rewrites them (it reformats SQL, e.g. `x::text` → `CAST(x AS TEXT)`).
- Skipping the guard and sending writes straight to Postgres: `CREATE TABLE` and `DELETE` → `cannot execute … in a read-only transaction`; `SELECT pg_sleep(3)` with a 1 s timeout → `canceling statement due to statement timeout`. So layers 2 and 3 hold on their own.
- `scripts/try_search` gives the same results through the shared connection.

### Check it yourself

```bash
.venv/bin/pytest -q tests/test_sql_guard.py
.venv/bin/python -c "from app.sql_guard import check_sql; print(check_sql('SELECT ward FROM building_permits'))"
.venv/bin/python -c "from app.sql_guard import check_sql; check_sql('SELECT * FROM building_permits; DROP TABLE building_permits')"
```

### Concepts

- **Parser vs. regex:** a parser turns SQL into a tree (statement → clauses → expressions), the way Postgres reads it. Checking the tree ("is any node a DELETE?") can't be fooled by comments, quotes or odd spacing, which a text pattern can.
- **Defence in depth:** several independent safety layers, so one mistake doesn't open the door. Here: the guard, the role, the read-only transaction.
- **Statement timeout:** Postgres cancels any query running longer than this. Stops a slow LLM-written query from tying up the database.

---

## Day 5 (1/3): one cached Gemini wrapper for every LLM call

**Goal:** every text-generation call (SQL agent today; router, answers and the eval judge later) goes through one function that caches, paces and retries, so the free tier lasts and re-runs cost nothing.

### What happened

- **`gemini-2.5-flash` is gone for new API keys** (404: "no longer available to new users"). Listing the models this key can use and timing one short question on each:

| Model | Time for one short question |
| --- | --- |
| gemini-3.8-flash | 268 s |
| gemini-3.5-flash | 23 s |
| **gemini-3.1-flash-lite** | **0.9 s** |

- The plan's target is under ~8 s per question (p95), so the default is now **`gemini-3.1-flash-lite`**. The slow times are probably the free tier queueing requests to the bigger models, not the models themselves. Day 10 compares models on the full eval set; the model is one setting (`llm_model`).

### What changed

| File | Change |
| --- | --- |
| `app/llm.py` | `generate(prompt, system, schema, model, temperature, thinking_budget)` → `LLMResult` (text, parsed object, token counts, cached, latency). Disk cache in `data/cache/llm/`, request pacing, retries |
| `app/config.py` | `llm_model = "gemini-3.1-flash-lite"`, `llm_requests_per_minute = 8` |
| `tests/test_llm.py` | 6 tests with a fake client: cache hit, new prompt = new call, JSON mode, per-minute 429 retried, daily quota stops at once, bad request not retried |

### Step by step

1. **Cache key** = SHA-256 of (model, system prompt, prompt, output schema, temperature, thinking budget). Change any of them and it's a new call; change none and the answer comes from `data/cache/llm/<key>.json`.
2. **Pacing:** the same `MinuteBudget` the embeddings use, counting requests instead of tokens (8 per rolling minute).
3. **Retries:** a per-minute 429 or a 5xx waits and tries again (10 s, 20 s, 40 s…). A **daily** quota raises `QuotaExhausted` at once: waiting minutes won't reset it. A 400 (bad request) is raised at once: it won't fix itself.
4. **Structured output:** with `schema=SomePydanticModel`, Gemini must reply with JSON of that shape, and the reply is parsed and validated by Pydantic. Cached replies are validated the same way.

### Check it yourself

```bash
.venv/bin/pytest -q tests/test_llm.py
ls data/cache/llm | head      # one JSON file per distinct call
```

### Concepts

- **Structured output:** instead of free text, the model is given a JSON schema (here generated from a Pydantic class) and must answer in that shape. The code gets fields (`sql`, `answerable`) instead of parsing prose.
- **Thinking tokens:** newer Gemini models can "think" (write hidden reasoning) before answering. It can improve hard answers but adds time and is billed as output. `thinking_budget=0` turns it off where the model allows.
- **Temperature:** how random the model's word choice is. 0 = (nearly) always the most likely answer, which makes caching and evals repeatable.

---

## Day 4 done: CLAUDE.md updated

**Goal:** keep the project briefing in step with what search actually does.

### What changed

| File | Change |
| --- | --- |
| `CLAUDE.md` | Project line: the reranker is optional. Build plan: Day 4 done, with its results and the reranker decision; Day 5 (SQL agent) next |

### Check it yourself

Read the "Build plan" section of `CLAUDE.md`; the numbers match the results table in the previous entry.

### Concepts

- **Keeping docs true:** a briefing that still says "reranker → top 5" after the reranker was turned off would send the next session (or reader) in the wrong direction. Update it in the same breath as the decision.

---

## Day 4: hybrid search (vector + BM25, merged with RRF), tried on 10 questions

**Goal:** given a question, return the 5 document chunks most likely to answer it, with their sources, and check by hand that the right ones come back.

### What happened

- **Postgres's keyword ranking isn't BM25.** Matching any word of "What minimum heat must my landlord provide?" with `ts_rank` ranked long landlord–tenant sections first (they repeat "landlord", which is in 36 chunks; "minimum" is in only 6). The heat rule wasn't in the top 5. With real BM25 it comes **first**.
- **The reranker made results worse**, so it's off by default:
  - On the 10 questions it pushed the right chunk down: MRR 0.88 → 0.59.
  - It ranked the *workplace* heat rule first for "my apartment", and lost the library budget page entirely.
  - Two causes. Every budget chunk starts with the same label ("2027 Budget Overview (proposed), page …"), which matches any budget question, so it scored nearly all of them 0.99+. And 11 of the 20 candidates are longer than its 512-token limit, so their endings were cut off.
  - Dropping the shared label helped only a little (MRR 0.62). It still misreads the code sections.

### What changed

| File | Change |
| --- | --- |
| `app/retrieval.py` | `search(question, mode, rerank)`: vector search (pgvector), BM25 over Postgres's stemmed words, exact lookup of section numbers named in the question, merged with RRF; optional cross-encoder reranker. Connects as `civic_reader` |
| `app/config.py` | `reranker_model = "BAAI/bge-reranker-base"`, `use_reranker = False` |
| `scripts/try_search.py` | The 10 hand-tried questions; prints each mode's top 5 and a summary |
| `requirements.txt` | `sentence-transformers` (for the reranker; brings PyTorch) |
| `tests/test_retrieval.py` | 12 tests: tsvector parsing, BM25 (rare words count more, long chunks don't win by repetition), section numbers, RRF, search wiring, reranker off by default |
| `README.md` | Diagram: reranker marked optional |

### How search works

1. **Vector search:** embed the question (`RETRIEVAL_QUERY`, cached), take the 50 nearest chunks by cosine distance.
2. **BM25:** Postgres stems the question with the same rules as the chunks (`to_tsvector`); Python scores all 351 chunks with BM25 and keeps the top 50. The index is built once per process, in milliseconds.
3. **Exact section lookup:** a number like `5-12-150` or `14X-8-803.6` in the question fetches that section directly; it's always among the candidates.
4. **RRF** merges the lists; the top 20 are candidates; the top 5 are returned. With `rerank=True`, the cross-encoder reorders the 20 first.

Each result says where it came from (`vector_rank`, `bm25_rank`, `exact_section`, `rrf_score`, `rerank_score`), which will help when reading eval failures.

### Results on the 10 questions

The expected chunks for the budget questions were chosen by searching the chunk text for the figures *before* running any search.

| Mode | Hits in top 5 | MRR | Median time |
| --- | --- | --- | --- |
| Vector only | 9/10 | 0.90 | 0.03 s (cached question) |
| BM25 only | 9/10 | 0.52 | 0.02 s |
| **Hybrid (default)** | **10/10** | **0.88** | 0.03 s |
| Hybrid + reranker | 10/10 | 0.62 | 0.92 s |

- **Vector misses** the total budget question: "$17.6 billion" is on an infographic page whose text is scattered.
- **BM25 misses** the air conditioning question: the code says "cooling and dehumidification equipment", never "air conditioning". Classic vocabulary mismatch.
- **Hybrid catches both**, because a chunk only needs to rank well in one list.
- The exact section lookup makes "What does section 5-12-150 say?" first in every mode.

10 questions is a small sample: these numbers show the direction, not the final result. Day 9 measures on ~80 questions.

### Check it yourself

```bash
python -m scripts.try_search           # every question's top 5 in each mode, then the table
python -m scripts.try_search --quiet   # just the table
pytest -q                              # 51 tests pass
```

```python
from app.retrieval import search
for r in search("What minimum heat must my landlord provide?"):
    print(r["id"], r["vector_rank"], r["bm25_rank"])
```

### Concepts

- **BM25:** the standard keyword-ranking formula. For each question word in a chunk, it multiplies how rare the word is (**IDF**, inverse document frequency) by how often it appears (with diminishing returns), then adjusts for chunk length. Postgres's `ts_rank` counts frequency but has no IDF.
- **Stemming:** reducing words to a common root (`provided`, `provides` → `provid`) so different forms match.
- **Reciprocal Rank Fusion (RRF):** merges ranked lists by giving each item `1 / (60 + position)` per list and adding them up. It uses positions only, so it can combine scores that aren't comparable (cosine distance vs. BM25).
- **Vocabulary mismatch:** the question and the source use different words for the same thing ("air conditioning" vs. "cooling equipment"). Embeddings handle it; keyword search can't.
- **Cross-encoder reranker:** a model that reads the question and a chunk *together* and scores the pair. It's usually more accurate than comparing two separate embeddings, but slower, and only as good as its training. This one (`bge-reranker-base`) wasn't good at Chicago's legal text.
- **MRR (mean reciprocal rank):** the average of 1 / position of the first correct chunk (first = 1, second = 0.5). It rewards putting the right chunk at the top, not just somewhere in the top 5.
- **Overfitting to a small test:** tuning until 10 questions look good can make the system worse on everything else. Hence one principled fix, then a decision, with the real comparison left for the full eval set.

---

## Embeddings move to app/embeddings.py

**Goal:** let search (Day 4) embed questions with the same cache and rate-limit handling as the document loader, without the app importing from the ingest scripts.

### What changed

| File | Change |
| --- | --- |
| `app/embeddings.py` | New: the embedding code from `ingest/load_docs.py` (cache, batching by tokens, per-minute pacing, retries), plus `embed_query()` for questions (`task_type="RETRIEVAL_QUERY"`) |
| `ingest/load_docs.py` | Imports `embed_texts` and `approx_tokens` from `app/embeddings.py`; extraction and chunking unchanged |
| `tests/test_embeddings.py` | The 5 embedding tests, moved from `tests/test_load_docs.py` |

### Step by step

1. Moved the functions as they were.
2. Checked that nothing changed: all 39 tests pass, and `python -m ingest.load_docs` still reports **0 API calls**, so the cache keys are identical.

### Check it yourself

```bash
python -m ingest.load_docs     # "embeddings: 351 (0 API calls, the rest from cache)"
pytest -q                      # 39 tests pass
```

### Concepts

- **Refactor:** changing where or how code is written without changing what it does. Check it the same way: same tests, same output (here, the same cache hits).
- **Dependency direction:** `app/` is the service that gets deployed; `ingest/` holds one-off loading scripts. Shared code lives in `app/`, and scripts import from it, not the other way round, so the deployed service doesn't depend on scripts it never runs.

---

## Day 3 done: documents recorded in SOURCES.md and CLAUDE.md

**Goal:** write down what each document file actually contains and how it was loaded, and move the plan to Day 4.

### What changed

| File | Change |
| --- | --- |
| `docs/SOURCES.md` | New "Loaded" table: what each PDF contains (checked from its text) and how many chunks it gives |
| `CLAUDE.md` | Day 3 marked done; Day 4 next, with the two lessons it needs (keyword search must match any word; embed questions as `RETRIEVAL_QUERY`); embedding limit and cache noted under Environment |

### Step by step

1. Recorded the surprises found while reading the files: `5-12.pdf` also contains Chapter 5-16, and `14X-8.pdf` is the complete chapter (4 pages long, but sections 801 to 806 are all there).
2. Updated the build plan in `CLAUDE.md`.

### Check it yourself

Read the "Loaded" table in `docs/SOURCES.md`, then compare it with:

```sql
SELECT doc, count(*) FROM doc_chunks GROUP BY doc;
```

### Concepts

- **Task type for embeddings:** Gemini embeds a stored passage (`RETRIEVAL_DOCUMENT`) slightly differently from a search question (`RETRIEVAL_QUERY`), so questions and the passages that answer them land close together.

---

## Day 3: embeddings for every chunk, paced for Gemini's free tier

**Goal:** give each of the 351 chunks an embedding, so Day 4 can search by meaning as well as by keyword.

### What happened

The first full run embedded 300 chunks, then failed on the last 51 with error **429 RESOURCE_EXHAUSTED**, even after five retries over about five minutes. The error names the limit: `EmbedContentTokensPerMinutePerProjectPerModel-FreeTier`, **30,000 tokens per minute**. The loader sent 50 chunks per request whatever their size. The last 51 are dense budget pages, so that one request was likely over 30,000 tokens by itself, and no amount of waiting could let it through. Every earlier batch also hit the limit and needed 2–3 retries.

### What changed

| File | Change |
| --- | --- |
| `ingest/load_docs.py` | Requests are sized by estimated tokens (~8,000 each) instead of 50 chunks |
| `ingest/load_docs.py` | A rolling one-minute budget (~18,000 estimated tokens) makes the loader wait *before* a request instead of after a refusal |
| `ingest/load_docs.py` | A daily-quota error stops at once with a clear message (waiting minutes won't help); retry messages name the quota that was hit |
| `scripts/table_sizes.py` | Counts `doc_chunks` too |
| `tests/test_load_docs.py` | 3 new tests: batching by size, waiting for the minute budget, stopping on a daily quota |

### Step by step

1. Found the limit's name in the full error text (the first logs were cut short by `tail`, which also hid Python's real exit code).
2. Rewrote the batching and pacing; the 300 cached embeddings were reused, so the rerun sent only the last 51 chunks: **3 requests, no refusals**.
3. Ran the load again: **0 API calls**, everything from the cache.
4. Sanity check: the six chunks closest in meaning to the heat rule (14X-8-802.2.2) are all heating or temperature sections. First is the workplace heat rule (802.3.2, similarity 0.953), then 802.2 (residential heating equipment) and 803.6 (cooling operation).
5. Sizes: `doc_chunks` is 4.4 MB with both indexes; all tables 360.6 MB, under the 400 MB target.

### Check it yourself

```bash
python -m ingest.load_docs      # "embeddings: 351 (0 API calls, the rest from cache)"
python scripts/table_sizes.py   # doc_chunks 4.4 MB, total 360.6 MB
pytest -q                       # 39 tests pass
```

```sql
-- the chunks most similar in meaning to the heat rule
SELECT b.id, round((1 - (b.embedding <=> a.embedding))::numeric, 3) AS similarity
FROM doc_chunks a, doc_chunks b
WHERE a.id = '14X-8-802.2.2' AND b.id <> a.id
ORDER BY b.embedding <=> a.embedding LIMIT 6;
```

### Concepts

- **Embedding:** a list of numbers (here 768) that captures what a text means; texts with similar meanings get similar lists. `gemini-embedding-001` normally returns 3,072 numbers; asking for 768 makes each vector 4 times smaller with little loss, and fits pgvector's index limit of 2,000.
- **Cosine distance (`<=>`):** how far apart two embeddings point, from 0 (same direction, same meaning) to 2. Similarity = 1 − distance.
- **HNSW index:** a graph that lets pgvector find the nearest embeddings without comparing the question with every row. With 351 rows it barely matters, but it's the standard setup.
- **Rate limit vs. quota:** a rate limit caps use per minute and resets quickly, so waiting works. A daily quota resets once a day, so waiting minutes only wastes retries.
- **Token budget pacing:** tracking what was sent in the last 60 seconds and pausing before going over. Cheaper than retrying, because refused requests can still count against limits.
- **Exit code through a pipe:** in `python ... | tail`, the shell reports `tail`'s exit code, not Python's, so a crash can look like success.

---

## Day 3: documents extracted, chunked and stored

**Goal:** turn the three Municipal Code chapters and the 2027 proposed budget into small, searchable pieces in Postgres, each knowing where it came from (section number, page, title).

### What happened

Read the extracted text of every PDF before writing the chunker, and found five problems:

1. **The code PDFs open with a table of contents** that repeats every section heading. Headings in it have three spaces after the number; real headings have one.
2. **Section numbers at the start of wrapped lines.** Lines like `5-12-110(a), the tenant shall recover...` look like headings but are the end of a sentence.
3. **`5-12.pdf` also contains all of Chapter 5-16.** Without a stop, those pages were glued onto 5-12-200 (Severability).
4. **"68ºF" became "68oF".** The PDFs use the masculine ordinal sign `º`, not the degree sign `°`, and Unicode clean-up turns `º` into the letter o.
5. **Budget tables fall apart in plain text**: all the row labels come first, then all the numbers. PyMuPDF's table reader mangled the numbers too (`$3956M` for `$395.6M`).

### What changed

| File | Change |
| --- | --- |
| `ingest/load_docs.py` | New: extract → chunk → (embed) → store. `--dry-run` prints stats only; `--no-embed` stores chunks without embeddings |
| `app/config.py` | `embedding_dims = 768` |
| `requirements.txt` | Adds `pymupdf` (PDF text extraction; license AGPL, fine for an open-source repo) |
| `tests/test_load_docs.py` | 13 tests: section ids, parents, wrapped references, degree sign, second chapter, long sections, packing and overlap, table rows, budget headings, embedding cache |

### How the chunks are made

- **Code: one chunk per numbered section.** The chunk id is the section number (`14X-8-802.2.2`), the same id eval q004 expects. Each chunk starts with its parent sections (`14X-8-802 Heating systems > 14X-8-802.2 Residential occupancies > 14X-8-802.2.2 Heat to be provided`), so a short subsection still says what it's about. Sections over ~800 tokens are split into parts at paragraph breaks (`5-12-110#1` … `#5`). Repealed ("Reserved") sections are skipped.
- **Budget: about 500 tokens per chunk, within one page.** Chunks never cross a page, so every citation has an exact page number; consecutive chunks overlap by ~50 tokens. Each chunk starts with `2027 Budget Overview (proposed), page 150, Program and Budget Summaries by Department > Community Services`, built from the budget's own table of contents (printed page = PDF page − 1).
- **Budget tables:** paragraphs are kept as PyMuPDF text blocks. Inside the areas PyMuPDF detects as tables, rows are rebuilt from word positions (same height = same row; wide gap = new column), giving `Library Fund | 1,033 | 90,544,346 | 1,033 | 99,795,421`.

Result: **351 chunks**, about 116k tokens. 14X-8 has 28, 5-12 has 35, 5-16 has 6 and the budget has 282.

### Step by step

1. Dumped all four PDFs to text and read them; confirmed 14X-8.pdf contains 802.2.2 (heat) and 803 (cooling), and that the budget's columns say "2027 Proposed".
2. Wrote the chunkers against the real layouts, then fixed problems 3 and 4 after inspecting the output.
3. Stored the chunks with `--no-embed` and tested keyword search as `civic_reader`.

### Check it yourself

```bash
python -m ingest.load_docs --dry-run        # chunk counts per document, ~40 s
python -m ingest.load_docs --no-embed       # stores 351 chunks
pytest -q                                   # 36 tests pass
```

```sql
SELECT text FROM doc_chunks WHERE id = '14X-8-802.2.2';     -- the heat rule, 68°F / 66°F
SELECT id, ts_rank(tsv, q) FROM doc_chunks, websearch_to_tsquery('english', 'minimum heat temperature') q
WHERE tsv @@ q ORDER BY 2 DESC;                             -- 802.3.2 (workplaces), then 802.2.2
```

### Known limits (for Day 4 and Day 11)

- `websearch_to_tsquery` requires **every** word: "minimum heat temperature landlord" finds nothing, because the code says "owner". Day 4's keyword search should match any word and rank.
- The workplace heat rule (802.3.2) outranks the residential one (802.2.2) on keywords alone: a job for the reranker.
- Infographic pages ("Where the Money Goes") keep their amounts but can separate them from their labels. Empty table cells collapse, so a column can shift (`Corporate Fund | 5,000,000 | 0`).

### Concepts

- **Chunk:** one small piece of a document, stored with where it came from. Small enough to search precisely and to fit several into a prompt.
- **Chunking by section vs. fixed size:** sections follow the document's own structure, so a chunk is one complete rule. Fixed size works for anything, but can cut a rule in two. Day 10 compares both.
- **Overlap:** repeating the end of one chunk at the start of the next, so a fact on a boundary appears whole in at least one chunk.
- **Full-text search (`tsvector`):** Postgres breaks text into normalized words (**stemming**: "provided" → `provid`), stores them in a `tsvector` column with a **GIN index**, and matches queries against them. `ts_rank` scores matches. It's the keyword half of hybrid search.
- **Generated column:** `tsv` is computed by Postgres from other columns and kept up to date automatically.
- **Unicode normalization (NFKC):** rewrites look-alike characters into standard ones (`ﬀ` → `ff`). Useful, but it can change meaning, as with `º` → `o`.

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
