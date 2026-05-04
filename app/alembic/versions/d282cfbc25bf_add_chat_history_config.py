"""Add chat history config keys

Revision ID: d282cfbc25bf
Revises: f4g5h6i7j8k9
Create Date: 2026-02-01

Ajoute les clés SystemConfig pour la continuité conversationnelle :
- chat.history_enabled : activer/désactiver l'injection de l'historique
- chat.history_max_turns : nombre max de tours d'historique envoyés au LLM
- chat.history_max_tokens : budget tokens maximum pour l'historique
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd282cfbc25bf'
down_revision: Union[str, None] = 'f4g5h6i7j8k9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Clés de configuration pour l'historique conversationnel
CHAT_HISTORY_CONFIGS = [
    {
        "key": "chat.history_enabled",
        "value": "true",
        "value_type": "bool",
        "category": "chat",
        "description": "Activer l'injection de l'historique conversationnel dans le prompt LLM",
        "is_sensitive": False,
    },
    {
        "key": "chat.history_max_turns",
        "value": "5",
        "value_type": "int",
        "category": "chat",
        "description": "Nombre maximum de tours d'historique envoyés au LLM (1 tour = 1 question + 1 réponse)",
        "is_sensitive": False,
    },
    {
        "key": "chat.history_max_tokens",
        "value": "4096",
        "value_type": "int",
        "category": "chat",
        "description": "Budget tokens maximum pour l'historique conversationnel (hors system prompt et question courante)",
        "is_sensitive": False,
    },
]


def upgrade() -> None:
    """Insère les clés de configuration chat.history_*."""
    for config in CHAT_HISTORY_CONFIGS:
        op.execute(
            sa.text(
                "INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive) "
                "VALUES (:key, :value, :value_type, :category, :description, :is_sensitive) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(**config)
        )


def downgrade() -> None:
    """Supprime les clés de configuration chat.history_*."""
    op.execute(
        sa.text(
            "DELETE FROM system_configs WHERE key IN ("
            "'chat.history_enabled', 'chat.history_max_turns', 'chat.history_max_tokens'"
            ")"
        )
    )
