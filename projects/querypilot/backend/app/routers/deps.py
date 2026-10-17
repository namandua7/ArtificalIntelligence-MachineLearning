from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Connection
from app.services import crypto


def get_connection(connection_id: int, db: Session = Depends(get_db)) -> Connection:
    connection = db.get(Connection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    return connection


def get_ready_connection(connection: Connection = Depends(get_connection)) -> Connection:
    if connection.index_status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Schema index is not ready (status: {connection.index_status}).",
        )
    return connection


def connection_url(connection: Connection) -> str:
    return crypto.decrypt(connection.encrypted_url)
