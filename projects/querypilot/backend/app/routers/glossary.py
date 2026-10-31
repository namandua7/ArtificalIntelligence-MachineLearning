from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Connection, GlossaryTerm
from app.routers.deps import get_connection
from app.schemas import GlossaryTermIn, GlossaryTermOut
from app.services import cache, glossary

router = APIRouter(tags=["glossary"])


def _term(db: Session, term_id: int) -> GlossaryTerm:
    row = db.get(GlossaryTerm, term_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return row


@router.get("/api/connections/{connection_id}/glossary", response_model=list[GlossaryTermOut])
def list_terms(connection: Connection = Depends(get_connection), db: Session = Depends(get_db)):
    return list(
        db.scalars(select(GlossaryTerm).where(GlossaryTerm.connection_id == connection.id).order_by(GlossaryTerm.term))
    )


@router.post("/api/connections/{connection_id}/glossary", response_model=GlossaryTermOut, status_code=201)
def create_term(body: GlossaryTermIn, connection: Connection = Depends(get_connection), db: Session = Depends(get_db)):
    existing = db.scalar(
        select(GlossaryTerm.id).where(
            GlossaryTerm.connection_id == connection.id, GlossaryTerm.term.ilike(body.term.strip())
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"'{body.term}' is already defined.")
    return glossary.add_term(db, connection.id, body.term, body.aliases, body.definition, body.sql_snippet)


@router.put("/api/glossary/{term_id}", response_model=GlossaryTermOut)
def update_term(term_id: int, body: GlossaryTermIn, db: Session = Depends(get_db)):
    return glossary.update_term(db, _term(db, term_id), body.term, body.aliases, body.definition, body.sql_snippet)


@router.delete("/api/glossary/{term_id}", status_code=204)
def delete_term(term_id: int, db: Session = Depends(get_db)) -> None:
    row = _term(db, term_id)
    connection_id = row.connection_id
    db.delete(row)
    db.commit()
    cache.bump(connection_id)
