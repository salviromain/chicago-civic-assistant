"""The SQL agent's flow, with a fake LLM and a fake database."""

import datetime as dt
from types import SimpleNamespace

import psycopg
import pytest

from app.sql_agent import SqlPlan, coverage_notes, query_tables, system_prompt

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
    llm = fake_llm(plan("SELECT count(*) FROM service_requests_311 WHERE NOT duplicate", ["Duplicates excluded"]))
    db = fake_db((["count"], [[721]], False))
    r = query_tables("potholes?", TODAY, generate=llm, run=db, data_ends={})
    assert r.ok and r.rows == [[721]] and r.notes == ["Duplicates excluded"]
    assert db.ran == ["SELECT COUNT(*) FROM service_requests_311 WHERE NOT duplicate LIMIT 500"]
    assert r.llm_calls == 1 and len(r.attempts) == 1
    assert "Today is 2026-11-25" in llm.prompts[0]


def test_refusal_never_touches_the_database():
    llm = fake_llm(SqlPlan(approach="a", answerable=False, refusal_reason="No ward column."))
    db = fake_db()
    r = query_tables("violations in ward 25?", TODAY, generate=llm, run=db, data_ends={})
    assert not r.answerable and r.refusal_reason == "No ward column." and db.ran == []


def test_database_error_is_sent_back_once_for_repair():
    llm = fake_llm(plan("SELECT wrd FROM building_permits"), plan("SELECT ward FROM building_permits"))
    db = fake_db(psycopg.errors.UndefinedColumn('column "wrd" does not exist'), (["ward"], [[25]], False))
    r = query_tables("q", TODAY, generate=llm, run=db, data_ends={})
    assert r.ok and r.rows == [[25]] and r.llm_calls == 2
    assert 'column "wrd" does not exist' in llm.prompts[1] and "SELECT wrd" in llm.prompts[1]
    assert [a.error is None for a in r.attempts] == [False, True]


def test_guard_rejection_is_repaired_without_running_it():
    llm = fake_llm(plan("SELECT * FROM doc_chunks"), plan("SELECT 1 FROM building_permits"))
    db = fake_db((["?column?"], [[1]], False))
    r = query_tables("q", TODAY, generate=llm, run=db, data_ends={})
    assert r.ok and len(db.ran) == 1 and "unknown table doc_chunks" in llm.prompts[1]


def test_gives_up_after_one_repair():
    bad = psycopg.errors.InvalidTextRepresentation('invalid input value for enum sr_short_code_t: "POT"')
    llm = fake_llm(plan("SELECT 1 FROM service_requests_311 WHERE sr_short_code = 'POT'"),
                   plan("SELECT 1 FROM service_requests_311 WHERE sr_short_code = 'PTH'"))
    db = fake_db(bad, bad)
    r = query_tables("q", TODAY, generate=llm, run=db, data_ends={})
    assert not r.ok and "invalid input value" in r.error and len(r.attempts) == 2


def test_database_down_is_not_a_repair_case():
    llm = fake_llm(plan("SELECT 1 FROM building_permits"))
    db = fake_db(psycopg.OperationalError("connection refused"))
    with pytest.raises(psycopg.OperationalError):
        query_tables("q", TODAY, generate=llm, run=db, data_ends={})


def test_prompt_contains_the_table_reference():
    p = system_prompt()
    assert "service_requests_311" in p and "13-196-410" in p and "PERMIT – EXPRESS" in p


ENDS = {"service_requests_311": dt.date(2026, 11, 18), "building_permits": dt.date(2026, 11, 17)}


def test_coverage_note_when_range_runs_past_the_data():
    sql = "SELECT COUNT(*) FROM service_requests_311 WHERE created_date >= '2026-11-16' AND created_date < '2026-11-23'"
    assert "ends on 2026-11-18" in coverage_notes(sql, ENDS)[0]
    full_2025 = "SELECT COUNT(*) FROM service_requests_311 WHERE created_date >= '2025-01-01' AND created_date < '2026-01-01'"
    assert coverage_notes(full_2025, ENDS) == []
    # a half-open end the day after the last data day is fully covered
    edge = "SELECT COUNT(*) FROM service_requests_311 WHERE created_date < '2026-11-19'"
    assert coverage_notes(edge, ENDS) == []


def test_coverage_note_before_the_start():
    sql = "SELECT COUNT(*) FROM building_permits WHERE issue_date >= '2024-06-01'"
    assert "starts on 2025-01-01" in coverage_notes(sql, ENDS)[0]


def test_coverage_notes_reach_the_result():
    llm = fake_llm(plan("SELECT count(*) FROM service_requests_311 WHERE NOT duplicate AND created_date >= '2026-11-16'"))
    db = fake_db((["count"], [[6889]], False))
    r = query_tables("last week?", TODAY, generate=llm, run=db, data_ends=ENDS)
    assert r.data_notes == []  # no end date in the SQL: nothing to flag
    llm = fake_llm(plan("SELECT count(*) FROM service_requests_311 WHERE NOT duplicate AND created_date >= '2026-11-16' AND created_date < '2026-11-23'"))
    db = fake_db((["count"], [[6889]], True))
    r = query_tables("last week?", TODAY, generate=llm, run=db, data_ends=ENDS)
    assert "ends on 2026-11-18" in r.data_notes[0] and "first 500 rows" in r.data_notes[1]


def test_review_problem_gets_one_fix_then_runs():
    drop = "SELECT count(*) FROM service_requests_311 WHERE NOT duplicate AND NOT origin IN ('Generated In House', 'Mass Entry')"
    keep = "SELECT count(*) FROM service_requests_311 WHERE NOT duplicate"
    llm = fake_llm(plan(drop), plan(keep))
    db = fake_db((["count"], [[5443]], False))
    r = query_tables("How many graffiti removal requests in 2025?", TODAY, generate=llm, run=db, data_ends={})
    assert r.ok and r.rows == [[5443]] and len(db.ran) == 1 and "keep city-generated" in llm.prompts[1]
    assert r.attempts[0].error.startswith("review:")


def test_review_never_blocks_the_last_attempt():
    drop = "SELECT count(*) FROM service_requests_311 WHERE NOT duplicate AND NOT origin IN ('Generated In House', 'Mass Entry')"
    llm = fake_llm(plan(drop), plan(drop))  # the model insists
    db = fake_db((["count"], [[4203]], False))
    r = query_tables("How many graffiti removal requests in 2025?", TODAY, generate=llm, run=db, data_ends={})
    assert r.ok and r.rows == [[4203]] and len(r.attempts) == 2
