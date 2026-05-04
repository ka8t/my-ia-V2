"""merge_all_heads

Revision ID: zz_merge_heads
Revises: x1y2z3a4b5c6, 47778f382be4
Create Date: 2026-01-27

Migration de fusion pour unifier toutes les branches.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'zz_merge_heads'
down_revision = ('x1y2z3a4b5c6', '47778f382be4')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge migration - no changes needed."""
    pass


def downgrade() -> None:
    """Merge migration - no changes needed."""
    pass
