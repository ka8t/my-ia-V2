"""Add LLM provider models config keys

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-02-05

Migration Phase 2 LLM Provider :
- Ajoute les cles llm.ollama.llm_model, llm.ollama.embedding_model
- Ajoute les cles llm.llamacpp.llm_model, llm.llamacpp.embedding_model
- Migre les valeurs existantes depuis rag.llm_model et rag.embedding_model
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les cles de configuration des modeles par provider LLM."""

    # Recuperer les valeurs actuelles de rag.llm_model et rag.embedding_model
    # pour les migrer vers llm.ollama.*
    conn = op.get_bind()

    # Lire les valeurs existantes
    llm_model_row = conn.execute(
        sa.text("SELECT value FROM system_configs WHERE key = 'rag.llm_model'")
    ).fetchone()
    llm_model = llm_model_row[0] if llm_model_row else 'mistral'

    embedding_model_row = conn.execute(
        sa.text("SELECT value FROM system_configs WHERE key = 'rag.embedding_model'")
    ).fetchone()
    embedding_model = embedding_model_row[0] if embedding_model_row else 'nomic-embed-text'

    # Inserer les nouvelles cles pour Ollama (avec valeurs migrees)
    op.execute(f"""
        INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
        VALUES
            ('llm.ollama.llm_model', '{llm_model}', 'string', 'llm', 'Modele LLM pour Ollama', false),
            ('llm.ollama.embedding_model', '{embedding_model}', 'string', 'llm', 'Modele embedding pour Ollama', false),
            ('llm.llamacpp.llm_model', '', 'string', 'llm', 'Modele LLM pour llama.cpp (fichier GGUF)', false),
            ('llm.llamacpp.embedding_model', '', 'string', 'llm', 'Modele embedding pour llama.cpp', false)
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    """Supprime les cles de configuration des modeles par provider."""

    op.execute("""
        DELETE FROM system_configs
        WHERE key IN (
            'llm.ollama.llm_model',
            'llm.ollama.embedding_model',
            'llm.llamacpp.llm_model',
            'llm.llamacpp.embedding_model'
        );
    """)
