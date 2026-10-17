from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.llm import LLMError, get_llm
from app.models import Connection, QueryRun
from app.routers.deps import connection_url, get_ready_connection
from app.schemas import FixRequest, FixResult, FormatResult, QueryRequest, QueryResultOut
from app.services import target
from app.services.retrieval import retrieve_tables
from app.services.sql_guard import SqlGuardError, format_sql

router = APIRouter(tags=["query"])

FIX_SYSTEM = """You fix broken PostgreSQL SELECT queries. Given the query, the database error and the \
relevant schema, return a corrected read-only query and a one-sentence explanation of what was wrong. \
Keep the query's intent and style; change only what's needed."""


@router.post("/api/connections/{connection_id}/query", response_model=QueryResultOut)
def run_query(
    body: QueryRequest, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)
) -> QueryResultOut:
    try:
        result = target.run_select(connection_url(connection), body.sql)
    except SqlGuardError as exc:
        db.add(QueryRun(connection_id=connection.id, source="editor", sql=body.sql, status="blocked", error=str(exc)))
        db.commit()
        raise HTTPException(status_code=400, detail=f"Blocked: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        message = str(getattr(exc, "pgerror", None) or exc).strip()
        db.add(QueryRun(connection_id=connection.id, source="editor", sql=body.sql, status="error", error=message))
        db.commit()
        raise HTTPException(status_code=400, detail=message) from exc
    db.add(
        QueryRun(
            connection_id=connection.id, source="editor", sql=result.sql, status="ok",
            duration_ms=result.duration_ms, row_count=result.row_count,
        )
    )
    db.commit()
    return QueryResultOut(**result.as_dict())


@router.post("/api/query/format", response_model=FormatResult)
def format_query(body: QueryRequest) -> FormatResult:
    return FormatResult(sql=format_sql(body.sql))


@router.post("/api/connections/{connection_id}/query/fix", response_model=FixResult)
def fix_query(
    body: FixRequest, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)
) -> FixResult:
    tables, _ = retrieve_tables(db, connection.id, f"{body.sql}\n{body.error}")
    schema = "\n\n".join(t.table.summary_text for t in tables)
    prompt = f"Query:\n{body.sql}\n\nError:\n{body.error}\n\nSchema:\n{schema}"
    try:
        return get_llm().generate_structured(FIX_SYSTEM, prompt, FixResult)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
