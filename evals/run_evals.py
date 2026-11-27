"""Run the eval set and compute every metric. (Day 9)

    .venv/bin/python -m evals.run_evals --label baseline            # all 87 questions + judge
    .venv/bin/python -m evals.run_evals --subset 10 --no-judge      # quick, no judge calls
    .venv/bin/python -m evals.run_evals --ids q005,q038 --label try

Writes evals/results/<label>.jsonl (one line per question, every detail; not
committed) and evals/results/<label>-summary.json (the metrics; committed).
LLM replies are cached, so a re-run (or a run stopped by the daily quota and
started again) only pays for what's new.

Metrics
    router accuracy      route == expected route                       (all questions)
    SQL execution        the agent's first result row holds the reference values (sql, both)
    recall@5, MRR        expected chunks among the 5 retrieved          (docs, both)
    answer checks        the answer contains the expected strings       (answerable)
    correct refusals     refused when unanswerable; false refusals when answerable
    citation accuracy    an expected source is cited                    (answered, answerable)
    faithfulness         judge: every claim is supported by the sources (answered)
    correctness (judge)  judge: answer agrees with the reference answer (answerable)
    latency p50/p95      only questions that made real API calls in this run
    tokens, cost         per question, at the configured prices
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

QUESTIONS = Path(__file__).parent / "questions.jsonl"
RESULTS = Path(__file__).parent / "results"
JUDGE_MODEL = "gemini-3.5-flash-lite"  # a different (newer) model than the one answering; 3.5-flash has too small a daily free quota


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Deterministic metrics

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[float]:
    """Every number written in the text, as a value: "$2,243,691,824" -> 2243691824.0,
    "$10.00" -> 10.0."""
    return {float(m.replace(",", "").rstrip(".")) for m in _NUMBER.findall(text)}


def contains(answer: str, expected: str) -> bool:
    """Does the answer contain `expected`? A plain number ("3", "5,443", "36.7") must
    appear as a whole number with the same value, so "3" doesn't match "2,032" or "13",
    and "10" matches "$10.00". Anything else ("March", "2.24 billion", "14X-8-802.2.2")
    is a case-insensitive substring match."""
    if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", expected):
        return float(expected.replace(",", "")) in _numbers(answer)
    return expected.lower() in answer.lower()


def must_contain_ok(answer: str, groups: list[list[str]]) -> bool:
    """True if the answer contains at least one string from every group."""
    return all(any(contains(answer, s) for s in group) for group in groups)


def recall_at_k(retrieved: list[str], relevant: list[str], k: int = 5) -> float:
    if not relevant:
        return 0.0
    return float(any(chunk in relevant for chunk in retrieved[:k]))


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    for position, chunk in enumerate(retrieved, start=1):
        if chunk in relevant:
            return 1.0 / position
    return 0.0


def _norm_value(v):
    """Values compared loosely: numbers to 1 decimal, text case-insensitive."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 1)
    return str(v).strip().lower()


def sql_matches(agent_rows: list[list], reference_rows: list[list], tie: bool = False) -> bool:
    """Execution match on the answer's key value: the first value of the reference's
    first row (the count, the share, the top ward) must appear in the agent's first
    row. Later reference columns are context (e.g. how many permits report a cost).
    A share may come back as a fraction or a percentage (0.367 = 36.7). For a tie, any
    of the tied reference rows will do."""
    if not agent_rows or not reference_rows:
        return False
    got = set()
    for v in agent_rows[0]:
        got.add(_norm_value(v))
        if isinstance(v, float) and 0 < v < 1:
            got.add(_norm_value(v * 100))
    candidates = [r for r in reference_rows if r[1:] == reference_rows[0][1:]] if tie else reference_rows[:1]
    return any(_norm_value(ref[0]) in got for ref in candidates)


def citation_ok(q: dict, cited: list[str]) -> bool:
    """An expected source is cited: the table result for sql, an expected chunk for docs,
    both for both."""
    need_sql = q["route"] in ("sql", "both")
    need_doc = q["route"] in ("docs", "both")
    return ((not need_sql or "T1" in cited) and
            (not need_doc or any(c in q["source_chunks"] for c in cited)))


# ---------------------------------------------------------------------------
# LLM judge


class Verdict(BaseModel):
    unsupported_claims: list[str] = Field(default_factory=list, description=(
        "Claims in the answer that the sources don't support. Empty if all are supported."))
    faithful: bool = Field(description="True if every claim in the answer is supported by the sources.")
    correctness: str = Field(description="correct, partial or incorrect, compared with the reference answer.")
    reason: str = Field(description="One sentence explaining the correctness verdict.")


