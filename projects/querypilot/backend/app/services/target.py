"""Everything that talks to a user's *target* database.

Queries run on a raw DBAPI cursor (not SQLAlchemy `text()`), so `%` and `:name` in user SQL are
never treated as bind parameters. Every query runs inside a READ ONLY transaction with a
statement timeout and is always rolled back.
"""

import base64
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta
from decimal import Decimal
from threading import Lock
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from app.config import settings
from app.services.sql_guard import guard_create_index, guard_select

_engines: dict[str, Engine] = {}
_engines_lock = Lock()


def normalize_url(url: str) -> str:
    parsed = make_url(url.strip())
    if parsed.get_backend_name() not in ("postgresql", "postgres"):
        raise ValueError("Only PostgreSQL connections are supported.")
    return parsed.set(drivername="postgresql+psycopg2").render_as_string(hide_password=False)


def redact_url(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=True)


def get_engine(url: str) -> Engine:
    with _engines_lock:
        engine = _engines.get(url)
        if engine is None:
            engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=3,
                max_overflow=2,
                connect_args={"connect_timeout": 5, "application_name": "querypilot"},
            )
            _engines[url] = engine
        return engine


def dispose_engine(url: str) -> None:
    with _engines_lock:
        engine = _engines.pop(url, None)
    if engine is not None:
        engine.dispose()


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value else None  # NaN → null
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, dt_time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        raw = bytes(value)
        return f"<{len(raw)} bytes> " + base64.b64encode(raw[:24]).decode()
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return str(value)


@dataclass
class QueryResult:
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    duration_ms: int = 0
    limit_added: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "sql": self.sql,
            "columns": self.columns,
            "rows": self.rows,
            "rowCount": self.row_count,
            "truncated": self.truncated,
            "durationMs": self.duration_ms,
            "limitAdded": self.limit_added,
        }


class _ReadOnlyCursor:
    """Context manager: raw cursor inside a READ ONLY transaction that is always rolled back."""

    def __init__(self, url: str, timeout_ms: int | None = None):
        self.url = url
        self.timeout_ms = timeout_ms or settings.statement_timeout_ms

    def __enter__(self):
        self.conn = get_engine(self.url).raw_connection()
        self.cur = self.conn.cursor()
        self.cur.execute("SET TRANSACTION READ ONLY")
        self.cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(self.timeout_ms),))
        return self.cur

    def __exit__(self, *exc):
        try:
            self.cur.close()
            self.conn.rollback()
        finally:
            self.conn.close()
        return False


def run_select(url: str, sql: str, max_rows: int | None = None) -> QueryResult:
    """Validate with the SQL guard, then execute read-only. Raises SqlGuardError or DB errors."""
    max_rows = max_rows or settings.max_result_rows
    guarded = guard_select(sql, max_rows)
    started = time.perf_counter()
    with _ReadOnlyCursor(url) as cur:
        cur.execute(guarded.sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1) if cur.description else []
    duration_ms = int((time.perf_counter() - started) * 1000)
    truncated = len(fetched) > max_rows
    rows = [[to_jsonable(v) for v in row] for row in fetched[:max_rows]]
    return QueryResult(
        sql=guarded.sql,
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        duration_ms=duration_ms,
        limit_added=guarded.limit_added,
    )


def explain(url: str, sql: str, analyze: bool = False) -> dict[str, Any]:
    """EXPLAIN in JSON format. ANALYZE actually runs the query (still read-only + timeout)."""
    guarded = guard_select(sql, settings.max_result_rows)
    options = "ANALYZE, BUFFERS, FORMAT JSON" if analyze else "FORMAT JSON"
    with _ReadOnlyCursor(url) as cur:
        cur.execute(f"EXPLAIN ({options}) {guarded.sql}")
        plan = cur.fetchone()[0]
    return plan[0] if isinstance(plan, list) else plan


def hypopg_available(url: str) -> bool:
    with _ReadOnlyCursor(url) as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'hypopg'")
        return cur.fetchone() is not None


def cost_with_hypothetical_index(url: str, sql: str, index_sql: str) -> tuple[float, float, bool]:
    """Return (cost_before, cost_after, index_used) using a hypopg hypothetical index.

    Hypothetical indexes live only in this backend session's memory; we reset them before the
    connection goes back to the pool.
    """
    guarded = guard_select(sql, settings.max_result_rows)
    index_sql = guard_create_index(index_sql)
    with _ReadOnlyCursor(url) as cur:
        cur.execute(f"EXPLAIN (FORMAT JSON) {guarded.sql}")
        before = cur.fetchone()[0][0]["Plan"]["Total Cost"]
        try:
            cur.execute("SELECT indexname FROM hypopg_create_index(%s)", (index_sql,))
            index_name = cur.fetchone()[0]
            cur.execute(f"EXPLAIN (FORMAT JSON) {guarded.sql}")
            plan = cur.fetchone()[0][0]
        finally:
            cur.execute("SELECT hypopg_reset()")
    after = plan["Plan"]["Total Cost"]
    return float(before), float(after), index_name in str(plan)


