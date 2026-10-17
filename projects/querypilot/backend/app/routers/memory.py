from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Connection, SavedQuery
from app.routers.deps import connection_url, get_ready_connection
from app.schemas import SavedQueryCreate, SavedQueryOut, SavedQueryUpdate
from app.services import target
from app.services.memory import save_query, update_question
from app.services.sql_guard import format_sql

router = APIRouter(tags=["memory"])


def _validate_sql(connection: Connection, sql: str) -> None:
    """Only store examples that actually run — bad examples teach the agent bad habits."""
    try:
        target.run_select(connection_url(connection), sql, max_rows=1)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"SQL failed: {str(exc).strip()}") from exc


@router.get("/api/connections/{connection_id}/memory", response_model=list[SavedQueryOut])
def list_saved(connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(SavedQuery).where(SavedQuery.connection_id == connection.id).order_by(SavedQuery.created_at.desc())
        )
    )


@router.post("/api/connections/{connection_id}/memory", response_model=SavedQueryOut, status_code=201)
def create_saved(
    body: SavedQueryCreate, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)
):
    _validate_sql(connection, body.sql)
    return save_query(db, connection.id, body.question.strip(), body.sql.strip())


@router.patch("/api/memory/{saved_id}", response_model=SavedQueryOut)
def update_saved(saved_id: int, body: SavedQueryUpdate, db: Session = Depends(get_db)):
    saved = db.get(SavedQuery, saved_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved query not found")
    if body.sql is not None and body.sql.strip() != saved.sql:
        _validate_sql(db.get(Connection, saved.connection_id), body.sql)
        saved.sql = format_sql(body.sql)
    if body.question is not None and body.question.strip() != saved.question:
        update_question(db, saved, body.question.strip())
    if body.verified is not None:
        saved.verified = body.verified
    db.commit()
    db.refresh(saved)
    return saved


@router.delete("/api/memory/{saved_id}", status_code=204)
def delete_saved(saved_id: int, db: Session = Depends(get_db)) -> None:
    saved = db.get(SavedQuery, saved_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved query not found")
    db.delete(saved)
    db.commit()
