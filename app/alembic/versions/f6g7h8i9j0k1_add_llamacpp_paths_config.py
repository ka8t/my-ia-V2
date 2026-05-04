"""Add llama.cpp paths configuration keys

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-02-21

Ajoute les cles de configuration pour les chemins llama.cpp:
- llm.llamacpp.server_path : chemin vers le binaire llama-server
- llm.llamacpp.models_dir : repertoire des modeles GGUF
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Nouvelles cles de configuration llama.cpp pour les chemins
LLAMACPP_PATHS_CONFIG_KEYS = [
    # (key, value, value_type, description)
    (
        "llm.llamacpp.server_path",
        "/Users/mac/Documents/Code/llama.cpp/build/bin/llama-server",
        "string",
        "Chemin absolu vers le binaire llama-server"
    ),
    (
        "llm.llamacpp.models_dir",
        "/Users/mac/Documents/Code/my-ia/models/gguf",
        "string",
        "Repertoire des modeles GGUF pour llama.cpp"
    ),
]


def upgrade() -> None:
    """Ajoute les cles de configuration llama.cpp pour les chemins."""
    conn = op.get_bind()

    for key, value, value_type, description in LLAMACPP_PATHS_CONFIG_KEYS:
        conn.execute(
            sa.text("""
                INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
                VALUES (:key, :value, :value_type, 'llm', :description, false)
                ON CONFLICT (key) DO NOTHING
            """),
            {
                "key": key,
                "value": value,
                "value_type": value_type,
                "description": description
            }
        )


def downgrade() -> None:
    """Supprime les cles de configuration llama.cpp pour les chemins."""
    conn = op.get_bind()

    for key, _, _, _ in LLAMACPP_PATHS_CONFIG_KEYS:
        conn.execute(
            sa.text("DELETE FROM system_configs WHERE key = :key"),
            {"key": key}
        )