def test_connection(url: str) -> str:
    with _ReadOnlyCursor(url, timeout_ms=5000) as cur:
        cur.execute("SELECT version()")
        return cur.fetchone()[0]


# --- Introspection -----------------------------------------------------------------------------

_TABLES_SQL = """
SELECT n.nspname, c.relname,
       CASE WHEN c.relkind IN ('v', 'm') THEN 'view' ELSE 'table' END AS kind,
       obj_description(c.oid, 'pg_class') AS comment,
       GREATEST(c.reltuples, 0)::bigint AS row_estimate
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm')
  AND NOT c.relispartition
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
  AND n.nspname NOT LIKE 'pg_temp%'
  AND has_table_privilege(c.oid, 'SELECT')
ORDER BY n.nspname, c.relname
"""

_COLUMNS_SQL = """
SELECT n.nspname, c.relname, a.attname,
       format_type(a.atttypid, a.atttypmod) AS type,
       NOT a.attnotnull AS nullable,
       col_description(c.oid, a.attnum) AS comment
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE a.attnum > 0 AND NOT a.attisdropped
  AND c.relkind IN ('r', 'p', 'v', 'm') AND NOT c.relispartition
  AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
ORDER BY n.nspname, c.relname, a.attnum
"""

_PK_SQL = """
SELECT n.nspname, c.relname, a.attname
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (con.conkey)
WHERE con.contype = 'p'
"""

_FK_SQL = """
SELECT n.nspname, c.relname, a.attname, fn.nspname, fc.relname, fa.attname
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_class fc ON fc.oid = con.confrelid
JOIN pg_namespace fn ON fn.oid = fc.relnamespace
JOIN LATERAL unnest(con.conkey, con.confkey) AS k(attnum, fattnum) ON true
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = k.attnum
JOIN pg_attribute fa ON fa.attrelid = fc.oid AND fa.attnum = k.fattnum
WHERE con.contype = 'f' AND NOT c.relispartition
"""


@dataclass
class IntrospectedTable:
    schema: str
    name: str
    kind: str
    comment: str | None
    row_estimate: int
    columns: list[dict[str, Any]]

    @property
    def qualified(self) -> str:
        return self.name if self.schema == "public" else f"{self.schema}.{self.name}"


@dataclass
class IntrospectedRelation:
    from_table: str
    from_column: str
    to_table: str
    to_column: str


def _qualify(schema: str, name: str) -> str:
    return name if schema == "public" else f"{schema}.{name}"


def introspect(url: str) -> tuple[list[IntrospectedTable], list[IntrospectedRelation]]:
    with _ReadOnlyCursor(url, timeout_ms=30_000) as cur:
        cur.execute(_TABLES_SQL)
        table_rows = cur.fetchall()
        cur.execute(_COLUMNS_SQL)
        column_rows = cur.fetchall()
        cur.execute(_PK_SQL)
        pk_rows = cur.fetchall()
        cur.execute(_FK_SQL)
        fk_rows = cur.fetchall()

    pks = {(s, t, c) for s, t, c in pk_rows}
    fks: dict[tuple[str, str, str], str] = {}
    relations: list[IntrospectedRelation] = []
    for s, t, c, fs, ft, fc in fk_rows:
        target = _qualify(fs, ft)
        fks[(s, t, c)] = f"{target}.{fc}"
        relations.append(IntrospectedRelation(_qualify(s, t), c, target, fc))

    tables: dict[tuple[str, str], IntrospectedTable] = {}
    for schema, name, kind, comment, row_estimate in table_rows:
        tables[(schema, name)] = IntrospectedTable(schema, name, kind, comment, int(row_estimate), [])

    for schema, name, col, col_type, nullable, comment in column_rows:
        table = tables.get((schema, name))
        if table is None:
            continue
        table.columns.append(
            {
                "name": col,
                "type": col_type,
                "nullable": bool(nullable),
                "pk": (schema, name, col) in pks,
                "fk": fks.get((schema, name, col)),
                "comment": comment,
            }
        )

    known = {t.qualified for t in tables.values()}
    relations = [r for r in relations if r.from_table in known and r.to_table in known]
    return list(tables.values()), relations


def sample_rows(url: str, qualified_table: str, limit: int = 3) -> QueryResult:
    schema, _, name = qualified_table.rpartition(".")
    ident = f'"{schema}"."{name}"' if schema else f'"{name}"'
    return run_select(url, f"SELECT * FROM {ident} LIMIT {int(limit)}")
