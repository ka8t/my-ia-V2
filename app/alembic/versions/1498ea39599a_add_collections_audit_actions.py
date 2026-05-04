"""Add collections audit actions

Revision ID: 1498ea39599a
Revises: 18edcd7b5686
Create Date: 2026-02-01

Ajoute les actions d'audit manquantes pour les collections.
"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1498ea39599a'
down_revision: Union[str, None] = '18edcd7b5686'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les actions d'audit pour les collections."""
    actions = [
        ('collection_updated', 'Collection mise à jour', 'info'),
        ('collection_cleared', 'Collection vidée', 'warning'),
        ('bulk_collections_deleted', 'Suppression groupée de collections', 'warning'),
        ('bulk_collections_cleared', 'Vidage groupé de collections', 'warning'),
    ]

    for name, display_name, severity in actions:
        op.execute(f"""
            INSERT INTO audit_actions (name, display_name, severity)
            VALUES ('{name}', '{display_name}', '{severity}')
            ON CONFLICT (name) DO NOTHING;
        """)


def downgrade() -> None:
    """Supprime les actions d'audit collections."""
    actions = [
        'collection_updated',
        'collection_cleared',
        'bulk_collections_deleted',
        'bulk_collections_cleared',
    ]
    for action in actions:
        op.execute(f"DELETE FROM audit_actions WHERE name = '{action}';")