JUDGE_SYSTEM = """You grade answers from a question-answering system about Chicago.

You get the question, the sources the system was given, the system's answer, and a
reference answer written by a person.

1. Faithfulness: list every claim in the answer that the SOURCES don't support (numbers,
   dates, section numbers, requirements). Rounding ("$2.24 billion" for 2,243,691,824) and
   plain-language paraphrase are supported. Saying something is missing from the sources
   is not a claim. faithful = no unsupported claims.
2. Correctness, against the REFERENCE ANSWER (not the sources: the sources may be wrong):
   - "correct": the key facts match (the number, section, date or requirement asked for).
     Rounding is fine; extra correct detail is fine.
   - "partial": the question has several parts and some are right, others missing or wrong.
   - "incorrect": the key fact asked for is wrong (e.g. a different count than the
     reference, even if it comes from the sources), or it refuses although the reference
     answers. For an unanswerable question (the reference says it can't be answered), a
     refusal is "correct" and an answer with a number is "incorrect".
   Don't judge style.
"""


def judge(q: dict, trace, model: str = JUDGE_MODEL, generate=None) -> tuple[Verdict, object]:
    from app.llm import generate as default_generate
    generate = generate or default_generate
    prompt = (f"Question: {q['question']}\n\nReference answer: {q['reference_answer']}\n\n"
              f"Sources given to the system:\n{trace.sources_text or '(none)'}\n\n"
              f"System's answer: {trace.draft.answer if trace.draft else trace.response.answer}")
    reply = generate(prompt, system=JUDGE_SYSTEM, schema=Verdict, model=model)
    return reply.parsed, reply


# ---------------------------------------------------------------------------


def score_one(q: dict, trace, verdict: Verdict | None) -> dict:
    r = trace.response
    sql = trace.sql
    rec = {
        "id": q["id"], "question": q["question"], "tags": q["tags"],
        "route_expected": q["route"], "route": r.route.value, "route_ok": r.route.value == q["route"],
        "answerable": q["answerable"], "refused": r.refused,
        "answer": r.answer, "citations": [c.source for c in r.citations], "cited": trace.cited,
        "latency_ms": r.latency_ms, "llm_calls": trace.llm_calls,
        "tokens": trace.input_tokens + trace.output_tokens, "cost_usd": r.cost_usd,
        "timings_ms": trace.timings_ms,
    }
    if q["answerable"]:
        # The citations are part of what the user sees ("[2] Section 5-12-110"), so they count
        shown = r.answer + "\n" + "\n".join(c.source for c in r.citations)
        rec["checks_ok"] = (not r.refused) and must_contain_ok(shown, q["answer_must_contain"])
        rec["citation_ok"] = (not r.refused) and citation_ok(q, trace.cited)
    else:
        rec["refusal_ok"] = r.refused
    if q["reference_sql"]:
        rec["agent_sql"] = sql.sql if sql else None
        rec["agent_rows"] = (sql.rows[:5] if sql else None)
        rec["sql_ok"] = bool(sql and sql.ok and sql_matches(sql.rows, q["reference_result"]["rows"],
                                                             tie="tie" in q["tags"]))
    if q["source_chunks"]:
        rec["retrieved"] = trace.chunk_ids
        rec["recall@5"] = recall_at_k(trace.chunk_ids, q["source_chunks"])
        rec["rr"] = reciprocal_rank(trace.chunk_ids, q["source_chunks"])
    if verdict:
        rec["judge"] = verdict.model_dump()
    return rec


def _rate(recs: list[dict], key: str) -> tuple[float, int] | None:
    vals = [r[key] for r in recs if key in r]
    return (sum(vals) / len(vals), len(vals)) if vals else None


