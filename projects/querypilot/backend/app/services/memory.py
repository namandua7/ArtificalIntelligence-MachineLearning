from sqlalchemy.orm import Session

from app.models import SavedQuery
from app.services.embeddings import embed_texts
from app.services.sql_guard import format_sql


def save_query(db: Session, connection_id: int, question: str, sql: str, verified: bool = True) -> SavedQuery:
    # Embedded as a *query* so it lands in the same space as future user questions.
    [embedding] = embed_texts([question], input_type="query")
    saved = SavedQuery(
        connection_id=connection_id, question=question, sql=format_sql(sql), verified=verified, embedding=embedding
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


def update_question(db: Session, saved: SavedQuery, question: str) -> None:
    [saved.embedding] = embed_texts([question], input_type="query")
    saved.question = question
