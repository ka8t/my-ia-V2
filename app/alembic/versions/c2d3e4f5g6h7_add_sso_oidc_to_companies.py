"""Add SSO OIDC configuration to companies

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-01-24 15:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5g6h7'
down_revision: Union[str, None] = 'b1c2d3e4f5g6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les champs SSO OIDC a la table companies."""

    # SSO enabled flag
    op.add_column('companies', sa.Column('sso_enabled', sa.Boolean(), nullable=False, server_default='false'))

    # Provider type (azure_ad, google, okta, generic)
    op.add_column('companies', sa.Column('sso_provider', sa.String(50), nullable=True))

    # OIDC credentials
    op.add_column('companies', sa.Column('oidc_client_id', sa.String(255), nullable=True))
    op.add_column('companies', sa.Column('oidc_client_secret', sa.Text(), nullable=True))  # Encrypted
    op.add_column('companies', sa.Column('oidc_discovery_url', sa.String(500), nullable=True))
    op.add_column('companies', sa.Column('oidc_scopes', sa.String(255), nullable=True, server_default='openid email profile'))

    # SSO behavior settings
    op.add_column('companies', sa.Column('sso_domain_restriction', sa.String(255), nullable=True))
    op.add_column('companies', sa.Column('sso_auto_create_users', sa.Boolean(), nullable=False, server_default='true'))
    op.add_column('companies', sa.Column('sso_default_role_id', sa.Integer(), nullable=True))

    # Foreign key for default role
    op.create_foreign_key(
        'fk_companies_sso_default_role',
        'companies',
        'roles',
        ['sso_default_role_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    """Supprime les champs SSO OIDC de la table companies."""

    # Drop foreign key first
    op.drop_constraint('fk_companies_sso_default_role', 'companies', type_='foreignkey')

    # Drop columns
    op.drop_column('companies', 'sso_default_role_id')
    op.drop_column('companies', 'sso_auto_create_users')
    op.drop_column('companies', 'sso_domain_restriction')
    op.drop_column('companies', 'oidc_scopes')
    op.drop_column('companies', 'oidc_discovery_url')
    op.drop_column('companies', 'oidc_client_secret')
    op.drop_column('companies', 'oidc_client_id')
    op.drop_column('companies', 'sso_provider')
    op.drop_column('companies', 'sso_enabled')
