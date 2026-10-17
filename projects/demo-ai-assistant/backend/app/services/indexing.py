from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Chunk, Post
from app.services.chunking import chunk_text
from app.services.embeddings import embed_texts


def reindex_post(db: Session, post: Post) -> None:
    """Delete this post's existing chunks and re-chunk/embed/insert fresh ones."""
    db.execute(delete(Chunk).where(Chunk.post_id == post.id))

    pieces = chunk_text(post.content)
    if pieces:
        embeddings = embed_texts(pieces, input_type="document")
        for index, (piece, embedding) in enumerate(zip(pieces, embeddings)):
            db.add(Chunk(post_id=post.id, chunk_index=index, content=piece, embedding=embedding))

    db.commit()
