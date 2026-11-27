"""The plain-model baseline: the same Gemini model answers from what it knows, with no
SQL, no documents and no search. It shows what the data and documents add.

    .venv/bin/python -m evals.run_evals --baseline plain --label baseline-plain

Kept fair: the same model, today's date, a description of what the questions are about,
the same answer rules as the real system (be specific, say "proposed" for the budget),
and permission to say it doesn't know (refused=true), so an honest "I can't know that"
counts as a refusal, not a wrong answer. Scored with the same deterministic answer and
refusal checks; route, SQL, retrieval, citation and faithfulness metrics don't apply.
"""

from __future__ import annotations

import datetime as dt
import time

from app.answer import AnswerDraft, Trace, estimate_cost
from app.schemas import QueryResponse, Route, Usage

SYSTEM = """You answer questions about Chicago: 311 service requests, building violations
and building permits (the City's open data portal), the Municipal Code of Chicago, and the
City's proposed 2027 budget. You have no tools and no documents: answer from what you know.

- Give the specific fact asked for: the number, the code section, the amount, the date.
- Write numbers as people do: thousands separators, one decimal for days and percentages.
- The 2027 budget is a PROPOSED budget, not adopted: say "proposed".
- If you don't know the answer, or it can't be known (e.g. exact counts from records you
  haven't seen, or a forecast), set refused=true and say briefly why. Don't guess numbers.
- Be brief: 1 to 4 sentences, plain language. No disclaimers.
"""


def run_plain(question: str, today: dt.date | None = None, *, model: str | None = None,
              generate=None) -> Trace:
    from app.llm import generate as default_generate
    generate = generate or default_generate
    today = today or dt.date.today()
    start = time.perf_counter()
    reply = generate(f"Today is {today.isoformat()}.\nQuestion: {question}",
                     system=SYSTEM, schema=AnswerDraft, model=model)
    draft = reply.parsed
    output = reply.output_tokens + reply.thinking_tokens
    response = QueryResponse(
        answer=draft.answer, route=Route.docs, citations=[], refused=draft.refused,
        latency_ms=round((time.perf_counter() - start) * 1000),
        usage=Usage(llm_calls=0 if reply.cached else 1, input_tokens=reply.input_tokens,
                    output_tokens=output),
        cost_usd=estimate_cost(reply.input_tokens, output))
    return Trace(question=question, response=response, draft=draft,
                 llm_calls=0 if reply.cached else 1, input_tokens=reply.input_tokens,
                 output_tokens=output, sources_text="(none: the model answered from memory)")


# Metrics that measure the pipeline's parts; a plain model has none of them
PIPELINE_ONLY = ("route_ok", "route", "sql_ok", "agent_sql", "agent_rows", "retrieved",
                 "recall@5", "rr", "citation_ok", "citations", "cited")
