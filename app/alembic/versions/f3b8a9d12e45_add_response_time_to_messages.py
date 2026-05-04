"""Add response_time column to messages table

Revision ID: f3b8a9d12e45
Revises: e2a7483c62cd
Create Date: 2025-12-26

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3b8a9d12e45'
down_revision = 'e2a7483c62cd'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Ajoute la colonne response_time pour stocker le temps de réponse en secondes"""
    op.add_column(
        'messages',
        sa.Column('response_time', sa.Float(), nullable=True)
    )


def downgrade() -> None:
    """Supprime la colonne response_time"""
    op.drop_column('messages', 'response_time')
