"""add_app_logs_table

Revision ID: 18edcd7b5686
Revises: 2f8f234ada85
Create Date: 2026-01-31

Crée la table app_logs pour la persistance des logs structurés (Plan Logging Phase 5).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '18edcd7b5686'
down_revision = '2f8f234ada85'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('app_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('level', sa.String(length=10), nullable=False),
        sa.Column('log_category', sa.String(length=20), nullable=False),
        sa.Column('service', sa.String(length=50), nullable=True),
        sa.Column('environment', sa.String(length=20), nullable=True),
        sa.Column('request_id', sa.String(length=36), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=True),
        sa.Column('session_id', sa.String(length=36), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('logger_name', sa.String(length=200), nullable=True),
        sa.Column('is_alert', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Logs applicatifs structurés — 5 catégories, format JSON'
    )
    op.create_index(op.f('ix_app_logs_level'), 'app_logs', ['level'], unique=False)
    op.create_index(op.f('ix_app_logs_log_category'), 'app_logs', ['log_category'], unique=False)
    op.create_index(op.f('ix_app_logs_timestamp'), 'app_logs', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_app_logs_timestamp'), table_name='app_logs')
    op.drop_index(op.f('ix_app_logs_log_category'), table_name='app_logs')
    op.drop_index(op.f('ix_app_logs_level'), table_name='app_logs')
    op.drop_table('app_logs')
