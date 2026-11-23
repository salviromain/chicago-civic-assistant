"""Text-to-SQL over the city tables, with guardrails. (Day 5)

Guardrails enforced in code, not by the LLM:
- SELECT-only check before execution
- Runs as the read-only `civic_reader` role (db/init.sql)
- Row limit appended if missing; statement timeout set on the role

Prompt schema: docs/TABLES.md (tables, columns, real values, data traps and
example queries). Load it into the prompt rather than repeating it here.
"""

import re

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|do)\b",
    re.IGNORECASE,
)


def is_safe_select(sql: str) -> bool:
    """Allow a single SELECT (or WITH ... SELECT) statement and nothing else."""
    stripped = sql.strip().rstrip(";").strip()
    if ";" in stripped:
        return False  # multiple statements
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        return False
    return not _FORBIDDEN.search(stripped)


def answer_with_sql(question: str) -> dict:
    raise NotImplementedError
