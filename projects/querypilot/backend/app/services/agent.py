"""The text-to-SQL agent: retrieve schema context, then let the LLM call tools until it
submits `final_answer`. Failed SQL is fed back to the model, which fixes it and retries.

`run_agent` is a generator of `AgentEvent`s so the chat route can stream every step over SSE
while evals and the MCP server consume the same events synchronously.
"""

import queue
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.llm import get_llm
from app.llm.base import AgentMessage, LLMError, LLMTurn, ToolCall, ToolSpec
from app.models import Connection, QueryRun, SchemaTable
from app.services import crypto, target
from app.services.retrieval import RetrievalResult, retrieve, retrieve_tables
from app.services.sql_guard import SqlGuardError, format_sql

MAX_STEPS = 8
MAX_NUDGES = 2
PREVIEW_ROWS = 10
MAX_CELL_CHARS = 120
CATALOG_LIMIT = 300

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="llm")


@dataclass
class AgentEvent:
    event: str
    data: dict[str, Any]


@dataclass
class HistoryTurn:
    question: str
    sql: str | None
    explanation: str


@dataclass
class _State:
    steps: list[dict[str, Any]] = field(default_factory=list)
    attempt: int = 0
    last_ok_sql: str | None = None


TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="search_schema",
        description=(
            "Semantic + keyword search over the database schema. Use when a table or column you "
            "need is not in the provided schema context."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "What you are looking for."}},
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="get_table_details",
        description="Full column list, foreign keys and a few sample rows for one table or view.",
        parameters={
            "type": "object",
            "properties": {"table": {"type": "string", "description": "Table name as listed in the schema."}},
            "required": ["table"],
        },
    ),
    ToolSpec(
        name="run_sql",
        description=(
            "Execute a read-only PostgreSQL SELECT and see the first rows, or the database error. "
            "Use it to test your query (and to check data ranges/values) before answering."
        ),
        parameters={
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "A single PostgreSQL SELECT statement."}},
            "required": ["sql"],
        },
    ),
    ToolSpec(
        name="final_answer",
        description=(
            "Submit the final SQL and a short explanation. The SQL is executed and shown to the user. "
            "Call this exactly once, after the SQL has run successfully."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "Final PostgreSQL SELECT. Empty string only if the question cannot be answered with SQL.",
                },
                "explanation": {
                    "type": "string",
                    "description": (
                        "Markdown for the user, 1-4 sentences: the answer/key finding (if you saw the "
                        "results) and any assumptions you made. Don't repeat the SQL."
                    ),
                },
                "chart": {
                    "type": "object",
                    "description": "How to visualise the result.",
                    "properties": {
                        "type": {"type": "string", "enum": ["bar", "line", "area", "pie", "none"]},
                        "x": {"type": "string", "description": "Result column for the x axis / pie labels."},
                        "y": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Numeric result column(s) to plot.",
                        },
                    },
                    "required": ["type"],
                },
            },
            "required": ["sql", "explanation", "chart"],
        },
    ),
]

SYSTEM_TEMPLATE = """You are QueryPilot, an expert PostgreSQL analyst. You turn questions into correct, \
efficient read-only SQL for the database described below, test it, and answer.

## Rules
- PostgreSQL dialect. Only SELECT / WITH queries; never modify data.
- Use ONLY tables and columns that exist. If unsure about a column, call get_table_details; if a table \
seems missing, call search_schema.
- ALWAYS test your query with run_sql before final_answer. If it errors, read the error, fix the SQL \
and try again. If it returns 0 rows unexpectedly, check your filters (e.g. inspect distinct values).
- For relative dates ("last month", "this year"), the data may be historical: first check the date range \
with run_sql (e.g. SELECT min(col), max(col)) and interpret relative to the latest data. State that assumption.
- Prefer explicit JOINs on the foreign keys listed below. Alias tables. Give computed columns readable \
aliases (e.g. total_revenue). Round money/averages with ROUND(x::numeric, 2).
- For "top N" questions use ORDER BY ... LIMIT N. Otherwise don't add a LIMIT (the system caps rows).
- Return the columns a person needs to understand the answer (names, not just ids).
- chart: use "line"/"area" for time series (x = date/period column), "bar" for comparing categories, \
"pie" only for parts of a whole with <= 8 slices, "none" for single values or wide tables.

## Relevant schema (retrieved for this question)
{schema}

## Join paths (foreign keys)
{relations}

## All tables in this database
{catalog}
{examples}"""

