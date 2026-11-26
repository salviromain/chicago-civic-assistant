"""Try the SQL agent on questions with known answers, against the real database.

    .venv/bin/python -m scripts.try_sql            # every question, with SQL
    .venv/bin/python -m scripts.try_sql --quiet    # summary only
    .venv/bin/python -m scripts.try_sql --model gemini-3.5-flash

Expected answers were computed by hand with SQL as civic_reader *before* the
agent was run (docs/BUILD_LOG.md, Day 5), so they aren't taken from its output.
LLM replies are cached: a second run makes no API calls.
"""

from __future__ import annotations

import argparse
import datetime as dt
import statistics

from dotenv import find_dotenv, load_dotenv

TODAY = dt.date(2026, 11, 25)  # fixed, so "last winter" means the same thing on every run


def first(r):
    return r.rows[0][0] if r.rows and r.rows[0] else None


def column(r, n=None):
    return [row[0] for row in r.rows[:n]]


def close(value, target, tol=0.05):
    return isinstance(value, (int, float)) and abs(value - target) <= tol


# (question, check on the result or "refuse", what we expect, in words)
QUESTIONS = [
    ("How many pothole complaints were there in ward 25 in 2026?",
     lambda r: first(r) == 721, "721 (duplicates excluded)"),
    ("In which 5 wards do residents report the most graffiti?",
     lambda r: column(r, 5) == [12, 1, 25, 14, 32], "wards 12, 1, 25, 14, 32 (residents only)"),
    ("Which wards got the most new construction permits in 2026?",
     lambda r: set(column(r, 2)) == {42, 27}, "wards 42 and 27, 120 each"),
    ("What is the median processing time for permits that go through standard plan review?",
     lambda r: any(close(v, 83, 0.5) for row in r.rows for v in row if isinstance(v, (int, float))),
     "83 days"),
    ("How many express permits were issued in 2025?",
     lambda r: first(r) == 20427, "20,427 (en dash in the type)"),
    ("How many heat violations were recorded between November 2025 and February 2026?",
     lambda r: first(r) == 339, "339 (ordinance 13-196-410)"),
    ("How many rat complaints are still open?",
     lambda r: first(r) == 960, "960 (duplicates excluded)"),
    ("How many tree-related 311 requests were made in 2025?",
     lambda r: first(r) == 123441, "123,441 (5 tree types; ILIKE '%tree%' also matches 'Street')"),
    ("What was the median number of days to close graffiti requests in 2026?",
     lambda r: close(first(r), 0.5, 0.06), "0.5 days (completed, duplicates excluded)"),
    ("How many duplicate pothole reports were there in 2025?",
     lambda r: first(r) == 16418, "16,418 (duplicates only)"),
    ("How many building violations were recorded in ward 25 in 2026?", "refuse", "no ward column"),
    ("How many aircraft noise complaints were there in 2026?", "refuse", "not loaded"),
    ("How many potholes were reported in 2023?", "refuse", "data starts 2025-01-01"),
    ("How many no-heat complaints were filed in Ward 25 between November 2025 and February 2026, "
     "excluding duplicates?", "refuse", "no 311 heat type; violations have no ward (eval q001)"),
    ("How many 311 complaints will Ward 25 get next winter?", "refuse", "a forecast (eval q003)"),
    ("What minimum temperature does the city code require landlords to keep?", "refuse",
     "law, not tables"),
]


def main() -> None:
    load_dotenv(find_dotenv(usecwd=True))
    p = argparse.ArgumentParser()
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--model")
    args = p.parse_args()

    from app.sql_agent import query_tables

    passed, api_calls, tokens, latencies, repairs = 0, 0, [], [], 0
    for i, (q, check, expected) in enumerate(QUESTIONS, 1):
        r = query_tables(q, TODAY, model=args.model)
        if check == "refuse":
            ok = not r.answerable
        else:
            ok = r.ok and check(r)
        passed += ok
        api_calls += r.llm_calls
        tokens.append(r.input_tokens + r.output_tokens)
        repairs += len(r.attempts) > 1
        if r.llm_calls:  # only time real calls; cached runs are ~instant
            latencies.append(r.latency_ms)
        print(f"{'PASS' if ok else 'FAIL'} {i:>2}. {q}")
        if not args.quiet or not ok:
            print(f"        expected: {expected}")
            if not r.answerable:
                print(f"        refused:  {r.refusal_reason}")
            else:
                for a in r.attempts:
                    print(f"        sql:      {a.sql}")
                    if a.error:
                        print(f"        error:    {a.error}")
                print(f"        rows:     {r.rows[:5]}{' …' if len(r.rows) > 5 else ''}")
            if r.notes:
                print(f"        notes:    {r.notes}")

    print(f"\n{passed}/{len(QUESTIONS)} correct · {repairs} needed a repair · {api_calls} API calls · "
          f"median {statistics.median(tokens):,.0f} tokens per question", end="")
    if latencies:
        print(f" · median {statistics.median(latencies) / 1000:.1f} s per question (uncached)")
    else:
        print(" · all replies cached")


if __name__ == "__main__":
    main()
