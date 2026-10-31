"""Root-cause helper: split the change in a metric between two periods into per-segment contributions.

The agent writes a query that returns (segment, period, value) for ONE dimension; this module does
the arithmetic deterministically so the numbers shown to the user are never LLM-computed. The agent
calls it once per candidate dimension (region, category, channel…) and the UI shows each breakdown.
"""

from dataclasses import dataclass
from numbers import Number
from typing import Any

MAX_DRIVERS = 10
_PERIOD_HINTS = ("period", "month", "week", "day", "quarter", "year", "date", "bucket", "when")


class DriverError(ValueError):
    pass


def _is_number(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def _numeric_columns(columns: list[str], rows: list[list[Any]]) -> list[int]:
    out = []
    for i in range(len(columns)):
        values = [r[i] for r in rows if r[i] is not None]
        if values and all(_is_number(v) for v in values):
            out.append(i)
    return out


def _pick_columns(columns: list[str], rows: list[list[Any]], dimension: str | None) -> tuple[int, int, int]:
    """Return (segment_idx, period_idx, value_idx)."""
    if len(columns) < 3:
        raise DriverError("The query must return three columns: segment, period, value.")
    numeric = _numeric_columns(columns, rows)
    if not numeric:
        raise DriverError("No numeric value column found.")
    value_idx = numeric[-1]

    candidates = [i for i in range(len(columns)) if i != value_idx]
    distinct = {i: len({r[i] for r in rows}) for i in candidates}
    period_idx = next(
        (i for i in candidates if any(h in columns[i].lower() for h in _PERIOD_HINTS) and 2 <= distinct[i] <= 12),
        None,
    )
    if period_idx is None:
        two = [i for i in candidates if distinct[i] == 2]
        if not two:
            raise DriverError("No period column found: expected a column with exactly two distinct values.")
        period_idx = two[0]
    rest = [i for i in candidates if i != period_idx]
    if not rest:
        raise DriverError("No segment column found.")
    segment_idx = next((i for i in rest if columns[i] == dimension), rest[0])
    return segment_idx, period_idx, value_idx


@dataclass
class Driver:
    segment: str
    before: float
    after: float
    delta: float
    share: float | None  # share of the total change; None when the total change is ~0
    pct_change: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "segment": self.segment,
            "before": round(self.before, 2),
            "after": round(self.after, 2),
            "delta": round(self.delta, 2),
            "share": None if self.share is None else round(self.share, 4),
            "pctChange": None if self.pct_change is None else round(self.pct_change, 4),
        }


def compute_drivers(columns: list[str], rows: list[list[Any]], dimension: str | None = None) -> dict[str, Any]:
    if not rows:
        raise DriverError("The query returned no rows.")
    segment_idx, period_idx, value_idx = _pick_columns(columns, rows, dimension)

    periods = sorted({str(r[period_idx]) for r in rows})
    if len(periods) < 2:
        raise DriverError("Only one period in the data: nothing to compare.")
    before_label, after_label = periods[0], periods[-1]  # earliest vs latest

    before: dict[str, float] = {}
    after: dict[str, float] = {}
    for row in rows:
        value = float(row[value_idx] or 0)
        segment = "(none)" if row[segment_idx] is None else str(row[segment_idx])
        bucket = before if str(row[period_idx]) == before_label else after if str(row[period_idx]) == after_label else None
        if bucket is not None:
            bucket[segment] = bucket.get(segment, 0.0) + value

    total_before, total_after = sum(before.values()), sum(after.values())
    delta = total_after - total_before
    drivers: list[Driver] = []
    for segment in before.keys() | after.keys():
        b, a = before.get(segment, 0.0), after.get(segment, 0.0)
        d = a - b
        drivers.append(
            Driver(
                segment=segment,
                before=b,
                after=a,
                delta=d,
                share=d / delta if abs(delta) > 1e-9 else None,
                pct_change=d / b if abs(b) > 1e-9 else None,
            )
        )
    drivers.sort(key=lambda d: abs(d.delta), reverse=True)

    return {
        "dimension": columns[segment_idx],
        "metric": columns[value_idx],
        "periodBefore": before_label,
        "periodAfter": after_label,
        "totalBefore": round(total_before, 2),
        "totalAfter": round(total_after, 2),
        "delta": round(delta, 2),
        "pctChange": round(delta / total_before, 4) if abs(total_before) > 1e-9 else None,
        "segmentCount": len(drivers),
        "drivers": [d.as_dict() for d in drivers[:MAX_DRIVERS]],
    }
