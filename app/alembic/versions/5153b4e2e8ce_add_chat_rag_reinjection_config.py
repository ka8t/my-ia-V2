"""Add chat RAG reinjection config

Revision ID: 5153b4e2e8ce
Revises: 9b9bec6ec9cc
Create Date: 2026-02-01

Ajoute la clé SystemConfig pour activer/désactiver la réinjection
des sources RAG du dernier message assistant dans les questions de suivi.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5153b4e2e8ce'
down_revision: Union[str, None] = '9b9bec6ec9cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RAG_REINJECTION_CONFIGS = [
    {
        "key": "chat.rag_reinjection_enabled",
        "value": "true",
        "value_type": "bool",
        "category": "chat",
        "description": "Réinjecter les sources RAG du dernier message assistant pour les questions de suivi",
        "is_sensitive": False,
    },
]


def upgrade() -> None:
    """Ajoute la clé SystemConfig pour la réinjection RAG."""
    for config in RAG_REINJECTION_CONFIGS:
        op.execute(
            sa.text(
                "INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive) "
                "VALUES (:key, :value, :value_type, :category, :description, :is_sensitive) "
                "ON CONFLICT (key) DO NOTHING"
            ).bindparams(**config)
        )


def downgrade() -> None:
    """Supprime la clé SystemConfig."""
    op.execute(
        sa.text(
            "DELETE FROM system_configs WHERE key IN ("
            "'chat.rag_reinjection_enabled'"
            ")"
        )
    )
