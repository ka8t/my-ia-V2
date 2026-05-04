"""Add collection_sources table for linking sources to collections

Revision ID: j2k3l4m5n6o7
Revises: h8i9j0k1l2m3
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'j2k3l4m5n6o7'
down_revision: Union[str, None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Creer la table de liaison collection_sources
    op.create_table(
        'collection_sources',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('collection_id', UUID(as_uuid=True), sa.ForeignKey('collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_id', UUID(as_uuid=True), sa.ForeignKey('context_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),
        sa.Column('is_enabled', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Contrainte d'unicite (une source ne peut etre liee qu'une fois a une collection)
    op.create_unique_constraint('uq_collection_source', 'collection_sources', ['collection_id', 'source_id'])

    # Index pour les requetes frequentes
    op.create_index('idx_collection_sources_collection', 'collection_sources', ['collection_id'])
    op.create_index('idx_collection_sources_source', 'collection_sources', ['source_id'])
    op.create_index('idx_collection_sources_priority', 'collection_sources', ['collection_id', 'priority'])

    # Ajouter les cles de configuration pour le filtrage par collection
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('rag.source_filter_by_collection', 'false', 'bool', 'rag', 'Filtrer les sources externes par collection (si false, toutes les sources actives sont utilisees)'),
        ('rag.include_global_sources', 'true', 'bool', 'rag', 'Inclure les sources non assignees a une collection dans le RAG')
        ON CONFLICT (key) DO NOTHING
    """)

    # Ajouter les actions d'audit (table audit_actions: name, display_name, severity)
    op.execute("""
        INSERT INTO audit_actions (name, display_name, severity) VALUES
        ('collection_source_added', 'Source ajoutee a collection', 'info'),
        ('collection_source_removed', 'Source retiree de collection', 'info'),
        ('collection_source_updated', 'Liaison source-collection modifiee', 'info')
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer les actions d'audit
    op.execute("""
        DELETE FROM audit_actions
        WHERE name IN ('collection_source_added', 'collection_source_removed', 'collection_source_updated')
    """)

    # Supprimer les cles de configuration
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN ('rag.source_filter_by_collection', 'rag.include_global_sources')
    """)

    # Supprimer les index
    op.drop_index('idx_collection_sources_priority')
    op.drop_index('idx_collection_sources_source')
    op.drop_index('idx_collection_sources_collection')

    # Supprimer la contrainte
    op.drop_constraint('uq_collection_source', 'collection_sources', type_='unique')

    # Supprimer la table
    op.drop_table('collection_sources')