def summarize(recs: list[dict]) -> dict:
    s: dict = {"questions": len(recs)}
    s["router_accuracy"] = _rate(recs, "route_ok")
    s["sql_execution"] = _rate(recs, "sql_ok")
    s["recall@5"] = _rate(recs, "recall@5")
    s["mrr"] = _rate(recs, "rr")
    s["answer_checks"] = _rate(recs, "checks_ok")
    s["correct_refusals"] = _rate(recs, "refusal_ok")
    answerable = [r for r in recs if r["answerable"]]
    s["false_refusals"] = ((sum(r["refused"] for r in answerable) / len(answerable), len(answerable))
                           if answerable else None)
    s["citation_accuracy"] = _rate([r for r in recs if not r["refused"]], "citation_ok")
    judged = [r for r in recs if "judge" in r]
    answered = [r for r in judged if not r["refused"]]
    if answered:
        s["faithfulness"] = (sum(r["judge"]["faithful"] for r in answered) / len(answered), len(answered))
    graded = [r for r in judged if r["answerable"]]
    if graded:
        s["correctness_judge"] = (sum(r["judge"]["correctness"] == "correct" for r in graded) / len(graded), len(graded))
        s["correct_or_partial_judge"] = (sum(r["judge"]["correctness"] in ("correct", "partial") for r in graded) / len(graded), len(graded))
    live = [r for r in recs if r["llm_calls"]]
    if live:
        def pct(vals, p):
            vals = sorted(vals)
            return round(vals[min(len(vals) - 1, int(p * len(vals)))] / 1000, 2)
        total = [r["latency_ms"] for r in live]
        # An eval run sends questions back to back, so the per-minute pacer makes later
        # ones wait; one user asking one question never waits. Report both.
        own = [r["latency_ms"] - r.get("timings_ms", {}).get("waited", 0) for r in live]
        s["latency_p50_s"], s["latency_p95_s"] = pct(total, 0.5), pct(total, 0.95)
        s["latency_p50_s_no_pacing"], s["latency_p95_s_no_pacing"] = pct(own, 0.5), pct(own, 0.95)
        s["latency_measured_on"] = len(live)
    s["tokens_per_question"] = round(statistics.mean(r["tokens"] for r in recs))
    s["cost_per_question_usd"] = round(statistics.mean((r["cost_usd"] or 0) for r in recs), 6)
    return s


def fmt(summary: dict) -> str:
    rows = []
    for key, val in summary.items():
        if isinstance(val, (tuple, list)) and len(val) == 2:
            rows.append(f"  {key:26} {val[0]:6.1%}  (n={val[1]})" if key != "mrr" else f"  {key:26} {val[0]:6.2f}  (n={val[1]})")
        elif val is not None:
            rows.append(f"  {key:26} {val}")
    return "\n".join(rows)


