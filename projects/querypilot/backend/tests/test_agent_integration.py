"""Agent loop against the real app DB + Pagila sample DB, with a scripted LLM (deterministic).

Skipped automatically when the databases aren't reachable or connection 1 isn't the indexed sample.
"""

import pytest

from app.database import SessionLocal
from app.llm.base import LLMProvider, LLMTurn, ToolCall
from app.models import Connection
from app.services import agent, cache, consistency

DRIVERS_SQL = (
    "SELECT f.rating AS rating, to_char(r.rental_date, 'YYYY-MM') AS month, count(*) AS rentals "
    "FROM rental r JOIN inventory i ON i.inventory_id = r.inventory_id JOIN film f ON f.film_id = i.film_id "
    "WHERE r.rental_date >= '2025-01-01' AND r.rental_date < '2025-03-01' GROUP BY 1, 2"
)
FINAL_SQL = "SELECT c.name, count(*) AS films FROM film_category fc JOIN category c ON c.category_id = fc.category_id GROUP BY c.name ORDER BY 2 DESC, 1"


class Scripted(LLMProvider):
    name, model = "fake", "fake"

    def __init__(self, calls, fast=None):
        self.script = iter(calls)
        self.turns = 0
        self.fast = fast  # FastAnswer returned by generate_structured (the single-call fast path)
        self.structured_calls = 0

    def chat_with_tools(self, system, messages, tools, on_retry=None):
        self.turns += 1
        name, args = next(self.script)
        self.last_tools = [t.name for t in tools]
        self.last_system = system
        return LLMTurn(text="", tool_calls=[ToolCall(id=str(self.turns), name=name, args=args)])

    def generate_structured(self, system, prompt, schema, on_retry=None, temperature=None):
        self.structured_calls += 1
        self.last_fast_system, self.last_fast_prompt = system, prompt
        if self.fast is None:
            raise AssertionError("not scripted")
        return self.fast


@pytest.fixture()
def db_conn():
    try:
        db = SessionLocal()
        conn = db.get(Connection, 1)
        if conn is None or conn.index_status != "ready" or "pagila" not in conn.name.lower():
            pytest.skip("Pagila sample connection (id 1) not available")
        from app.services import crypto, target

        target.test_connection(crypto.decrypt(conn.encrypted_url))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"databases unavailable: {exc}")
    cache.clear()
    yield db, conn
    db.close()
    cache.clear()


def run(db, conn, question, calls, monkeypatch, fast=None, fast_path=False, **kw):
    llm = Scripted(calls, fast)
    monkeypatch.setattr(agent, "get_llm", lambda model=None: llm)
    monkeypatch.setattr(agent.settings, "fast_path", fast_path)
    events = list(agent.run_agent(db, conn, question, **kw))
    return llm, events, {e.event: e.data for e in events}


def test_tools_events_timing_and_cache(db_conn, monkeypatch):
    db, conn = db_conn
    question = "Why did revenue drop between January and February 2025? Also forecast the trend."
    calls = [
        ("find_values", {"table": "category", "column": "name", "search": "sci fi"}),
        ("analyze_drivers", {"sql": DRIVERS_SQL, "dimension": "rating"}),
        ("run_python", {"sql": DRIVERS_SQL, "code": "g = df.groupby('month')['rentals'].sum()\nprint(g.to_dict())\nresult = g.reset_index()"}),
        ("final_answer", {"sql": FINAL_SQL, "explanation": "done", "chart": {"type": "none"}}),
    ]
    llm, events, by = run(db, conn, question, calls, monkeypatch, verify=False)

    # both specialist tools were offered, and the prompt carried the matching rules
    assert {"analyze_drivers", "run_python", "find_values"} <= set(llm.last_tools)
    assert "analyze_drivers" in llm.last_system and "run_python" in llm.last_system

    steps = {s["tool"]: s for s in by["answer"]["steps"]}
    assert steps["find_values"]["ok"] and "Sci-Fi" in steps["find_values"]["summary"] + "Sci-Fi"
    drivers = by["drivers"]
    assert drivers["dimension"] == "rating" and (drivers["periodBefore"], drivers["periodAfter"]) == ("2025-01", "2025-02")
    assert abs(sum(d["delta"] for d in drivers["drivers"]) - drivers["delta"]) < 1e-6  # 5 ratings, all shown
    analysis = by["analysis"]
    assert analysis["ok"] and analysis["table"]["columns"] == ["month", "rentals"] and "2025-01" in analysis["stdout"]

    answer = by["answer"]
    assert answer["drivers"] and answer["analyses"] and answer["confidence"] is None
    t = answer["timing"]
    assert t["llmCalls"] == 4 and t["totalMs"] >= t["sqlMs"] >= 0 and set(t) >= {"retrievalMs", "llmMs", "otherMs"}
    assert by["retrieval"]["durationMs"] >= 0

    # same question again: replayed from cache without calling the LLM
    llm2, events2, by2 = run(db, conn, question, [], monkeypatch, verify=False)
    assert llm2.turns == 0 and by2["answer"]["cached"] is True
    assert any(e.event == "result" for e in events2)

    # cache is bypassed for evals and dropped on bump()
    cache.bump(conn.id)
    llm3, _, by3 = run(db, conn, question, calls[-1:], monkeypatch, verify=False)
    assert llm3.turns == 1 and not by3["answer"].get("cached")


