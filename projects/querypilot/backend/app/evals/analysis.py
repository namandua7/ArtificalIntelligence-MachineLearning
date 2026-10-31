"""Pure functions over eval results: breakdowns, run-vs-run comparison and the regression gate."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Protocol


class ResultLike(Protocol):
    question: str
    passed: bool
    difficulty: str | None
    category: str | None
    failure_type: str | None
    steps: int
    duration_ms: int
    predicted_sql: str | None


DIFFICULTY_ORDER = ["easy", "medium", "hard"]


def _bucket(items: list[ResultLike], key) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[ResultLike]] = defaultdict(list)
    for r in items:
        value = key(r)
        if value:
            groups[value].append(r)
    return {
        k: {"total": len(v), "passed": sum(r.passed for r in v), "accuracy": round(sum(r.passed for r in v) / len(v), 4)}
        for k, v in groups.items()
    }


def breakdown(results: list[ResultLike]) -> dict[str, Any]:
    """Accuracy by difficulty and category, failure counts by type, plus cost metrics."""
    by_difficulty = _bucket(results, lambda r: r.difficulty)
    ordered = {k: by_difficulty[k] for k in DIFFICULTY_ORDER if k in by_difficulty}
    ordered.update({k: v for k, v in by_difficulty.items() if k not in ordered})
    failures: dict[str, int] = defaultdict(int)
    for r in results:
        if not r.passed:
            failures[r.failure_type or "unknown"] += 1
    n = len(results) or 1
    return {
        "byDifficulty": ordered,
        "byCategory": dict(sorted(_bucket(results, lambda r: r.category).items())),
        "failures": dict(sorted(failures.items(), key=lambda kv: -kv[1])),
        "avgSteps": round(sum(r.steps for r in results) / n, 2),
        "avgDurationMs": int(sum(r.duration_ms for r in results) / n),
    }


@dataclass
class Comparison:
    items: list[dict[str, Any]]
    summary: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {"items": self.items, "summary": self.summary}


def compare(a: list[ResultLike], b: list[ResultLike]) -> Comparison:
    """Question-by-question diff of run A (baseline) vs run B (candidate), matched by question text."""
    a_by_q = {r.question: r for r in a}
    b_by_q = {r.question: r for r in b}
    items: list[dict[str, Any]] = []
    summary = {"fixed": 0, "regressed": 0, "bothPass": 0, "bothFail": 0, "onlyA": 0, "onlyB": 0}
    for question in [*a_by_q, *[q for q in b_by_q if q not in a_by_q]]:
        ra, rb = a_by_q.get(question), b_by_q.get(question)
        if ra is None or rb is None:
            change = "onlyB" if ra is None else "onlyA"
        elif ra.passed and rb.passed:
            change = "bothPass"
        elif not ra.passed and not rb.passed:
            change = "bothFail"
        else:
            change = "fixed" if rb.passed else "regressed"
        summary[change] += 1
        ref = rb or ra
        items.append(
            {
                "question": question,
                "difficulty": ref.difficulty,
                "category": ref.category,
                "change": change,
                "a": None if ra is None else {"passed": ra.passed, "sql": ra.predicted_sql, "failureType": ra.failure_type},
                "b": None if rb is None else {"passed": rb.passed, "sql": rb.predicted_sql, "failureType": rb.failure_type},
            }
        )
    order = {"regressed": 0, "fixed": 1, "bothFail": 2, "onlyA": 3, "onlyB": 3, "bothPass": 4}
    items.sort(key=lambda i: order[i["change"]])
    return Comparison(items, summary)


def gate(
    accuracy: float,
    *,
    min_accuracy: float | None = None,
    baseline_accuracy: float | None = None,
    max_drop: float = 0.0,
    regressions: int = 0,
    allow_regressions: bool = True,
) -> list[str]:
    """Reasons the run should fail CI (empty = pass)."""
    reasons: list[str] = []
    if min_accuracy is not None and accuracy < min_accuracy:
        reasons.append(f"accuracy {accuracy:.1%} is below the required minimum {min_accuracy:.1%}")
    if baseline_accuracy is not None and accuracy < baseline_accuracy - max_drop:
        reasons.append(
            f"accuracy {accuracy:.1%} dropped more than {max_drop:.1%} below the baseline {baseline_accuracy:.1%}"
        )
    if not allow_regressions and regressions:
        reasons.append(f"{regressions} question(s) that passed in the baseline now fail")
    return reasons
