"""Add deleted_at column to messages table for soft delete

Revision ID: a1b2c3d4e5f6
Revises: f3b8a9d12e45
Create Date: 2025-12-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f3b8a9d12e45'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ajoute la colonne deleted_at pour le soft delete des messages"""
    op.add_column(
        'messages',
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True)
    )
    # Index pour optimiser les requêtes sur les messages non supprimés
    op.create_index(
        'ix_messages_deleted_at',
        'messages',
        ['deleted_at'],
        postgresql_where=sa.text('deleted_at IS NULL')
    )


def downgrade() -> None:
    """Supprime la colonne deleted_at"""
    op.drop_index('ix_messages_deleted_at', table_name='messages')
    op.drop_column('messages', 'deleted_at')
