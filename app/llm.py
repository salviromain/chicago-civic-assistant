"""Every Gemini text call goes through here: cached on disk, paced, retried.

    result = generate(prompt, system="You write SQL.", schema=SqlPlan)
    result.parsed   -> a SqlPlan (Pydantic checks the shape)
    result.cached   -> True if it came from data/cache/llm/ (no API call)

Why a cache: the free tier allows only a few requests per minute and a few
hundred per day. The same prompt to the same model at temperature 0 gets
(almost) the same answer, so we keep the first one. Re-running the evals or a
test script then costs nothing. Delete data/cache/llm/ to ask again.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from app.embeddings import MinuteBudget, _quota_id

from app.config import PROJECT_ROOT

CACHE_DIR = PROJECT_ROOT / "data" / "cache" / "llm"


class QuotaExhausted(RuntimeError):
    """The daily free-tier quota is used up: waiting minutes won't help."""


@dataclass
class LLMResult:
    text: str
    parsed: Any = None           # an instance of `schema`, when one was given
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0       # the answer itself
    thinking_tokens: int = 0     # Gemini 2.5 "thinks" before answering; billed as output
    cached: bool = False
    latency_ms: int = 0          # time the API call took (kept in the cache too)
    waited_ms: int = 0           # time spent waiting for the per-minute budget


def cache_key(model: str, system: str | None, prompt: str, schema: type[BaseModel] | None,
              temperature: float, thinking_budget: int | None, thinking_level: str | None = None) -> str:
    schema_json = json.dumps(schema.model_json_schema(), sort_keys=True) if schema else ""
    parts = [model, system or "", prompt, schema_json, temperature, thinking_budget]
    if thinking_level:  # only when set, so older cache entries keep their keys
        parts.append(thinking_level)
    raw = json.dumps(parts)
    return hashlib.sha256(raw.encode()).hexdigest()


_budgets: dict[str, MinuteBudget] = {}
_budget_lock = threading.Lock()  # the API (Day 7) handles requests in parallel threads


def _minute_budget(model: str) -> MinuteBudget:
    """One request budget per model per process, shared by every caller. Google's
    free-tier limits are per model, so the eval judge doesn't slow the answers."""
    if model not in _budgets:
        from app.config import get_settings
        _budgets[model] = MinuteBudget(per_minute=get_settings().llm_requests_per_minute)
    return _budgets[model]


@lru_cache(maxsize=1)
def _client():
    """One client per process. Calls that hang are cut off after llm_timeout_s."""
    from google import genai
    from google.genai import types

    from app.config import get_settings
    s = get_settings()
    key = os.getenv("GEMINI_API_KEY") or s.gemini_api_key
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set (add it to .env)")
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=s.llm_timeout_s * 1000))


def _is_timeout(error: Exception) -> bool:
    return "timeout" in type(error).__name__.lower()  # httpx ReadTimeout, ConnectTimeout, ...


def _call_with_retry(client, model: str, prompt: str, config, attempts: int = 5):
    """One generate_content request. Retries per-minute limits (429), server
    errors (5xx) and calls that timed out; a daily quota or a bad request is
    raised at once."""
    from google.genai import errors
    for attempt in range(attempts):
        try:
            return client.models.generate_content(model=model, contents=prompt, config=config)
        except errors.APIError as e:
            if e.code != 429 and (e.code or 0) < 500:
                raise
            quota = _quota_id(e) if e.code == 429 else f"server error {e.code}"
            if "PerDay" in quota:
                raise QuotaExhausted(f"daily Gemini quota reached ({quota}); cached answers still work")
            if attempt == attempts - 1:
                raise
            # A rate limit needs real waiting; a 5xx is usually a brief hiccup
            wait = min(2 ** attempt * 10, 60) if e.code == 429 else min(2 ** attempt * 2, 16)
            print(f"  Gemini {e.code} ({quota}), retrying in {wait}s", flush=True)
            time.sleep(wait)
        except Exception as e:
            if not _is_timeout(e):
                raise
            # On the free tier a call sometimes stalls for a minute; a fresh one is usually fast
            if attempt >= 2:
                raise
            print("  Gemini call timed out, retrying now", flush=True)
            continue


def generate(prompt: str, *, system: str | None = None, schema: type[BaseModel] | None = None,
             model: str | None = None, temperature: float = 0.0,
             thinking_budget: int | None = None, thinking_level: str | None = None,
             cache_dir: Path | None = None,
             client=None, budget: MinuteBudget | None = None) -> LLMResult:
    """Ask Gemini. With `schema`, the reply must be JSON of that shape (structured
    output) and comes back parsed. Thinking (hidden reasoning before the answer):
    thinking_level "minimal" | "low" | "medium" | "high" for Gemini 3 models, or
    thinking_budget N tokens for 2.5 models; None = the model's default."""
    from app.config import get_settings
    model = model or get_settings().llm_model
    cache_dir = cache_dir or get_settings().llm_cache_dir or CACHE_DIR
    key = cache_key(model, system, prompt, schema, temperature, thinking_budget, thinking_level)
    f = cache_dir / f"{key}.json"

    if f.exists():
        data = json.loads(f.read_text())
        result = LLMResult(**data, cached=True)
    else:
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=temperature,
            response_mime_type="application/json" if schema else None,
            response_schema=schema,
            thinking_config=(types.ThinkingConfig(thinking_budget=thinking_budget,
                                                  thinking_level=thinking_level)
                             if thinking_budget is not None or thinking_level else None))
        t0 = time.perf_counter()
        with _budget_lock:
            (budget or _minute_budget(model)).wait_for(1)
        waited_ms = round((time.perf_counter() - t0) * 1000)
        start = time.perf_counter()
        response = _call_with_retry(client or _client(), model, prompt, config)
        usage = response.usage_metadata
        result = LLMResult(
            text=response.text or "", model=model,
            input_tokens=(usage and usage.prompt_token_count) or 0,
            output_tokens=(usage and usage.candidates_token_count) or 0,
            thinking_tokens=(usage and usage.thoughts_token_count) or 0,
            latency_ms=round((time.perf_counter() - start) * 1000), waited_ms=waited_ms)
        # Check the reply before caching it: a cut-off or empty reply must not be
        # stored, or every re-run would fail on it
        if not result.text.strip():
            raise RuntimeError(f"{model} returned an empty reply")
        if schema:
            schema.model_validate_json(result.text)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: getattr(result, k) for k in
                                   ("text", "model", "input_tokens", "output_tokens",
                                    "thinking_tokens", "latency_ms")}))
        tmp.replace(f)

    if schema:
        # Parsed from the text on both paths, so a cached answer is checked the same way
        result.parsed = schema.model_validate_json(result.text)
    return result
