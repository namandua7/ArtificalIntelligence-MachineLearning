"""Self-consistency: write the query independently a few more times and see whether the results agree.

NL→SQL fails silently: a plausible but wrong query returns plausible but wrong numbers. When two or
three independent attempts (higher temperature, no sight of the primary SQL) return the same values,
the answer is very likely right; when they differ the user is told, and shown the other readings.
"""

import contextvars
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import get_llm
from app.llm.base import LLMError, usage_sink
from app.services import target
from app.services.compare import results_equivalent

PROMPT = """Write one PostgreSQL SELECT query that answers the question below, using only the schema in \
your instructions. Think independently about the most direct, correct way to answer it. Prefer \
explicit joins on the listed foreign keys. Return the columns a person needs (names, not just ids).

Question: {question}"""


class Candidate(BaseModel):
    sql: str = Field(description="A single PostgreSQL SELECT statement, no commentary.")


@dataclass
class Alternative:
    sql: str
    status: str  # agrees | differs | error
    row_count: int | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"sql": self.sql, "status": self.status, "rowCount": self.row_count, "error": self.error}


def enabled(verify: bool | None) -> bool:
    if verify is not None:
        return verify
    if settings.self_consistency == "on":
        return True
    if settings.self_consistency == "off":
        return False
    return settings.llm_provider == "gemini"  # auto: local models are too slow to run it by default


def level(agreeing: int, total: int) -> str:
    if total == 0:
        return "unverified"
    if agreeing == total:
        return "high"
    return "medium" if agreeing > 0 else "low"


def _generate(system: str, question: str, model: str | None) -> str | None:
    try:
        return get_llm(model).generate_structured(
            system, PROMPT.format(question=question), Candidate, temperature=0.8
        ).sql.strip() or None
    except LLMError:
        return None


def check(
    *,
    system: str,
    question: str,
    primary: target.QueryResult,
    url: str,
    model: str | None = None,
    n: int | None = None,
    generate: Callable[[str, str, str | None], str | None] = _generate,
    sink: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Run `n` independent candidates and compare each against `primary`. Never raises."""
    n = settings.consistency_candidates if n is None else n
    def attempt(_: int) -> str | None:
        ctx = contextvars.copy_context()  # pool threads need the caller's token counter
        if sink is not None:
            ctx.run(usage_sink.set, sink)
        return ctx.run(generate, system, question, model)

    with ThreadPoolExecutor(max_workers=max(n, 1)) as pool:
        candidates = [c for c in pool.map(attempt, range(n)) if c]

    alternatives: list[Alternative] = []
    for sql in candidates:
        try:
            result = target.run_select(url, sql, max_rows=settings.max_result_rows)
        except Exception as exc:  # noqa: BLE001 — a failing candidate is just a vote against agreement
            alternatives.append(Alternative(sql, "error", error=str(getattr(exc, "pgerror", None) or exc).strip()))
            continue
        agrees = results_equivalent(primary, result)
        alternatives.append(Alternative(result.sql, "agrees" if agrees else "differs", result.row_count))

    # A candidate that errors says nothing about the primary's correctness; only count ones that ran.
    ran = [a for a in alternatives if a.status != "error"]
    agreeing = sum(a.status == "agrees" for a in ran)
    return {
        "level": level(agreeing, len(ran)),
        "agreeing": agreeing,
        "total": len(ran),
        "attempted": n,
        "alternatives": [a.as_dict() for a in alternatives],
    }
