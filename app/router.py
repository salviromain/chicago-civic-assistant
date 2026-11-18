"""Decides whether a question needs SQL, documents, or both. (Day 6)

Plan:
- One LLM call with structured output (Pydantic) returning a Route.
- Few-shot examples: counts/trends -> sql; rules/requirements -> docs; both -> both.
- Evaluate with router accuracy on the eval set.
"""

from app.schemas import Route


def route(question: str) -> Route:
    raise NotImplementedError
