from dataclasses import dataclass

from app.evals.analysis import breakdown, compare, gate
from app.services.compare import results_equivalent, results_match
from app.services.target import QueryResult


@dataclass
class R:
    question: str
    passed: bool
    difficulty: str | None = "easy"
    category: str | None = "agg"
    failure_type: str | None = None
    steps: int = 2
    duration_ms: int = 1000
    predicted_sql: str | None = "SELECT 1"


def test_breakdown_orders_difficulty_and_counts_failures():
    rs = [R("a", True), R("b", False, failure_type="wrong_result"), R("c", False, "hard", "join", "sql_error"),
          R("d", True, "medium", "join")]
    out = breakdown(rs)
    assert list(out["byDifficulty"]) == ["easy", "medium", "hard"]
    assert out["byDifficulty"]["easy"] == {"total": 2, "passed": 1, "accuracy": 0.5}
    assert out["byCategory"]["join"]["total"] == 2
    assert out["failures"] == {"wrong_result": 1, "sql_error": 1}
    assert out["avgSteps"] == 2 and out["avgDurationMs"] == 1000


def test_compare_classifies_changes_and_sorts_regressions_first():
    a = [R("q1", True), R("q2", False), R("q3", True), R("q4", False), R("only-a", True)]
    b = [R("q1", False), R("q2", True), R("q3", True), R("q4", False), R("only-b", True)]
    out = compare(a, b)
    assert out.summary == {"fixed": 1, "regressed": 1, "bothPass": 1, "bothFail": 1, "onlyA": 1, "onlyB": 1}
    assert out.items[0]["question"] == "q1" and out.items[0]["change"] == "regressed"
    assert out.items[1]["change"] == "fixed"


def test_gate_reasons():
    assert gate(0.8, min_accuracy=0.7) == []
    assert "below the required minimum" in gate(0.6, min_accuracy=0.7)[0]
    assert gate(0.78, baseline_accuracy=0.8, max_drop=0.05) == []
    assert "dropped more than" in gate(0.7, baseline_accuracy=0.8, max_drop=0.05)[0]
    assert gate(0.9, regressions=2, allow_regressions=False)
    assert gate(0.9, regressions=2, allow_regressions=True) == []


def qr(cols, rows):
    return QueryResult(sql="x", columns=cols, rows=rows, row_count=len(rows))


def test_results_match_ignores_names_order_and_extra_columns():
    gold = qr(["n"], [[3], [5]])
    assert results_match(gold, qr(["a", "b"], [["x", 5], ["y", 3]]))
    assert not results_match(gold, qr(["a"], [[3], [6]]))
    assert not results_match(gold, qr(["a"], [[3]]))
    assert results_match(qr(["v"], [["Sci-Fi "]]), qr(["w"], [["sci-fi"]]))
    assert results_match(qr(["v"], [[1.004]]), qr(["w"], [["1.0"]]))


def test_results_equivalent_is_symmetric():
    narrow, wide = qr(["a"], [[1], [2]]), qr(["x", "y"], [["n", 2], ["m", 1]])
    assert results_equivalent(narrow, wide) and results_equivalent(wide, narrow)
