"""Add oauth_accounts table for OAuth2 authentication

Revision ID: f7g8h9i0j1k2
Revises: e6f7g8h9i0j1
Create Date: 2025-12-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f7g8h9i0j1k2'
down_revision: Union[str, None] = 'e6f7g8h9i0j1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Creer la table oauth_accounts
    op.create_table(
        'oauth_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('oauth_name', sa.String(100), nullable=False, index=True),
        sa.Column('access_token', sa.String(1024), nullable=False),
        sa.Column('expires_at', sa.Integer(), nullable=True),
        sa.Column('refresh_token', sa.String(1024), nullable=True),
        sa.Column('account_id', sa.String(320), nullable=False, index=True),
        sa.Column('account_email', sa.String(320), nullable=True),
    )

    # Index composite pour recherche rapide
    op.create_index(
        'ix_oauth_accounts_oauth_name_account_id',
        'oauth_accounts',
        ['oauth_name', 'account_id'],
        unique=True
    )


def downgrade() -> None:
    op.drop_index('ix_oauth_accounts_oauth_name_account_id', table_name='oauth_accounts')
    op.drop_table('oauth_accounts')
