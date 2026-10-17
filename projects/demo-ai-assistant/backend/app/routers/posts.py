from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Post
from app.schemas import PostCreate, PostListItem, PostOut, PostUpdate
from app.services.indexing import reindex_post

router = APIRouter(prefix="/api/posts", tags=["posts"])

EXCERPT_LENGTH = 150


def _excerpt(content: str) -> str:
    stripped = content.strip()
    if len(stripped) <= EXCERPT_LENGTH:
        return stripped
    return stripped[:EXCERPT_LENGTH].rsplit(" ", 1)[0] + "…"


def _get_post_or_404(db: Session, slug: str) -> Post:
    post = db.execute(select(Post).where(Post.slug == slug)).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return post


@router.get("", response_model=list[PostListItem])
def list_posts(db: Session = Depends(get_db)) -> list[PostListItem]:
    posts = db.execute(select(Post).order_by(Post.created_at.desc())).scalars().all()
    return [
        PostListItem(
            id=p.id, title=p.title, slug=p.slug, created_at=p.created_at, excerpt=_excerpt(p.content)
        )
        for p in posts
    ]


@router.get("/{slug}", response_model=PostOut)
def get_post(slug: str, db: Session = Depends(get_db)) -> Post:
    return _get_post_or_404(db, slug)


@router.post("", response_model=PostOut, status_code=201)
def create_post(payload: PostCreate, db: Session = Depends(get_db)) -> Post:
    post = Post(title=payload.title, slug=payload.slug, content=payload.content)
    db.add(post)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A post with this slug already exists") from exc
    db.refresh(post)

    reindex_post(db, post)
    db.refresh(post)
    return post


@router.put("/{slug}", response_model=PostOut)
def update_post(slug: str, payload: PostUpdate, db: Session = Depends(get_db)) -> Post:
    post = _get_post_or_404(db, slug)
    post.title = payload.title
    post.slug = payload.slug
    post.content = payload.content
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A post with this slug already exists") from exc
    db.refresh(post)

    reindex_post(db, post)
    db.refresh(post)
    return post


@router.delete("/{slug}", status_code=204)
def delete_post(slug: str, db: Session = Depends(get_db)) -> None:
    post = _get_post_or_404(db, slug)
    db.delete(post)
    db.commit()
