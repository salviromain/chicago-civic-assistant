"""Document search: vector + BM25 (+ exact section lookup), merged with RRF, then reranked.

    search("What minimum heat must my landlord provide?")
    -> 5 chunks, best first, each with its source (id, doc, section, page, url)

Modes, so evals can compare them (Day 10):
    mode="vector"   meaning only (pgvector, Gemini embeddings)
    mode="keyword"  words only (BM25 over Postgres's stemmed words)
    mode="hybrid"   both, merged with Reciprocal Rank Fusion (default)
    rerank=True     a cross-encoder re-scores the candidates and keeps the best 5
                    (off by default: it hurt on the Day 4 questions)

Connects as the read-only civic_reader role.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

CANDIDATES = 50  # results taken from each search before merging

# A section number in a question: 14X-8-803.6, 5-12-150. Not 5-12-110(a)'s "(a)".
SECTION_RE = re.compile(r"\b((?:14X|\d{1,2})-\d{1,2}-\d{3}(?:\.\d+)*)\b", re.IGNORECASE)
_LEXEME_RE = re.compile(r"'((?:[^']|'')+)'(?::([0-9A-D,]+))?")

COLUMNS = "id, doc, kind, section, title, parent, page, url, text"


# ---------------------------------------------------------------------------
# Database


def _connect():
    from pgvector.psycopg import register_vector

    from app.db import connect_readonly
    conn = connect_readonly()
    register_vector(conn)
    return conn


def fetch_chunks(ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    with _connect() as conn:
        rows = conn.execute(f"SELECT {COLUMNS} FROM doc_chunks WHERE id = ANY(%s)", [ids]).fetchall()
    names = COLUMNS.split(", ")
    return {r[0]: dict(zip(names, r)) for r in rows}


# ---------------------------------------------------------------------------
# Vector search


def vector_search(question: str, k: int = CANDIDATES) -> list[str]:
    """Chunk ids closest in meaning to the question (cosine distance), best first."""
    import numpy as np

    from app.embeddings import embed_query
    qvec = np.array(embed_query(question), dtype=np.float32)
    with _connect() as conn:
        rows = conn.execute("SELECT id FROM doc_chunks ORDER BY embedding <=> %s LIMIT %s",
                            [qvec, k]).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# BM25 keyword search


def parse_tsvector(text: str) -> Counter:
    """Postgres tsvector text ("'heat':4,9 'provid':7") -> {lexeme: count}."""
    counts: Counter = Counter()
    for lexeme, positions in _LEXEME_RE.findall(text):
        counts[lexeme.replace("''", "'")] = len(positions.split(",")) if positions else 1
    return counts


class BM25Index:
    """Okapi BM25. For each query word in a chunk:

        idf(word) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * chunk_length / average_length))

    idf is high for rare words ("minimum": 6 chunks) and low for common ones
    ("landlord": 36). The length term keeps long chunks from winning just by
    repeating a word. k1 limits how much repeats count; b sets how much length matters.
    """

    def __init__(self, docs: dict[str, Counter], k1: float = 1.2, b: float = 0.75):
        self.docs, self.k1, self.b = docs, k1, b
        self.lengths = {d: sum(tf.values()) for d, tf in docs.items()}
        self.avg_len = (sum(self.lengths.values()) / len(docs)) if docs else 0.0
        df: Counter = Counter()
        for tf in docs.values():
            df.update(tf.keys())
        n = len(docs)
        self.idf = {w: math.log(1 + (n - f + 0.5) / (f + 0.5)) for w, f in df.items()}

    def scores(self, terms: set[str]) -> dict[str, float]:
        out: dict[str, float] = {}
        for doc_id, tf in self.docs.items():
            norm = self.k1 * (1 - self.b + self.b * self.lengths[doc_id] / self.avg_len)
            s = sum(self.idf[t] * tf[t] * (self.k1 + 1) / (tf[t] + norm) for t in terms if t in tf)
            if s > 0:
                out[doc_id] = s
        return out

    def search(self, terms: set[str], k: int = CANDIDATES) -> list[str]:
        scores = self.scores(terms)
        return sorted(scores, key=lambda d: (-scores[d], d))[:k]


@lru_cache(maxsize=1)
def bm25_index() -> BM25Index:
    """Built once per process from the stored tsvectors (351 chunks: milliseconds)."""
    with _connect() as conn:
        rows = conn.execute("SELECT id, tsv::text FROM doc_chunks").fetchall()
    return BM25Index({doc_id: parse_tsvector(tsv) for doc_id, tsv in rows})


def query_terms(question: str) -> set[str]:
    """The question's words, stemmed by Postgres exactly like the chunks were."""
    with _connect() as conn:
        tsv = conn.execute("SELECT to_tsvector('english', %s)::text", [question]).fetchone()[0]
    return set(parse_tsvector(tsv))