EXAMPLES_TEMPLATE = """
## Verified examples from this database (follow their conventions when relevant)
{items}
"""


def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value


def _build_system_prompt(db: Session, connection_id: int, ctx: RetrievalResult) -> str:
    schema = "\n\n".join(t.table.summary_text for t in ctx.tables) or "(no tables indexed)"
    relations = (
        "\n".join(f"- {r.from_table}.{r.from_column} → {r.to_table}.{r.to_column}" for r in ctx.relations)
        or "(none)"
    )
    names = list(
        db.scalars(
            select(SchemaTable.table_name)
            .where(SchemaTable.connection_id == connection_id)
            .order_by(SchemaTable.table_name)
            .limit(CATALOG_LIMIT)
        )
    )
    catalog = ", ".join(names)
    examples = ""
    if ctx.examples:
        examples = EXAMPLES_TEMPLATE.format(
            items="\n\n".join(f"Q: {e.question}\nSQL:\n{e.sql}" for e in ctx.examples)
        )
    return SYSTEM_TEMPLATE.format(schema=schema, relations=relations, catalog=catalog, examples=examples)


def _history_messages(history: list[HistoryTurn]) -> list[AgentMessage]:
    messages: list[AgentMessage] = []
    for turn in history:
        messages.append(AgentMessage(role="user", text=turn.question))
        answer = turn.explanation
        if turn.sql:
            answer = f"SQL used:\n```sql\n{turn.sql}\n```\n\n{turn.explanation}"
        messages.append(AgentMessage(role="assistant", turn=LLMTurn(text=answer, tool_calls=[])))
    return messages


def _record_run(
    db: Session,
    connection_id: int,
    message_id: int | None,
    source: str,
    attempt: int,
    sql: str,
    status: str,
    error: str | None = None,
    duration_ms: int | None = None,
    row_count: int | None = None,
) -> None:
    db.add(
        QueryRun(
            connection_id=connection_id,
            message_id=message_id,
            source=source,
            attempt=attempt,
            sql=sql,
            status=status,
            error=error,
            duration_ms=duration_ms,
            row_count=row_count,
        )
    )
    db.commit()


def _call_llm(system: str, messages: list[AgentMessage]) -> Generator[AgentEvent, None, LLMTurn]:
    """Run the blocking LLM call in a worker thread, streaming retry notices while we wait."""
    notices: queue.Queue[tuple[float, str]] = queue.Queue()
    llm = get_llm()
    future = _executor.submit(
        llm.chat_with_tools, system, messages, TOOLS, lambda delay, why: notices.put((delay, why))
    )
    while True:
        try:
            delay, why = notices.get(timeout=0.25)
            yield AgentEvent("status", {"text": f"LLM {why}, retrying in {delay:.0f}s…"})
        except queue.Empty:
            pass
        if future.done() and notices.empty():
            return future.result()


