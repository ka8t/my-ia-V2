"""Add voice auto-send and TTS preferences

Revision ID: g7h8i9j0k1l2
Revises: f6e5d4c3b2a1
Create Date: 2026-02-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6e5d4c3b2a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les colonnes vocales dans user_preferences et les cles speech.* dans system_configs."""

    # --- 5 colonnes dans user_preferences ---
    op.add_column('user_preferences', sa.Column('voice_auto_send', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('user_preferences', sa.Column('voice_tts_enabled', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.add_column('user_preferences', sa.Column('voice_tts_auto_play', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    op.add_column('user_preferences', sa.Column('voice_tts_voice', sa.String(length=100), nullable=False, server_default=sa.text("''")))
    op.add_column('user_preferences', sa.Column('voice_tts_rate', sa.Float(), nullable=False, server_default=sa.text('1.0')))

    # --- 6 cles speech.* dans system_configs ---
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
        VALUES
            ('speech.auto_send_enabled', 'true', 'bool', 'speech', 'Activer globalement l''auto-envoi apres dictee', false),
            ('speech.silence_duration_ms', '1500', 'int', 'speech', 'Duree de silence avant arret automatique (ms)', false),
            ('speech.silence_threshold', '0.01', 'float', 'speech', 'Seuil RMS de detection du silence (0-1)', false),
            ('speech.tts_enabled', 'true', 'bool', 'speech', 'Activer globalement la lecture vocale TTS', false),
            ('speech.tts_mode', 'native', 'string', 'speech', 'Mode TTS : native (navigateur) ou server (Piper)', false),
            ('speech.tts_default_rate', '1.0', 'float', 'speech', 'Vitesse de lecture TTS par defaut (0.5-2.0)', false)
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    """Supprime les colonnes vocales et les cles speech.* ajoutees."""

    # --- Supprimer les colonnes ---
    op.drop_column('user_preferences', 'voice_tts_rate')
    op.drop_column('user_preferences', 'voice_tts_voice')
    op.drop_column('user_preferences', 'voice_tts_auto_play')
    op.drop_column('user_preferences', 'voice_tts_enabled')
    op.drop_column('user_preferences', 'voice_auto_send')

    # --- Supprimer les cles config ---
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN (
            'speech.auto_send_enabled',
            'speech.silence_duration_ms',
            'speech.silence_threshold',
            'speech.tts_enabled',
            'speech.tts_mode',
            'speech.tts_default_rate'
        );
    """)
