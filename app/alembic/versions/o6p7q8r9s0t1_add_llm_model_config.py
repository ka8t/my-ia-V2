"""Add rag.llm_model config key

Revision ID: o6p7q8r9s0t1
Revises: n5o6p7q8r9s0
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'o6p7q8r9s0t1'
down_revision: Union[str, None] = 'n5o6p7q8r9s0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la cle rag.llm_model dans system_configs
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('rag.llm_model', 'mistral', 'string', 'rag',
         'Modele LLM utilise pour la generation de reponses')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer la cle ajoutee
    op.execute("""
        DELETE FROM system_configs
        WHERE key = 'rag.llm_model'
    """)