def run_agent(
    db: Session,
    connection: Connection,
    question: str,
    history: list[HistoryTurn] | None = None,
    *,
    use_memory: bool = True,
    message_id: int | None = None,
    source: str = "agent",
) -> Generator[AgentEvent, None, None]:
    """Yields: status, retrieval, step, step_result, thought, result, answer, error."""
    url = crypto.decrypt(connection.encrypted_url)
    state = _State()

    def tool_search_schema(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        query = str(args.get("query", "")).strip() or question
        tables, _ = retrieve_tables(db, connection.id, query)
        found = [t.table for t in tables[:5]]
        return (
            {"tables": [t.summary_text for t in found]},
            "Found " + ", ".join(t.table_name for t in found),
        )

    def tool_get_table_details(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        name = str(args.get("table", "")).strip().strip('"')
        table = db.scalar(
            select(SchemaTable).where(
                SchemaTable.connection_id == connection.id, SchemaTable.table_name == name
            )
        )
        if table is None:
            table = db.scalar(
                select(SchemaTable).where(
                    SchemaTable.connection_id == connection.id,
                    SchemaTable.table_name.ilike(f"%{name.split('.')[-1]}"),
                )
            )
        if table is None:
            return {"error": f"Table '{name}' not found. Use search_schema."}, f"'{name}' not found"
        result: dict[str, Any] = {"schema": table.summary_text}
        if settings.allow_sample_rows:
            try:
                sample = target.sample_rows(url, table.table_name, limit=3)
                result["sample_rows"] = [
                    dict(zip(sample.columns, [_truncate(v) for v in row], strict=True)) for row in sample.rows
                ]
            except Exception as exc:  # noqa: BLE001
                result["sample_rows_error"] = str(exc).strip()
        return result, f"Read {table.table_name} ({len(table.columns)} columns)"

    def execute(sql: str, max_rows: int | None = None) -> tuple[target.QueryResult | None, str | None]:
        state.attempt += 1
        try:
            res = target.run_select(url, sql, max_rows=max_rows)
        except SqlGuardError as exc:
            _record_run(db, connection.id, message_id, source, state.attempt, sql, "blocked", str(exc))
            return None, f"Blocked by SQL guard: {exc}"
        except Exception as exc:  # noqa: BLE001 — DB errors are fed back to the model
            message = str(getattr(exc, "pgerror", None) or exc).strip()
            _record_run(db, connection.id, message_id, source, state.attempt, sql, "error", message)
            return None, message
        _record_run(
            db, connection.id, message_id, source, state.attempt, res.sql, "ok",
            duration_ms=res.duration_ms, row_count=res.row_count,
        )
        state.last_ok_sql = sql  # the original, not the copy with run_sql's preview LIMIT
        return res, None

    def tool_run_sql(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        sql = str(args.get("sql", "")).strip()
        res, error = execute(sql, max_rows=200)
        if error is not None:
            return {"ok": False, "error": error}, error
        assert res is not None
        preview = [[_truncate(v) for v in row] for row in res.rows[:PREVIEW_ROWS]]
        return (
            {
                "ok": True,
                "columns": res.columns,
                "rows": preview,
                "row_count": res.row_count,
                "more_rows": res.truncated or res.row_count > PREVIEW_ROWS,
            },
            f"{res.row_count}{'+' if res.truncated else ''} rows in {res.duration_ms} ms",
        )

    handlers = {
        "search_schema": tool_search_schema,
        "get_table_details": tool_get_table_details,
        "run_sql": tool_run_sql,
    }

    try:
        yield AgentEvent("status", {"text": "Searching schema…"})
        ctx = retrieve(db, connection.id, question, use_memory=use_memory)
        yield AgentEvent("retrieval", ctx.summary())

        system = _build_system_prompt(db, connection.id, ctx)
        messages = _history_messages(history or [])
        messages.append(AgentMessage(role="user", text=question))
        nudges = 0

        for step_no in range(1, MAX_STEPS + 1):
            yield AgentEvent("status", {"text": "Thinking…" if step_no == 1 else "Reviewing results…"})
            turn = yield from _call_llm(system, messages)
            messages.append(AgentMessage(role="assistant", turn=turn))
            if turn.text:
                yield AgentEvent("thought", {"text": turn.text})

            if not turn.tool_calls:
                if nudges < MAX_NUDGES:
                    nudges += 1
                    messages.append(
                        AgentMessage(
                            role="user",
                            text="Use the tools: test your SQL with run_sql, then call final_answer.",
                        )
                    )
                    continue
                # Small local models sometimes just answer in prose; accept it rather than fail.
                yield from _finish(state, sql=state.last_ok_sql or "", explanation=turn.text, chart={"type": "none"},
                                   execute=execute)
                return

            results: list[tuple[ToolCall, dict[str, Any]]] = []
            for call in turn.tool_calls:
                step_id = f"s{len(state.steps) + 1}"
                step = {"id": step_id, "tool": call.name, "args": call.args}
                state.steps.append(step)
                yield AgentEvent("step", step)

                if call.name == "final_answer":
                    sql = str(call.args.get("sql", "")).strip()
                    explanation = str(call.args.get("explanation", "")).strip()
                    chart = call.args.get("chart") or {"type": "none"}
                    if not sql:
                        step.update(ok=True, summary="Answered without SQL")
                        yield AgentEvent("step_result", step)
                        yield from _finish(state, sql="", explanation=explanation, chart=chart, execute=execute)
                        return
                    res, error = execute(sql)
                    if error is None and res is not None:
                        step.update(ok=True, summary=f"{res.row_count} rows", durationMs=res.duration_ms)
                        yield AgentEvent("step_result", step)
                        yield from _finish(state, sql=res.sql, explanation=explanation, chart=chart, result=res,
                                           execute=execute)
                        return
                    step.update(ok=False, summary=error, error=error)
                    yield AgentEvent("step_result", step)
                    results.append((call, {"ok": False, "error": f"Final SQL failed: {error}. Fix it and call final_answer again."}))
                    continue

                handler = handlers.get(call.name)
                started = time.perf_counter()
                if handler is None:
                    payload, summary = {"error": f"Unknown tool {call.name}"}, f"Unknown tool {call.name}"
                else:
                    payload, summary = handler(call.args)
                ok = not ("error" in payload or payload.get("ok") is False)
                step.update(ok=ok, summary=summary, durationMs=int((time.perf_counter() - started) * 1000))
                if not ok:
                    step["error"] = summary
                yield AgentEvent("step_result", step)
                results.append((call, payload))

            messages.append(AgentMessage(role="tool", results=results))

        # Out of steps: fall back to the last query that worked, if any.
        if state.last_ok_sql:
            yield from _finish(
                state,
                sql=state.last_ok_sql,
                explanation="I ran out of steps before finalising; this is the last query that ran successfully.",
                chart={"type": "none"},
                execute=execute,
            )
        else:
            yield AgentEvent("error", {"message": "The agent couldn't produce a working query. Try rephrasing.",
                                       "steps": state.steps})
    except LLMError as exc:
        yield AgentEvent("error", {"message": str(exc), "steps": state.steps})
    except Exception as exc:  # noqa: BLE001
        yield AgentEvent("error", {"message": f"{type(exc).__name__}: {exc}", "steps": state.steps})


def _finish(
    state: _State,
    *,
    sql: str,
    explanation: str,
    chart: dict[str, Any],
    execute,
    result: target.QueryResult | None = None,
) -> Generator[AgentEvent, None, None]:
    if sql and result is None:
        result, error = execute(sql)
        if error is not None:
            explanation = f"{explanation}\n\n_Final query failed: {error}_".strip()
    if result is not None:
        result.sql = format_sql(result.sql)
        yield AgentEvent("result", result.as_dict())
    yield AgentEvent(
        "answer",
        {
            "sql": result.sql if result else sql,
            "explanation": explanation,
            "chart": _clean_chart(chart, result),
            "steps": state.steps,
            "attempts": state.attempt,
        },
    )


def _clean_chart(chart: dict[str, Any], result: target.QueryResult | None) -> dict[str, Any]:
    """Drop chart specs that reference columns the result doesn't have."""
    if not result or not isinstance(chart, dict) or chart.get("type") in (None, "none"):
        return {"type": "none"}
    columns = set(result.columns)
    x = chart.get("x")
    y = [c for c in (chart.get("y") or []) if c in columns]
    if x not in columns or not y or result.row_count < 2:
        return {"type": "none"}
    return {"type": chart["type"], "x": x, "y": y}