def main() -> None:
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    p = argparse.ArgumentParser()
    p.add_argument("--label", default="run")
    p.add_argument("--questions", default=str(QUESTIONS), help="question file (evals/questions_holdout.jsonl for the final score)")
    p.add_argument("--subset", type=int, help="only the first N questions")
    p.add_argument("--ids", help="comma-separated question ids")
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--judge-model", default=JUDGE_MODEL)
    p.add_argument("--model", help="answer model for the whole pipeline (default: llm_model)")
    p.add_argument("--search-mode", choices=["vector", "keyword", "hybrid"])
    p.add_argument("--sql-thinking", help="thinking level for the SQL agent: minimal, low, medium, high")
    p.add_argument("--fail-under", type=float, help=(
        "exit with an error if answer checks or correct refusals fall below this share, "
        "or any question errored or wasn't run (CI uses 0.8)"))
    p.add_argument("--retry-wait", type=int, default=30, help=(
        "seconds to wait before retrying errored questions once (-1: don't retry)"))
    p.add_argument("--timing-from", help=(
        "results .jsonl of an earlier live run: re-scoring from the cache takes ~0 s per "
        "question, so take each question's timings from that run instead"))
    args = p.parse_args()
    # Experiments override settings through the environment, before anything reads them
    import os

    from app.config import get_settings
    for flag, env in (("model", "LLM_MODEL"), ("search_mode", "SEARCH_MODE"), ("sql_thinking", "SQL_THINKING_LEVEL")):
        if getattr(args, flag):
            os.environ[env] = getattr(args, flag)
    get_settings.cache_clear()
    timing = {}
    if args.timing_from:
        for line in Path(args.timing_from).open():
            old = json.loads(line)
            if old.get("llm_calls"):
                timing[old["id"]] = {k: old[k] for k in ("latency_ms", "llm_calls", "timings_ms") if k in old}

    from app.answer import run
    from app.llm import QuotaExhausted

    qs = load_questions(Path(args.questions))
    if args.ids:
        wanted = set(args.ids.split(","))
        qs = [q for q in qs if q["id"] in wanted]
    if args.subset:
        qs = qs[:args.subset]
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{args.label}.jsonl"
    results: dict[str, dict] = {}  # question id -> scored record, or {"id", "error"}
    start = time.perf_counter()
    stopped = False

    def one_pass(todo: list[dict], f) -> None:
        """Run each question; record a score or the error. Stops on the daily quota."""
        nonlocal stopped
        for i, q in enumerate(todo, 1):
            today = dt.date.fromisoformat(q["as_of"])
            try:
                trace = run(q["question"], today)
                verdict = None
                if not args.no_judge:
                    verdict, _ = judge(q, trace, model=args.judge_model)
            except QuotaExhausted as e:
                print(f"\nstopped at {q['id']}: {e}\nRun the same command later: cached answers are reused.")
                stopped = True
                return
            except Exception as e:  # noqa: BLE001 - record it and go on
                results[q["id"]] = {"id": q["id"], "error": f"{type(e).__name__}: {e}"}
                f.write(json.dumps(results[q["id"]]) + "\n")
                print(f"[{i}/{len(todo)}] {q['id']} ERROR {type(e).__name__}: {str(e)[:120]}")
                continue
            rec = score_one(q, trace, verdict)
            if q["id"] in timing and not rec["llm_calls"]:
                rec.update(timing[q["id"]], timing_from=args.timing_from)
            results[q["id"]] = rec
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            f.flush()
            marks = " ".join(k for k in ("route_ok", "sql_ok", "checks_ok", "refusal_ok", "citation_ok")
                             if k in rec and not rec[k])
            j = rec.get("judge", {})
            print(f"[{i}/{len(todo)}] {q['id']} {rec['route']:4} {rec['latency_ms'] / 1000:5.1f}s "
                  f"{'refused' if rec['refused'] else 'answered'}"
                  f"{' judge=' + j['correctness'] + ('' if j['faithful'] else ' UNFAITHFUL') if j else ''}"
                  f"{'  FAILED: ' + marks if marks else ''}", flush=True)

    with out.open("w") as f:  # written as it goes, so a crash keeps what's done
        one_pass(qs, f)
        # An error is usually the model service failing (a 504 from an overloaded free
        # tier), not the system: retry those questions once. A second failure counts.
        failed = [q for q in qs if "error" in results.get(q["id"], {})]
        if failed and not stopped and args.retry_wait >= 0:
            print(f"\nretrying {len(failed)} errored question(s) in {args.retry_wait} s", flush=True)
            time.sleep(args.retry_wait)
            one_pass(failed, f)
    # The final file: one line per question, in order, the retry replacing the error
    out.write_text("".join(json.dumps(results[q["id"]], ensure_ascii=False, default=str) + "\n"
                           for q in qs if q["id"] in results))
    recs = [r for r in results.values() if "error" not in r]
    errors = [i for i, r in results.items() if "error" in r]

    if not recs:
        if args.fail_under is not None:
            sys.exit("FAILED: no question was answered")
        return
    summary = {"label": args.label, "date": dt.date.today().isoformat(),
               "minutes": round((time.perf_counter() - start) / 60, 1), "errors": errors}
    s = get_settings()
    summary["model"] = s.llm_model
    summary["search_mode"], summary["sql_thinking_level"] = s.search_mode, s.sql_thinking_level
    summary["judge_model"] = None if args.no_judge else args.judge_model
    summary["all"] = summarize(recs)
    unseen = [r for r in recs if "seen-in-tuning" not in r["tags"]]
    if len(unseen) < len(recs):
        summary["without_seen_in_tuning"] = summarize(unseen)
    for kind in ("sql", "docs", "both"):
        sub = [r for r in recs if r["route_expected"] == kind and r["answerable"]]
        if sub:
            summary[f"route_{kind}"] = summarize(sub)
    (RESULTS / f"{args.label}-summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(f"\n{args.label}: {len(recs)} questions, {len(errors)} errors, {summary['minutes']} min\n{fmt(summary['all'])}")
    print(f"\nDetails: {out}\nSummary: {RESULTS / (args.label + '-summary.json')}")
    if args.fail_under is not None:
        problems = gate(summary["all"], len(qs), len(errors), args.fail_under)
        if problems:
            sys.exit("FAILED: " + "; ".join(problems))
        print(f"passed: every metric at or above {args.fail_under:.0%}")


def gate(metrics: dict, expected: int, errors: int, threshold: float) -> list[str]:
    """Why a CI eval run fails, or [] if it passes."""
    problems = []
    if metrics["questions"] + errors < expected:
        problems.append(f"only {metrics['questions'] + errors} of {expected} questions ran (quota?)")
    if errors:
        problems.append(f"{errors} questions errored")
    for name in ("answer_checks", "correct_refusals"):
        if metrics.get(name) and metrics[name][0] < threshold:
            problems.append(f"{name} {metrics[name][0]:.0%} < {threshold:.0%}")
    return problems


if __name__ == "__main__":
    main()
