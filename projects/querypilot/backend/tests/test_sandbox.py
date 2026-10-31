import pytest

from app.services.sandbox import run_python

COLS = ["month", "revenue", "region"]
ROWS = [["2024-01-01", 100, "N"], ["2024-02-01", 130, "S"], ["2024-03-01", 160, "N"], ["2024-04-01", 190, "S"]]


def run(code):
    return run_python(code, COLS, ROWS)


def test_dataframe_result_becomes_table():
    res = run("result = df.groupby('region')['revenue'].sum().reset_index()")
    assert res.ok, res.error
    assert res.table["columns"] == ["region", "revenue"]
    assert sorted(map(tuple, res.table["rows"])) == [("N", 260), ("S", 320)]


def test_print_and_scalar_value():
    res = run("print(df.revenue.mean())\nresult = float(df.revenue.max())")
    assert res.ok, res.error
    assert res.stdout.strip() == "145.0"
    assert res.value == 190.0


def test_dates_are_parsed_and_forecast_with_numpy():
    code = (
        "x = np.arange(len(df))\n"
        "slope, intercept = np.polyfit(x, df.revenue.to_numpy(), 1)\n"
        "result = {'slope': round(float(slope), 2), 'next': round(float(slope * len(df) + intercept), 1),"
        " 'is_dt': str(df.month.dtype).startswith('datetime')}"
    )
    res = run(code)
    assert res.ok, res.error
    assert res.value == {"slope": 30.0, "next": 220.0, "is_dt": True}


@pytest.mark.parametrize(
    "code",
    [
        "import os\nresult = os.listdir('/')",
        "import subprocess",
        "from os import path",
        "open('/etc/passwd').read()",
        "__import__('os').system('id')",
        "result = df.__class__.__bases__",
        "pd.read_csv('/etc/passwd')",
        "df.to_csv('/tmp/x.csv')",
        "np.load('/tmp/x.npy')",
        "eval('1+1')",
        "exec('x=1')",
        "getattr(df, 'x')",
        "result = ().__class__",
        "class A: pass",
        "import socket",
    ],
)
def test_escape_attempts_are_blocked(code):
    res = run(code)
    assert not res.ok
    assert "not allowed" in res.error


def test_runtime_error_is_reported_with_line():
    res = run("x = 1\nresult = df['nope']")
    assert not res.ok
    assert "KeyError" in res.error and "line 2" in res.error


def test_timeout_kills_runaway_code(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "sandbox_timeout_s", 2)
    res = run("while True:\n    pass")
    assert not res.ok
    assert "Timed out" in res.error or "CPU" in res.error or "failed" in res.error
