"""switch embedding column to 768 dims (Ollama nomic-embed-text, was 512-dim Voyage)

Revision ID: 0002_ollama_embedding_dim
Revises: 0001_initial
Create Date: 2026-10-16

"""
from typing import Sequence, Union

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0002_ollama_embedding_dim"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_DIM = 512
NEW_DIM = 768


def upgrade() -> None:
    # Existing embeddings were produced by a different model/dimension; they can't be
    # cast in place. Drop them — posts must be re-saved (or re-indexed) afterward.
    op.execute("TRUNCATE TABLE chunks")
    op.alter_column(
        "chunks",
        "embedding",
        type_=pgvector.sqlalchemy.Vector(NEW_DIM),
        existing_type=pgvector.sqlalchemy.Vector(OLD_DIM),
    )


def downgrade() -> None:
    op.execute("TRUNCATE TABLE chunks")
    op.alter_column(
        "chunks",
        "embedding",
        type_=pgvector.sqlalchemy.Vector(OLD_DIM),
        existing_type=pgvector.sqlalchemy.Vector(NEW_DIM),
    )
