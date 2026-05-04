"""Add corpus_id to documents - Documents can belong to a corpus or a collection

Un document appartient soit a un corpus (docs publics geres par admin),
soit a une collection privee (docs prives d'un utilisateur).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '702cded8cb2c'
down_revision = 'n6o7p8q9r0s1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === Collection sources - normalisation index ===
    op.alter_column('collection_sources', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index('idx_collection_sources_collection', table_name='collection_sources', if_exists=True)
    op.drop_index('idx_collection_sources_priority', table_name='collection_sources', if_exists=True)
    op.drop_index('idx_collection_sources_source', table_name='collection_sources', if_exists=True)
    op.create_index(op.f('ix_collection_sources_collection_id'), 'collection_sources', ['collection_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_collection_sources_source_id'), 'collection_sources', ['source_id'], unique=False, if_not_exists=True)

    # === Collections - normalisation index corpus_id ===
    op.drop_index('idx_collections_group', table_name='collections', if_exists=True)
    op.create_index(op.f('ix_collections_corpus_id'), 'collections', ['corpus_id'], unique=False, if_not_exists=True)

    # === Corpus - normalisation timestamps ===
    op.alter_column('corpus', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.alter_column('corpus', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index('idx_collection_groups_active', table_name='corpus', if_exists=True)
    op.drop_index('idx_collection_groups_name', table_name='corpus', if_exists=True)

    # === Corpus collections - normalisation index ===
    op.alter_column('corpus_collections', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index('idx_group_members_collection', table_name='corpus_collections', if_exists=True)
    op.drop_index('idx_group_members_group', table_name='corpus_collections', if_exists=True)
    op.drop_index('idx_group_members_priority', table_name='corpus_collections', if_exists=True)
    op.create_index(op.f('ix_corpus_collections_collection_id'), 'corpus_collections', ['collection_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_corpus_collections_corpus_id'), 'corpus_collections', ['corpus_id'], unique=False, if_not_exists=True)

    # === Corpus sources - normalisation index ===
    op.alter_column('corpus_sources', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False,
               existing_server_default=sa.text('now()'))
    op.drop_index('idx_group_sources_group', table_name='corpus_sources', if_exists=True)
    op.drop_index('idx_group_sources_priority', table_name='corpus_sources', if_exists=True)
    op.drop_index('idx_group_sources_source', table_name='corpus_sources', if_exists=True)
    op.create_index(op.f('ix_corpus_sources_corpus_id'), 'corpus_sources', ['corpus_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_corpus_sources_source_id'), 'corpus_sources', ['source_id'], unique=False, if_not_exists=True)

    # === Documents - ajout corpus_id ===
    # 1. Ajouter la colonne corpus_id
    op.add_column('documents', sa.Column('corpus_id', sa.Uuid(), nullable=True))

    # 2. Rendre collection_id nullable
    op.alter_column('documents', 'collection_id',
               existing_type=sa.UUID(),
               nullable=True)

    # 3. Creer les index
    op.create_index(op.f('ix_documents_collection_id'), 'documents', ['collection_id'], unique=False, if_not_exists=True)
    op.create_index(op.f('ix_documents_corpus_id'), 'documents', ['corpus_id'], unique=False, if_not_exists=True)

    # 4. Mettre a jour les foreign keys
    op.drop_constraint('fk_documents_collection', 'documents', type_='foreignkey')
    op.create_foreign_key('fk_documents_corpus', 'documents', 'corpus', ['corpus_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_documents_collection', 'documents', 'collections', ['collection_id'], ['id'], ondelete='CASCADE')

    # 5. Note: La contrainte CHECK sera ajoutee plus tard, une fois les documents existants migres
    # Les documents existants ont deja collection_id, donc ils sont valides
    # op.create_check_constraint(
    #     'ck_document_corpus_or_collection',
    #     'documents',
    #     '(corpus_id IS NOT NULL AND collection_id IS NULL) OR (corpus_id IS NULL AND collection_id IS NOT NULL)'
    # )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint(None, 'documents', type_='foreignkey')
    op.drop_constraint(None, 'documents', type_='foreignkey')
    op.create_foreign_key('fk_documents_collection', 'documents', 'collections', ['collection_id'], ['id'])
    op.drop_index(op.f('ix_documents_corpus_id'), table_name='documents')
    op.drop_index(op.f('ix_documents_collection_id'), table_name='documents')
    op.alter_column('documents', 'collection_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('documents', 'corpus_id')
    op.drop_index(op.f('ix_corpus_sources_source_id'), table_name='corpus_sources')
    op.drop_index(op.f('ix_corpus_sources_corpus_id'), table_name='corpus_sources')
    op.create_index('idx_group_sources_source', 'corpus_sources', ['source_id'], unique=False)
    op.create_index('idx_group_sources_priority', 'corpus_sources', ['corpus_id', 'priority'], unique=False)
    op.create_index('idx_group_sources_group', 'corpus_sources', ['corpus_id'], unique=False)
    op.alter_column('corpus_sources', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.drop_index(op.f('ix_corpus_collections_corpus_id'), table_name='corpus_collections')
    op.drop_index(op.f('ix_corpus_collections_collection_id'), table_name='corpus_collections')
    op.create_index('idx_group_members_priority', 'corpus_collections', ['corpus_id', 'priority'], unique=False)
    op.create_index('idx_group_members_group', 'corpus_collections', ['corpus_id'], unique=False)
    op.create_index('idx_group_members_collection', 'corpus_collections', ['collection_id'], unique=False)
    op.alter_column('corpus_collections', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.create_index('idx_collection_groups_name', 'corpus', ['name'], unique=False)
    op.create_index('idx_collection_groups_active', 'corpus', ['is_active'], unique=False)
    op.alter_column('corpus', 'updated_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.alter_column('corpus', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    op.drop_index(op.f('ix_collections_corpus_id'), table_name='collections')
    op.create_index('idx_collections_group', 'collections', ['corpus_id'], unique=False)
    op.drop_index(op.f('ix_collection_sources_source_id'), table_name='collection_sources')
    op.drop_index(op.f('ix_collection_sources_collection_id'), table_name='collection_sources')
    op.create_index('idx_collection_sources_source', 'collection_sources', ['source_id'], unique=False)
    op.create_index('idx_collection_sources_priority', 'collection_sources', ['collection_id', 'priority'], unique=False)
    op.create_index('idx_collection_sources_collection', 'collection_sources', ['collection_id'], unique=False)
    op.alter_column('collection_sources', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=True,
               existing_server_default=sa.text('now()'))
    # ### end Alembic commands ###
