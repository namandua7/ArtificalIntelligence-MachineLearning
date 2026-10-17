"""Schema retrieval: hybrid (vector + keyword) search fused with RRF, then FK-graph expansion.

Vectors catch meaning ("revenue" → payment.amount); keywords catch exact identifiers
("rental_rate"). Join tables rarely match a question on their own, so after ranking we pull in
direct foreign-key neighbours of the top hits.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from app.models import SavedQuery, SchemaRelation, SchemaTable
from app.services.embeddings import embed_query

TOP_K = 6
MAX_TABLES = 10
RRF_K = 60
CANDIDATES = 20
EXAMPLES_K = 3
EXAMPLE_MIN_SIMILARITY = 0.55

_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9]{1,}")


@dataclass
class RetrievedTable:
    table: SchemaTable
    score: float
    reason: str  # "match" | "join"


@dataclass
class RetrievedExample:
    question: str
    sql: str
    similarity: float


@dataclass
class RetrievalResult:
    tables: list[RetrievedTable] = field(default_factory=list)
    examples: list[RetrievedExample] = field(default_factory=list)
    relations: list[SchemaRelation] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "tables": [
                {"name": t.table.table_name, "score": round(t.score, 4), "reason": t.reason}
                for t in self.tables
            ],
            "examples": [
                {"question": e.question, "similarity": round(e.similarity, 3)} for e in self.examples
            ],
        }


def _keyword_query(question: str) -> str | None:
    words = {w.lower() for w in _WORD.findall(question)}
    return " | ".join(sorted(words)) if words else None


def _vector_ranking(db: Session, connection_id: int, query_vec: list[float]) -> list[int]:
    stmt = (
        select(SchemaTable.id)
        .where(SchemaTable.connection_id == connection_id)
        .order_by(SchemaTable.embedding.cosine_distance(query_vec))
        .limit(CANDIDATES)
    )
    return list(db.scalars(stmt))


def _keyword_ranking(db: Session, connection_id: int, question: str) -> list[int]:
    raw = _keyword_query(question)
    if raw is None:
        return []
    tsquery = func.to_tsquery("english", raw)
    rank = func.ts_rank_cd(SchemaTable.tsv, tsquery)
    stmt = (
        select(SchemaTable.id)
        .where(SchemaTable.connection_id == connection_id, SchemaTable.tsv.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(CANDIDATES)
    )
    return list(db.scalars(stmt))


def retrieve_tables(
    db: Session, connection_id: int, question: str, query_vec: list[float] | None = None
) -> tuple[list[RetrievedTable], list[SchemaRelation]]:
    query_vec = query_vec if query_vec is not None else embed_query(question)

    scores: dict[int, float] = {}
    for ranking in (_vector_ranking(db, connection_id, query_vec), _keyword_ranking(db, connection_id, question)):
        for rank, table_id in enumerate(ranking):
            scores[table_id] = scores.get(table_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    top_ids = [tid for tid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:TOP_K]]
    all_tables = {
        t.id: t for t in db.scalars(select(SchemaTable).where(SchemaTable.connection_id == connection_id))
    }
    by_name = {t.table_name: t for t in all_tables.values()}

    picked: list[RetrievedTable] = [
        RetrievedTable(all_tables[tid], scores[tid], "match") for tid in top_ids if tid in all_tables
    ]
    picked_scores = {p.table.table_name: p.score for p in picked}
    picked_names = set(picked_scores)

    relations = list(
        db.scalars(select(SchemaRelation).where(SchemaRelation.connection_id == connection_id))
    )

    # FK expansion: neighbours of matched tables, weighted by how strongly their neighbours matched.
    neighbour_hits: dict[str, float] = {}
    for rel in relations:
        for here, there in ((rel.from_table, rel.to_table), (rel.to_table, rel.from_table)):
            if here in picked_scores and there not in picked_names and there in by_name:
                neighbour_hits[there] = neighbour_hits.get(there, 0.0) + picked_scores[here]
    for name, score in sorted(neighbour_hits.items(), key=lambda kv: kv[1], reverse=True):
        if len(picked) >= MAX_TABLES:
            break
        picked.append(RetrievedTable(by_name[name], score / 2, "join"))
        picked_names.add(name)

    used_relations = [
        r for r in relations if r.from_table in picked_names and r.to_table in picked_names
    ]
    return picked, used_relations


def retrieve_examples(
    db: Session, connection_id: int, query_vec: list[float], k: int = EXAMPLES_K
) -> list[RetrievedExample]:
    distance = SavedQuery.embedding.cosine_distance(query_vec)
    stmt = (
        select(SavedQuery, cast(distance, Float))
        .where(SavedQuery.connection_id == connection_id, SavedQuery.verified.is_(True))
        .order_by(distance)
        .limit(k)
    )
    examples = []
    for saved, dist in db.execute(stmt).all():
        similarity = 1.0 - float(dist)
        if similarity >= EXAMPLE_MIN_SIMILARITY:
            examples.append(RetrievedExample(saved.question, saved.sql, similarity))
    return examples


def retrieve(
    db: Session, connection_id: int, question: str, use_memory: bool = True
) -> RetrievalResult:
    query_vec = embed_query(question)
    tables, relations = retrieve_tables(db, connection_id, question, query_vec)
    examples = retrieve_examples(db, connection_id, query_vec) if use_memory else []
    return RetrievalResult(tables=tables, examples=examples, relations=relations)
