"""Add chat topic detection config keys

Revision ID: 5f389c414c75
Revises: d282cfbc25bf
Create Date: 2026-02-01

Ajoute les clés SystemConfig pour la détection de changement de sujet :
- chat.topic_detection_enabled : activer/désactiver la détection
- chat.topic_similarity_threshold : seuil de similarité cosinus
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5f389c414c75'
down_revision: Union[str, None] = 'd282cfbc25bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHAT_TOPIC_CONFIGS = [
    {
        "key": "chat.topic_detection_enabled",
        "value": "true",
        "value_type": "bool",
        "category": "chat",
        "description": "Activer la détection de changement de sujet dans les conversations (via similarité d'embeddings)",
        "is_sensitive": False,
    },
    {
        "key": "chat.topic_similarity_threshold",
        "value": "0.3",
        "value_type": "float",
        "category": "chat",
        "description": "Seuil de similarité cosinus en dessous duquel un changement de sujet est détecté (0.0 à 1.0)",
        "is_sensitive": False,
    },
]


def upgrade() -> None:
    """Insère les clés de configuration chat.topic_*."""
    for config in CHAT_TOPIC_CONFIGS:
        op.execute(
            sa.text(
                "INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive) "
                "VALUES (:key, :value, :value_type, :category, :description, :is_sensitive) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(**config)
        )


def downgrade() -> None:
    """Supprime les clés de configuration chat.topic_*."""
    op.execute(
        sa.text(
            "DELETE FROM system_configs WHERE key IN ("
            "'chat.topic_detection_enabled', 'chat.topic_similarity_threshold'"
            ")"
        )
    )
