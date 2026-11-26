"""Text-to-SQL over the three city tables. (Day 5)

    query_tables("How many pothole complaints in ward 25 in 2026?")
    -> SqlResult(answerable=True, sql="SELECT count(*) ...", columns=["count"],
                 rows=[[721]], notes=["Duplicates excluded", ...])

Steps:
1. Gemini reads docs/TABLES.md (columns, real values, traps, example queries)
   plus the question, and returns a SqlPlan (structured output): either SQL,
   or answerable=false with the reason.
2. The SQL goes through app/sql_guard.py (one SELECT, the three tables only,
   a row limit) and runs as civic_reader in a READ ONLY transaction (app/db.py).
3. If the guard or Postgres rejects it (a typo'd column, an enum value that
   doesn't exist, a missing ::text cast), the error goes back to Gemini once
   to fix. Then it stops: no endless loops.

The answer step (Day 6) turns the rows and notes into a cited sentence.
"""

from __future__ import annotations

import datetime as dt
import time
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

from app.sql_guard import UnsafeSQL, check_sql, is_safe_select  # noqa: F401

TABLES_MD = Path(__file__).resolve().parent.parent / "docs" / "TABLES.md"
MAX_ATTEMPTS = 2  # first try + one repair


class SqlPlan(BaseModel):
    """What the LLM returns. Field order matters: it writes `approach` first, so
    it thinks about tables and traps before writing the SQL."""
    approach: str = Field(description="One or two sentences: which table, which filters, which traps apply.")
    answerable: bool = Field(description="False if these tables can't answer the question.")
    sql: str | None = Field(None, description="One PostgreSQL SELECT, or null when not answerable.")
    notes: list[str] = Field(default_factory=list, description=(
        "Filters and assumptions the answer must mention, e.g. 'Duplicates excluded', "
        "'Date range 2025-12-01 to 2026-02-28', 'Counted heat violations; 311 has no heat type'."))
    refusal_reason: str | None = Field(None, description="When not answerable: what's missing, in one sentence.")


class Attempt(BaseModel):
    sql: str | None
    error: str | None = None


class SqlResult(BaseModel):
    question: str
    answerable: bool
    sql: str | None = None             # the checked SQL that ran
    columns: list[str] = []
    rows: list[list] = []
    truncated: bool = False            # more rows than the row limit
    notes: list[str] = []
    refusal_reason: str | None = None
    error: str | None = None           # set when every attempt failed
    attempts: list[Attempt] = []
    llm_calls: int = 0                 # API calls (cached replies don't count)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.answerable and self.error is None


SYSTEM = """You write PostgreSQL queries that answer questions about Chicago from three tables:
service_requests_311, building_violations and building_permits. The reference below describes
every column, the real values, the traps and tested example queries. Follow it exactly.

How to answer:
- Write ONE SELECT (WITH is fine). Use only tables, columns and values from the reference.
  Enum values must be copied exactly from the reference; an unknown value is an error.
- Apply the reference's default filters (e.g. NOT duplicate for 311 counts) and put every
  filter or assumption that changes the meaning of the number in `notes`, in plain words.
- Return the numbers the question asks for (counts, medians, top N), not raw rows,
  unless it asks for a list. Lists: LIMIT 50 or fewer.
- Relative dates ("last winter", "this year") are relative to today's date, given with the
  question. Winter = December 1 to the end of February. Use half-open ranges and say the
  exact range in `notes`. If the range runs past the end of the data, say so in `notes`.
- Set answerable=false (sql=null) and give `refusal_reason` when the tables can't answer:
  anything in "Not in these tables"; forecasts or predictions; opinions; what the law
  requires (that's the Municipal Code, not these tables); budget figures. Don't swap in a
  different measure to get a number, except where the reference says to (heat questions
  use heat violations in building_violations: say so in `notes`).

Examples of refusals:
- "How many building violations were there in ward 25?" -> building_violations has no ward column.
- "How many aircraft noise complaints in 2026?" -> aircraft noise complaints aren't loaded.
- "How many potholes were reported in 2023?" -> the data starts on 2025-01-01.
- "How many potholes will be reported next spring?" -> a forecast; the tables only record the past.
- "How many no-heat complaints in ward 25?" -> 311 has no heat type, and heat violations have no ward.

=== Reference: docs/TABLES.md ===
"""


@lru_cache(maxsize=1)
def system_prompt() -> str:
    return SYSTEM + TABLES_MD.read_text()


def question_prompt(question: str, today: dt.date) -> str:
    return f"Today is {today.isoformat()}.\nQuestion: {question}"


def repair_prompt(question: str, today: dt.date, sql: str | None, error: str) -> str:
    return (question_prompt(question, today) +
            f"\n\nYour previous query failed.\nQuery:\n{sql}\nError: {error}\n"
            "Fix the query (or set answerable=false if the tables can't answer).")


def query_tables(question: str, today: dt.date | None = None, *, model: str | None = None,
                 generate=None, run=None) -> SqlResult:
    """Question -> SQL -> rows, or a refusal. `generate` and `run` can be replaced in tests."""
    from app.config import get_settings
    from app.llm import generate as default_generate

    s = get_settings()
    generate = generate or default_generate
    if run is None:
        from app.db import run_select
        run = run_select
    today = today or dt.date.today()
    start = time.perf_counter()
    result = SqlResult(question=question, answerable=True)

    def ask(prompt: str) -> SqlPlan:
        reply = generate(prompt, system=system_prompt(), schema=SqlPlan, model=model)
        result.llm_calls += 0 if reply.cached else 1
        result.input_tokens += reply.input_tokens
        result.output_tokens += reply.output_tokens + reply.thinking_tokens
        return reply.parsed

    plan = ask(question_prompt(question, today))
    for attempt in range(MAX_ATTEMPTS):
        result.notes = plan.notes
        if not plan.answerable or not plan.sql:
            result.answerable = False
            result.refusal_reason = plan.refusal_reason or "These tables can't answer the question."
            break
        try:
            sql = check_sql(plan.sql, s.sql_row_limit)
            columns, rows, truncated = run(sql, s.sql_row_limit)
        except Exception as e:  # noqa: BLE001 - only the errors a better query could fix
            if not _fixable(e):
                raise
            message = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
            result.attempts.append(Attempt(sql=plan.sql, error=message))
            if attempt == MAX_ATTEMPTS - 1:
                result.error = message
                break
            plan = ask(repair_prompt(question, today, plan.sql, message))
            continue
        result.attempts.append(Attempt(sql=sql))
        result.sql, result.columns, result.rows, result.truncated = sql, columns, rows, truncated
        break

    result.latency_ms = round((time.perf_counter() - start) * 1000)
    return result


def _fixable(error: Exception) -> bool:
    """Errors a corrected query could avoid: rejected by the guard, a SQL mistake
    (unknown column, bad syntax), a bad value (unknown enum value), or too slow.
    Not: the database being down, a wrong password."""
    if isinstance(error, UnsafeSQL):
        return True
    # Postgres error codes (SQLSTATE): 42xxx syntax or access (unknown column,
    # missing cast, no permission), 22xxx bad data (unknown enum value),
    # 57014 timeout, 25006 write in a read-only transaction.
    code = getattr(error, "sqlstate", None) or ""
    return code[:2] in {"42", "22"} or code in {"57014", "25006"}
