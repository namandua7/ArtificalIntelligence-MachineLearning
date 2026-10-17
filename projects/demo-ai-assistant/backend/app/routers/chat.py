from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ChatRequest
from app.services.rag import stream_chat_response

router = APIRouter(prefix="/api/chat", tags=["chat"])

HISTORY_LIMIT = 6


@router.post("")
def chat(payload: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    trimmed_history = payload.history[-HISTORY_LIMIT:]
    generator = stream_chat_response(db, payload.message, trimmed_history)
    return StreamingResponse(generator, media_type="text/event-stream")
