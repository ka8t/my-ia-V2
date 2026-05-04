"""Add llama.cpp configuration keys

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-02-21

Ajoute les cles de configuration llama.cpp pour le chargement depuis BDD:
- llm.llamacpp.host, port, ctx_size, batch_size, gpu_layers
- llm.llamacpp.parallel, threads, mmap, mlock, flash_attn
- llm.llamacpp.embedding_mode, metrics_enabled
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, None] = 'b5852d8fe717'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Configuration llama.cpp avec valeurs par defaut
LLAMACPP_CONFIG_KEYS = [
    # (key, value, value_type, description)
    ("llm.llamacpp.host", "host.docker.internal", "string", "Hote llama-server (depuis Docker vers hote natif)"),
    ("llm.llamacpp.port", "8085", "integer", "Port llama-server"),
    ("llm.llamacpp.ctx_size", "4096", "integer", "Taille du contexte en tokens (512-131072)"),
    ("llm.llamacpp.batch_size", "2048", "integer", "Taille du batch de traitement (1-8192)"),
    ("llm.llamacpp.gpu_layers", "99", "integer", "Couches GPU (0=CPU, 99=toutes)"),
    ("llm.llamacpp.parallel", "-1", "integer", "Slots paralleles (-1=auto, max 32)"),
    ("llm.llamacpp.threads", "-1", "integer", "Threads CPU (-1=auto)"),
    ("llm.llamacpp.mmap", "true", "boolean", "Memory-map du modele (recommande)"),
    ("llm.llamacpp.mlock", "false", "boolean", "Verrouillage RAM (empeche swap)"),
    ("llm.llamacpp.flash_attn", "auto", "string", "Flash attention (auto/on/off)"),
    ("llm.llamacpp.embedding_mode", "true", "boolean", "Active endpoint /v1/embeddings"),
    ("llm.llamacpp.metrics_enabled", "true", "boolean", "Active endpoint /metrics Prometheus"),
]


def upgrade() -> None:
    """Ajoute les cles de configuration llama.cpp."""
    conn = op.get_bind()

    for key, value, value_type, description in LLAMACPP_CONFIG_KEYS:
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
    """Supprime les cles de configuration llama.cpp."""
    conn = op.get_bind()

    for key, _, _, _ in LLAMACPP_CONFIG_KEYS:
        conn.execute(
            sa.text("DELETE FROM system_configs WHERE key = :key"),
            {"key": key}
        )
