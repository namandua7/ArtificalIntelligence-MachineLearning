"""Static validation of SQL before it reaches a target database.

This is the first of three safety layers (guard → read-only transaction → read-only DB role).
It only allows a single SELECT (incl. WITH/UNION) and adds a LIMIT when there is none.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

WRITE_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,  # anything sqlglot can't model (COPY, VACUUM, GRANT, SET, ...)
    exp.Into,  # SELECT ... INTO new_table
    exp.Lock,  # SELECT ... FOR UPDATE
)

BLOCKED_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "pg_reload_conf",
    "set_config",
    "pg_advisory_lock",
    "nextval",
    "setval",
}


class SqlGuardError(ValueError):
    pass


@dataclass
class GuardedSql:
    sql: str
    limit_added: bool


def _function_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return node.sql_name().lower()


def guard_select(sql: str, max_rows: int) -> GuardedSql:
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise SqlGuardError("Empty SQL.")

    try:
        statements = [s for s in sqlglot.parse(cleaned, read="postgres") if s is not None]
    except ParseError as exc:
        raise SqlGuardError(f"Could not parse SQL: {exc.errors[0]['description'] if exc.errors else exc}") from exc

    if len(statements) != 1:
        raise SqlGuardError("Only a single statement is allowed.")
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        raise SqlGuardError(f"Only SELECT queries are allowed (got {tree.key.upper()}).")

    for node in tree.walk():
        if isinstance(node, WRITE_NODES):
            raise SqlGuardError(f"Statement contains a disallowed operation: {node.key.upper()}.")
        if isinstance(node, exp.Func) and _function_name(node) in BLOCKED_FUNCTIONS:
            raise SqlGuardError(f"Function {_function_name(node)}() is not allowed.")

    limit_added = False
    if isinstance(tree, exp.Select) and tree.args.get("limit") is None:
        tree = tree.limit(max_rows)
        limit_added = True
        return GuardedSql(sql=tree.sql(dialect="postgres"), limit_added=limit_added)

    # Keep the user's original text (formatting, comments) when we didn't need to change it.
    return GuardedSql(sql=cleaned, limit_added=limit_added)


def guard_create_index(sql: str) -> str:
    """Validate an LLM-suggested CREATE INDEX before passing it to hypopg."""
    cleaned = sql.strip().rstrip(";").strip()
    try:
        statements = [s for s in sqlglot.parse(cleaned, read="postgres") if s is not None]
    except ParseError as exc:
        raise SqlGuardError(f"Could not parse index SQL: {exc}") from exc
    if len(statements) != 1:
        raise SqlGuardError("Expected exactly one CREATE INDEX statement.")
    tree = statements[0]
    if not (isinstance(tree, exp.Create) and str(tree.args.get("kind", "")).upper() == "INDEX"):
        raise SqlGuardError("Only CREATE INDEX statements can be tested.")
    return cleaned


def format_sql(sql: str) -> str:
    try:
        return ";\n\n".join(
            s.sql(dialect="postgres", pretty=True)
            for s in sqlglot.parse(sql, read="postgres")
            if s is not None
        )
    except ParseError:
        return sql
