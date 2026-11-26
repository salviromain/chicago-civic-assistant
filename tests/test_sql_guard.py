"""SQL guardrails: what may run, what's rejected, and the row limit. No database needed."""

import re
from pathlib import Path

import pytest

from app.sql_guard import UnsafeSQL, check_sql, is_safe_select


@pytest.mark.parametrize("sql", [
    "SELECT count(*) FROM service_requests_311",
    "with w as (select ward from building_permits) select * from w;",
    "SELECT ward FROM building_permits UNION SELECT ward FROM service_requests_311",
    "SELECT sr_type::text FROM service_requests_311 WHERE sr_type::text ILIKE '%tree%'",
    "SELECT m FROM generate_series('2025-01-01'::date, '2025-12-01', interval '1 month') AS m",
    "SELECT count(*) FROM public.building_violations",
])
def test_allows_read_only_queries(sql):
    assert is_safe_select(sql)


@pytest.mark.parametrize("sql, reason", [
    ("DROP TABLE service_requests_311", "only SELECT"),
    ("SELECT 1; DELETE FROM service_requests_311", "exactly one statement"),
    ("UPDATE service_requests_311 SET status = 'Open'", "only SELECT"),
    ("SELECT * INTO copy_of_permits FROM building_permits", "INTO"),
    ("SELECT * FROM building_permits FOR UPDATE", "FOR UPDATE"),
    ("SELECT pg_sleep(30)", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
    ("SELECT * FROM pg_catalog.pg_roles", "schema pg_catalog"),
    ("SELECT * FROM doc_chunks", "unknown table doc_chunks"),
    ("WITH x AS (DELETE FROM building_permits RETURNING *) SELECT * FROM x", "not allowed"),
    ("COPY building_permits TO '/tmp/out.csv'", "only SELECT"),
    ("SET ROLE postgres", "only SELECT"),
    ("SELEC count(*) FROM building_permits", "could not parse"),
])
def test_rejects_with_a_reason(sql, reason):
    with pytest.raises(UnsafeSQL, match=re.escape(reason)):
        check_sql(sql)


def test_comment_cannot_hide_a_second_statement():
    out = check_sql("SELECT 1 FROM building_permits -- ; DROP TABLE building_permits")
    assert "DROP" not in out.upper() and "--" not in out


def test_row_limit_added_or_lowered_never_raised():
    assert check_sql("SELECT ward FROM building_permits", 500).endswith("LIMIT 500")
    assert check_sql("SELECT ward FROM building_permits LIMIT 9000", 500).endswith("LIMIT 500")
    assert check_sql("SELECT ward FROM building_permits LIMIT 5", 500).endswith("LIMIT 5")
    union = check_sql("SELECT 1 FROM building_permits UNION SELECT 2 FROM building_permits", 10)
    assert union.endswith("LIMIT 10")


def test_values_survive_rewriting():
    # the en dash in the express permit type must not be changed
    out = check_sql("SELECT count(*) FROM building_permits WHERE permit_type = 'PERMIT – EXPRESS PERMIT PROGRAM'")
    assert "'PERMIT – EXPRESS PERMIT PROGRAM'" in out


def test_every_example_in_tables_md_passes():
    text = Path("docs/TABLES.md").read_text()
    blocks = re.findall(r"```sql\n(.*?)```", text, re.S)
    queries = [q.strip() for b in blocks for q in b.split(";") if "SELECT" in q]
    assert len(queries) >= 7
    for q in queries:
        check_sql(q)