def bm25_search(question: str, k: int = CANDIDATES) -> list[str]:
    return bm25_index().search(query_terms(question), k)


# ---------------------------------------------------------------------------
# Exact section lookup


def section_numbers(question: str) -> list[str]:
    return [m.upper() for m in SECTION_RE.findall(question)]


def section_search(question: str) -> list[str]:
    """Chunks of any section named in the question (and its parts and subsections)."""
    nums = section_numbers(question)
    if not nums:
        return []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM doc_chunks WHERE section = ANY(%s) OR section LIKE ANY(%s) ORDER BY id",
            [nums, [n + ".%" for n in nums]]).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Merging and reranking


def rrf_scores(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion: each list gives a chunk 1 / (k + its position).
    Chunks ranked well by several lists add up; k = 60 is the usual constant."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position + 1)
    return scores


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Merge several ranked lists of chunk ids into one ranking."""
    scores = rrf_scores(rankings, k)
    return sorted(scores, key=scores.get, reverse=True)


@lru_cache(maxsize=1)
def _cross_encoder():
    from sentence_transformers import CrossEncoder

    from app.config import get_settings
    return CrossEncoder(get_settings().reranker_model, max_length=512)


def rerank_scores(question: str, texts: list[str]) -> list[float]:
    """Cross-encoder relevance score for each (question, text) pair: higher is better."""
    if not texts:
        return []
    return [float(s) for s in _cross_encoder().predict([(question, t) for t in texts])]


def rerank_text(chunk: dict) -> str:
    """What the reranker reads. Budget chunks start with a label they all share
    ("2027 Budget Overview (proposed), page 150, <heading>"). It helps vector and
    BM25 search, but it matches any budget question ("2027 budget propose") so
    well that the reranker scored almost every budget chunk 0.99+. Keep only the
    chunk's own heading. Code chunks keep their section path, which differs per chunk."""
    if chunk.get("kind") != "budget":
        return chunk["text"]
    body = chunk["text"].split("\n", 1)[-1]
    return f"{chunk['title']}\n{body}" if chunk.get("title") else body


# ---------------------------------------------------------------------------


def search(question: str, mode: str = "hybrid", rerank: bool | None = None,
           top_k: int | None = None, candidates: int | None = None) -> list[dict]:
    """Best chunks for a question, each a dict with its source and why it ranked.

    Steps: candidate lists (vector / BM25 / exact section) -> RRF -> top `candidates`
    (retrieval_top_k, 20) -> optional reranker -> top `top_k` (rerank_top_k, 5).
    rerank=None follows the use_reranker setting (off by default).
    """
    from app.config import get_settings
    s = get_settings()
    top_k = top_k or s.rerank_top_k
    candidates = candidates or s.retrieval_top_k
    rerank = s.use_reranker if rerank is None else rerank
    if mode not in {"vector", "keyword", "hybrid"}:
        raise ValueError(f"unknown mode {mode!r}")

    exact = section_search(question)
    vec = vector_search(question) if mode in {"vector", "hybrid"} else []
    kw = bm25_search(question) if mode in {"keyword", "hybrid"} else []
    lists = [exact] + [lst for lst in (vec, kw) if lst]
    fused = rrf_scores(lists)
    # Sections named in the question always make the candidate list; the reranker
    # still decides their final order.
    ranked = sorted(fused, key=lambda i: -fused[i])
    ids = (exact + [i for i in ranked if i not in exact])[:max(candidates, len(exact))]

    rows = fetch_chunks(ids)
    results = []
    for i in ids:
        r = dict(rows[i])
        r.update(vector_rank=vec.index(i) + 1 if i in vec else None,
                 bm25_rank=kw.index(i) + 1 if i in kw else None,
                 exact_section=i in exact, rrf_score=fused[i], rerank_score=None)
        results.append(r)

    if rerank:
        for r, score in zip(results, rerank_scores(question, [rerank_text(r) for r in results])):
            r["rerank_score"] = score
        results.sort(key=lambda r: -r["rerank_score"])
    return results[:top_k]
