"""Semantic layer: business terms → authoritative definitions injected into the agent prompt.

Matching is hybrid. A term (or alias) that literally appears in the question always wins; embedding
similarity then catches paraphrases ("sales" for a term defined as "revenue").
"""

import re
from dataclasses import dataclass

from sqlalchemy import Float, cast, select
from sqlalchemy.orm import Session

from app.models import GlossaryTerm
from app.services import cache
from app.services.embeddings import embed_texts

MAX_TERMS = 4
SEMANTIC_MIN_SIMILARITY = 0.62


@dataclass
class RetrievedTerm:
    id: int
    term: str
    definition: str
    sql_snippet: str | None
    reason: str  # "exact" | "similar"
    similarity: float | None = None

    def summary(self) -> dict:
        return {"term": self.term, "reason": self.reason}


def embedding_text(term: str, aliases: list[str], definition: str) -> str:
    return ". ".join(p for p in (term, ", ".join(aliases), definition) if p)


def _clean_aliases(aliases: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for alias in aliases:
        alias = alias.strip()
        if alias:
            seen.setdefault(alias.lower(), alias)
    return list(seen.values())


def add_term(
    db: Session, connection_id: int, term: str, aliases: list[str], definition: str, sql_snippet: str | None
) -> GlossaryTerm:
    aliases = _clean_aliases(aliases)
    [embedding] = embed_texts([embedding_text(term, aliases, definition)], input_type="document")
    row = GlossaryTerm(
        connection_id=connection_id,
        term=term.strip(),
        aliases=aliases,
        definition=definition.strip(),
        sql_snippet=(sql_snippet or "").strip() or None,
        embedding=embedding,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    cache.bump(connection_id)
    return row


def update_term(
    db: Session, row: GlossaryTerm, term: str, aliases: list[str], definition: str, sql_snippet: str | None
) -> GlossaryTerm:
    aliases = _clean_aliases(aliases)
    [row.embedding] = embed_texts([embedding_text(term, aliases, definition)], input_type="document")
    row.term, row.aliases, row.definition = term.strip(), aliases, definition.strip()
    row.sql_snippet = (sql_snippet or "").strip() or None
    db.commit()
    db.refresh(row)
    cache.bump(row.connection_id)
    return row


def _pattern(phrase: str) -> re.Pattern[str]:
    # Word-boundary match, tolerant of a plural/possessive suffix: "customer" matches "customers".
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase.strip())}(?:s|es|'s)?(?![A-Za-z0-9])", re.IGNORECASE)


def lexical_matches(question: str, terms: list[GlossaryTerm]) -> list[GlossaryTerm]:
    return [
        t for t in terms if any(p.strip() and _pattern(p).search(question) for p in [t.term, *t.aliases])
    ]


def match_terms(db: Session, connection_id: int, question: str, query_vec: list[float]) -> list[RetrievedTerm]:
    rows = list(db.scalars(select(GlossaryTerm).where(GlossaryTerm.connection_id == connection_id)))
    if not rows:
        return []
    picked: dict[int, RetrievedTerm] = {
        t.id: RetrievedTerm(t.id, t.term, t.definition, t.sql_snippet, "exact") for t in lexical_matches(question, rows)
    }
    if len(picked) < MAX_TERMS:
        distance = GlossaryTerm.embedding.cosine_distance(query_vec)
        stmt = (
            select(GlossaryTerm, cast(distance, Float))
            .where(GlossaryTerm.connection_id == connection_id)
            .order_by(distance)
            .limit(MAX_TERMS)
        )
        for row, dist in db.execute(stmt).all():
            similarity = 1.0 - float(dist)
            if row.id not in picked and similarity >= SEMANTIC_MIN_SIMILARITY:
                picked[row.id] = RetrievedTerm(row.id, row.term, row.definition, row.sql_snippet, "similar", similarity)
    return list(picked.values())[:MAX_TERMS]


def prompt_block(terms: list[RetrievedTerm]) -> str:
    if not terms:
        return ""
    lines = []
    for t in terms:
        line = f"- **{t.term}**: {t.definition}"
        if t.sql_snippet:
            line += f"\n  SQL: `{t.sql_snippet}`"
        lines.append(line)
    return (
        "\n## Business definitions (authoritative: if the question uses one of these terms, use exactly this "
        "meaning and SQL)\n" + "\n".join(lines) + "\n"
    )
