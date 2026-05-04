"""add_sharepoint_connector

Revision ID: 47778f382be4
Revises: c2d3e4f5g6h7
Create Date: 2026-01-24

Tables SharePoint/OneDrive Connector pour la synchronisation de documents.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '47778f382be4'
down_revision = 'c2d3e4f5g6h7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table de configuration SharePoint
    op.create_table('sharepoint_configs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False, server_default='sharepoint_online'),
        sa.Column('tenant_id', sa.String(length=100), nullable=False),
        sa.Column('client_id', sa.String(length=100), nullable=False),
        sa.Column('client_secret', sa.Text(), nullable=False),  # Chiffre via EncryptedString
        sa.Column('site_url', sa.String(length=500), nullable=True),
        sa.Column('drive_id', sa.String(length=100), nullable=True),
        sa.Column('folder_path', sa.String(length=500), nullable=False, server_default='/'),
        sa.Column('file_extensions', postgresql.ARRAY(sa.String()), nullable=False,
                  server_default='{pdf,docx,doc,txt,md}'),
        sa.Column('max_file_size_bytes', sa.Integer(), nullable=False, server_default='52428800'),
        sa.Column('sync_interval_minutes', sa.Integer(), nullable=False, server_default='60'),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('last_sync_message', sa.Text(), nullable=True),
        sa.Column('files_synced_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sharepoint_configs_company', 'sharepoint_configs', ['company_id'])

    # Table d'historique de synchronisation
    op.create_table('sharepoint_sync_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('config_id', sa.Uuid(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('files_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('files_synced', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('files_skipped', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('files_error', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_details', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['config_id'], ['sharepoint_configs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sharepoint_sync_logs_config', 'sharepoint_sync_logs', ['config_id'])
    op.create_index('ix_sharepoint_sync_logs_started', 'sharepoint_sync_logs', ['started_at'])


def downgrade() -> None:
    op.drop_index('ix_sharepoint_sync_logs_started', table_name='sharepoint_sync_logs')
    op.drop_index('ix_sharepoint_sync_logs_config', table_name='sharepoint_sync_logs')
    op.drop_table('sharepoint_sync_logs')
    op.drop_index('ix_sharepoint_configs_company', table_name='sharepoint_configs')
    op.drop_table('sharepoint_configs')
