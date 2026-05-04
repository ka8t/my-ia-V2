"""Rename groups to corpus

Revision ID: n6o7p8q9r0s1
Revises: m5n6o7p8q9r0
Create Date: 2026-02-05

Renomme les tables et configurations "group" en "corpus" :
- collection_groups → corpus
- collection_group_members → corpus_collections
- group_sources → corpus_sources
- rag.use_groups → rag.use_corpus
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n6o7p8q9r0s1'
down_revision: Union[str, None] = 'm5n6o7p8q9r0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Renommer les tables
    op.rename_table('collection_groups', 'corpus')
    op.rename_table('collection_group_members', 'corpus_collections')
    op.rename_table('group_sources', 'corpus_sources')

    # 2. Renommer les colonnes group_id en corpus_id
    op.alter_column('corpus_collections', 'group_id', new_column_name='corpus_id')
    op.alter_column('corpus_sources', 'group_id', new_column_name='corpus_id')

    # 3. Renommer la FK dans collections (group_id → corpus_id)
    # D'abord supprimer l'ancienne contrainte FK
    op.drop_constraint('collections_group_id_fkey', 'collections', type_='foreignkey')
    # Renommer la colonne
    op.alter_column('collections', 'group_id', new_column_name='corpus_id')
    # Recréer la FK avec le nouveau nom
    op.create_foreign_key(
        'collections_corpus_id_fkey',
        'collections', 'corpus',
        ['corpus_id'], ['id'],
        ondelete='SET NULL'
    )

    # 4. Renommer les contraintes d'unicité
    op.drop_constraint('uq_group_collection', 'corpus_collections', type_='unique')
    op.create_unique_constraint('uq_corpus_collection', 'corpus_collections', ['corpus_id', 'collection_id'])

    op.drop_constraint('uq_group_source', 'corpus_sources', type_='unique')
    op.create_unique_constraint('uq_corpus_source', 'corpus_sources', ['corpus_id', 'source_id'])

    # 5. Renommer la clé de configuration
    op.execute("""
        UPDATE system_configs
        SET key = 'rag.use_corpus'
        WHERE key = 'rag.use_groups'
    """)


def downgrade() -> None:
    # 1. Renommer la clé de configuration
    op.execute("""
        UPDATE system_configs
        SET key = 'rag.use_groups'
        WHERE key = 'rag.use_corpus'
    """)

    # 2. Renommer les contraintes d'unicité
    op.drop_constraint('uq_corpus_source', 'corpus_sources', type_='unique')
    op.create_unique_constraint('uq_group_source', 'corpus_sources', ['corpus_id', 'source_id'])

    op.drop_constraint('uq_corpus_collection', 'corpus_collections', type_='unique')
    op.create_unique_constraint('uq_group_collection', 'corpus_collections', ['corpus_id', 'collection_id'])

    # 3. Renommer la FK dans collections
    op.drop_constraint('collections_corpus_id_fkey', 'collections', type_='foreignkey')
    op.alter_column('collections', 'corpus_id', new_column_name='group_id')
    op.create_foreign_key(
        'collections_group_id_fkey',
        'collections', 'corpus',
        ['group_id'], ['id'],
        ondelete='SET NULL'
    )

    # 4. Renommer les colonnes corpus_id en group_id
    op.alter_column('corpus_sources', 'corpus_id', new_column_name='group_id')
    op.alter_column('corpus_collections', 'corpus_id', new_column_name='group_id')

    # 5. Renommer les tables
    op.rename_table('corpus_sources', 'group_sources')
    op.rename_table('corpus_collections', 'collection_group_members')
    op.rename_table('corpus', 'collection_groups')
