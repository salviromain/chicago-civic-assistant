"""Text-to-SQL over the city tables, with guardrails. (Day 5)

Guardrails enforced in code, not by the LLM:
- SELECT-only check before execution
- Runs as the read-only `civic_reader` role (db/init.sql)
- Row limit appended if missing; statement timeout set on the role

Table descriptions to include in the prompt (data traps):
- service_requests_311: exclude `duplicate = true` unless the user asks for all reports
- `origin` values 'Generated In House' / 'Mass Entry' come from city operations, not residents
- Filter request types on `sr_short_code`, not the long `sr_type` text
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
