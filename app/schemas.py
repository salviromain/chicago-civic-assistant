"""Request and response shapes for the API (Pydantic validates both)."""

from enum import Enum

from pydantic import BaseModel, Field


class Route(str, Enum):
    sql = "sql"
    docs = "docs"
    both = "both"


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000,
                          examples=["How many no-heat complaints were filed in Ward 25 last winter?"])


class Citation(BaseModel):
    source: str = Field(..., description="Table name or document section, e.g. 'Municipal Code 14X-8-802.2.2'")
    snippet: str | None = Field(None, description="The supporting text or the SQL that was run")
    url: str | None = None


class QueryResponse(BaseModel):
    answer: str
    route: Route
    citations: list[Citation] = []
    refused: bool = Field(False, description="True when the sources did not support an answer")
    latency_ms: int
    cost_usd: float | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
