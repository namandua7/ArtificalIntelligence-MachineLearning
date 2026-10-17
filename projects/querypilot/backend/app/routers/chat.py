import json
from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.models import Connection, Conversation, Message, SavedQuery
from app.routers.deps import get_connection, get_ready_connection
from app.schemas import (
    ChatRequest,
    ConversationDetail,
    ConversationOut,
    FeedbackRequest,
    FeedbackResult,
)
from app.services.agent import HistoryTurn, run_agent
from app.services.memory import save_query

router = APIRouter(tags=["chat"])

HISTORY_TURNS = 3
STORED_ROWS = 200  # rows persisted with a message so old answers re-render without re-running


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _history(conversation: Conversation, before_id: int) -> list[HistoryTurn]:
    turns: list[HistoryTurn] = []
    pending_question: str | None = None
    for msg in conversation.messages:
        if msg.id >= before_id:
            break
        if msg.role == "user":
            pending_question = msg.content
        elif msg.role == "assistant" and pending_question:
            payload = msg.payload or {}
            turns.append(HistoryTurn(pending_question, payload.get("sql"), msg.content))
            pending_question = None
    return turns[-HISTORY_TURNS:]


def _stream(connection_id: int, conversation_id: int, user_message_id: int, assistant_id: int) -> Generator[str, None, None]:
    # Own session: the request-scoped one may be closed before streaming finishes.
    db = SessionLocal()
    try:
        connection = db.get(Connection, connection_id)
        conversation = db.get(Conversation, conversation_id)
        user_msg = db.get(Message, user_message_id)
        assistant = db.get(Message, assistant_id)
        yield _sse("meta", {"conversationId": conversation_id, "messageId": assistant_id, "title": conversation.title})

        payload: dict[str, Any] = {"steps": []}
        for ev in run_agent(
            db, connection, user_msg.content, _history(conversation, user_message_id), message_id=assistant_id
        ):
            yield _sse(ev.event, ev.data)
            if ev.event == "retrieval":
                payload["retrieval"] = ev.data
            elif ev.event == "result":
                payload["result"] = {**ev.data, "rows": ev.data["rows"][:STORED_ROWS]}
            elif ev.event == "answer":
                payload.update(sql=ev.data["sql"], chart=ev.data["chart"], steps=ev.data["steps"],
                               attempts=ev.data["attempts"])
                assistant.content = ev.data["explanation"]
            elif ev.event == "error":
                payload.update(error=ev.data["message"], steps=ev.data.get("steps", []))
                assistant.content = ""

        assistant.payload = payload
        db.commit()
        yield _sse("done", {"messageId": assistant_id})
    except GeneratorExit:
        # Client hit Stop / closed the tab: persist what we have instead of leaving it "pending".
        payload.setdefault("error", "Stopped before finishing.")
        assistant.payload = payload
        db.commit()
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        yield _sse("error", {"message": str(exc)})
    finally:
        db.close()


@router.post("/api/connections/{connection_id}/chat")
def chat(
    body: ChatRequest, connection: Connection = Depends(get_ready_connection), db: Session = Depends(get_db)
) -> StreamingResponse:
    if body.conversation_id is not None:
        conversation = db.get(Conversation, body.conversation_id)
        if conversation is None or conversation.connection_id != connection.id:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        title = body.question.strip().splitlines()[0][:80]
        conversation = Conversation(connection_id=connection.id, title=title)
        db.add(conversation)
        db.flush()

    user_msg = Message(conversation_id=conversation.id, role="user", content=body.question.strip())
    db.add(user_msg)
    db.flush()
    assistant = Message(conversation_id=conversation.id, role="assistant", content="", payload={"pending": True})
    db.add(assistant)
    db.commit()

    return StreamingResponse(
        _stream(connection.id, conversation.id, user_msg.id, assistant.id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/connections/{connection_id}/conversations", response_model=list[ConversationOut])
def list_conversations(connection: Connection = Depends(get_connection), db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Conversation)
            .where(Conversation.connection_id == connection.id)
            .order_by(Conversation.created_at.desc())
            .limit(100)
        )
    )


@router.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete("/api/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: int, db: Session = Depends(get_db)) -> None:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conversation)
    db.commit()


@router.post("/api/messages/{message_id}/feedback", response_model=FeedbackResult)
def feedback(message_id: int, body: FeedbackRequest, db: Session = Depends(get_db)) -> FeedbackResult:
    """👍 saves the question→SQL pair to memory (few-shot examples); 👎 removes it again."""
    assistant = db.get(Message, message_id)
    if assistant is None or assistant.role != "assistant":
        raise HTTPException(status_code=404, detail="Message not found")
    payload = dict(assistant.payload or {})
    sql = payload.get("sql")
    question = db.scalar(
        select(Message.content)
        .where(Message.conversation_id == assistant.conversation_id, Message.id < assistant.id, Message.role == "user")
        .order_by(Message.id.desc())
        .limit(1)
    )
    connection_id = assistant.conversation.connection_id

    saved_id: int | None = payload.get("savedQueryId")
    if body.verified:
        if not sql or not question:
            raise HTTPException(status_code=400, detail="This answer has no SQL to save.")
        if saved_id is None or db.get(SavedQuery, saved_id) is None:
            saved_id = save_query(db, connection_id, question, sql).id
    elif saved_id is not None:
        saved = db.get(SavedQuery, saved_id)
        if saved is not None:
            db.delete(saved)
        saved_id = None

    payload.update(feedback="up" if body.verified else "down", savedQueryId=saved_id)
    assistant.payload = payload
    db.commit()
    return FeedbackResult(saved_query_id=saved_id)
