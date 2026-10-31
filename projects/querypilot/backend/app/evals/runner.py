"""Execution-accuracy evals: run the agent on known questions and compare results to gold SQL.

A prediction passes when every gold column has a matching predicted column with the same multiset
of (normalised) values. That ignores column names/order, row order and extra columns, so
`SELECT name, count(*) AS films` and `SELECT count(*) AS n, name` both pass.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.llm import describe_llm
from app.models import Connection, EvalResult, EvalRun
from app.services import crypto, target
from app.services.agent import run_agent
from app.services.compare import results_match
from app.services.sql_guard import SqlGuardError

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


def _db_error(exc: Exception) -> str:
    return str(getattr(exc, "pgerror", None) or exc).strip()


def _evaluate_one(
    db: Session,
    connection: Connection,
    url: str,
    item: dict[str, str],
    use_memory: bool,
    verify: bool = False,
    model: str | None = None,
) -> EvalResult:
    started = time.perf_counter()
    predicted_sql: str | None = None
    steps = 0
    error: str | None = None
    failure: str | None = None
    # use_cache=False: a cached replay would measure the cache, not the agent.
    for event in run_agent(
        db, connection, item["question"], use_memory=use_memory, source="eval",
        verify=verify, model=model, use_cache=False,
    ):
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
        except Exception as exc:  # noqa: BLE001
            error, failure = f"Gold SQL failed: {_db_error(exc)}", "gold_error"
        else:
            try:
                predicted = target.run_select(url, predicted_sql, max_rows=settings.max_result_rows)
                passed = results_match(gold, predicted)
                if not passed:
                    failure = "wrong_result"
            except SqlGuardError as exc:
                error, failure = str(exc), "blocked"
            except Exception as exc:  # noqa: BLE001
                error, failure = _db_error(exc), "sql_error"
    elif error is None:
        error, failure = "No SQL produced.", "no_sql"
    else:
        failure = "agent_error"

    return EvalResult(
        question=item["question"],
        gold_sql=item["gold_sql"],
        predicted_sql=predicted_sql,
        passed=passed,
        steps=steps,
        duration_ms=int((time.perf_counter() - started) * 1000),
        error=error,
        difficulty=item.get("difficulty"),
        category=item.get("category"),
        failure_type=None if passed else failure,
    )


def create_run(
    db: Session,
    connection_id: int,
    dataset: str,
    use_memory: bool,
    verify: bool = False,
    model: str | None = None,
    label: str | None = None,
) -> EvalRun:
    items = load_dataset(dataset)
    llm = describe_llm()
    run = EvalRun(
        connection_id=connection_id,
        dataset=dataset,
        use_memory=use_memory,
        verify=verify,
        model=f"{llm['provider']}:{model or llm['model']}",
        label=(label or "").strip() or None,
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
                result = _evaluate_one(
                    db, connection, url, item, run.use_memory, run.verify, run.model.split(":", 1)[-1]
                )
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
