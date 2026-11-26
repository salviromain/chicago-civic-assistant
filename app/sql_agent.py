"""Text-to-SQL over the city tables, with guardrails. (Day 5)

Guardrails enforced in code, not by the LLM:
- SELECT-only check before execution
- Runs as the read-only `civic_reader` role (db/init.sql)
- Row limit appended if missing; statement timeout set on the role

Prompt schema: docs/TABLES.md (tables, columns, real values, data traps and
example queries). Load it into the prompt rather than repeating it here.
"""

from app.sql_guard import UnsafeSQL, check_sql, is_safe_select  # noqa: F401


def answer_with_sql(question: str) -> dict:
    raise NotImplementedError
