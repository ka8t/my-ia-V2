"""Add context_sources table for external RAG sources

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
Create Date: 2026-01-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision: str = 'q8r9s0t1u2v3'
down_revision: Union[str, None] = 'p7q8r9s0t1u2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Creer la table context_sources
    op.create_table(
        'context_sources',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), unique=True, nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('source_type', sa.String(20), nullable=False),  # 'web' | 'database' | 'api'
        sa.Column('config', JSONB, nullable=False, server_default='{}'),
        sa.Column('is_enabled', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('timeout_seconds', sa.Integer, nullable=False, server_default='30'),
        sa.Column('max_results', sa.Integer, nullable=False, server_default='5'),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),
        sa.Column('health_status', sa.String(20), server_default="'unknown'"),
        sa.Column('last_health_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Index pour les sources actives
    op.create_index('idx_context_sources_enabled', 'context_sources', ['is_enabled'])
    op.create_index('idx_context_sources_type', 'context_sources', ['source_type'])

    # Ajouter les configs systeme pour les sources
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('sources.enabled', 'false', 'bool', 'sources', 'Active/desactive globalement les sources externes'),
        ('sources.parallel_execution', 'true', 'bool', 'sources', 'Executer les requetes en parallele'),
        ('sources.global_timeout', '60', 'int', 'sources', 'Timeout global pour toutes les sources (secondes)'),
        ('sources.max_context_items', '10', 'int', 'sources', 'Nombre max de resultats a fusionner avec ChromaDB')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer les configs
    op.execute("""
        DELETE FROM system_configs
        WHERE category = 'sources'
    """)

    # Supprimer les index
    op.drop_index('idx_context_sources_type')
    op.drop_index('idx_context_sources_enabled')

    # Supprimer la table
    op.drop_table('context_sources')
