from app.services.insights import compute_facts


def test_category_leader_share_and_spread():
    facts = compute_facts(["category", "revenue"], [["A", 500.0], ["B", 300.0], ["C", 200.0]])
    text = " ".join(facts["highlights"])
    assert "A leads revenue with 500 (50% of the total)" in text
    assert "top 3 account for 100%" in text
    assert "Lowest revenue: C (200)" in text
    assert "2.5x" in text
    assert facts["metrics"]["revenue"]["sum"] == 1000.0


def test_time_series_trend_peak_and_low():
    rows = [["2024-03-01", 150], ["2024-01-01", 100], ["2024-02-01", 200]]
    text = " ".join(compute_facts(["month", "orders"], rows)["highlights"])
    assert "from 100 (2024-01-01) to 150 (2024-03-01) (+50.0%)" in text
    assert "Peak orders: 200 in 2024-02-01" in text


def test_single_row_and_empty():
    assert compute_facts(["n"], [[42]])["highlights"] == ["n: 42"]
    assert compute_facts(["n"], [])["highlights"] == []
    assert compute_facts(["name", "city"], [["a", "x"], ["b", "y"]])["highlights"] == []


def test_negative_values_dont_report_share():
    text = " ".join(compute_facts(["seg", "delta"], [["a", -5.0], ["b", -9.0]])["highlights"])
    assert "of the total" not in text and "Highest delta: a (-5)" in text
