"""Day 10 retrieval experiments: one change at a time, scored on the eval set.

    .venv/bin/python -m evals.experiments build-fixed   # make doc_chunks_fixed (code cut every ~500 tokens)
    .venv/bin/python -m evals.experiments retrieval     # every search configuration, recall@5 and MRR
    .venv/bin/python -m evals.experiments drop-fixed    # remove the experiment table

Questions: the 44 answerable docs and both questions. A both-question is searched
with the router's document part (from the cache: no new LLM calls), as in the
real pipeline.

Relevance: a chunk is relevant if it contains the question's key phrase (the fact
the answer depends on, checked on Day 8). That works for both chunkings: chunk ids
from one don't exist in the other.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import time

from evals.run_evals import RESULTS, load_questions

FIXED = "doc_chunks_fixed"


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


# ---------------------------------------------------------------------------
# The fixed-size chunking


def fixed_code_chunks():
    """Each code chapter's full text cut into ~500-token chunks (50 overlap), ignoring
    section boundaries. 5-12.pdf also contains 5-16, so text after a second CHAPTER
    line is dropped, as the section chunker does."""
    from ingest.load_docs import CODE_URL, DOCS_DIR, Chunk, chunk_fixed, extract_code_pages
    chunks = []
    for path in sorted((DOCS_DIR / "code").glob("*.pdf")):
        chapter = path.stem
        text = "\n\n".join(p.text for p in extract_code_pages(path))
        starts = [m.start() for m in re.finditer(r"^CHAPTER\b", text, re.M)]
        if len(starts) > 1:
            text = text[:starts[1]]
        for i, body in enumerate(chunk_fixed(text), 1):
            chunks.append(Chunk(id=f"fixed-{chapter}-{i:03d}", doc=f"Municipal Code of Chicago, Chapter {chapter}",
                                kind="code", section=None, title=None, parent=None, page=0, url=CODE_URL,
                                text=f"Municipal Code of Chicago, Chapter {chapter}\n{body}"))
    return chunks


def build_fixed() -> None:
    import os

    from app.config import get_settings
    from app.embeddings import embed_texts
    from ingest.load_docs import Chunk, store
    s = get_settings()
    code = fixed_code_chunks()
    vectors, calls = embed_texts([c.text for c in code], s.embedding_model, s.embedding_dims,
                                 "RETRIEVAL_DOCUMENT", os.getenv("GEMINI_API_KEY") or s.gemini_api_key)
    # Budget chunks are the same in both chunkings: copy them with their embeddings
    import psycopg
    from pgvector.psycopg import register_vector
    url = (os.getenv("DATABASE_URL") or s.database_url).replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        register_vector(conn)
        rows = conn.execute("SELECT id, doc, kind, section, title, parent, page, url, text, embedding "
                            "FROM doc_chunks WHERE kind = 'budget' ORDER BY id").fetchall()
    budget = [Chunk(id=r[0], doc=r[1], kind=r[2], section=r[3], title=r[4], parent=r[5], page=r[6],
                    url=r[7], text=r[8]) for r in rows]
    store(code + budget, vectors + [r[9].to_list() for r in rows], url, s.embedding_dims, table=FIXED)
    sizes = [c.n_tokens for c in code]
    print(f"{FIXED}: {len(code)} code chunks (median {statistics.median(sizes):.0f} tokens, "
          f"{calls} embedding calls) + {len(budget)} budget chunks")


def drop_fixed() -> None:
    import os

    import psycopg

    from app.config import get_settings
    url = (os.getenv("DATABASE_URL") or get_settings().database_url).replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as conn:
        conn.execute(f"DROP TABLE IF EXISTS {FIXED}")
    print(f"dropped {FIXED}")


# ---------------------------------------------------------------------------
# Retrieval experiments


CONFIGS = [  # (name, table, mode, rerank)
    ("vector only", "doc_chunks", "vector", False),
    ("keyword only (BM25)", "doc_chunks", "keyword", False),
    ("hybrid (current)", "doc_chunks", "hybrid", False),
    ("hybrid + reranker", "doc_chunks", "hybrid", True),
    ("fixed 500-token chunks, hybrid", FIXED, "hybrid", False),
    ("fixed 500-token chunks, vector", FIXED, "vector", False),
]


def search_questions() -> list[tuple[dict, str]]:
    """(question, text to search): the question, or for both the router's document part."""
    from app.router import route_question
    out = []
    for q in load_questions():
        if not (q["answerable"] and q["route"] in ("docs", "both")):
            continue
        text = q["question"]
        if q["route"] == "both":
            decision, _ = route_question(q["question"])  # cached from the baseline run
            text = decision.docs_question or text
        out.append((q, text))
    return out


def relevant(chunk_text: str, phrase: str) -> bool:
    return _norm(phrase) in _norm(chunk_text)


def retrieval(configs=CONFIGS) -> list[dict]:
    from app import retrieval as r
    items = search_questions()
    rows = []
    for name, table, mode, rerank in configs:
        hits, rrs, times, misses = [], [], [], []
        with r.use_table(table):
            for q, text in items:
                start = time.perf_counter()
                results = r.search(text, mode=mode, rerank=rerank, top_k=5)
                times.append(time.perf_counter() - start)
                rank = next((i for i, c in enumerate(results, 1) if relevant(c["text"], q["key_phrase"])), None)
                hits.append(rank is not None)
                rrs.append(1 / rank if rank else 0.0)
                if rank is None:
                    misses.append(q["id"])
        rows.append({"config": name, "recall@5": sum(hits) / len(hits), "mrr": statistics.mean(rrs),
                     "median_s": statistics.median(times), "n": len(items), "misses": misses})
        print(f"  {name:34} recall@5 {rows[-1]['recall@5']:6.1%}  MRR {rows[-1]['mrr']:.2f}  "
              f"median {rows[-1]['median_s']:.2f} s  misses {misses}", flush=True)
    return rows


def main() -> None:
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    p = argparse.ArgumentParser()
    p.add_argument("what", choices=["build-fixed", "retrieval", "drop-fixed"])
    args = p.parse_args()
    if args.what == "build-fixed":
        build_fixed()
    elif args.what == "drop-fixed":
        drop_fixed()
    else:
        rows = retrieval()
        RESULTS.mkdir(exist_ok=True)
        out = RESULTS / "experiments-retrieval.json"
        out.write_text(json.dumps({"date": dt.date.today().isoformat(), "relevance": "contains the key phrase",
                                   "results": rows}, indent=2) + "\n")
        print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
