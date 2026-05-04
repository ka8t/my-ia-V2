"""Add RAG config keys for similarity_threshold, temperature, top_k, chunking_strategy

Revision ID: n5o6p7q8r9s0
Revises: m4n5o6p7q8r9
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'n5o6p7q8r9s0'
down_revision: Union[str, None] = 'm4n5o6p7q8r9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter les nouvelles cles RAG dans system_configs
    # On utilise INSERT ... ON CONFLICT DO NOTHING pour eviter les erreurs si les cles existent
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('rag.top_k', '5', 'int', 'rag',
         'Nombre de chunks retournés par recherche vectorielle (1-20)'),
        ('rag.similarity_threshold', '0.7', 'float', 'rag',
         'Seuil de similarité minimum pour retourner un chunk (0.0-1.0)'),
        ('rag.temperature', '0.7', 'float', 'rag',
         'Température du LLM pour la génération de réponses (0.0-2.0)'),
        ('rag.chunk_size', '1000', 'int', 'rag',
         'Taille des chunks en caractères (100-4000)'),
        ('rag.chunk_overlap', '200', 'int', 'rag',
         'Chevauchement entre les chunks (0-500)'),
        ('rag.chunking_strategy', 'semantic', 'string', 'rag',
         'Stratégie de découpage des documents (semantic, fixed, recursive)')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer les cles ajoutees
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN (
            'rag.top_k',
            'rag.similarity_threshold',
            'rag.temperature',
            'rag.chunk_size',
            'rag.chunk_overlap',
            'rag.chunking_strategy'
        )
    """)
