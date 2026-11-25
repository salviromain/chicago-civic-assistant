"""Try 10 questions on document search and compare the four modes.

Usage:
    python -m scripts.try_search            # summary table + each question's top 5
    python -m scripts.try_search --quiet    # summary table only

Modes: vector only, BM25 only, hybrid (RRF), hybrid + reranker.
A code chunk counts as a hit at section level (5-12-110#3 matches 5-12-110).
The expected budget chunks were chosen by searching the chunk text for the
figures before running any search, not by looking at search results.
"""

from __future__ import annotations

import argparse
import statistics
import time

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

from app import retrieval  # noqa: E402
from evals.run_evals import recall_at_k, reciprocal_rank  # noqa: E402

QUESTIONS = [
    ("What minimum temperature must my landlord keep my apartment at during the day?", ["14X-8-802.2.2"]),
    ("Which code section sets the minimum heat landlords must provide?", ["14X-8-802.2.2"]),
    ("Can my landlord make me pay for the gas that heats my apartment?", ["14X-8-802.2.1", "5-16-010"]),
    ("What can I do if my landlord doesn't fix the heat?", ["5-12-110"]),
    ("How much interest does my landlord owe on my security deposit?", ["5-12-080", "5-12-081"]),
    ("When does a building have to run its air conditioning?", ["14X-8-803.6"]),
    ("What does section 5-12-150 say?", ["5-12-150"]),
    ("How much does the 2027 budget propose for the Chicago Public Library?",
     ["budget-2027-p150-1", "budget-2027-p138-1"]),
    ("What is the total proposed 2027 budget across all funds?",
     ["budget-2027-p039-1", "budget-2027-p041-1"]),
    ("How much will transaction taxes bring in in 2027?", ["budget-2027-p043-1", "budget-2027-p043-2"]),
]

MODES = [
    ("vector", dict(mode="vector", rerank=False)),
    ("BM25", dict(mode="keyword", rerank=False)),
    ("hybrid", dict(mode="hybrid", rerank=False)),
    ("hybrid+rerank", dict(mode="hybrid", rerank=True)),
]


def base_id(chunk_id: str) -> str:
    """5-12-110#3 -> 5-12-110 (parts of one section count as that section)."""
    return chunk_id.split("#")[0]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    retrieval.rerank_scores("warm up", ["load the model before timing"])
    stats = {name: {"hits": [], "rr": [], "secs": []} for name, _ in MODES}
    for n, (question, expected) in enumerate(QUESTIONS, start=1):
        if not args.quiet:
            print(f"\nQ{n}. {question}\n    expected: {', '.join(expected)}")
        for name, kwargs in MODES:
            t = time.perf_counter()
            results = retrieval.search(question, top_k=5, **kwargs)
            stats[name]["secs"].append(time.perf_counter() - t)
            got = [base_id(r["id"]) for r in results]
            stats[name]["hits"].append(recall_at_k(got, expected, k=5))
            stats[name]["rr"].append(reciprocal_rank(got, expected))
            if not args.quiet:
                marked = ", ".join(f"{r['id']}{' ✓' if base_id(r['id']) in expected else ''}" for r in results)
                print(f"    {name:<14} {marked}")

    print(f"\n{'mode':<15}{'hits@5':>8}{'MRR':>7}{'median s':>10}")
    for name, _ in MODES:
        s = stats[name]
        print(f"{name:<15}{sum(s['hits']):>5.0f}/{len(QUESTIONS)}{statistics.mean(s['rr']):>7.2f}"
              f"{statistics.median(s['secs']):>10.2f}")


if __name__ == "__main__":
    main()
