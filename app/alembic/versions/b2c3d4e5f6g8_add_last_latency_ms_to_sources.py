"""add last_latency_ms to context_sources

Revision ID: b2c3d4e5f6g8
Revises: a1b2c3d4e5f7
Create Date: 2026-02-14
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g8'
down_revision = 'a1b2c3d4e5f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'context_sources',
        sa.Column('last_latency_ms', sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('context_sources', 'last_latency_ms')
