"""Add summary to conversations and chat summary config

Revision ID: 9b9bec6ec9cc
Revises: 5f389c414c75
Create Date: 2026-02-01

Ajoute la colonne summary sur la table conversations pour stocker
le résumé automatique des conversations longues, et les clés
SystemConfig pour la configuration du résumé.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9b9bec6ec9cc'
down_revision: Union[str, None] = '5f389c414c75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHAT_SUMMARY_CONFIGS = [
    {
        "key": "chat.summary_enabled",
        "value": "true",
        "value_type": "bool",
        "category": "chat",
        "description": "Activer le résumé automatique des conversations longues",
        "is_sensitive": False,
    },
    {
        "key": "chat.summary_trigger_messages",
        "value": "10",
        "value_type": "int",
        "category": "chat",
        "description": "Nombre de messages dans la conversation avant déclenchement du résumé automatique",
        "is_sensitive": False,
    },
    {
        "key": "chat.summary_max_tokens",
        "value": "500",
        "value_type": "int",
        "category": "chat",
        "description": "Taille maximale du résumé en tokens (~4 caractères par token)",
        "is_sensitive": False,
    },
]


def upgrade() -> None:
    """Ajoute la colonne summary et les clés SystemConfig."""
    # Colonne summary sur conversations
    op.add_column(
        'conversations',
        sa.Column('summary', sa.Text(), nullable=True)
    )

    # Clés SystemConfig
    for config in CHAT_SUMMARY_CONFIGS:
        op.execute(
            sa.text(
                "INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive) "
                "VALUES (:key, :value, :value_type, :category, :description, :is_sensitive) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(**config)
        )


def downgrade() -> None:
    """Supprime la colonne summary et les clés SystemConfig."""
    op.drop_column('conversations', 'summary')

    op.execute(
        sa.text(
            "DELETE FROM system_configs WHERE key IN ("
            "'chat.summary_enabled', 'chat.summary_trigger_messages', 'chat.summary_max_tokens'"
            ")"
        )
    )
