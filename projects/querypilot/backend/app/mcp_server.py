"""QueryPilot as an MCP server (stdio), so Claude Code / Cursor / any MCP client can query your
databases through the same agent, guard and read-only executor as the web app.

    claude mcp add querypilot -- /ABS/PATH/backend/.venv/bin/python /ABS/PATH/backend/app/mcp_server.py

MCP clients don't set a working directory, so this file can be run by path; backend/.env is
resolved relative to the package (see app/config.py).
"""

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from sqlalchemy import select

from app.database import SessionLocal
from app.llm import LLMError
from app.models import Connection, SchemaRelation, SchemaTable
from app.services import crypto, target
from app.services.agent import run_agent
from app.services.doctor import diagnose
from app.services.retrieval import retrieve_tables

MAX_ROWS_TO_CLIENT = 50

server = MCPServer(
    name="querypilot",
    instructions=(
        "QueryPilot answers questions about the user's connected PostgreSQL databases. "
        "Call list_connections first to get a connection_id. Use ask_database for natural-language "
        "questions (it writes, tests and self-corrects SQL), get_schema to inspect tables, "
        "run_readonly_sql to execute your own SELECT, and analyze_query_performance for slow queries. "
        "All access is read-only."
    ),
)


@contextmanager
def _expected_errors() -> Iterator[None]:
    """Report guard blocks, DB and LLM errors to the calling model (mcp hides other exceptions)."""
    try:
        yield
    except (ValueError, LLMError, psycopg2.Error) as exc:  # SqlGuardError is a ValueError
        raise ToolError(str(getattr(exc, "pgerror", None) or exc).strip()) from exc


def _connection(db, connection_id: int) -> Connection:
    connection = db.get(Connection, connection_id)
    if connection is None:
        raise ValueError(f"No connection with id {connection_id}. Call list_connections.")
    if connection.index_status != "ready":
        raise ValueError(f"Connection {connection_id} is not indexed yet (status: {connection.index_status}).")
    return connection


def _rows_as_records(columns: list[str], rows: list[list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row, strict=True)) for row in rows[:MAX_ROWS_TO_CLIENT]]


@server.tool()
def list_connections() -> list[dict[str, Any]]:
    """List the databases connected in QueryPilot."""
    with SessionLocal() as db:
        return [
            {
                "connection_id": c.id,
                "name": c.name,
                "url": target.redact_url(crypto.decrypt(c.encrypted_url)),
                "status": c.index_status,
                "tables": c.table_count,
            }
            for c in db.scalars(select(Connection).order_by(Connection.id))
        ]


@server.tool()
def get_schema(connection_id: int, table: str | None = None, search: str | None = None) -> str:
    """Describe a database schema.

    With `table`: that table's columns and foreign keys. With `search`: the most relevant tables for
    a topic (semantic + keyword search). With neither: a list of all tables and FK relationships.
    """
    with _expected_errors(), SessionLocal() as db:
        connection = _connection(db, connection_id)
        if table:
            row = db.scalar(
                select(SchemaTable).where(SchemaTable.connection_id == connection.id, SchemaTable.table_name == table)
            )
            return row.summary_text if row else f"Table '{table}' not found."
        if search:
            tables, _ = retrieve_tables(db, connection.id, search)
            return "\n\n".join(t.table.summary_text for t in tables)
        names = db.scalars(
            select(SchemaTable.table_name).where(SchemaTable.connection_id == connection.id).order_by(SchemaTable.table_name)
        )
        rels = db.scalars(select(SchemaRelation).where(SchemaRelation.connection_id == connection.id))
        return "Tables: " + ", ".join(names) + "\n\nForeign keys:\n" + "\n".join(
            f"- {r.from_table}.{r.from_column} → {r.to_table}.{r.to_column}" for r in rels
        )


@server.tool()
def ask_database(connection_id: int, question: str) -> dict[str, Any]:
    """Answer a natural-language question about the data. QueryPilot's agent retrieves the relevant
    schema, writes SQL, tests and self-corrects it, and returns the SQL, explanation and rows."""
    with _expected_errors(), SessionLocal() as db:
        connection = _connection(db, connection_id)
        out: dict[str, Any] = {}
        for event in run_agent(db, connection, question, source="mcp"):
            if event.event == "result":
                out["rows"] = _rows_as_records(event.data["columns"], event.data["rows"])
                out["row_count"] = event.data["rowCount"]
                out["truncated"] = event.data["truncated"] or event.data["rowCount"] > MAX_ROWS_TO_CLIENT
            elif event.event == "answer":
                out.update(sql=event.data["sql"], explanation=event.data["explanation"],
                           attempts=event.data["attempts"])
            elif event.event == "error":
                out["error"] = event.data["message"]
        return out


@server.tool()
def run_readonly_sql(connection_id: int, sql: str) -> dict[str, Any]:
    """Execute one read-only SELECT (validated, read-only transaction, statement timeout)."""
    with _expected_errors():
        with SessionLocal() as db:
            url = crypto.decrypt(_connection(db, connection_id).encrypted_url)
        result = target.run_select(url, sql)
    return {
        "sql": result.sql,
        "rows": _rows_as_records(result.columns, result.rows),
        "row_count": result.row_count,
        "truncated": result.truncated or result.row_count > MAX_ROWS_TO_CLIENT,
        "duration_ms": result.duration_ms,
    }


@server.tool()
def analyze_query_performance(connection_id: int, sql: str, analyze: bool = False) -> str:
    """EXPLAIN a SELECT, diagnose bottlenecks and suggest indexes/rewrites. Suggested indexes are
    measured with hypothetical indexes (hypopg) when available. `analyze=True` runs the query."""
    with _expected_errors(), SessionLocal() as db:
        report = diagnose(db, _connection(db, connection_id), sql, analyze=analyze)
    report.pop("plan", None)
    return json.dumps(report, indent=2, default=str)


def main() -> None:
    server.run("stdio")


if __name__ == "__main__":
    main()
