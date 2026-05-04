"""Add embedding provider configuration key

Revision ID: 20260221_1520
Revises: f6g7h8i9j0k1
Create Date: 2026-02-21

Ajoute la cle de configuration pour le provider d'embedding separe:
- llm.embedding_provider : permet d'utiliser un provider different pour les embeddings
  (ex: Ollama pour embeddings, llama.cpp pour chat)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260221_1520'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute la cle de configuration llm.embedding_provider."""
    conn = op.get_bind()

    conn.execute(
        sa.text("""
            INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
            VALUES (
                'llm.embedding_provider',
                'ollama',
                'string',
                'llm',
                'Provider pour les embeddings (ollama ou llamacpp). Si different de llm.provider, permet mode hybride.',
                false
            )
            ON CONFLICT (key) DO NOTHING
        """)
    )


def downgrade() -> None:
    """Supprime la cle de configuration llm.embedding_provider."""
    conn = op.get_bind()

    conn.execute(
        sa.text("DELETE FROM system_configs WHERE key = 'llm.embedding_provider'")
    )
