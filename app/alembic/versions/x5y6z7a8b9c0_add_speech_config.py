"""Add speech configuration keys

Revision ID: x5y6z7a8b9c0
Revises: w4x5y6z7a8b9
Create Date: 2026-01-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'x5y6z7a8b9c0'
down_revision: Union[str, None] = 'w4x5y6z7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les cles de configuration speech dans system_configs."""
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
        VALUES
            ('speech.enabled', 'true', 'bool', 'speech', 'Activer le service Speech-to-Text globalement', false),
            ('speech.model', 'small', 'string', 'speech', 'Modele Whisper (tiny/base/small/medium)', false),
            ('speech.default_language', 'fr', 'string', 'speech', 'Langue par defaut pour la transcription', false),
            ('speech.max_duration', '60', 'int', 'speech', 'Duree max audio en secondes', false),
            ('speech.timeout', '120', 'int', 'speech', 'Timeout transcription en secondes', false)
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    """Supprime les cles de configuration speech."""
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN (
            'speech.enabled',
            'speech.model',
            'speech.default_language',
            'speech.max_duration',
            'speech.timeout'
        );
    """)
