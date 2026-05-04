"""Add sources indexation configuration keys

Revision ID: z7a8b9c0d1e2
Revises: y6z7a8b9c0d1
Create Date: 2026-01-23

Adds configuration keys for source indexation system:
- Scheduler intervals (check, cleanup docs, cleanup logs)
- Log retention period
- Freshness thresholds (warning, expired)
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime, timezone


# revision identifiers, used by Alembic.
revision = 'z7a8b9c0d1e2'
down_revision = 'y6z7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Insert source indexation configuration keys."""

    # Configuration keys for source indexation
    config_keys = [
        # Scheduler intervals
        {
            'key': 'sources.scheduler_check_interval_minutes',
            'value': '15',
            'value_type': 'int',
            'category': 'sources',
            'description': 'Interval in minutes between source refresh checks',
            'is_sensitive': False
        },
        {
            'key': 'sources.scheduler_cleanup_docs_interval_hours',
            'value': '1',
            'value_type': 'int',
            'category': 'sources',
            'description': 'Interval in hours between expired documents cleanup',
            'is_sensitive': False
        },
        {
            'key': 'sources.scheduler_cleanup_logs_interval_days',
            'value': '1',
            'value_type': 'int',
            'category': 'sources',
            'description': 'Interval in days between old indexation logs cleanup',
            'is_sensitive': False
        },
        # Log retention
        {
            'key': 'sources.log_retention_days',
            'value': '30',
            'value_type': 'int',
            'category': 'sources',
            'description': 'Number of days to keep indexation logs',
            'is_sensitive': False
        },
        # Freshness thresholds
        {
            'key': 'sources.freshness_warning_percent',
            'value': '30',
            'value_type': 'int',
            'category': 'sources',
            'description': 'Freshness percentage below which a warning is shown (0-100)',
            'is_sensitive': False
        },
        {
            'key': 'sources.freshness_expired_percent',
            'value': '0',
            'value_type': 'int',
            'category': 'sources',
            'description': 'Freshness percentage at which source is considered expired',
            'is_sensitive': False
        },
        # Scheduler enabled flag
        {
            'key': 'sources.scheduler_enabled',
            'value': 'true',
            'value_type': 'bool',
            'category': 'sources',
            'description': 'Enable or disable the automatic source indexation scheduler',
            'is_sensitive': False
        },
    ]

    # Get connection for parameterized inserts
    connection = op.get_bind()
    now = datetime.now(timezone.utc)

    # Insert each config key
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
    """Remove source indexation configuration keys."""
    keys_to_remove = [
        'sources.scheduler_check_interval_minutes',
        'sources.scheduler_cleanup_docs_interval_hours',
        'sources.scheduler_cleanup_logs_interval_days',
        'sources.log_retention_days',
        'sources.freshness_warning_percent',
        'sources.freshness_expired_percent',
        'sources.scheduler_enabled',
    ]

    connection = op.get_bind()
    for key in keys_to_remove:
        connection.execute(
            sa.text("DELETE FROM system_configs WHERE key = :key"),
            {'key': key}
        )
