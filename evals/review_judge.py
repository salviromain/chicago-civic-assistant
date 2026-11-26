"""Hand-check the LLM judge: does a person agree with its verdicts?

    .venv/bin/python -m evals.review_judge --label baseline            # write the review sheet
    .venv/bin/python -m evals.review_judge --label baseline --score    # agreement, from evals/judge_checks.json

The sheet (evals/results/<label>-judge-review.md) shows 20 verdicts: every one the
judge called unfaithful, incorrect or partial (where mistakes matter most), then
the rest spread evenly. Each comes with the question, reference answer, the sources
the system saw, the system's answer, and the judge's verdict.

--canary plants a made-up claim in three real answers and checks the judge flags
each one: a judge that calls everything faithful would otherwise look perfect.

A person records their own verdicts in evals/judge_checks.json:
    {"<label>": {"q005": {"faithful": true, "correctness": "incorrect", "note": "..."}, ...}}
--score compares them with the judge's.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.run_evals import RESULTS, load_questions

CHECKS = Path(__file__).parent / "judge_checks.json"
N = 20


def pick(recs: list[dict], n: int = N) -> list[dict]:
    judged = [r for r in recs if "judge" in r]
    flagged = [r for r in judged if not r["judge"]["faithful"] or r["judge"]["correctness"] != "correct"]
    rest = [r for r in judged if r not in flagged]
    need = max(n - len(flagged), 0)
    step = max(len(rest) // need, 1) if need else 1
    return (flagged + rest[::step][:need])[:n]


def sheet(label: str) -> Path:
    from app.answer import run
    import datetime as dt
    recs = [json.loads(l) for l in (RESULTS / f"{label}.jsonl").open() if '"judge"' in l]
    qs = {q["id"]: q for q in load_questions()}
    out = [f"# Judge review: {label}\n", "For each: do you agree with `faithful` and `correctness`? Record yours in `evals/judge_checks.json`.\n"]
    for r in pick(recs):
        q = qs[r["id"]]
        trace = run(q["question"], dt.date.fromisoformat(q["as_of"]))  # cached: rebuilds the sources text
        j = r["judge"]
        out += [f"\n---\n\n## {r['id']} ({q['route']}{'' if q['answerable'] else ', unanswerable'})\n",
                f"**Question:** {q['question']}\n", f"**Reference:** {q['reference_answer']}\n",
                f"**Answer:** {trace.draft.answer if trace.draft else r['answer']}\n",
                f"**Judge:** faithful={j['faithful']}, correctness={j['correctness']}. {j['reason']}"
                + (f" Unsupported: {j['unsupported_claims']}" if j["unsupported_claims"] else "") + "\n",
                "<details><summary>Sources</summary>\n\n```\n" + (trace.sources_text or "(none)")[:6000] + "\n```\n</details>\n"]
    path = RESULTS / f"{label}-judge-review.md"
    path.write_text("\n".join(out))
    return path


def score(label: str) -> dict:
    human = json.loads(CHECKS.read_text())[label]
    recs = {r["id"]: r for r in map(json.loads, (RESULTS / f"{label}.jsonl").open()) if "judge" in r}
    rows = [(recs[i]["judge"], h) for i, h in human.items() if i in recs]
    faith = sum(j["faithful"] == h["faithful"] for j, h in rows)
    corr = sum(j["correctness"] == h["correctness"] for j, h in rows)
    disagreements = [i for i, h in human.items() if i in recs and
                     (recs[i]["judge"]["faithful"] != h["faithful"] or recs[i]["judge"]["correctness"] != h["correctness"])]
    return {"checked": len(rows), "faithfulness_agreement": faith / len(rows),
            "correctness_agreement": corr / len(rows), "disagreements": disagreements}


CANARIES = {  # question id -> an answer with one claim the sources don't support
    "q038": ("Your landlord must give at least two days' notice before entering [D1], "
             "and must also pay you $50 for each entry [D1].", "$50"),
    "q063": ("The proposed 2027 budget for the Chicago Fire Department is $914,383,396 [D1], "
             "which adds 300 new firefighters [D1].", "300"),
    "q016": ("There were 43059 tree emergency requests in 2026 [T1], most of them in ward 41 "
             "after the July storms [T1].", "ward 41"),
}


def canary() -> dict:
    import datetime as dt
    from types import SimpleNamespace

    from app.answer import run
    from evals.run_evals import judge
    qs = {q["id"]: q for q in load_questions()}
    caught = {}
    for qid, (fake, planted) in CANARIES.items():
        q = qs[qid]
        trace = run(q["question"], dt.date.fromisoformat(q["as_of"]))  # cached: the real sources
        trace.draft = SimpleNamespace(answer=fake)
        verdict, _ = judge(q, trace)
        caught[qid] = (not verdict.faithful) and any(planted in c for c in verdict.unsupported_claims)
    return {"planted": len(CANARIES), "caught": sum(caught.values()), "by_question": caught}


def main() -> None:
    from dotenv import find_dotenv, load_dotenv
    load_dotenv(find_dotenv(usecwd=True))
    p = argparse.ArgumentParser()
    p.add_argument("--label", default="baseline")
    p.add_argument("--score", action="store_true")
    p.add_argument("--canary", action="store_true")
    args = p.parse_args()
    if args.canary:
        print(json.dumps(canary(), indent=2))
    elif args.score:
        print(json.dumps(score(args.label), indent=2))
    else:
        print(f"wrote {sheet(args.label)}")


if __name__ == "__main__":
    main()
