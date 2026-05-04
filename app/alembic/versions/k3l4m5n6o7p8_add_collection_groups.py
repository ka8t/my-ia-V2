"""Add collection_groups tables for grouping collections and sources

Revision ID: k3l4m5n6o7p8
Revises: j2k3l4m5n6o7
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'k3l4m5n6o7p8'
down_revision: Union[str, None] = 'j2k3l4m5n6o7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ==========================================================================
    # Table principale: collection_groups
    # ==========================================================================
    op.create_table(
        'collection_groups',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Index pour recherche par nom
    op.create_index('idx_collection_groups_name', 'collection_groups', ['name'])
    op.create_index('idx_collection_groups_active', 'collection_groups', ['is_active'])

    # ==========================================================================
    # Table de liaison: collection_group_members (groupes <-> collections)
    # ==========================================================================
    op.create_table(
        'collection_group_members',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('group_id', UUID(as_uuid=True), sa.ForeignKey('collection_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('collection_id', UUID(as_uuid=True), sa.ForeignKey('collections.id', ondelete='CASCADE'), nullable=False),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Contrainte d'unicite (une collection ne peut apparaitre qu'une fois dans un groupe)
    op.create_unique_constraint('uq_group_collection', 'collection_group_members', ['group_id', 'collection_id'])

    # Index pour les requetes frequentes
    op.create_index('idx_group_members_group', 'collection_group_members', ['group_id'])
    op.create_index('idx_group_members_collection', 'collection_group_members', ['collection_id'])
    op.create_index('idx_group_members_priority', 'collection_group_members', ['group_id', 'priority'])

    # ==========================================================================
    # Table de liaison: group_sources (groupes <-> sources externes)
    # ==========================================================================
    op.create_table(
        'group_sources',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('group_id', UUID(as_uuid=True), sa.ForeignKey('collection_groups.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_id', UUID(as_uuid=True), sa.ForeignKey('context_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('priority', sa.Integer, nullable=False, server_default='100'),
        sa.Column('is_enabled', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )

    # Contrainte d'unicite (une source ne peut apparaitre qu'une fois dans un groupe)
    op.create_unique_constraint('uq_group_source', 'group_sources', ['group_id', 'source_id'])

    # Index pour les requetes frequentes
    op.create_index('idx_group_sources_group', 'group_sources', ['group_id'])
    op.create_index('idx_group_sources_source', 'group_sources', ['source_id'])
    op.create_index('idx_group_sources_priority', 'group_sources', ['group_id', 'priority'])

    # ==========================================================================
    # Creer le groupe par defaut "Global" (contient toutes les ressources)
    # ==========================================================================
    op.execute("""
        INSERT INTO collection_groups (name, display_name, description, is_active)
        VALUES (
            'global',
            'Global',
            'Groupe par defaut contenant toutes les collections publiques et sources actives',
            true
        )
    """)

    # ==========================================================================
    # Ajouter les cles de configuration
    # ==========================================================================
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description) VALUES
        ('rag.use_groups', 'false', 'bool', 'rag', 'Utiliser les groupes de collections pour le RAG (si false, comportement actuel)'),
        ('rag.default_group', 'global', 'string', 'rag', 'Nom du groupe par defaut si aucun groupe selectionne')
        ON CONFLICT (key) DO NOTHING
    """)

    # ==========================================================================
    # Ajouter les actions d'audit
    # ==========================================================================
    op.execute("""
        INSERT INTO audit_actions (name, display_name, severity) VALUES
        ('collection_group_created', 'Groupe de collections cree', 'info'),
        ('collection_group_updated', 'Groupe de collections modifie', 'info'),
        ('collection_group_deleted', 'Groupe de collections supprime', 'warning'),
        ('group_collection_added', 'Collection ajoutee au groupe', 'info'),
        ('group_collection_removed', 'Collection retiree du groupe', 'info'),
        ('group_source_added', 'Source ajoutee au groupe', 'info'),
        ('group_source_removed', 'Source retiree du groupe', 'info'),
        ('group_source_updated', 'Liaison source-groupe modifiee', 'info')
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer les actions d'audit
    op.execute("""
        DELETE FROM audit_actions
        WHERE name IN (
            'collection_group_created', 'collection_group_updated', 'collection_group_deleted',
            'group_collection_added', 'group_collection_removed',
            'group_source_added', 'group_source_removed', 'group_source_updated'
        )
    """)

    # Supprimer les cles de configuration
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN ('rag.use_groups', 'rag.default_group')
    """)

    # Supprimer les index et tables group_sources
    op.drop_index('idx_group_sources_priority')
    op.drop_index('idx_group_sources_source')
    op.drop_index('idx_group_sources_group')
    op.drop_constraint('uq_group_source', 'group_sources', type_='unique')
    op.drop_table('group_sources')

    # Supprimer les index et tables collection_group_members
    op.drop_index('idx_group_members_priority')
    op.drop_index('idx_group_members_collection')
    op.drop_index('idx_group_members_group')
    op.drop_constraint('uq_group_collection', 'collection_group_members', type_='unique')
    op.drop_table('collection_group_members')

    # Supprimer les index et table collection_groups
    op.drop_index('idx_collection_groups_active')
    op.drop_index('idx_collection_groups_name')
    op.drop_table('collection_groups')
