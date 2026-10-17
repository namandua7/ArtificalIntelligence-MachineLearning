import json
from collections.abc import Generator

import ollama
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Chunk, Post
from app.schemas import ChatMessage
from app.services.embeddings import embed_query

TOP_K = 5

_ollama_client: ollama.Client | None = None


def _get_ollama_client() -> ollama.Client:
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = ollama.Client(host=settings.ollama_base_url)
    return _ollama_client


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _retrieve(db: Session, query_embedding: list[float]) -> list[tuple[Chunk, str, str, float]]:
    stmt = (
        select(
            Chunk,
            Post.title,
            Post.slug,
            Chunk.embedding.cosine_distance(query_embedding).label("distance"),
        )
        .join(Post, Chunk.post_id == Post.id)
        .order_by("distance")
        .limit(TOP_K)
    )
    rows = db.execute(stmt).all()
    return [(row[0], row[1], row[2], float(row[3])) for row in rows]


def _build_system_prompt(context_blocks: list[str], from_blog: bool) -> str:
    if from_blog:
        context = "\n\n---\n\n".join(context_blocks)
        return (
            "You are a helpful assistant answering questions about a personal blog. "
            "Answer the user's question using ONLY the blog content provided below as context. "
            "If the context does not contain enough information to answer, say so clearly instead "
            "of making something up. Do not mention that you were given 'context' or 'chunks' — "
            "just answer naturally as if you know the blog.\n\n"
            f"BLOG CONTEXT:\n{context}"
        )
    return (
        "You are a helpful, general-purpose assistant. The user's question did not closely match "
        "any content on the blog this assistant is attached to, so answer from your own general "
        "knowledge. Be helpful and concise."
    )


def stream_chat_response(
    db: Session, message: str, history: list[ChatMessage]
) -> Generator[str, None, None]:
    try:
        query_embedding = embed_query(message)
        retrieved = _retrieve(db, query_embedding)

        best_similarity = (1.0 - retrieved[0][3]) if retrieved else 0.0
        from_blog = best_similarity >= settings.similarity_threshold

        sources: list[dict[str, str]] = []
        context_blocks: list[str] = []
        if from_blog:
            seen_slugs: set[str] = set()
            for chunk, title, slug, _distance in retrieved:
                context_blocks.append(f"### {title}\n{chunk.content}")
                if slug not in seen_slugs:
                    seen_slugs.add(slug)
                    sources.append({"title": title, "slug": slug})

        system_prompt = _build_system_prompt(context_blocks, from_blog)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": m.role, "content": m.content} for m in history)
        messages.append({"role": "user", "content": message})

        client = _get_ollama_client()
        stream = client.chat(model=settings.ollama_chat_model, messages=messages, stream=True)
        for chunk in stream:
            text = chunk.message.content
            if text:
                yield _sse("token", text)

        yield _sse("sources", {"fromBlog": from_blog, "sources": sources})
        yield _sse("done", {})
    except Exception as exc:  # noqa: BLE001
        yield _sse("error", {"message": str(exc)})
