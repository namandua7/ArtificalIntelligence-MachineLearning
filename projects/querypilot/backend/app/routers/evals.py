from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.evals.runner import create_run, execute_run, list_datasets
from app.models import Connection, EvalRun
from app.routers.deps import get_ready_connection
from app.evals import analysis
from app.schemas import EvalCompareOut, EvalCreate, EvalDataset, EvalRunDetail, EvalRunOut

router = APIRouter(tags=["evals"])


@router.get("/api/evals/datasets", response_model=list[EvalDataset])
def datasets() -> list[EvalDataset]:
    return [EvalDataset(**d) for d in list_datasets()]


@router.get("/api/connections/{connection_id}/evals", response_model=list[EvalRunOut])
def list_runs(connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)):
    return list(
        db.scalars(select(EvalRun).where(EvalRun.connection_id == connection.id).order_by(EvalRun.created_at.desc()))
    )


@router.get("/api/connections/{connection_id}/evals/compare", response_model=EvalCompareOut)
def compare_runs(a: int, b: int, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)):
    """Question-by-question diff of run `a` (baseline) against run `b` (candidate)."""
    runs = []
    for run_id in (a, b):
        run = db.get(EvalRun, run_id)
        if run is None or run.connection_id != connection.id:
            raise HTTPException(status_code=404, detail=f"Eval run #{run_id} not found")
        runs.append(run)
    cmp = analysis.compare(runs[0].results, runs[1].results)
    return EvalCompareOut(
        a=EvalRunOut.model_validate(runs[0]),
        b=EvalRunOut.model_validate(runs[1]),
        items=cmp.items,
        summary=cmp.summary,
        by_difficulty_a=analysis.breakdown(runs[0].results)["byDifficulty"],
        by_difficulty_b=analysis.breakdown(runs[1].results)["byDifficulty"],
    )


@router.post("/api/connections/{connection_id}/evals", response_model=EvalRunOut, status_code=201)
def start_run(
    body: EvalCreate,
    background: BackgroundTasks,
    connection: Connection = Depends(get_ready_connection),
    db: Session = Depends(get_db),
):
    running = db.scalar(
        select(EvalRun.id).where(EvalRun.connection_id == connection.id, EvalRun.status == "running")
    )
    if running is not None:
        raise HTTPException(status_code=409, detail=f"Eval run #{running} is still running.")
    try:
        run = create_run(db, connection.id, body.dataset, body.use_memory, body.verify, body.model, body.label)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background.add_task(execute_run, run.id)
    return run


@router.get("/api/evals/{run_id}", response_model=EvalRunDetail)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.get(EvalRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    detail = EvalRunDetail.model_validate(run)
    detail.breakdown = analysis.breakdown(run.results)
    return detail
