"""Gemini embeddings with a disk cache, paced for the free tier.

Used by the document loader (chunks, task RETRIEVAL_DOCUMENT) and by search
(questions, task RETRIEVAL_QUERY). Every embedding is cached in
data/cache/embeddings/, keyed by model, size, task and text, so asking for the
same text twice costs one API call.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from app.config import PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "embeddings"

# Gemini free tier: 30,000 input tokens per minute for embeddings
# (quota EmbedContentTokensPerMinutePerProjectPerModel-FreeTier). Our token
# counts are estimates and numbers-heavy budget text counts higher, so stay well under.
EMBED_BATCH_TOKENS = 8_000      # estimated tokens per request
EMBED_MINUTE_TOKENS = 18_000    # estimated tokens sent per rolling minute
EMBED_BATCH_MAX = 100           # texts per request (API limit)


def approx_tokens(text: str) -> int:
    """Rough token count: about 1.3 tokens per English word. Good enough for sizing."""
    return round(len(text.split()) * 1.3)


def cache_key(model: str, dims: int, task: str, text: str) -> str:
    return hashlib.sha256(f"{model}|{dims}|{task}|{text}".encode()).hexdigest()


def _normalize(vec: list[float]) -> list[float]:
    """Scale to length 1. Google recommends this for embeddings shortened below 3072."""
    norm = sum(v * v for v in vec) ** 0.5 or 1.0
    return [v / norm for v in vec]


def token_batches(texts: list[str], idx: list[int], max_tokens: int = EMBED_BATCH_TOKENS,
                  max_items: int = EMBED_BATCH_MAX) -> list[list[int]]:
    """Group text indexes into requests by estimated size, not just by count."""
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for i in idx:
        n = approx_tokens(texts[i])
        if current and (size + n > max_tokens or len(current) >= max_items):
            batches.append(current)
            current, size = [], 0
        current.append(i)
        size += n
    if current:
        batches.append(current)
    return batches


class MinuteBudget:
    """Wait before a request if it would push the last 60 s over the token budget.
    Pacing up front avoids hitting the limit and burning retries."""

    def __init__(self, per_minute: int = EMBED_MINUTE_TOKENS, clock=time.monotonic, sleep=time.sleep):
        self.per_minute, self.clock, self.sleep = per_minute, clock, sleep
        self.sent: list[tuple[float, int]] = []

    def wait_for(self, tokens: int) -> None:
        while True:
            now = self.clock()
            self.sent = [(t, n) for t, n in self.sent if now - t < 60]
            used = sum(n for _, n in self.sent)
            if not self.sent or used + tokens <= self.per_minute:
                self.sent.append((now, tokens))
                return
            self.sleep(60 - (now - self.sent[0][0]) + 0.5)


def embed_texts(texts: list[str], model: str, dims: int, task: str,
                api_key: str | None, cache_dir: Path = CACHE_DIR,
                client=None, budget: MinuteBudget | None = None,
                progress: bool = True) -> tuple[list[list[float]], int]:
    """Embed texts, reading and writing a per-text cache. Returns (vectors, API calls).
    progress prints a line per batch (ingest); the API turns it off (one JSON line per request)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    vectors: list[list[float] | None] = [None] * len(texts)
    missing = []
    for i, text in enumerate(texts):
        f = cache_dir / f"{cache_key(model, dims, task, text)}.json"
        if f.exists():
            vectors[i] = json.loads(f.read_text())
        else:
            missing.append(i)
    calls = 0
    if missing:
        if client is None:
            if not api_key:
                raise SystemExit("GEMINI_API_KEY is not set (add it to .env), or use --no-embed")
            from google import genai
            client = genai.Client(api_key=api_key)
        budget = budget or MinuteBudget()
        done = 0
        for idx in token_batches(texts, missing):
            budget.wait_for(sum(approx_tokens(texts[i]) for i in idx))
            result = _embed_with_retry(client, model, dims, task, [texts[i] for i in idx])
            calls += 1
            for i, emb in zip(idx, result):
                vec = _normalize(list(emb))
                vectors[i] = vec
                f = cache_dir / f"{cache_key(model, dims, task, texts[i])}.json"
                tmp = f.with_suffix(".tmp")
                tmp.write_text(json.dumps(vec))
                tmp.replace(f)  # never leave a half-written cache file
            done += len(idx)
            if progress:
                print(f"  embedded {done}/{len(missing)}", flush=True)
    return vectors, calls  # type: ignore[return-value]


def _quota_id(error) -> str:
    """Which quota a 429 hit, e.g. ...TokensPerMinute... or ...PerDay..."""
    m = re.search(r"'quotaId': '([^']+)'", str(error))
    return m.group(1) if m else "unknown quota"


def _embed_with_retry(client, model: str, dims: int, task: str, texts: list[str],
                      attempts: int = 6) -> list[list[float]]:
    """One embedding request; retries rate limits (429) and server errors (5xx).
    A daily quota won't reset by waiting minutes, so that stops at once."""
    from google.genai import errors, types
    config = types.EmbedContentConfig(task_type=task, output_dimensionality=dims)
    for attempt in range(attempts):
        try:
            result = client.models.embed_content(model=model, contents=texts, config=config)
            return [e.values for e in result.embeddings]
        except errors.APIError as e:
            if e.code != 429 and (e.code or 0) < 500:
                raise  # a bad request won't fix itself
            quota = _quota_id(e) if e.code == 429 else f"server error {e.code}"
            if "PerDay" in quota:
                raise SystemExit(f"daily embedding quota reached ({quota}); run again tomorrow, "
                                 "cached embeddings are kept")
            if attempt == attempts - 1:
                raise
            wait = min(2 ** attempt * 15, 120)
            print(f"  embedding API {e.code} ({quota}), retrying in {wait}s", flush=True)
            time.sleep(wait)
    return []


def embed_query(text: str) -> list[float]:
    """Embed a search question (task RETRIEVAL_QUERY), using the cache."""
    import os

    from app.config import get_settings
    s = get_settings()
    vectors, _ = embed_texts([text], s.embedding_model, s.embedding_dims, "RETRIEVAL_QUERY",
                             os.getenv("GEMINI_API_KEY") or s.gemini_api_key, progress=False)
    return vectors[0]
