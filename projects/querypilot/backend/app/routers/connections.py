from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Connection
from app.routers.deps import connection_url, get_connection
from app.schemas import ConnectionCreate, ConnectionOut, ConnectionTest, ConnectionTestResult
from app.services import crypto, target
from app.services.indexing import reindex_connection_background

router = APIRouter(prefix="/api/connections", tags=["connections"])


def _out(connection: Connection) -> ConnectionOut:
    return ConnectionOut(
        id=connection.id,
        name=connection.name,
        dialect=connection.dialect,
        display_url=target.redact_url(connection_url(connection)),
        index_status=connection.index_status,
        index_error=connection.index_error,
        table_count=connection.table_count,
        last_indexed_at=connection.last_indexed_at,
        created_at=connection.created_at,
    )


@router.get("", response_model=list[ConnectionOut])
def list_connections(db: Session = Depends(get_db)) -> list[ConnectionOut]:
    return [_out(c) for c in db.scalars(select(Connection).order_by(Connection.created_at.desc()))]


@router.post("/test", response_model=ConnectionTestResult)
def test_connection(body: ConnectionTest) -> ConnectionTestResult:
    try:
        version = target.test_connection(target.normalize_url(body.url))
    except Exception as exc:  # noqa: BLE001
        return ConnectionTestResult(ok=False, error=str(exc).strip())
    return ConnectionTestResult(ok=True, version=version)


@router.post("", response_model=ConnectionOut, status_code=201)
def create_connection(
    body: ConnectionCreate, background: BackgroundTasks, db: Session = Depends(get_db)
) -> ConnectionOut:
    try:
        url = target.normalize_url(body.url)
        target.test_connection(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not connect: {str(exc).strip()}") from exc

    connection = Connection(name=body.name.strip(), encrypted_url=crypto.encrypt(url), index_status="pending")
    db.add(connection)
    db.commit()
    db.refresh(connection)
    background.add_task(reindex_connection_background, connection.id)
    return _out(connection)


@router.get("/{connection_id}", response_model=ConnectionOut)
def get_one(connection: Connection = Depends(get_connection)) -> ConnectionOut:
    return _out(connection)


@router.post("/{connection_id}/reindex", response_model=ConnectionOut)
def reindex(
    background: BackgroundTasks,
    connection: Connection = Depends(get_connection),
    db: Session = Depends(get_db),
) -> ConnectionOut:
    connection.index_status = "pending"
    db.commit()
    background.add_task(reindex_connection_background, connection.id)
    return _out(connection)


@router.delete("/{connection_id}", status_code=204)
def delete_connection(connection_id: int, db: Session = Depends(get_db)) -> None:
    connection = db.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    target.dispose_engine(connection_url(connection))
    db.delete(connection)
    db.commit()
