"""Add source indexation log table and config fields

Revision ID: y6z7a8b9c0d1
Revises: x5y6z7a8b9c0
Create Date: 2026-01-23

Adds:
- source_indexation_log table for tracking indexation history
- New fields in context_sources for per-source indexation config
- Config key for log retention
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'y6z7a8b9c0d1'
down_revision: Union[str, None] = 'x5y6z7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Ajouter les champs d'indexation à context_sources
    op.add_column('context_sources', sa.Column('index_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('context_sources', sa.Column('index_ttl_hours', sa.Integer(), nullable=True))
    op.add_column('context_sources', sa.Column('auto_refresh', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('context_sources', sa.Column('refresh_interval_hours', sa.Integer(), nullable=True))
    op.add_column('context_sources', sa.Column('replace_on_refresh', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('context_sources', sa.Column('last_indexed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('context_sources', sa.Column('last_content_hash', sa.String(64), nullable=True))

    # 2. Créer la table source_indexation_log
    op.create_table(
        'source_indexation_log',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_id', UUID(as_uuid=True), sa.ForeignKey('context_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('indexed_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),

        # Statistiques
        sa.Column('documents_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('replaced_count', sa.Integer(), nullable=False, server_default='0'),

        # Déclencheur
        sa.Column('trigger_type', sa.String(20), nullable=False),  # 'manual', 'scheduled', 'on_create'
        sa.Column('triggered_by', UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),

        # Détection de changements
        sa.Column('content_hash', sa.String(64), nullable=True),
        sa.Column('content_changed', sa.Boolean(), nullable=False, server_default='false'),

        # Résultat
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),  # 'pending', 'running', 'success', 'failed'
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
    )

    # 3. Créer les index pour la recherche
    op.create_index('ix_source_indexation_log_source_id', 'source_indexation_log', ['source_id'])
    op.create_index('ix_source_indexation_log_indexed_at', 'source_indexation_log', ['indexed_at'])
    op.create_index('ix_source_indexation_log_status', 'source_indexation_log', ['status'])

    # 4. Ajouter la clé de configuration pour la rétention des logs
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('sources.log_retention_days', '90', 'int', 'sources',
         'Durée de rétention des logs d''indexation en jours (0 = illimité)'),
        ('sources.stale_warning_percent', '80', 'int', 'sources',
         'Seuil d''alerte fraîcheur en pourcentage du TTL (50-100)')
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer les clés de configuration
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN ('sources.log_retention_days', 'sources.stale_warning_percent')
    """)

    # Supprimer les index
    op.drop_index('ix_source_indexation_log_status', table_name='source_indexation_log')
    op.drop_index('ix_source_indexation_log_indexed_at', table_name='source_indexation_log')
    op.drop_index('ix_source_indexation_log_source_id', table_name='source_indexation_log')

    # Supprimer la table
    op.drop_table('source_indexation_log')

    # Supprimer les colonnes de context_sources
    op.drop_column('context_sources', 'last_content_hash')
    op.drop_column('context_sources', 'last_indexed_at')
    op.drop_column('context_sources', 'replace_on_refresh')
    op.drop_column('context_sources', 'refresh_interval_hours')
    op.drop_column('context_sources', 'auto_refresh')
    op.drop_column('context_sources', 'index_ttl_hours')
    op.drop_column('context_sources', 'index_enabled')
