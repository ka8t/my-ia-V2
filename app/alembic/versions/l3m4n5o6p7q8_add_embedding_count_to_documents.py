"""Add embedding_count column to documents table

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-01-14

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'l3m4n5o6p7q8'
down_revision = 'k2l3m4n5o6p7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ajoute la colonne embedding_count pour stocker le nombre d'embeddings ChromaDB"""
    op.add_column(
        'documents',
        sa.Column('embedding_count', sa.Integer(), nullable=False, server_default='0')
    )
    # Initialiser embedding_count = chunk_count pour les documents existants
    op.execute("UPDATE documents SET embedding_count = chunk_count")


def downgrade() -> None:
    """Supprime la colonne embedding_count"""
    op.drop_column('documents', 'embedding_count')
