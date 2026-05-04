"""Add voice_to_text_enabled to user_preferences

Revision ID: w4x5y6z7a8b9
Revises: v3w4x5y6z7a8
Create Date: 2026-01-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'w4x5y6z7a8b9'
down_revision: Union[str, None] = 'v3w4x5y6z7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la colonne voice_to_text_enabled avec valeur par defaut false
    op.add_column(
        'user_preferences',
        sa.Column('voice_to_text_enabled', sa.Boolean(), nullable=False, server_default='false')
    )


def downgrade() -> None:
    # Supprimer la colonne
    op.drop_column('user_preferences', 'voice_to_text_enabled')
