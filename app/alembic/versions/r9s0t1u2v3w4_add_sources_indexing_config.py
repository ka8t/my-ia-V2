"""Add sources indexing configuration keys

Revision ID: r9s0t1u2v3w4
Revises: q8r9s0t1u2v3
Create Date: 2026-01-16

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'r9s0t1u2v3w4'
down_revision: Union[str, None] = 'q8r9s0t1u2v3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter les clés de configuration pour l'indexation des sources externes
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('sources.min_context_results', '3', 'int', 'sources',
         'Nombre minimum de résultats ChromaDB avant appel sources externes (1-10)'),
        ('sources.min_similarity', '0.6', 'float', 'sources',
         'Similarité minimum pour considérer un résultat pertinent (0.0-1.0)'),
        ('sources.index_results', 'true', 'bool', 'sources',
         'Indexer les résultats des sources externes dans ChromaDB'),
        ('sources.index_ttl_hours', '24', 'int', 'sources',
         'Durée de vie des résultats indexés en heures (1-168)'),
        ('sources.collection_name', 'external_sources', 'string', 'sources',
         'Nom de la collection ChromaDB pour les sources externes')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer les clés ajoutées
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN (
            'sources.min_context_results',
            'sources.min_similarity',
            'sources.index_results',
            'sources.index_ttl_hours',
            'sources.collection_name'
        )
    """)
