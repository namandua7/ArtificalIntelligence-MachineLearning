"""Insights beyond the answer: deterministic key facts from the result, plus LLM follow-up questions.

The numbers in `facts` are computed in Python from the stored result, never by the LLM; the LLM
only phrases takeaways from those facts and proposes follow-ups, so a hallucinated statistic can't
reach the user. The LLM sees aggregates (and a few rows only when ALLOW_SAMPLE_ROWS is on).
"""

import re
from numbers import Number
from typing import Any

from pydantic import BaseModel, Field

from app.config import settings
from app.llm import get_llm
from app.llm.base import LLMError

_ISO = re.compile(r"^\d{4}-\d{2}(-\d{2})?")
SAMPLE_ROWS = 5

SYSTEM = """You are a sharp data analyst helping someone explore their database results. You are given a \
question, the SQL used and verified facts computed from the result. Never invent numbers: only use \
the facts given."""

PROMPT = """Question: {question}

SQL:
{sql}

Verified facts about the result:
{facts}
{sample}
Return:
- takeaways: up to 3 short plain-English insights a busy person would care about, each citing numbers from the facts.
- followups: exactly 3 natural next questions to ask this database (short, specific, answerable with SQL; \
phrase them as the user would type them; don't repeat the original question)."""


class Insights(BaseModel):
    takeaways: list[str] = Field(default_factory=list, max_length=3)
    followups: list[str] = Field(default_factory=list, max_length=3)


def _is_number(v: Any) -> bool:
    return isinstance(v, Number) and not isinstance(v, bool)


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 1000 or float(x).is_integer() else f"{x:,.2f}"


def compute_facts(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    """Deterministic highlights. Returns {"rowCount", "highlights": [str], "metrics": {col: stats}}."""
    facts: dict[str, Any] = {"rowCount": len(rows), "highlights": [], "metrics": {}}
    if not rows:
        return facts

    numeric = [
        i for i in range(len(columns))
        if (vals := [r[i] for r in rows if r[i] is not None]) and all(_is_number(v) for v in vals)
    ]
    labels = [i for i in range(len(columns)) if i not in numeric]
    for i in numeric[:4]:
        vals = [float(r[i]) for r in rows if r[i] is not None]
        facts["metrics"][columns[i]] = {
            "min": min(vals), "max": max(vals), "sum": sum(vals), "mean": sum(vals) / len(vals), "count": len(vals),
        }

    if len(rows) == 1:
        facts["highlights"].append(", ".join(f"{c}: {r}" for c, r in zip(columns, rows[0], strict=True)))
        return facts
    if not numeric:
        return facts

    metric = numeric[0]
    name = columns[metric]
    label = labels[0] if labels else None
    pairs = [(r[label] if label is not None else idx + 1, float(r[metric])) for idx, r in enumerate(rows) if r[metric] is not None]
    total = sum(v for _, v in pairs)

    temporal = label is not None and all(isinstance(r[label], str) and _ISO.match(r[label]) for r in rows)
    if temporal and len(pairs) >= 2:
        ordered = sorted(pairs, key=lambda p: str(p[0]))
        first, last = ordered[0], ordered[-1]
        change = last[1] - first[1]
        pct = f" ({change / first[1]:+.1%})" if first[1] else ""
        facts["highlights"].append(
            f"{name} went from {_fmt(first[1])} ({str(first[0])[:10]}) to {_fmt(last[1])} ({str(last[0])[:10]}){pct}."
        )
        peak = max(ordered, key=lambda p: p[1])
        low = min(ordered, key=lambda p: p[1])
        facts["highlights"].append(
            f"Peak {name}: {_fmt(peak[1])} in {str(peak[0])[:10]}; lowest: {_fmt(low[1])} in {str(low[0])[:10]}."
        )
    elif label is not None:
        ranked = sorted(pairs, key=lambda p: p[1], reverse=True)
        lead, trail = ranked[0], ranked[-1]
        if total > 0 and lead[1] >= 0:
            facts["highlights"].append(f"{lead[0]} leads {name} with {_fmt(lead[1])} ({lead[1] / total:.0%} of the total).")
            if len(ranked) >= 3:
                top3 = sum(v for _, v in ranked[:3])
                facts["highlights"].append(f"The top 3 account for {top3 / total:.0%} of {name}.")
        else:
            facts["highlights"].append(f"Highest {name}: {lead[0]} ({_fmt(lead[1])}).")
        if len(ranked) > 1:
            facts["highlights"].append(f"Lowest {name}: {trail[0]} ({_fmt(trail[1])}).")
        if lead[1] and trail[1] > 0:
            facts["highlights"].append(f"The spread between highest and lowest is {lead[1] / trail[1]:.1f}x.")
    return facts


def generate(question: str, sql: str, facts: dict[str, Any], columns: list[str], rows: list[list[Any]]) -> Insights:
    sample = ""
    if settings.allow_sample_rows and rows:
        lines = [" | ".join(columns)] + [" | ".join(str(v) for v in r) for r in rows[:SAMPLE_ROWS]]
        sample = "\nFirst rows:\n" + "\n".join(lines) + "\n"
    fact_text = "\n".join(f"- {h}" for h in facts["highlights"]) or "- (no derived highlights)"
    fact_text += f"\n- {facts['rowCount']} rows; columns: {', '.join(columns)}"
    return get_llm().generate_structured(
        SYSTEM, PROMPT.format(question=question, sql=sql, facts=fact_text, sample=sample), Insights
    )


def build(question: str, sql: str, columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    """Facts always; LLM takeaways/follow-ups when available (an LLM failure degrades, never raises)."""
    facts = compute_facts(columns, rows)
    out: dict[str, Any] = {"facts": facts["highlights"], "takeaways": [], "followups": [], "llmError": None}
    try:
        generated = generate(question, sql, facts, columns, rows)
        out["takeaways"] = [t.strip() for t in generated.takeaways if t.strip()][:3]
        out["followups"] = [f.strip() for f in generated.followups if f.strip() and f.strip().lower() != question.strip().lower()][:3]
    except LLMError as exc:
        out["llmError"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        out["llmError"] = f"{type(exc).__name__}: {exc}"
    return out
