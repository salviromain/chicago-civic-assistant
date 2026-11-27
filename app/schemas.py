"""Request and response shapes for the API (Pydantic validates both)."""

from enum import Enum

from pydantic import BaseModel, Field


class Route(str, Enum):
    sql = "sql"
    docs = "docs"
    both = "both"


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000,
                          examples=["How many heat violations were recorded last winter, and what does the city code require landlords to provide?"])


class Citation(BaseModel):
    source: str = Field(..., description="Table name or document section, e.g. 'Municipal Code 14X-8-802.2.2'")
    snippet: str | None = Field(None, description="The supporting text or the SQL that was run")
    url: str | None = None
    highlights: list[str] = Field([], description="Words in the snippet that match the answer, to highlight")


class Usage(BaseModel):
    llm_calls: int = Field(0, description="Gemini API calls made (cached replies don't count)")
    input_tokens: int = 0
    output_tokens: int = Field(0, description="Including thinking tokens")


class QueryResponse(BaseModel):
    answer: str
    route: Route
    citations: list[Citation] = []
    refused: bool = Field(False, description="True when the sources did not support an answer")
    latency_ms: int
    cost_usd: float | None = Field(None, description=(
        "Estimated LLM cost at the configured list prices, cached replies included (the free tier is not billed)"))
    usage: Usage = Usage()


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    database: str = Field("unknown", description="ok, or unavailable")


class ErrorResponse(BaseModel):
    detail: str
