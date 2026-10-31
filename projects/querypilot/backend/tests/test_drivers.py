import pytest

from app.services.drivers import DriverError, compute_drivers

COLS = ["region", "month", "revenue"]


def test_splits_change_across_segments():
    rows = [
        ["EU", "2024-02", 100.0], ["EU", "2024-03", 60.0],
        ["US", "2024-02", 200.0], ["US", "2024-03", 190.0],
        ["APAC", "2024-02", 50.0], ["APAC", "2024-03", 55.0],
    ]
    out = compute_drivers(COLS, rows)
    assert out["dimension"] == "region" and out["metric"] == "revenue"
    assert (out["periodBefore"], out["periodAfter"]) == ("2024-02", "2024-03")
    assert out["totalBefore"] == 350.0 and out["totalAfter"] == 305.0 and out["delta"] == -45.0
    top = out["drivers"][0]
    assert top["segment"] == "EU" and top["delta"] == -40.0
    assert top["share"] == pytest.approx(40 / 45, abs=1e-3)
    assert top["pctChange"] == pytest.approx(-0.4)
    assert sum(d["delta"] for d in out["drivers"]) == pytest.approx(out["delta"])


def test_segment_missing_in_one_period_counts_as_zero():
    rows = [["A", "p1", 10], ["A", "p2", 10], ["B", "p2", 5]]
    out = compute_drivers(["seg", "period", "v"], rows)
    new = next(d for d in out["drivers"] if d["segment"] == "B")
    assert new["before"] == 0 and new["after"] == 5 and new["pctChange"] is None


def test_uses_earliest_and_latest_period():
    rows = [["A", "2024-01", 1], ["A", "2024-02", 5], ["A", "2024-03", 9]]
    out = compute_drivers(["seg", "month", "v"], rows)
    assert (out["periodBefore"], out["periodAfter"], out["delta"]) == ("2024-01", "2024-03", 8.0)


def test_zero_total_change_has_no_share():
    rows = [["A", "p1", 10], ["A", "p2", 5], ["B", "p1", 5], ["B", "p2", 10]]
    out = compute_drivers(["seg", "period", "v"], rows)
    assert out["delta"] == 0 and all(d["share"] is None for d in out["drivers"])


@pytest.mark.parametrize(
    "columns,rows",
    [(["a", "b"], [["x", 1]]), (["seg", "period", "v"], []), (["seg", "period", "v"], [["a", "p", 1]])],
)
def test_bad_shapes_raise(columns, rows):
    with pytest.raises(DriverError):
        compute_drivers(columns, rows)
