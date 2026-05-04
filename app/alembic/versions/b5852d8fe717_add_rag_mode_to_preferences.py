"""add_rag_mode_to_preferences

Revision ID: b5852d8fe717
Revises: d4e5f6g7h8i9
Create Date: 2026-02-18

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b5852d8fe717'
down_revision = 'd4e5f6g7h8i9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajouter la colonne avec une valeur par défaut serveur
    op.add_column('user_preferences', sa.Column('rag_mode', sa.String(length=10), nullable=False, server_default='auto'))


def downgrade() -> None:
    op.drop_column('user_preferences', 'rag_mode')
