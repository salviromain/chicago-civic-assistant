"""Decides whether a question needs the tables (SQL), the documents, or both. (Day 6)

    route_question("How many heat violations last winter, and what must landlords provide?")
    -> RouteDecision(route="both",
                     sql_question="How many heat violations were recorded last winter?",
                     docs_question="What heat must landlords provide under the city code?")

One Gemini call with structured output. For "both", the question is split in
two, so each part goes to the system that can answer it (the SQL agent refuses
law questions; search can't count).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas import Route


class RouteDecision(BaseModel):
    reasoning: str = Field(description="One sentence: what the question needs.")
    route: Route
    sql_question: str | None = Field(None, description=(
        "For sql and both: the part to answer from the tables, as a standalone question."))
    docs_question: str | None = Field(None, description=(
        "For docs and both: the part to answer from the documents, as a standalone question."))


SYSTEM = """You route questions about Chicago to the source that can answer them.

sql  = city data tables (Chicago Data Portal, 2025-01-01 to 2026-11-18): 311 service requests
       (potholes, rats, graffiti, trees, street lights, ...), building violations found by
       inspectors (including heat violations), building permits. Use for counts, totals,
       medians, trends, rankings, lists of records, "how many", "which ward", "how long".
docs = city documents: Municipal Code chapter 14X-8 (property maintenance: heat, cooling,
       ventilation), 5-12 (Residential Landlord and Tenant Ordinance: deposits, repairs,
       entry, remedies), 5-16 (heat cost disclosure), and the proposed 2027 city budget.
       Use for rules, requirements, rights, definitions, what a section says, budget figures.
both = the question asks for data AND a rule, e.g. a count plus what the code requires.

Pick the route by what the question asks for, even if the source may not have it: data
questions the tables can't answer (forecasts, years before 2025, missing columns) still go
to sql, and rule or budget questions the documents may not cover still go to docs; those
systems decide to refuse. Questions about something else entirely (sports, weather,
general facts) go to docs.

For both, split the question into two standalone questions (sql_question and docs_question),
keeping dates, places and other details in the part that needs them. For sql or docs, leave
both empty: the question is used exactly as asked.

Examples:
- "How many pothole complaints were there in ward 25 in 2026?" -> sql
- "Which wards got the most new construction permits?" -> sql
- "How many potholes will there be next year?" -> sql (the SQL agent will refuse a forecast)
- "What minimum temperature must my landlord keep?" -> docs
- "How much interest is owed on a security deposit?" -> docs
- "How much does the 2027 budget propose for libraries?" -> docs
- "What does section 5-12-150 say?" -> docs
- "How many heat violations were recorded last winter, and what heat does the code require?"
  -> both; sql_question "How many heat violations were recorded last winter?",
  docs_question "What heat does the city code require landlords to provide?"
- "How many no air conditioning complaints were there in 2025, and when must cooling run?"
  -> both
"""


def route_question(question: str, *, model: str | None = None, generate=None) -> tuple[RouteDecision, object]:
    """Returns (decision, the LLMResult for token counting)."""
    from app.llm import generate as default_generate
    generate = generate or default_generate
    reply = generate(f"Question: {question}", system=SYSTEM, schema=RouteDecision, model=model)
    d: RouteDecision = reply.parsed
    # Single route: the question exactly as asked. Rewording it ("... according to the
    # municipal code") pushed the right chunk out of the top 5 in testing (Day 6).
    # Both: the model's two parts, or the whole question if a part is missing.
    if d.route == Route.sql:
        d.sql_question, d.docs_question = question, None
    elif d.route == Route.docs:
        d.sql_question, d.docs_question = None, question
    else:
        d.sql_question = d.sql_question or question
        d.docs_question = d.docs_question or question
    return d, reply


def route(question: str) -> Route:
    return route_question(question)[0].route
