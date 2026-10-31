"""Compact, token-cheap schema text for the LLM prompt.

The stored `summary_text` (one line per column, full type names, FK notes) is good for embedding and for
`get_table_details`, but it is ~3x bigger than the model needs to write a query. This renders a table as
one dense line:

    film (~1,000): film_id int PK, title varchar, language_id int→language.language_id, rating mpaa_rating{G|PG|R}, ...

Foreign keys stay inline as `→table.col`, so no separate join-path section is needed.
"""

from typing import Any

MAX_COLUMNS = 40
MAX_VALUES = 8
MAX_COMMENT = 80

_TYPES = {
    "character varying": "varchar",
    "character": "char",
    "integer": "int",
    "smallint": "smallint",
    "bigint": "bigint",
    "boolean": "bool",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamptz",
    "time without time zone": "time",
    "time with time zone": "timetz",
    "double precision": "float8",
    "numeric": "numeric",
    "text": "text",
}


def short_type(pg_type: str) -> str:
    base, paren, rest = pg_type.partition("(")
    base = base.strip()
    arrays = ""
    while base.endswith("[]"):
        base, arrays = base[:-2].strip(), arrays + "[]"
    short = _TYPES.get(base, base)
    # keep numeric(p,s) (it tells you about money/precision); drop varchar(255) lengths
    return f"{short}({rest.rstrip(')')})" + arrays if paren and short == "numeric" else short + arrays


def compact_table(
    name: str,
    kind: str,
    columns: list[dict[str, Any]],
    row_estimate: int | None = None,
    comment: str | None = None,
    values: dict[str, list[str]] | None = None,
) -> str:
    values = values or {}
    parts = []
    for col in columns[:MAX_COLUMNS]:
        piece = f"{col['name']} {short_type(col['type'])}"
        if col.get("pk"):
            piece += " PK"
        if col.get("fk"):
            piece += f"→{col['fk']}"
        vals = values.get(col["name"])
        if vals:
            shown = "|".join(vals[:MAX_VALUES]) + ("|…" if len(vals) > MAX_VALUES else "")
            piece += "{" + shown + "}"
        parts.append(piece)
    if len(columns) > MAX_COLUMNS:
        parts.append(f"…+{len(columns) - MAX_COLUMNS} more columns (get_table_details)")
    head = f"{'VIEW ' if kind == 'view' else ''}{name}"
    if kind == "table" and row_estimate:
        head += f" (~{row_estimate:,})"
    note = f" -- {comment.strip()[:MAX_COMMENT]}" if comment and comment.strip() else ""
    return f"{head}{note}: " + ", ".join(parts)
