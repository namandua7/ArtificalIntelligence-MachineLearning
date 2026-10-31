"""The text-to-SQL agent: retrieve schema context, then let the LLM call tools until it
submits `final_answer`. Failed SQL is fed back to the model, which fixes it and retries.

`run_agent` is a generator of `AgentEvent`s so the chat route can stream every step over SSE
while evals and the MCP server consume the same events synchronously.
"""

import contextvars
import queue
import re
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.llm import get_llm
from app.llm.base import AgentMessage, LLMError, LLMOutputError, LLMTurn, ToolCall, ToolSpec, usage_sink
from app.models import Connection, QueryRun, SchemaTable
from app.services import cache, consistency, crypto, sandbox, target
from app.services.drivers import DriverError, compute_drivers
from app.services.glossary import prompt_block
from app.services.retrieval import RetrievalResult, retrieve, retrieve_tables
from app.services.schema_text import compact_table
from app.services.sql_guard import SqlGuardError, format_sql

MAX_STEPS = 6
MAX_NUDGES = 2
PREVIEW_ROWS = 5  # rows of a run_sql result shown to the model (the user always sees the full result)
MAX_CELL_CHARS = 60
CATALOG_LIMIT = 60  # names of tables NOT already in the prompt; the rest are reachable via search_schema
EXPLANATION_CHARS = 240  # per history turn

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
    started: float = field(default_factory=time.perf_counter)
    retrieval_ms: int = 0
    llm_ms: int = 0
    llm_calls: int = 0
    sql_ms: int = 0
    # Events raised by tool handlers (analysis, drivers); flushed by the loop after each handler.
    events: list[AgentEvent] = field(default_factory=list)
    analyses: list[dict[str, Any]] = field(default_factory=list)
    drivers: list[dict[str, Any]] = field(default_factory=list)
    confidence: dict[str, Any] | None = None
    tokens: dict[str, int] = field(default_factory=lambda: {"in": 0, "out": 0})

    def timing(self) -> dict[str, int]:
        total = int((time.perf_counter() - self.started) * 1000)
        return {
            "totalMs": total,
            "retrievalMs": self.retrieval_ms,
            "llmMs": self.llm_ms,
            "llmCalls": self.llm_calls,
            "sqlMs": self.sql_ms,
            "tokensIn": self.tokens["in"],
            "tokensOut": self.tokens["out"],
            "otherMs": max(total - self.retrieval_ms - self.llm_ms - self.sql_ms, 0),
        }


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
        name="find_values",
        description=(
            "Look up the exact stored values of a text column, optionally filtered by a fuzzy search "
            "('sci fi' finds 'Sci-Fi'). Use before filtering on a text column whose values you aren't sure of."
        ),
        parameters={
            "type": "object",
            "properties": {
                "table": {"type": "string"},
                "column": {"type": "string"},
                "search": {"type": "string", "description": "Optional words to look for."},
            },
            "required": ["table", "column"],
        },
    ),
    ToolSpec(
        name="analyze_drivers",
        description=(
            "Explain WHY a metric changed between two periods. Pass a SELECT that returns exactly three "
            "columns for ONE dimension: the segment (e.g. category), the period (two distinct values, e.g. "
            "'2024-02' and '2024-03'), and the numeric value. The tool computes each segment's contribution "
            "to the change. Call it once per plausible dimension (2-4 dimensions)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SELECT returning segment, period, value."},
                "dimension": {"type": "string", "description": "Name of the segment column."},
            },
            "required": ["sql"],
        },
    ),
    ToolSpec(
        name="run_python",
        description=(
            "Run pandas/numpy on a query result for analysis SQL does poorly: correlation, growth rates, "
            "moving averages, percentiles, outliers, cohort retention, linear forecasts (np.polyfit). The "
            "result is available as DataFrame `df`; date-like and numeric columns are already typed. Put the "
            "answer in a variable named `result` (DataFrame, dict or number) and/or print it. No file or "
            "network access; only pandas, numpy, math, statistics, datetime may be imported."
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code using `df`; assign `result`."},
                "sql": {
                    "type": "string",
                    "description": "SELECT whose result becomes `df`. Defaults to the last query that ran successfully.",
                },
            },
            "required": ["code"],
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

SYSTEM_TEMPLATE = """You are QueryPilot, a PostgreSQL analyst. Answer with correct read-only SQL for this database.

Rules:
- PostgreSQL; SELECT/WITH only. Use only the tables/columns listed (get_table_details / search_schema if unsure).
- Test with run_sql before final_answer; on an error or unexpected 0 rows, fix the SQL and retry.
- Data may be historical: for relative dates check min/max first and state the assumption.
- Explicit JOINs via the → foreign keys, table aliases, readable aliases, ROUND(x::numeric, 2) for money/averages. \
"Top N" → ORDER BY … LIMIT N, otherwise no LIMIT. Return names, not just ids.
- {{a|b}} after a column lists its stored values: use those exact spellings, else call find_values.
- Business definitions (if present) override your own interpretation.
{extra_rules}- chart: line/area for time series, bar for categories, pie for ≤8 parts, none for single values or wide tables.

Schema (table (~rows): column type PK →foreign_key{{values}}):
{schema}
{catalog}{examples}{glossary}"""

FAST_TEMPLATE = """You are QueryPilot, a PostgreSQL analyst. Write ONE correct read-only SQL query for the question.

Rules:
- PostgreSQL; a single SELECT/WITH. Use only the tables/columns listed.
- Explicit JOINs via the → foreign keys, table aliases, readable aliases for computed columns, \
ROUND(x::numeric, 2) for money/averages. "Top N" → ORDER BY … LIMIT N, otherwise no LIMIT. Return names, not just ids.
- {{a|b}} after a column lists its stored values: use those exact spellings in filters.
- Business definitions (if present) are authoritative.
- explanation: one short sentence stating any assumption (empty if none).
- chart: line/area for time series, bar for categories, pie for ≤8 parts, none for single values or wide tables.

Schema (table (~rows): column type PK →foreign_key{{values}}):
{schema}
{catalog}{examples}{glossary}"""

EXAMPLES_TEMPLATE = """
Verified examples (follow their conventions):
{items}
"""


class FastAnswer(BaseModel):
    """Single-call answer: the common case needs one LLM call, not a tool loop."""

    sql: str = Field(description="One PostgreSQL SELECT statement.")
    explanation: str = Field(default="", description="One short sentence with any assumption, or empty.")
    chart_type: Literal["bar", "line", "area", "pie", "none"] = "none"
    chart_x: str = ""
    chart_y: list[str] = Field(default_factory=list)


# Specialist tools (and the prompt rules for them) are offered only when the question calls for them:
# every extra tool makes small local models less reliable at the basic run_sql → final_answer loop.
_ANALYSIS_RE = re.compile(
    r"correlat|forecast|predict|project(ion|ed)|growth|moving average|rolling|percentile|outlier|median|"
    r"std\b|standard deviation|variance|cohort|retention|regression|statistic|trend ?line|year[- ]over[- ]year|"
    r"month[- ]over[- ]month|\byoy\b|\bmom\b",
    re.IGNORECASE,
)
_DRIVERS_RE = re.compile(
    r"\bwhy\b|root cause|\bcaus(e|ed|es)\b|\breason\b|\bdriver|what happened|explain (the )?(drop|dip|rise|spike|change|decline)|"
    r"\b(drop|dropped|fell|fall|decline|declined|dip|dipped|spike|spiked|surge|jump)\b",
    re.IGNORECASE,
)
RULE_PYTHON = "- For statistics SQL does poorly (correlation, growth, forecast, outliers, cohorts): get the data with SQL, then run_python; report its printed numbers.\n"
RULE_DRIVERS = '- For "why did X change": fix the two periods, then call analyze_drivers once per plausible dimension and explain from the measured contributions.\n'


def _wants(question: str) -> tuple[bool, bool]:
    """(needs run_python, needs analyze_drivers)"""
    return (
        settings.sandbox_enabled and bool(_ANALYSIS_RE.search(question)),
        bool(_DRIVERS_RE.search(question)),
    )

def _truncate(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
        return value[:MAX_CELL_CHARS] + "…"
    return value


def _build_system_prompt(
    db: Session, connection_id: int, ctx: RetrievalResult, question: str = "", fast: bool = False
) -> str:
    schema = "\n".join(
        compact_table(
            t.table.table_name, t.table.kind, t.table.columns, t.table.row_estimate, t.table.comment,
            t.table.value_profiles,
        )
        for t in ctx.tables
    ) or "(no tables indexed)"
    shown = {t.table.table_name for t in ctx.tables}
    names = list(
        db.scalars(
            select(SchemaTable.table_name)
            .where(SchemaTable.connection_id == connection_id, SchemaTable.table_name.notin_(shown))
            .order_by(SchemaTable.table_name)
            .limit(CATALOG_LIMIT + 1)
        )
    )
    catalog = ""
    if names:
        more = ", … (use search_schema)" if len(names) > CATALOG_LIMIT else ""
        catalog = "Other tables: " + ", ".join(names[:CATALOG_LIMIT]) + more + "\n"
    examples = ""
    if ctx.examples:
        examples = EXAMPLES_TEMPLATE.format(
            items="\n".join(f"Q: {e.question}\nSQL: {' '.join(e.sql.split())}" for e in ctx.examples)
        )
    python, drivers = _wants(question)
    return (FAST_TEMPLATE if fast else SYSTEM_TEMPLATE).format(
        schema=schema,
        catalog=catalog,
        examples=examples,
        glossary=prompt_block(ctx.terms),
        extra_rules=(RULE_PYTHON if python else "") + (RULE_DRIVERS if drivers else ""),
    )


def _history_messages(history: list[HistoryTurn]) -> list[AgentMessage]:
    messages: list[AgentMessage] = []
    for turn in history:
        messages.append(AgentMessage(role="user", text=turn.question))
        answer = turn.explanation[:EXPLANATION_CHARS]
        if turn.sql:
            answer = f"SQL used: {' '.join(turn.sql.split())}\n{answer}"
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


def _tools(question: str) -> list[ToolSpec]:
    python, drivers = _wants(question)
    hidden = {name for name, wanted in (("run_python", python), ("analyze_drivers", drivers)) if not wanted}
    return [t for t in TOOLS if t.name not in hidden]


def _blocking(state: _State, fn, *args) -> Generator[AgentEvent, None, Any]:
    """Run a blocking LLM call (`fn(*args, on_retry)`) in a worker thread, streaming retry notices while we
    wait and charging its time and tokens to `state`."""
    notices: queue.Queue[tuple[float, str]] = queue.Queue()
    started = time.perf_counter()
    ctx = contextvars.copy_context()  # worker threads don't inherit context; carry the token counter over
    ctx.run(usage_sink.set, state.tokens)
    future = _executor.submit(ctx.run, fn, *args, lambda delay, why: notices.put((delay, why)))
    try:
        while True:
            try:
                delay, why = notices.get(timeout=0.25)
                yield AgentEvent("status", {"text": f"LLM {why}, retrying in {delay:.0f}s…"})
            except queue.Empty:
                pass
            if future.done() and notices.empty():
                return future.result()
    finally:
        state.llm_ms += int((time.perf_counter() - started) * 1000)
        state.llm_calls += 1


def _call_llm(
    system: str, messages: list[AgentMessage], model: str | None, state: _State, tools: list[ToolSpec]
) -> Generator[AgentEvent, None, LLMTurn]:
    return (yield from _blocking(state, get_llm(model).chat_with_tools, system, messages, tools))


def _fast_prompt(question: str, history: list[HistoryTurn] | None) -> str:
    if not history:
        return question
    earlier = "\n".join(
        f"Q: {t.question}\nSQL: {' '.join(t.sql.split())}" for t in (history or [])[-2:] if t.sql
    )
    return f"Earlier in this chat:\n{earlier}\n\nNew question (may refer to the above): {question}" if earlier else question


def _run_agent(
    db: Session,
    connection: Connection,
    question: str,
    history: list[HistoryTurn] | None,
    *,
    use_memory: bool,
    message_id: int | None,
    source: str,
    verify_on: bool,
    model: str | None,
) -> Generator[AgentEvent, None, None]:
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

    def find_table(raw: Any) -> tuple[SchemaTable | None, str]:
        name = str(raw or "").strip().strip('"')
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
        return table, name

    def tool_get_table_details(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        table, name = find_table(args.get("table"))
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
        started = time.perf_counter()
        try:
            res = target.run_select(url, sql, max_rows=max_rows)
        except SqlGuardError as exc:
            _record_run(db, connection.id, message_id, source, state.attempt, sql, "blocked", str(exc))
            return None, f"Blocked by SQL guard: {exc}"
        except Exception as exc:  # noqa: BLE001 — DB errors are fed back to the model
            message = str(getattr(exc, "pgerror", None) or exc).strip()
            _record_run(db, connection.id, message_id, source, state.attempt, sql, "error", message)
            return None, message
        state.sql_ms += int((time.perf_counter() - started) * 1000)
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

    def tool_find_values(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        if not settings.allow_sample_rows:
            return {"error": "Value lookup is disabled (ALLOW_SAMPLE_ROWS=false)."}, "Value lookup disabled"
        table, name = find_table(args.get("table"))
        if table is None:
            return {"error": f"Table '{name}' not found. Use search_schema."}, f"'{name}' not found"
        column = str(args.get("column", "")).strip().strip('"')
        known = [c["name"] for c in table.columns]
        if column not in known:
            msg = f"Column '{column}' not in {table.table_name}. Columns: {', '.join(known)}"
            return {"error": msg}, f"No column '{column}'"
        search = str(args.get("search", "")).strip() or None
        try:
            values = target.find_values(url, table.table_name, column, search)
        except Exception as exc:  # noqa: BLE001
            message = str(getattr(exc, "pgerror", None) or exc).strip()
            return {"error": message}, message
        return (
            {"table": table.table_name, "column": column, "values": [_truncate(v) for v in values]},
            f"{len(values)} value(s) in {table.table_name}.{column}",
        )

    def tool_run_python(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        code = str(args.get("code", "")).strip()
        if not code:
            return {"ok": False, "error": "No code given."}, "No code given"
        sql = str(args.get("sql", "")).strip() or state.last_ok_sql
        if not sql:
            msg = "Run a SQL query first (run_sql), or pass `sql`: the analysis needs data."
            return {"ok": False, "error": msg}, msg
        res, error = execute(sql, max_rows=settings.max_result_rows)
        if error is not None or res is None:
            return {"ok": False, "error": error}, error or "query failed"
        out = sandbox.run_python(code, res.columns, res.rows)
        analysis = {"code": code, "sql": format_sql(res.sql), "inputRows": res.row_count, **out.as_dict()}
        state.analyses.append(analysis)
        state.events.append(AgentEvent("analysis", analysis))
        table = out.table
        if table and len(table["rows"]) > 20:
            table = {**table, "rows": table["rows"][:20], "truncated": True}
        payload = {"ok": out.ok, "stdout": out.stdout[:3000], "error": out.error, "value": out.value, "table": table}
        return payload, ("Analysis ran" if out.ok else out.error or "Analysis failed")

    def tool_analyze_drivers(args: dict[str, Any]) -> tuple[dict[str, Any], str]:
        sql = str(args.get("sql", "")).strip()
        res, error = execute(sql, max_rows=settings.max_result_rows)
        if error is not None or res is None:
            return {"ok": False, "error": error}, error or "query failed"
        try:
            drivers = compute_drivers(res.columns, res.rows, str(args.get("dimension", "")).strip() or None)
        except DriverError as exc:
            return {"ok": False, "error": str(exc)}, str(exc)
        drivers["sql"] = format_sql(res.sql)
        state.drivers.append(drivers)
        state.events.append(AgentEvent("drivers", drivers))
        lead = drivers["drivers"][0] if drivers["drivers"] else None
        summary = f"by {drivers['dimension']}: {drivers['delta']:+,.2f}" + (f", mostly {lead['segment']}" if lead else "")
        return {"ok": True, **{k: v for k, v in drivers.items() if k not in ("sql", "drivers")},
                "drivers": drivers["drivers"][:6]}, summary

    handlers = {
        "search_schema": tool_search_schema,
        "get_table_details": tool_get_table_details,
        "find_values": tool_find_values,
        "run_sql": tool_run_sql,
        "analyze_drivers": tool_analyze_drivers,
        "run_python": tool_run_python,
    }

    try:
        yield AgentEvent("status", {"text": "Searching schema…"})
        started = time.perf_counter()
        ctx = retrieve(db, connection.id, question, use_memory=use_memory)
        state.retrieval_ms = int((time.perf_counter() - started) * 1000)
        yield AgentEvent("retrieval", {**ctx.summary(), "durationMs": state.retrieval_ms})

        tools = _tools(question)

        def cross_check(res: target.QueryResult, system_prompt: str) -> Generator[AgentEvent, None, None]:
            if not (verify_on and res.row_count > 0):
                return
            yield AgentEvent("status", {"text": "Cross-checking with independent attempts…"})
            started_check = time.perf_counter()
            state.confidence = consistency.check(
                system=system_prompt, question=question, primary=res, url=url, model=model, sink=state.tokens
            )
            state.confidence["durationMs"] = int((time.perf_counter() - started_check) * 1000)
            state.llm_ms += state.confidence["durationMs"]
            yield AgentEvent("confidence", state.confidence)

        # Fast path: one structured LLM call writes the SQL, which we run ourselves. The multi-step tool loop
        # (which re-sends the whole prompt every turn) is only needed when that attempt fails.
        seed: str | None = None
        if settings.fast_path and not any(_wants(question)):
            fast_system = _build_system_prompt(db, connection.id, ctx, question, fast=True)
            yield AgentEvent("status", {"text": "Writing SQL…"})
            try:
                fast = yield from _blocking(
                    state, get_llm(model).generate_structured, fast_system, _fast_prompt(question, history), FastAnswer
                )
            except LLMOutputError:
                fast = None  # malformed output (common on tiny local models): use the tool loop instead
            sql = fast.sql.strip() if fast else ""
            if sql:
                chart = {"type": fast.chart_type, "x": fast.chart_x, "y": fast.chart_y}
                step = {"id": "s1", "tool": "final_answer", "args": {"sql": sql, "explanation": fast.explanation, "chart": chart}}
                state.steps.append(step)
                yield AgentEvent("step", step)
                res, error = execute(sql)
                if error is None and res is not None and res.row_count > 0:
                    step.update(ok=True, summary=f"{res.row_count} rows", durationMs=res.duration_ms)
                    yield AgentEvent("step_result", step)
                    yield from cross_check(res, fast_system)
                    yield from _finish(state, sql=res.sql, explanation=fast.explanation, chart=chart, result=res,
                                       execute=execute)
                    return
                problem = error or "it returned 0 rows (check the filters; use find_values for exact spellings)"
                step.update(ok=False, summary=problem, error=problem)
                yield AgentEvent("step_result", step)
                seed = (
                    f"{question}\n\nA first attempt failed.\nSQL: {sql}\nProblem: {problem}\n"
                    "Fix it: test with run_sql, then call final_answer."
                )

        system = _build_system_prompt(db, connection.id, ctx, question)
        messages = _history_messages(history or [])
        messages.append(AgentMessage(role="user", text=seed or question))
        nudges = 0

        for step_no in range(1, MAX_STEPS + 1):
            yield AgentEvent("status", {"text": "Thinking…" if step_no == 1 else "Reviewing results…"})
            turn = yield from _call_llm(system, messages, model, state, tools)
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
                        yield from cross_check(res, system)
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
                for pending in state.events:
                    yield pending
                state.events.clear()
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
            "timing": state.timing(),
            "confidence": state.confidence,
            "analyses": state.analyses,
            "drivers": state.drivers,
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


def run_agent(
    db: Session,
    connection: Connection,
    question: str,
    history: list[HistoryTurn] | None = None,
    *,
    use_memory: bool = True,
    message_id: int | None = None,
    source: str = "agent",
    verify: bool | None = None,
    model: str | None = None,
    use_cache: bool | None = None,
) -> Generator[AgentEvent, None, None]:
    """Yields: status, retrieval, step, step_result, thought, result, analysis, drivers, confidence,
    answer, error.

    `verify` runs self-consistency (None = per settings), `model` overrides the chat model (evals
    compare models), `use_cache` defaults to on for first-turn questions outside evals.
    """
    verify_on = consistency.enabled(verify)
    cacheable = use_cache if use_cache is not None else (not history and use_memory and model is None and source != "eval")
    flavour = f"verify={int(verify_on)}"

    if cacheable:
        started = time.perf_counter()
        cached = cache.get(connection.id, question, flavour)
        if cached is not None:
            yield AgentEvent("status", {"text": "Answered from cache"})
            for event in cached:
                if event.event == "answer":
                    ms = int((time.perf_counter() - started) * 1000)
                    event = AgentEvent(
                        "answer",
                        {**event.data, "cached": True, "timing": {**event.data.get("timing", {}), "totalMs": ms, "cachedMs": ms}},
                    )
                yield event
            return

    recorded: list[AgentEvent] = []
    failed = False
    for event in _run_agent(
        db, connection, question, history,
        use_memory=use_memory, message_id=message_id, source=source, verify_on=verify_on, model=model,
    ):
        if event.event in ("status", "thought"):
            pass
        else:
            recorded.append(event)
        failed = failed or event.event == "error"
        yield event
    if cacheable and not failed and any(e.event == "answer" for e in recorded):
        cache.put(connection.id, question, recorded, flavour)
