"""The SQL agent's flow, with a fake LLM and a fake database."""

import datetime as dt
from types import SimpleNamespace

import psycopg
import pytest

from app.sql_agent import SqlPlan, query_tables, system_prompt

TODAY = dt.date(2026, 11, 25)


def fake_llm(*plans):
    """Returns the given SqlPlans in order and records the prompts it saw."""
    queue, prompts = list(plans), []

    def generate(prompt, **kw):
        prompts.append(prompt)
        return SimpleNamespace(parsed=queue.pop(0), cached=False, input_tokens=1000,
                               output_tokens=50, thinking_tokens=0)
    generate.prompts = prompts
    return generate


def fake_db(*outcomes):
    queue, ran = list(outcomes), []

    def run(sql, max_rows):
        ran.append(sql)
        out = queue.pop(0)
        if isinstance(out, Exception):
            raise out
        return out
    run.ran = ran
    return run


def plan(sql, notes=()):
    return SqlPlan(approach="a", answerable=True, sql=sql, notes=list(notes))


def test_answerable_question_runs_checked_sql():
    llm = fake_llm(plan("SELECT count(*) FROM service_requests_311", ["Duplicates excluded"]))
    db = fake_db((["count"], [[721]], False))
    r = query_tables("potholes?", TODAY, generate=llm, run=db)
    assert r.ok and r.rows == [[721]] and r.notes == ["Duplicates excluded"]
    assert db.ran == ["SELECT COUNT(*) FROM service_requests_311 LIMIT 500"]
    assert r.llm_calls == 1 and len(r.attempts) == 1
    assert "Today is 2026-11-25" in llm.prompts[0]


def test_refusal_never_touches_the_database():
    llm = fake_llm(SqlPlan(approach="a", answerable=False, refusal_reason="No ward column."))
    db = fake_db()
    r = query_tables("violations in ward 25?", TODAY, generate=llm, run=db)
    assert not r.answerable and r.refusal_reason == "No ward column." and db.ran == []


def test_database_error_is_sent_back_once_for_repair():
    llm = fake_llm(plan("SELECT wrd FROM building_permits"), plan("SELECT ward FROM building_permits"))
    db = fake_db(psycopg.errors.UndefinedColumn('column "wrd" does not exist'), (["ward"], [[25]], False))
    r = query_tables("q", TODAY, generate=llm, run=db)
    assert r.ok and r.rows == [[25]] and r.llm_calls == 2
    assert 'column "wrd" does not exist' in llm.prompts[1] and "SELECT wrd" in llm.prompts[1]
    assert [a.error is None for a in r.attempts] == [False, True]


def test_guard_rejection_is_repaired_without_running_it():
    llm = fake_llm(plan("SELECT * FROM doc_chunks"), plan("SELECT 1 FROM building_permits"))
    db = fake_db((["?column?"], [[1]], False))
    r = query_tables("q", TODAY, generate=llm, run=db)
    assert r.ok and len(db.ran) == 1 and "unknown table doc_chunks" in llm.prompts[1]


def test_gives_up_after_one_repair():
    bad = psycopg.errors.InvalidTextRepresentation('invalid input value for enum sr_short_code_t: "POT"')
    llm = fake_llm(plan("SELECT 1 FROM service_requests_311 WHERE sr_short_code = 'POT'"),
                   plan("SELECT 1 FROM service_requests_311 WHERE sr_short_code = 'PTH'"))
    db = fake_db(bad, bad)
    r = query_tables("q", TODAY, generate=llm, run=db)
    assert not r.ok and "invalid input value" in r.error and len(r.attempts) == 2


def test_database_down_is_not_a_repair_case():
    llm = fake_llm(plan("SELECT 1 FROM building_permits"))
    db = fake_db(psycopg.OperationalError("connection refused"))
    with pytest.raises(psycopg.OperationalError):
        query_tables("q", TODAY, generate=llm, run=db)


def test_prompt_contains_the_table_reference():
    p = system_prompt()
    assert "service_requests_311" in p and "13-196-410" in p and "PERMIT – EXPRESS" in p
