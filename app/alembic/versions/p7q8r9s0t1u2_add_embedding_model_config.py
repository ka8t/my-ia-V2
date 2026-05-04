"""Add rag.embedding_model config key

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'p7q8r9s0t1u2'
down_revision: Union[str, None] = 'o6p7q8r9s0t1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la cle rag.embedding_model dans system_configs (si elle n'existe pas deja)
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description)
        VALUES ('rag.embedding_model', 'nomic-embed-text', 'string', 'rag', 'Modèle d''embedding utilisé pour la vectorisation des documents')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer la cle ajoutee
    op.execute("""
        DELETE FROM system_configs
        WHERE key = 'rag.embedding_model'
    """)
