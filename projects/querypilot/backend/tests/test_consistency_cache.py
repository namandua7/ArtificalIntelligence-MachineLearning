import time

import pytest

from app.config import settings
from app.services import cache, consistency, target


def qr(rows, cols=("a",)):
    return target.QueryResult(sql="x", columns=list(cols), rows=rows, row_count=len(rows))


@pytest.mark.parametrize("agree,total,expected", [(0, 0, "unverified"), (2, 2, "high"), (1, 2, "medium"), (0, 2, "low")])
def test_level(agree, total, expected):
    assert consistency.level(agree, total) == expected


def test_enabled_resolution(monkeypatch):
    assert consistency.enabled(True) and not consistency.enabled(False)
    monkeypatch.setattr(settings, "self_consistency", "auto")
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    assert not consistency.enabled(None)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    assert consistency.enabled(None)
    monkeypatch.setattr(settings, "self_consistency", "off")
    assert not consistency.enabled(None)


def test_check_votes(monkeypatch):
    results = {"SELECT 1": qr([[1]]), "SELECT 2": qr([[2]])}

    def fake_run(url, sql, max_rows=None):
        if sql == "BAD":
            raise RuntimeError("boom")
        return results[sql]

    monkeypatch.setattr(target, "run_select", fake_run)
    sqls = iter(["SELECT 1", "SELECT 2", "BAD"])
    out = consistency.check(
        system="s", question="q", primary=qr([[1]]), url="u", n=3, generate=lambda *_: next(sqls)
    )
    statuses = sorted(a["status"] for a in out["alternatives"])
    assert statuses == ["agrees", "differs", "error"]
    # the erroring candidate is not counted either way
    assert (out["agreeing"], out["total"], out["level"]) == (1, 2, "medium")


def test_check_without_candidates_is_unverified():
    out = consistency.check(system="s", question="q", primary=qr([[1]]), url="u", n=2, generate=lambda *_: None)
    assert out["level"] == "unverified" and out["alternatives"] == []


def test_cache_hit_normalises_question_and_bump_invalidates(monkeypatch):
    cache.clear()
    monkeypatch.setattr(settings, "answer_cache_ttl_s", 60)
    cache.put(1, "Top films?", ["e1", "e2"])
    assert cache.get(1, "  top   FILMS ") == ["e1", "e2"]
    assert cache.get(2, "top films") is None  # other connection
    assert cache.get(1, "top films", flavour="verify") is None
    cache.bump(1)
    assert cache.get(1, "top films") is None


def test_cache_ttl_and_disable(monkeypatch):
    cache.clear()
    monkeypatch.setattr(settings, "answer_cache_ttl_s", 1)
    cache.put(1, "q", ["x"])
    time.sleep(1.2)
    assert cache.get(1, "q") is None
    monkeypatch.setattr(settings, "answer_cache_ttl_s", 0)
    cache.put(1, "q", ["x"])
    assert cache.get(1, "q") is None


def test_specialist_tools_only_offered_when_relevant():
    from app.services.agent import _tools, _wants

    plain = {t.name for t in _tools("How many films are rated PG-13?")}
    assert plain == {"search_schema", "get_table_details", "find_values", "run_sql", "final_answer"}
    assert _wants("Why did revenue drop in March?") == (False, True)
    assert _wants("Is there a correlation between length and rental rate?") == (True, False)
    assert {"analyze_drivers"} <= {t.name for t in _tools("what caused the dip in rentals")}
    assert {"run_python"} <= {t.name for t in _tools("forecast next month's revenue")}
