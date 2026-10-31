"""Compare two query results by value, ignoring column names/order, row order and extra columns.

Shared by the evals (prediction vs gold SQL) and self-consistency (candidate vs candidate).
"""

from collections import Counter
from typing import Any

from app.services.target import QueryResult


def norm(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return round(float(stripped), 2)
        except ValueError:
            return stripped.lower()
    return str(value)


def _columns(result: QueryResult) -> list[Counter]:
    return [Counter(norm(row[i]) for row in result.rows) for i in range(len(result.columns))]


def results_match(gold: QueryResult, predicted: QueryResult) -> bool:
    """True when every `gold` column has a distinct matching `predicted` column (multiset equal).

    Asymmetric on purpose: the prediction may return extra columns. Use `results_equivalent` when
    neither side is the reference.
    """
    if gold.row_count != predicted.row_count:
        return False
    predicted_cols = _columns(predicted)
    used: set[int] = set()
    for gold_col in _columns(gold):
        match = next((pi for pi, col in enumerate(predicted_cols) if pi not in used and col == gold_col), None)
        if match is None:
            return False
        used.add(match)
    return True


def results_equivalent(a: QueryResult, b: QueryResult) -> bool:
    """Symmetric: the narrower result must be contained in the wider one (extra columns are fine)."""
    if len(a.columns) <= len(b.columns):
        return results_match(a, b)
    return results_match(b, a)
