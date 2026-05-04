"""Add progress tracking to source_indexation_log

Revision ID: e2f3g4h5i6j7
Revises: d1e2f3g4h5i6
Create Date: 2026-01-30

Adds progress tracking fields to source_indexation_log:
- progress: integer 0-100 for percentage tracking
- progress_message: short message describing current step
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2f3g4h5i6j7'
down_revision: Union[str, None] = 'd1e2f3g4h5i6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'source_indexation_log',
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0')
    )
    op.add_column(
        'source_indexation_log',
        sa.Column('progress_message', sa.String(255), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('source_indexation_log', 'progress_message')
    op.drop_column('source_indexation_log', 'progress')
