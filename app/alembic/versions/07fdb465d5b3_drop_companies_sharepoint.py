"""Drop companies and sharepoint tables (dead code cleanup)

Revision ID: 07fdb465d5b3
Revises: 1498ea39599a
Create Date: 2026-02-01

Supprime les tables companies, sharepoint_configs, sharepoint_sync_logs
et la colonne users.company_id (modules obsolètes).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '07fdb465d5b3'
down_revision: Union[str, None] = '1498ea39599a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Supprime les tables et colonnes liées aux companies et SharePoint."""

    # 1. Supprimer sharepoint_sync_logs (FK -> sharepoint_configs)
    op.drop_index('ix_sharepoint_sync_logs_started', table_name='sharepoint_sync_logs')
    op.drop_index('ix_sharepoint_sync_logs_config', table_name='sharepoint_sync_logs')
    op.drop_table('sharepoint_sync_logs')

    # 2. Supprimer sharepoint_configs (FK -> companies)
    op.drop_index('ix_sharepoint_configs_company', table_name='sharepoint_configs')
    op.drop_table('sharepoint_configs')

    # 3. Supprimer users.company_id FK et colonne
    op.drop_constraint('fk_users_company_id', 'users', type_='foreignkey')
    op.drop_column('users', 'company_id')

    # 4. Supprimer la table companies
    op.drop_index('ix_companies_code', table_name='companies')
    op.drop_table('companies')

    # 5. Supprimer les actions d'audit company_*
    company_actions = [
        'company_created', 'company_updated', 'company_deleted',
        'company_joined', 'company_left',
    ]
    for action in company_actions:
        op.execute(f"DELETE FROM audit_actions WHERE name = '{action}';")

    # 6. Supprimer le resource_type 'company'
    op.execute("DELETE FROM resource_types WHERE name = 'company';")


def downgrade() -> None:
    """Recrée les tables companies et SharePoint."""

    # Recréer la table companies
    op.create_table(
        'companies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('logo_url', sa.String(500), nullable=True),
        sa.Column('primary_color', sa.String(7), server_default='#3b82f6', nullable=False),
        sa.Column('secondary_color', sa.String(7), nullable=True),
        sa.Column('welcome_message', sa.Text(), nullable=True),
        sa.Column('custom_system_prompt', sa.Text(), nullable=True),
        sa.Column('default_collection_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('max_users', sa.Integer(), nullable=True),
        sa.Column('contact_email', sa.String(255), nullable=True),
        sa.Column('contact_name', sa.String(200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('sso_enabled', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('sso_provider', sa.String(50), nullable=True),
        sa.Column('oidc_client_id', sa.String(255), nullable=True),
        sa.Column('oidc_client_secret', sa.Text(), nullable=True),
        sa.Column('oidc_discovery_url', sa.String(500), nullable=True),
        sa.Column('oidc_scopes', sa.String(255), nullable=True, server_default='openid email profile'),
        sa.Column('sso_domain_restriction', sa.String(255), nullable=True),
        sa.Column('sso_auto_create_users', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('sso_default_role_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.ForeignKeyConstraint(['default_collection_id'], ['collections.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sso_default_role_id'], ['roles.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_companies_code', 'companies', ['code'], unique=True)

    # Recréer users.company_id
    op.add_column('users', sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_users_company_id', 'users', 'companies', ['company_id'], ['id'], ondelete='SET NULL')

    # Recréer sharepoint_configs
    op.create_table(
        'sharepoint_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('provider', sa.String(50), server_default='sharepoint_online', nullable=False),
        sa.Column('tenant_id', sa.String(100), nullable=False),
        sa.Column('client_id', sa.String(100), nullable=False),
        sa.Column('client_secret', sa.Text(), nullable=False),
        sa.Column('site_url', sa.String(500), nullable=True),
        sa.Column('drive_id', sa.String(200), nullable=True),
        sa.Column('folder_path', sa.String(500), server_default='/', nullable=False),
        sa.Column('file_extensions', postgresql.JSON(), nullable=True),
        sa.Column('max_file_size_bytes', sa.BigInteger(), server_default='52428800', nullable=False),
        sa.Column('sync_interval_minutes', sa.Integer(), server_default='60', nullable=False),
        sa.Column('is_enabled', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(20), server_default='pending', nullable=False),
        sa.Column('last_sync_message', sa.Text(), nullable=True),
        sa.Column('files_synced_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_sharepoint_configs_company', 'sharepoint_configs', ['company_id'])

    # Recréer sharepoint_sync_logs
    op.create_table(
        'sharepoint_sync_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('config_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(20), server_default='running', nullable=False),
        sa.Column('files_processed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('files_added', sa.Integer(), server_default='0', nullable=False),
        sa.Column('files_updated', sa.Integer(), server_default='0', nullable=False),
        sa.Column('files_failed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['config_id'], ['sharepoint_configs.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_sharepoint_sync_logs_config', 'sharepoint_sync_logs', ['config_id'])
    op.create_index('ix_sharepoint_sync_logs_started', 'sharepoint_sync_logs', ['started_at'])

    # Recréer les audit actions et resource type
    op.execute("""
        INSERT INTO resource_types (name, display_name)
        VALUES ('company', 'Entreprise')
        ON CONFLICT (name) DO NOTHING;
    """)
    company_actions = [
        ('company_created', 'Entreprise creee', 'info'),
        ('company_updated', 'Entreprise mise a jour', 'info'),
        ('company_deleted', 'Entreprise supprimee', 'warning'),
        ('company_joined', 'Utilisateur a rejoint une entreprise', 'info'),
        ('company_left', 'Utilisateur a quitte une entreprise', 'info'),
    ]
    for name, display_name, severity in company_actions:
        op.execute(f"""
            INSERT INTO audit_actions (name, display_name, severity)
            VALUES ('{name}', '{display_name}', '{severity}')
            ON CONFLICT (name) DO NOTHING;
        """)
