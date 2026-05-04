"""Add indexed_provider columns to documents and context_sources

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-02-17

Ajoute la colonne indexed_provider pour tracer quel provider LLM
(ollama/llamacpp) a été utilisé pour indexer un document ou une source.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Utiliser execute pour IF NOT EXISTS (non supporté par op.add_column)
    conn = op.get_bind()

    # Ajouter indexed_provider à documents si absent
    conn.execute(sa.text(
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS indexed_provider VARCHAR(50)"
    ))

    # Ajouter indexed_provider à context_sources si absent
    conn.execute(sa.text(
        "ALTER TABLE context_sources ADD COLUMN IF NOT EXISTS indexed_provider VARCHAR(50)"
    ))


def downgrade() -> None:
    op.drop_column('context_sources', 'indexed_provider')
    op.drop_column('documents', 'indexed_provider')
