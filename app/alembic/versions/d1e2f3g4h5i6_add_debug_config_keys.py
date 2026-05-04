"""Add debug configuration keys

Revision ID: d1e2f3g4h5i6
Revises: zz_merge_heads
Create Date: 2026-01-30

Adds configuration keys for the debug system:
- verbose_logging: toggle INFO/DEBUG log level at runtime
- timing_headers_enabled: inject X-Debug-* headers on API responses
- endpoints_enabled: enable/disable /auth/debug/* endpoints
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3g4h5i6'
down_revision: Union[str, None] = 'zz_merge_heads'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert debug configuration keys into system_configs."""

    config_keys = [
        {
            'key': 'debug.verbose_logging',
            'value': 'false',
            'value_type': 'bool',
            'category': 'debug',
            'description': 'Active le logging verbeux (niveau DEBUG) pour le root logger et les librairies externes',
            'is_sensitive': False
        },
        {
            'key': 'debug.timing_headers_enabled',
            'value': 'false',
            'value_type': 'bool',
            'category': 'debug',
            'description': 'Ajoute les headers X-Debug-Total-Ms, X-Debug-Path et X-Debug-Method sur chaque reponse API',
            'is_sensitive': False
        },
        {
            'key': 'debug.endpoints_enabled',
            'value': 'false',
            'value_type': 'bool',
            'category': 'debug',
            'description': 'Active les endpoints /auth/debug/* (inscription avec ecrasement, roles)',
            'is_sensitive': False
        },
    ]

    connection = op.get_bind()
    now = datetime.now(timezone.utc)

    for config in config_keys:
        connection.execute(
            sa.text("""
                INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive, created_at, updated_at)
                VALUES (:key, :value, :value_type, :category, :description, :is_sensitive, :created_at, :updated_at)
                ON CONFLICT (key) DO UPDATE SET
                    description = EXCLUDED.description,
                    updated_at = EXCLUDED.updated_at
            """),
            {
                **config,
                'created_at': now,
                'updated_at': now
            }
        )


def downgrade() -> None:
    """Remove debug configuration keys."""
    keys_to_remove = [
        'debug.verbose_logging',
        'debug.timing_headers_enabled',
        'debug.endpoints_enabled',
    ]

    connection = op.get_bind()
    for key in keys_to_remove:
        connection.execute(
            sa.text("DELETE FROM system_configs WHERE key = :key"),
            {'key': key}
        )
