from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.llm import LLMError
from app.models import Connection
from app.routers.deps import get_ready_connection
from app.schemas import DoctorRequest
from app.services.doctor import diagnose
from app.services.sql_guard import SqlGuardError

router = APIRouter(tags=["doctor"])


@router.post("/api/connections/{connection_id}/doctor")
def run_doctor(
    body: DoctorRequest, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)
) -> dict[str, Any]:
    try:
        return diagnose(db, connection, body.sql, analyze=body.analyze)
    except SqlGuardError as exc:
        raise HTTPException(status_code=400, detail=f"Blocked: {exc}") from exc
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — usually a DB error in EXPLAIN
        raise HTTPException(status_code=400, detail=str(getattr(exc, "pgerror", None) or exc).strip()) from exc
