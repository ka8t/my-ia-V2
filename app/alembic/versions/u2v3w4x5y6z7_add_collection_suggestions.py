"""Add suggested_questions and suggestions_generated_at to collections

Revision ID: u2v3w4x5y6z7
Revises: t1u2v3w4x5y6
Create Date: 2026-01-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'u2v3w4x5y6z7'
down_revision = 't1u2v3w4x5y6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add suggested_questions cache columns to collections table."""
    # Cache des questions suggerees generees par Ollama
    op.add_column(
        'collections',
        sa.Column('suggested_questions', JSONB, nullable=True)
    )
    # Timestamp de generation pour invalider le cache
    op.add_column(
        'collections',
        sa.Column('suggestions_generated_at', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Remove suggested_questions cache columns from collections table."""
    op.drop_column('collections', 'suggestions_generated_at')
    op.drop_column('collections', 'suggested_questions')
