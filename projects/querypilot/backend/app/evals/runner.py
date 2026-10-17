"""Execution-accuracy evals: run the agent on known questions and compare results to gold SQL.

A prediction passes when every gold column has a matching predicted column with the same multiset
of (normalised) values. That ignores column names/order, row order and extra columns, so
`SELECT name, count(*) AS films` and `SELECT count(*) AS n, name` both pass.
"""

import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.llm import describe_llm
from app.models import Connection, EvalResult, EvalRun
from app.services import crypto, target
from app.services.agent import run_agent

logger = logging.getLogger(__name__)

DATASETS_DIR = Path(__file__).parent / "datasets"
# Pause between questions to stay under free-tier requests-per-minute limits.
DEFAULT_PACE_SECONDS = 4.0


def list_datasets() -> list[dict[str, Any]]:
    return [
        {"name": p.stem, "size": len(json.loads(p.read_text()))}
        for p in sorted(DATASETS_DIR.glob("*.json"))
    ]


def load_dataset(name: str) -> list[dict[str, str]]:
    path = DATASETS_DIR / f"{name}.json"
    if not path.is_file() or path.parent != DATASETS_DIR:
        raise ValueError(f"Unknown dataset '{name}'.")
    return json.loads(path.read_text())


def _norm(value: Any) -> Any:
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


def results_match(gold: target.QueryResult, predicted: target.QueryResult) -> bool:
    if gold.row_count != predicted.row_count:
        return False
    predicted_cols = [
        Counter(_norm(row[i]) for row in predicted.rows) for i in range(len(predicted.columns))
    ]
    used: set[int] = set()
    for gi in range(len(gold.columns)):
        gold_col = Counter(_norm(row[gi]) for row in gold.rows)
        match = next(
            (pi for pi, col in enumerate(predicted_cols) if pi not in used and col == gold_col), None
        )
        if match is None:
            return False
        used.add(match)
    return True


def _evaluate_one(db: Session, connection: Connection, url: str, item: dict[str, str], use_memory: bool) -> EvalResult:
    started = time.perf_counter()
    predicted_sql: str | None = None
    steps = 0
    error: str | None = None
    for event in run_agent(db, connection, item["question"], use_memory=use_memory, source="eval"):
        if event.event == "answer":
            predicted_sql = event.data.get("sql") or None
            steps = len(event.data.get("steps", []))
        elif event.event == "error":
            error = event.data.get("message")
            steps = len(event.data.get("steps", []))

    passed = False
    if predicted_sql:
        try:
            gold = target.run_select(url, item["gold_sql"], max_rows=settings.max_result_rows)
            predicted = target.run_select(url, predicted_sql, max_rows=settings.max_result_rows)
            passed = results_match(gold, predicted)
        except Exception as exc:  # noqa: BLE001
            error = str(exc).strip()
    elif error is None:
        error = "No SQL produced."

    return EvalResult(
        question=item["question"],
        gold_sql=item["gold_sql"],
        predicted_sql=predicted_sql,
        passed=passed,
        steps=steps,
        duration_ms=int((time.perf_counter() - started) * 1000),
        error=error,
    )


def create_run(db: Session, connection_id: int, dataset: str, use_memory: bool) -> EvalRun:
    items = load_dataset(dataset)
    run = EvalRun(
        connection_id=connection_id,
        dataset=dataset,
        use_memory=use_memory,
        model=f"{describe_llm()['provider']}:{describe_llm()['model']}",
        total=len(items),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def execute_run(run_id: int, pace_seconds: float = DEFAULT_PACE_SECONDS) -> None:
    """Runs synchronously with its own session (used by BackgroundTasks and the CLI)."""
    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        if run is None:
            return
        connection = db.get(Connection, run.connection_id)
        assert connection is not None
        url = crypto.decrypt(connection.encrypted_url)
        items = load_dataset(run.dataset)
        try:
            for i, item in enumerate(items):
                if i:
                    time.sleep(pace_seconds)
                result = _evaluate_one(db, connection, url, item, run.use_memory)
                result.run_id = run.id
                db.add(result)
                run.completed += 1
                run.passed += int(result.passed)
                # The API marks "running" rows as interrupted on startup; a CLI run in another
                # process is still alive, so re-assert our status.
                run.status, run.error = "running", None
                db.commit()
                logger.info("eval %s [%d/%d] %s %s", run.id, i + 1, len(items),
                            "PASS" if result.passed else "FAIL", item["question"])
            run.status = "done"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Eval run %s failed", run_id)
            db.rollback()
            run = db.get(EvalRun, run_id)
            run.status = "error"
            run.error = str(exc)
        run.accuracy = round(run.passed / run.completed, 4) if run.completed else None
        db.commit()
    finally:
        db.close()
