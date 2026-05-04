"""Add username column to app_logs

Revision ID: f4g5h6i7j8k9
Revises: 07fdb465d5b3
Create Date: 2026-02-01

Ajoute la colonne username dans la table app_logs pour enrichir
les logs applicatifs avec le nom de l'utilisateur authentifié.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f4g5h6i7j8k9'
down_revision: Union[str, None] = '07fdb465d5b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute la colonne username à app_logs."""
    op.add_column(
        'app_logs',
        sa.Column('username', sa.String(100), nullable=True)
    )


def downgrade() -> None:
    """Supprime la colonne username de app_logs."""
    op.drop_column('app_logs', 'username')
