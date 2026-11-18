"""Run the eval set and compute every metric. (Day 9)

Metrics: router accuracy, SQL execution accuracy, recall@k, MRR,
faithfulness and answer correctness (LLM judge), citation accuracy,
correct refusal rate, latency p50/p95, cost per query.

Usage (later): python -m evals.run_evals [--subset 10]
"""

import json
from pathlib import Path

QUESTIONS = Path(__file__).parent / "questions.jsonl"


def load_questions(path: Path = QUESTIONS) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


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
