"""Add group_id to collections table

Revision ID: l4m5n6o7p8q9
Revises: k3l4m5n6o7p8
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'l4m5n6o7p8q9'
down_revision: Union[str, None] = 'k3l4m5n6o7p8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter la colonne group_id à la table collections
    op.add_column(
        'collections',
        sa.Column(
            'group_id',
            UUID(as_uuid=True),
            sa.ForeignKey('collection_groups.id', ondelete='SET NULL'),
            nullable=True
        )
    )

    # Index pour les requêtes fréquentes
    op.create_index('idx_collections_group', 'collections', ['group_id'])

    # Assigner le groupe "global" par défaut à toutes les collections publiques existantes
    op.execute("""
        UPDATE collections
        SET group_id = (SELECT id FROM collection_groups WHERE name = 'global')
        WHERE type = 'public'
    """)


def downgrade() -> None:
    # Supprimer l'index
    op.drop_index('idx_collections_group')

    # Supprimer la colonne
    op.drop_column('collections', 'group_id')
