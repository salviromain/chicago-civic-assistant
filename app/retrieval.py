"""Hybrid search over document chunks. (Day 4)

Plan:
- Embedding search with pgvector (cosine distance)
- Keyword search with Postgres full-text search (ts_rank)
- Merge with Reciprocal Rank Fusion, keep top `retrieval_top_k`
- Rerank with a cross-encoder, keep top `rerank_top_k`
"""


def reciprocal_rank_fusion(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Merge several ranked lists of chunk ids into one ranking."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, chunk_id in enumerate(ranking):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + position + 1)
    return sorted(scores, key=scores.get, reverse=True)


def search(question: str) -> list[dict]:
    raise NotImplementedError
