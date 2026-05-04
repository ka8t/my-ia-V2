"""Enable rag.use_groups by default

Revision ID: m5n6o7p8q9r0
Revises: l4m5n6o7p8q9
Create Date: 2026-02-05

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'm5n6o7p8q9r0'
down_revision: Union[str, None] = 'l4m5n6o7p8q9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Activer les groupes par défaut pour que les conversations
    # utilisent automatiquement le groupe de leur collection
    op.execute("""
        UPDATE system_configs
        SET value = 'true'
        WHERE key = 'rag.use_groups'
    """)


def downgrade() -> None:
    # Revenir à l'ancien comportement
    op.execute("""
        UPDATE system_configs
        SET value = 'false'
        WHERE key = 'rag.use_groups'
    """)