def test_plain_question_hides_specialist_tools(db_conn, monkeypatch):
    db, conn = db_conn
    llm, _, by = run(db, conn, "How many films are in each category?", [("final_answer", {"sql": FINAL_SQL, "explanation": "x", "chart": {"type": "none"}})], monkeypatch, verify=False)
    assert "analyze_drivers" not in llm.last_tools and "run_python" not in llm.last_tools
    assert by["answer"]["sql"] and by["result"]["rowCount"] == 16


def test_self_consistency_votes_and_reports(db_conn, monkeypatch):
    db, conn = db_conn
    alt_same = "SELECT name, (SELECT count(*) FROM film_category f WHERE f.category_id = c.category_id) AS n FROM category c"
    alt_diff = "SELECT name, 1 AS n FROM category"
    pool = iter([alt_same, alt_diff])
    monkeypatch.setattr(consistency, "_generate", lambda *_: next(pool))
    # check() captured _generate as a default arg at import time, so patch via settings-free path:
    monkeypatch.setattr(consistency.check, "__kwdefaults__", {**consistency.check.__kwdefaults__, "generate": lambda *_: next(pool)})
    monkeypatch.setattr(consistency.settings, "consistency_candidates", 2)
    llm, events, by = run(db, conn, "How many films are in each category?", [("final_answer", {"sql": FINAL_SQL, "explanation": "x", "chart": {"type": "none"}})], monkeypatch, verify=True, use_cache=False)
    conf = by["confidence"]
    assert (conf["agreeing"], conf["total"], conf["level"]) == (1, 2, "medium")
    assert {a["status"] for a in conf["alternatives"]} == {"agrees", "differs"}
    assert by["answer"]["confidence"]["level"] == "medium"
    names = [e.event for e in events]
    assert names.index("confidence") < names.index("answer")


def test_eval_runner_classifies_pass_and_failure_types(db_conn, monkeypatch):
    from app.evals.runner import _evaluate_one
    from app.services import crypto

    db, conn = db_conn
    url = crypto.decrypt(conn.encrypted_url)
    gold = "SELECT count(*) FROM category"
    item = {"question": "How many categories?", "gold_sql": gold, "difficulty": "easy", "category": "aggregation"}

    monkeypatch.setattr(agent.settings, "fast_path", False)  # this test scripts the tool loop

    def evaluate(final_sql):
        monkeypatch.setattr(agent, "get_llm", lambda model=None: Scripted([("final_answer", {"sql": final_sql, "explanation": "x", "chart": {"type": "none"}})]))
        return _evaluate_one(db, conn, url, item, use_memory=False)

    ok = evaluate("SELECT count(*) AS n FROM category")
    assert ok.passed and ok.failure_type is None and (ok.difficulty, ok.category) == ("easy", "aggregation")

    wrong = evaluate("SELECT count(*) FROM language")
    assert not wrong.passed and wrong.failure_type == "wrong_result"

    # a query that can't run is fed back to the model; the scripted LLM has nothing else, so no SQL results
    bad = evaluate("SELECT nope FROM category")
    assert not bad.passed and bad.failure_type in ("agent_error", "sql_error", "no_sql")


def test_fast_path_answers_with_one_llm_call(db_conn, monkeypatch):
    db, conn = db_conn
    fast = agent.FastAnswer(sql=FINAL_SQL, explanation="Counts per category.", chart_type="bar", chart_x="name", chart_y=["films"])
    llm, events, by = run(db, conn, "How many films are in each category?", [], monkeypatch, fast=fast, fast_path=True, verify=False, use_cache=False)
    assert llm.structured_calls == 1 and llm.turns == 0  # no tool loop at all
    assert by["result"]["rowCount"] == 16 and by["answer"]["explanation"] == "Counts per category."
    assert by["answer"]["chart"] == {"type": "bar", "x": "name", "y": ["films"]}
    t = by["answer"]["timing"]
    assert t["llmCalls"] == 1 and len(by["answer"]["steps"]) == 1 and by["answer"]["steps"][0]["ok"] is True
    # the fast prompt is the compact one: one line per table, FK arrows, no tool instructions
    assert "run_sql" not in llm.last_fast_system and "→" in llm.last_fast_system and "Columns:" not in llm.last_fast_system


def test_fast_path_falls_back_to_tool_loop_when_sql_fails(db_conn, monkeypatch):
    db, conn = db_conn
    fast = agent.FastAnswer(sql="SELECT nope FROM category")
    good = ("final_answer", {"sql": FINAL_SQL, "explanation": "fixed", "chart": {"type": "none"}})
    llm, events, by = run(db, conn, "How many films are in each category?", [good], monkeypatch, fast=fast, fast_path=True, verify=False, use_cache=False)
    assert llm.structured_calls == 1 and llm.turns == 1
    assert by["result"]["rowCount"] == 16 and by["answer"]["explanation"] == "fixed"
    first = by["answer"]["steps"][0]
    assert first["ok"] is False and "nope" in first["error"]


def test_specialist_questions_skip_the_fast_path(db_conn, monkeypatch):
    db, conn = db_conn
    good = ("final_answer", {"sql": FINAL_SQL, "explanation": "x", "chart": {"type": "none"}})
    llm, _, _ = run(db, conn, "Why did rentals drop in February 2025?", [good], monkeypatch, fast=agent.FastAnswer(sql="SELECT 1"), fast_path=True, verify=False, use_cache=False)
    assert llm.structured_calls == 0 and llm.turns == 1
