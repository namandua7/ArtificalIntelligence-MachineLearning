from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# nomic-embed-text output size. Changing the embed model means a new migration + re-index.
EMBEDDING_DIM = 768


class Connection(Base):
    """A target database the user has connected. The URL is Fernet-encrypted at rest."""

    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    dialect: Mapped[str] = mapped_column(String(30), nullable=False, default="postgresql")
    encrypted_url: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | indexing | ready | error
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    index_error: Mapped[str | None] = mapped_column(Text)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    tables: Mapped[list["SchemaTable"]] = relationship(
        back_populates="connection", cascade="all, delete-orphan", passive_deletes=True
    )


class SchemaTable(Base):
    """One table/view of a target DB, flattened to text and embedded for retrieval."""

    __tablename__ = "schema_tables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schema_name: Mapped[str] = mapped_column(String(120), nullable=False)
    table_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="table")  # table | view
    comment: Mapped[str | None] = mapped_column(Text)
    row_estimate: Mapped[int | None] = mapped_column(Integer)
    # [{"name","type","nullable","pk","fk": "table.col" | null, "comment"}]
    columns: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    tsv: Mapped[str] = mapped_column(TSVECTOR, nullable=False)

    connection: Mapped[Connection] = relationship(back_populates="tables")


class SchemaRelation(Base):
    """A foreign-key edge; the graph used for join expansion and the ER diagram."""

    __tablename__ = "schema_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_table: Mapped[str] = mapped_column(String(120), nullable=False)
    from_column: Mapped[str] = mapped_column(String(120), nullable=False)
    to_table: Mapped[str] = mapped_column(String(120), nullable=False)
    to_column: Mapped[str] = mapped_column(String(120), nullable=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Assistant only: {sql, chart, steps, result: {columns, rows, rowCount, truncated}, error}
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class QueryRun(Base):
    """Every SQL execution attempt, including the agent's failed ones (drives the timeline)."""

    __tablename__ = "query_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # agent | editor | eval | mcp
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # ok | error | blocked
    error: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    row_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SavedQuery(Base):
    """Verified question→SQL pairs; retrieved as few-shot examples (the agent's memory)."""

    __tablename__ = "saved_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("connections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dataset: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    use_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accuracy: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    results: Mapped[list["EvalResult"]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="EvalResult.id"
    )


class EvalResult(Base):
    __tablename__ = "eval_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    gold_sql: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_sql: Mapped[str | None] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
