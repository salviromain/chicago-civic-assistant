"""Run the eval set and compute every metric. (Day 9)

Metrics: router accuracy, SQL execution accuracy, recall@k, MRR,
faithfulness and answer correctness (LLM judge), citation accuracy,
correct refusal rate, latency p50/p95, cost per query.

Usage (later): python -m evals.run_evals [--subset 10]
"""

import json
import re
from pathlib import Path

QUESTIONS = Path(__file__).parent / "questions.jsonl"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> set[str]:
    """Every number written in the text, without thousands commas: "$2,243,691,824" -> "2243691824"."""
    return {m.replace(",", "").rstrip(".") for m in _NUMBER.findall(text)}


def contains(answer: str, expected: str) -> bool:
    """Does the answer contain `expected`? A plain number ("3", "5,443", "36.7") must
    appear as a whole number, so "3" doesn't match "2,032" or "13". Anything else
    ("March", "2.24 billion", "14X-8-802.2.2") is a case-insensitive substring match."""
    if re.fullmatch(r"\d[\d,]*(?:\.\d+)?", expected):
        return expected.replace(",", "") in _numbers(answer)
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


if __name__ == "__main__":
    qs = load_questions()
    print(f"Loaded {len(qs)} questions. Metrics come on Day 9.")
