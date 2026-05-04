"""add chunk_count to context_sources

Revision ID: 369d59635d04
Revises: 702cded8cb2c
Create Date: 2026-02-09
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '369d59635d04'
down_revision = '702cded8cb2c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'context_sources',
        sa.Column('chunk_count', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    op.drop_column('context_sources', 'chunk_count')
