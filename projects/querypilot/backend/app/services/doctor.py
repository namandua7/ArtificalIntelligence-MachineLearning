"""Performance Doctor: EXPLAIN a query, have the LLM diagnose the plan (structured output),
then measure each suggested index with a hypopg hypothetical index — no real index is built.
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm import get_llm
from app.models import Connection, SchemaTable
from app.services import crypto, target
from app.services.sql_guard import format_sql


class Suggestion(BaseModel):
    kind: Literal["index", "rewrite", "other"]
    title: str = Field(description="Short imperative title, e.g. 'Index rental(customer_id)'.")
    detail: str = Field(description="Why this helps, referencing plan nodes. 1-3 sentences.")
    sql: str = Field(
        default="",
        description="For kind=index: one CREATE INDEX statement. For kind=rewrite: the full rewritten SELECT. Else empty.",
    )


class Diagnosis(BaseModel):
    summary: str = Field(description="2-3 sentence plain-English explanation of how the query executes and its main cost.")
    bottlenecks: list[str] = Field(description="The most expensive plan steps and why, most important first.")
    suggestions: list[Suggestion] = Field(description="At most 4 concrete improvements, best first.")


SYSTEM = """You are a senior PostgreSQL performance engineer. Given a query, its EXPLAIN (JSON) plan \
and the schema of the tables involved, explain the plan and suggest concrete fixes.
- Only suggest indexes on columns that exist, as valid single CREATE INDEX statements (no CONCURRENTLY, \
no index name needed).
- Don't suggest an index that already exists (primary keys and listed indexes).
- Rewrites must be semantically equivalent SELECTs.
- If the query is already efficient for the data size, say so and keep suggestions minimal."""


def _plan_stats(plan: dict[str, Any]) -> dict[str, Any]:
    root = plan.get("Plan", {})
    return {
        "totalCost": root.get("Total Cost"),
        "planRows": root.get("Plan Rows"),
        "executionMs": plan.get("Execution Time"),
        "planningMs": plan.get("Planning Time"),
    }


def _tables_in_plan(node: dict[str, Any], found: set[str]) -> set[str]:
    if "Relation Name" in node:
        found.add(node["Relation Name"])
    for child in node.get("Plans", []):
        _tables_in_plan(child, found)
    return found


def _compact_plan(node: dict[str, Any]) -> dict[str, Any]:
    """Strip noisy keys so the plan fits comfortably in the prompt."""
    keep = (
        "Node Type", "Relation Name", "Alias", "Index Name", "Join Type", "Strategy",
        "Startup Cost", "Total Cost", "Plan Rows", "Actual Rows", "Actual Total Time", "Actual Loops",
        "Filter", "Index Cond", "Hash Cond", "Merge Cond", "Join Filter", "Rows Removed by Filter",
        "Sort Key", "Group Key", "Sort Method", "Shared Hit Blocks", "Shared Read Blocks",
    )
    out = {k: node[k] for k in keep if k in node}
    if node.get("Plans"):
        out["Plans"] = [_compact_plan(child) for child in node["Plans"]]
    return out


def diagnose(db: Session, connection: Connection, sql: str, analyze: bool) -> dict[str, Any]:
    url = crypto.decrypt(connection.encrypted_url)
    plan = target.explain(url, sql, analyze=analyze)

    tables = _tables_in_plan(plan.get("Plan", {}), set())
    summaries = list(
        db.scalars(
            select(SchemaTable.summary_text).where(
                SchemaTable.connection_id == connection.id,
                SchemaTable.table_name.in_(tables),
            )
        )
    )
    prompt = (
        f"Query:\n{format_sql(sql)}\n\n"
        f"EXPLAIN{' ANALYZE' if analyze else ''} plan:\n{json.dumps(_compact_plan(plan.get('Plan', {})), indent=1)}\n\n"
        f"Schema of tables involved:\n" + "\n\n".join(summaries)
    )
    diagnosis = get_llm().generate_structured(SYSTEM, prompt, Diagnosis)

    has_hypopg = target.hypopg_available(url)
    suggestions: list[dict[str, Any]] = []
    for s in diagnosis.suggestions[:4]:
        item = s.model_dump()
        if s.kind == "index" and s.sql and has_hypopg:
            try:
                before, after, used = target.cost_with_hypothetical_index(url, sql, s.sql)
                item["hypothetical"] = {
                    "costBefore": round(before, 2),
                    "costAfter": round(after, 2),
                    "improvementPct": round((1 - after / before) * 100, 1) if before else 0.0,
                    "indexUsed": used,
                }
            except Exception as exc:  # noqa: BLE001 — guard or DB error, shown on the card
                item["hypotheticalError"] = str(exc).strip()
        elif s.kind == "rewrite" and s.sql:
            try:
                rewritten = target.explain(url, s.sql, analyze=False)
                before = plan.get("Plan", {}).get("Total Cost")
                after = rewritten.get("Plan", {}).get("Total Cost")
                if before and after is not None:
                    item["rewriteCost"] = {
                        "costBefore": round(before, 2),
                        "costAfter": round(after, 2),
                        "improvementPct": round((1 - after / before) * 100, 1),
                    }
            except Exception as exc:  # noqa: BLE001 — guard or DB error, shown on the card
                item["rewriteError"] = str(exc).strip()
        suggestions.append(item)

    return {
        "plan": plan,
        "stats": _plan_stats(plan),
        "summary": diagnosis.summary,
        "bottlenecks": diagnosis.bottlenecks,
        "suggestions": suggestions,
        "hypopg": has_hypopg,
    }
