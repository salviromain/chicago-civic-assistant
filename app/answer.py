"""Runs the whole flow and writes the cited answer. (Day 6)

route -> (sql_agent and/or retrieval) -> LLM answer that:
- uses only the given sources and cites each claim
- refuses ("I don't know") when the sources don't support an answer
- returns latency and token cost for logging
"""

from app.schemas import QueryResponse


def answer(question: str) -> QueryResponse:
    raise NotImplementedError
