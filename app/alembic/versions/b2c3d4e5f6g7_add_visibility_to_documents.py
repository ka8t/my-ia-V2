"""Add visibility and is_indexed to documents

Revision ID: b2c3d4e5f6g7
Revises: f3b8a9d12e45
Create Date: 2025-12-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'ae72919117df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Creer l'enum pour la visibilite
    visibility_enum = sa.Enum('public', 'private', name='document_visibility')
    visibility_enum.create(op.get_bind(), checkfirst=True)

    # Ajouter les colonnes
    op.add_column('documents', sa.Column(
        'visibility',
        sa.Enum('public', 'private', name='document_visibility'),
        nullable=False,
        server_default='public'
    ))
    op.add_column('documents', sa.Column(
        'is_indexed',
        sa.Boolean(),
        nullable=False,
        server_default='true'
    ))
    op.add_column('documents', sa.Column(
        'updated_at',
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=True
    ))


def downgrade() -> None:
    op.drop_column('documents', 'updated_at')
    op.drop_column('documents', 'is_indexed')
    op.drop_column('documents', 'visibility')

    # Supprimer l'enum
    visibility_enum = sa.Enum('public', 'private', name='document_visibility')
    visibility_enum.drop(op.get_bind(), checkfirst=True)
