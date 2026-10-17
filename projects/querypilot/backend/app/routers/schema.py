from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Connection, SchemaRelation, SchemaTable
from app.routers.deps import connection_url, get_ready_connection
from app.schemas import QueryResultOut, RelationOut, RetrieveRequest, SchemaOut, TableOut
from app.services import target
from app.services.retrieval import retrieve

router = APIRouter(prefix="/api/connections/{connection_id}/schema", tags=["schema"])


@router.get("", response_model=SchemaOut)
def get_schema(connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)) -> SchemaOut:
    tables = db.scalars(
        select(SchemaTable).where(SchemaTable.connection_id == connection.id).order_by(SchemaTable.table_name)
    )
    relations = db.scalars(select(SchemaRelation).where(SchemaRelation.connection_id == connection.id))
    return SchemaOut(
        tables=[
            TableOut(
                name=t.table_name, kind=t.kind, comment=t.comment, row_estimate=t.row_estimate, columns=t.columns
            )
            for t in tables
        ],
        relations=[
            RelationOut(from_table=r.from_table, from_column=r.from_column, to_table=r.to_table, to_column=r.to_column)
            for r in relations
        ],
    )


@router.get("/tables/{table_name}/sample", response_model=QueryResultOut)
def sample(
    table_name: str, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)
) -> QueryResultOut:
    if not settings.allow_sample_rows:
        raise HTTPException(status_code=403, detail="Sample rows are disabled (ALLOW_SAMPLE_ROWS=false).")
    exists = db.scalar(
        select(SchemaTable.id).where(SchemaTable.connection_id == connection.id, SchemaTable.table_name == table_name)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Table not found")
    try:
        result = target.sample_rows(connection_url(connection), table_name, limit=20)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc).strip()) from exc
    return QueryResultOut(**result.as_dict())


@router.post("/retrieve")
def debug_retrieve(
    body: RetrieveRequest, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Shows what the RAG step would hand the agent for a question (useful for tuning)."""
    return retrieve(db, connection.id, body.question).summary()
