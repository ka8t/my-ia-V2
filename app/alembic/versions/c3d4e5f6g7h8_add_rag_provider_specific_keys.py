"""Add RAG provider-specific config keys

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g8
Create Date: 2026-02-16

Cette migration ajoute des clés de configuration RAG spécifiques à chaque provider.
Les clés globales rag.* sont copiées vers rag.ollama.* et rag.llamacpp.*
pour permettre une configuration RAG différente selon le provider actif.

Pattern: rag.<provider>.<key>
Exemple: rag.ollama.top_k, rag.llamacpp.temperature
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Clés RAG à migrer vers configuration provider-specific
RAG_KEYS = [
    ("top_k", "5", "integer", "Nombre de chunks par recherche"),
    ("similarity_threshold", "0.7", "float", "Seuil de similarité (0-1)"),
    ("temperature", "0.7", "float", "Température du LLM (0-2)"),
    ("chunk_size", "1000", "integer", "Taille des chunks en caractères"),
    ("chunk_overlap", "200", "integer", "Chevauchement entre chunks"),
    ("chunking_strategy", "semantic", "string", "Stratégie de découpage"),
    ("min_chunk_length", "50", "integer", "Longueur minimale d'un chunk"),
    ("keyword_boost", "0.15", "float", "Boost pour la recherche hybride"),
    ("stopwords_language", "fr", "string", "Langue des stop words"),
    ("use_corpus", "true", "boolean", "Utiliser les corpus"),
    ("require_sources", "false", "boolean", "Exiger des sources pour répondre"),
]


def upgrade() -> None:
    """Crée les clés RAG spécifiques à chaque provider."""
    conn = op.get_bind()

    providers = ["ollama", "llamacpp"]

    for key, default_value, value_type, description in RAG_KEYS:
        # Lire la valeur globale existante (rag.<key>)
        result = conn.execute(
            sa.text(f"SELECT value FROM system_configs WHERE key = 'rag.{key}'")
        ).fetchone()

        # Utiliser la valeur existante ou le défaut
        value = result[0] if result else default_value

        # Créer les clés pour chaque provider
        for provider in providers:
            conn.execute(
                sa.text("""
                    INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
                    VALUES (:key, :value, :value_type, 'rag', :description, false)
                    ON CONFLICT (key) DO NOTHING
                """),
                {
                    "key": f"rag.{provider}.{key}",
                    "value": value,
                    "value_type": value_type,
                    "description": f"{description} ({provider})"
                }
            )


def downgrade() -> None:
    """Supprime les clés RAG provider-specific."""
    conn = op.get_bind()

    providers = ["ollama", "llamacpp"]

    for key, _, _, _ in RAG_KEYS:
        for provider in providers:
            conn.execute(
                sa.text(f"DELETE FROM system_configs WHERE key = 'rag.{provider}.{key}'")
            )
