"""Introspect a target DB and (re)build its schema index: one embedded document per table/view."""

import logging
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Connection, SchemaRelation, SchemaTable
from app.services import crypto, target
from app.services.embeddings import embed_texts

logger = logging.getLogger(__name__)

EMBED_BATCH = 32


def _column_line(col: dict) -> str:
    parts = [col["name"], col["type"]]
    if col["pk"]:
        parts.append("PK")
    if col["fk"]:
        parts.append(f"→ {col['fk']}")
    if col.get("comment"):
        parts.append(f"-- {col['comment']}")
    return " ".join(parts)


def build_summary(
    table: target.IntrospectedTable, referenced_by: list[str]
) -> str:
    """The text the LLM sees for this table, and the text that gets embedded."""
    header = f"{table.kind.capitalize()} {table.qualified}"
    if table.kind == "table":
        header += f" (~{table.row_estimate:,} rows)"
    lines = [header]
    if table.comment:
        lines.append(f"Description: {table.comment}")
    lines.append("Columns:")
    lines.extend(f"  - {_column_line(c)}" for c in table.columns)
    if referenced_by:
        lines.append("Referenced by: " + ", ".join(sorted(referenced_by)))
    return "\n".join(lines)


def _keyword_doc(table: target.IntrospectedTable) -> str:
    words = [table.name, *(c["name"] for c in table.columns)]
    if table.comment:
        words.append(table.comment)
    return " ".join(words).replace("_", " ")


def reindex_connection(db: Session, connection: Connection) -> None:
    url = crypto.decrypt(connection.encrypted_url)
    tables, relations = target.introspect(url)

    referenced_by: dict[str, list[str]] = defaultdict(list)
    for rel in relations:
        referenced_by[rel.to_table].append(f"{rel.from_table}.{rel.from_column}")

    summaries = [build_summary(t, referenced_by[t.qualified]) for t in tables]
    embeddings: list[list[float]] = []
    for i in range(0, len(summaries), EMBED_BATCH):
        embeddings.extend(embed_texts(summaries[i : i + EMBED_BATCH], input_type="document"))

    db.execute(delete(SchemaTable).where(SchemaTable.connection_id == connection.id))
    db.execute(delete(SchemaRelation).where(SchemaRelation.connection_id == connection.id))
    for table, summary, embedding in zip(tables, summaries, embeddings, strict=True):
        db.add(
            SchemaTable(
                connection_id=connection.id,
                schema_name=table.schema,
                table_name=table.qualified,
                kind=table.kind,
                comment=table.comment,
                row_estimate=table.row_estimate,
                columns=table.columns,
                summary_text=summary,
                embedding=embedding,
                tsv=func.to_tsvector("english", _keyword_doc(table)),
            )
        )
    for rel in relations:
        db.add(
            SchemaRelation(
                connection_id=connection.id,
                from_table=rel.from_table,
                from_column=rel.from_column,
                to_table=rel.to_table,
                to_column=rel.to_column,
            )
        )

    connection.table_count = len(tables)
    connection.index_status = "ready"
    connection.index_error = None
    connection.last_indexed_at = datetime.now(timezone.utc)
    db.commit()


def reindex_connection_background(connection_id: int) -> None:
    """Entry point for FastAPI BackgroundTasks: owns its own session and records failures."""
    db = SessionLocal()
    try:
        connection = db.get(Connection, connection_id)
        if connection is None:
            return
        connection.index_status = "indexing"
        connection.index_error = None
        db.commit()
        try:
            reindex_connection(db, connection)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Indexing connection %s failed", connection_id)
            db.rollback()
            connection = db.get(Connection, connection_id)
            if connection is not None:
                connection.index_status = "error"
                connection.index_error = str(exc)
                db.commit()
    finally:
        db.close()
