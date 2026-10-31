"""Column value profiling: which columns are worth listing values for, and doing it cheaply.

For low-cardinality text/enum/boolean columns (ratings, statuses, categories, countries…) we store
the distinct values with the table's summary. The embedded summary then matches "PG-13" or
"Sci-Fi", and the LLM sees the exact stored spelling instead of guessing it.

Privacy: values are sent to the LLM like sample rows are, so this honours ALLOW_SAMPLE_ROWS, and
columns whose names suggest personal data are never profiled.
"""

import logging
import re
import time

from app.config import settings
from app.services import target

logger = logging.getLogger(__name__)

TEXT_TYPES = ("character varying", "character", "text", "citext", "boolean", "bpchar", "name")
SENSITIVE = re.compile(
    r"(e_?mail|phone|mobile|pass(word|wd)?|secret|token|ssn|card|iban|salary|birth|dob|address|ip_?addr|"
    r"first_?name|last_?name|full_?name|surname|user_?name|login|api_?key|hash|license|passport)",
    re.IGNORECASE,
)
MAX_VALUE_CHARS = 40
MAX_SCAN_ROWS = 5_000_000  # without planner stats, only scan tables up to this size
TIME_BUDGET_S = 90


def is_candidate(column: dict) -> bool:
    """Cheap, catalog-only check: text-like or enum column that is neither key nor sensitive."""
    if column["pk"] or column["fk"] or SENSITIVE.search(column["name"]):
        return False
    col_type = column["type"].lower()
    if "[" in col_type:  # arrays
        return False
    if col_type.startswith(TEXT_TYPES) or col_type in TEXT_TYPES:
        return True
    # Enums report their type name (e.g. "mpaa_rating"); anything not a known built-in family.
    builtin = ("int", "bigint", "smallint", "numeric", "decimal", "real", "double", "date", "time", "timestamp",
               "interval", "uuid", "json", "bytea", "oid", "money", "inet", "cidr", "xml", "tsvector", "bit",
               "point", "box", "array")
    return not any(col_type.startswith(b) for b in builtin) and "[" not in col_type and "(" not in col_type


def plausible(estimate: float | None, row_estimate: int, max_distinct: int) -> bool:
    """Use planner stats to skip high-cardinality columns without scanning the table."""
    if estimate is None:  # never analyzed: only scan small tables
        return row_estimate <= MAX_SCAN_ROWS // 100
    if estimate < 0:  # negative = fraction of rows that are distinct
        return abs(estimate) * max(row_estimate, 1) <= max_distinct
    return 0 < estimate <= max_distinct


def clean_values(values: list[str], max_distinct: int) -> list[str] | None:
    """None when the column turned out to be high-cardinality or holds long free text."""
    if len(values) > max_distinct:
        return None
    cleaned = [v.strip() for v in values if v is not None and v.strip()]
    if not cleaned or any(len(v) > MAX_VALUE_CHARS for v in cleaned):
        return None
    return cleaned


def profile_tables(url: str, tables: list[target.IntrospectedTable]) -> dict[str, dict[str, list[str]]]:
    """qualified table name → {column: [distinct values]}. Never raises: profiling is best-effort."""
    if not (settings.profile_values and settings.allow_sample_rows):
        return {}
    started = time.perf_counter()
    max_distinct = settings.profile_max_distinct
    try:
        estimates = target.column_distinct_estimates(url)
    except Exception:  # noqa: BLE001
        logger.warning("Could not read pg_stats; profiling small tables only", exc_info=True)
        estimates = {}

    out: dict[str, dict[str, list[str]]] = {}
    scanned = 0
    for table in tables:
        if table.kind != "table":
            continue
        for col in table.columns:
            if scanned >= settings.profile_max_columns or time.perf_counter() - started > TIME_BUDGET_S:
                logger.info("Value profiling stopped early after %d columns", scanned)
                return out
            if not is_candidate(col):
                continue
            if col["type"].lower() == "boolean":
                out.setdefault(table.qualified, {})[col["name"]] = ["true", "false"]
                continue
            if not plausible(estimates.get((table.schema, table.name, col["name"])), table.row_estimate, max_distinct):
                continue
            scanned += 1
            try:
                values = target.distinct_values(url, table.qualified, col["name"], max_distinct + 1)
            except Exception:  # noqa: BLE001 — timeouts / permissions on one column shouldn't stop the rest
                continue
            cleaned = clean_values(values, max_distinct)
            if cleaned:
                out.setdefault(table.qualified, {})[col["name"]] = cleaned
    logger.info("Profiled %d columns in %.1fs", scanned, time.perf_counter() - started)
    return out
