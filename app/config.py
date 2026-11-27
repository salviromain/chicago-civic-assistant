"""Settings read from environment variables (or a local .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The repo folder, so .env and data/ are found wherever the app is started from
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/civic"
    readonly_database_url: str = "postgresql://civic_reader:change-me@localhost:5432/civic"
    gemini_api_key: str = ""
    service_api_key: str = "change-me"
    request_timeout_s: int = 30  # one /query request; past this the API answers 504

    # Request limits for /query (app/ratelimit.py); 0 turns one off. Days end at midnight Pacific.
    rate_limit_per_minute: int = 5     # per client
    rate_limit_per_day: int = 50       # per client
    rate_limit_total_per_day: int = 500  # whole service: at ~$0.003 a question, at most ~$1.50 a day
    # Proxies in front of the app that append to X-Forwarded-For: 0 locally, 1 on Cloud Run.
    # The client's address is read that many places from the right; never trust more.
    trusted_proxies: int = 0
    log_questions: bool = False  # off: strangers' questions stay out of the logs (length is logged)

    # Prices for the cost estimate, US$ per million tokens: the paid list prices of
    # gemini-3.1-flash-lite (change them with llm_model). The estimate is what a question
    # costs at list price; on the free tier nothing is billed. 0 turns the estimate off.
    llm_usd_per_m_input: float = 0.25
    llm_usd_per_m_output: float = 1.50

    # Model choices (compare Flash vs Pro in the evals)
    llm_model: str = "gemini-3.1-flash-lite"  # 2.5 retired for new keys; 3.8/3.5 Flash took 268 s / 23 s on the free tier
    sql_thinking_level: str | None = None  # Gemini 3 thinking for the SQL agent: None, minimal, low, medium, high
    llm_requests_per_minute: int = 8  # free tier; raise it on a paid key (LLM_REQUESTS_PER_MINUTE)
    # Where LLM replies are cached (None = data/cache/llm). Point it at an empty folder to
    # time the pipeline with every call live, without touching the real cache.
    llm_cache_dir: Path | None = None
    llm_timeout_s: int = 12  # a stalled call is cut off and retried (free-tier calls sometimes hang ~1 min)  # free tier allows 10 for Flash; stay under
    embedding_model: str = "gemini-embedding-001"
    embedding_dims: int = 768  # shortened from 3072: 4x smaller, fits pgvector's HNSW index

    # Guardrails and retrieval knobs
    sql_row_limit: int = 500
    sql_timeout_s: int = 15  # also set on the civic_reader role (db/init.sql)
    retrieval_top_k: int = 20
    rerank_top_k: int = 5
    reranker_model: str = "BAAI/bge-reranker-base"  # local cross-encoder, runs on CPU
    # Off by default: on the 10 Day 4 questions it lowered MRR from 0.88 to 0.62
    # (docs/BUILD_LOG.md). Day 10 compares rerankers on the full eval set.
    use_reranker: bool = False
    # vector, keyword or hybrid. Vector won on the 87-question eval set (Day 10): recall@5
    # 100% vs 95.5%, answer checks 87.0% vs 84.4%. Exact section lookup runs in every mode.
    search_mode: str = "vector"


@lru_cache
def get_settings() -> Settings:
    return Settings()
