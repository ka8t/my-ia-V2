"""Add language column to user_preferences

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
Create Date: 2026-01-16

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 's0t1u2v3w4x5'
down_revision = 'r9s0t1u2v3w4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add language column to user_preferences table."""
    op.add_column(
        'user_preferences',
        sa.Column('language', sa.String(5), nullable=False, server_default='fr')
    )


def downgrade() -> None:
    """Remove language column from user_preferences table."""
    op.drop_column('user_preferences', 'language')
