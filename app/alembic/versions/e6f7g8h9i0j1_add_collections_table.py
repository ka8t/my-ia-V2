"""Add collections table and FK to conversations/documents

Revision ID: e6f7g8h9i0j1
Revises: d5e6f7g8h9i0
Create Date: 2025-12-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6f7g8h9i0j1'
down_revision: Union[str, None] = 'd5e6f7g8h9i0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Supprimer les conversations et documents existants (pas de retrocompatibilite)
    op.execute("TRUNCATE TABLE messages CASCADE")
    op.execute("TRUNCATE TABLE document_versions CASCADE")
    op.execute("TRUNCATE TABLE document_shares CASCADE")
    op.execute("TRUNCATE TABLE conversations CASCADE")
    op.execute("TRUNCATE TABLE documents CASCADE")

    # 2. Creer la table collections
    op.create_table(
        'collections',
        sa.Column('id', sa.UUID(), nullable=False, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('owner_id', sa.UUID(), nullable=True),
        sa.Column('space', sa.String(20), server_default='cosine', nullable=False),
        sa.Column('document_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('chunk_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('name')
    )
    op.create_index('idx_collections_type', 'collections', ['type'])
    op.create_index('idx_collections_owner', 'collections', ['owner_id'])

    # 3. Ajouter collection_id a conversations (NOT NULL)
    op.add_column('conversations', sa.Column('collection_id', sa.UUID(), nullable=True))

    # 4. Ajouter collection_id a documents (NOT NULL)
    op.add_column('documents', sa.Column('collection_id', sa.UUID(), nullable=True))

    # 5. Creer les collections privees pour chaque utilisateur existant
    op.execute("""
        INSERT INTO collections (name, display_name, type, owner_id)
        SELECT
            'user_' || id::text,
            'Ma bibliothèque',
            'private',
            id
        FROM users
    """)

    # 6. Creer une collection publique par defaut
    op.execute("""
        INSERT INTO collections (name, display_name, type, description)
        VALUES ('public_general', 'Collection generale', 'public', 'Documents accessibles a tous les utilisateurs')
    """)

    # 7. Rendre collection_id NOT NULL apres creation des collections
    # Pour conversations: mettre la collection privee de l'utilisateur par defaut
    # (pas de donnees car TRUNCATE)
    op.alter_column('conversations', 'collection_id', nullable=False)
    op.create_foreign_key('fk_conversations_collection', 'conversations', 'collections', ['collection_id'], ['id'])
    op.create_index('idx_conversations_collection', 'conversations', ['collection_id'])

    # Pour documents: idem
    op.alter_column('documents', 'collection_id', nullable=False)
    op.create_foreign_key('fk_documents_collection', 'documents', 'collections', ['collection_id'], ['id'])
    op.create_index('idx_documents_collection', 'documents', ['collection_id'])


def downgrade() -> None:
    # Supprimer les FK et colonnes
    op.drop_constraint('fk_documents_collection', 'documents', type_='foreignkey')
    op.drop_index('idx_documents_collection', 'documents')
    op.drop_column('documents', 'collection_id')

    op.drop_constraint('fk_conversations_collection', 'conversations', type_='foreignkey')
    op.drop_index('idx_conversations_collection', 'conversations')
    op.drop_column('conversations', 'collection_id')

    # Supprimer la table collections
    op.drop_index('idx_collections_owner', 'collections')
    op.drop_index('idx_collections_type', 'collections')
    op.drop_table('collections')
