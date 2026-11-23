"""Settings read from environment variables (or a local .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://postgres:postgres@localhost:5432/civic"
    readonly_database_url: str = "postgresql://civic_reader:change-me@localhost:5432/civic"
    gemini_api_key: str = ""
    service_api_key: str = "change-me"

    # Model choices (compare Flash vs Pro in the evals)
    llm_model: str = "gemini-2.5-flash"
    embedding_model: str = "gemini-embedding-001"
    embedding_dims: int = 768  # shortened from 3072: 4x smaller, fits pgvector's HNSW index

    # Guardrails and retrieval knobs
    sql_row_limit: int = 500
    retrieval_top_k: int = 20
    rerank_top_k: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
