from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """snake_case in Python, camelCase on the wire."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# --- Connections -------------------------------------------------------------------------------


class ConnectionCreate(CamelModel):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1)


class ConnectionTest(CamelModel):
    url: str = Field(min_length=1)


class ConnectionTestResult(CamelModel):
    ok: bool
    version: str | None = None
    error: str | None = None


class ConnectionOut(CamelModel):
    id: int
    name: str
    dialect: str
    display_url: str
    index_status: str
    index_error: str | None
    table_count: int
    last_indexed_at: datetime | None
    created_at: datetime


# --- Schema ------------------------------------------------------------------------------------


class ColumnOut(CamelModel):
    name: str
    type: str
    nullable: bool
    pk: bool
    fk: str | None = None
    comment: str | None = None


class TableOut(CamelModel):
    name: str
    kind: str
    comment: str | None
    row_estimate: int | None
    columns: list[ColumnOut]


class RelationOut(CamelModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str


class SchemaOut(CamelModel):
    tables: list[TableOut]
    relations: list[RelationOut]


class RetrieveRequest(CamelModel):
    question: str = Field(min_length=1)


# --- Queries -----------------------------------------------------------------------------------


class QueryRequest(CamelModel):
    sql: str = Field(min_length=1)


class QueryResultOut(CamelModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    duration_ms: int
    limit_added: bool


class FormatResult(CamelModel):
    sql: str


class FixRequest(CamelModel):
    sql: str = Field(min_length=1)
    error: str = Field(min_length=1)


class FixResult(CamelModel):
    sql: str
    explanation: str


# --- Chat --------------------------------------------------------------------------------------


class ChatRequest(CamelModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


class ConversationOut(CamelModel):
    id: int
    title: str
    created_at: datetime


class MessageOut(CamelModel):
    id: int
    role: str
    content: str
    payload: dict[str, Any] | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class FeedbackRequest(CamelModel):
    verified: bool


class FeedbackResult(CamelModel):
    saved_query_id: int | None


# --- Doctor ------------------------------------------------------------------------------------


class DoctorRequest(CamelModel):
    sql: str = Field(min_length=1)
    analyze: bool = False


# --- Memory ------------------------------------------------------------------------------------


class SavedQueryCreate(CamelModel):
    question: str = Field(min_length=1)
    sql: str = Field(min_length=1)


class SavedQueryUpdate(CamelModel):
    question: str | None = None
    sql: str | None = None
    verified: bool | None = None


class SavedQueryOut(CamelModel):
    id: int
    question: str
    sql: str
    verified: bool
    created_at: datetime


# --- Evals -------------------------------------------------------------------------------------


class EvalCreate(CamelModel):
    dataset: str = "pagila"
    use_memory: bool = True


class EvalDataset(CamelModel):
    name: str
    size: int


class EvalResultOut(CamelModel):
    id: int
    question: str
    gold_sql: str
    predicted_sql: str | None
    passed: bool
    steps: int
    duration_ms: int
    error: str | None


class EvalRunOut(CamelModel):
    id: int
    dataset: str
    status: str
    use_memory: bool
    model: str
    total: int
    completed: int
    passed: int
    accuracy: float | None
    error: str | None
    created_at: datetime


class EvalRunDetail(EvalRunOut):
    results: list[EvalResultOut]
