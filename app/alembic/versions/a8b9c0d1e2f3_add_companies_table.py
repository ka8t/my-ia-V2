"""Add companies table for enterprise personalization

Revision ID: a8b9c0d1e2f3
Revises: z7a8b9c0d1e2
Create Date: 2025-01-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a8b9c0d1e2f3'
down_revision: Union[str, None] = 'z7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Créer la table companies
    op.create_table(
        'companies',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        # Branding
        sa.Column('logo_url', sa.String(500), nullable=True),
        sa.Column('primary_color', sa.String(7), server_default='#3b82f6', nullable=False),
        sa.Column('secondary_color', sa.String(7), nullable=True),
        # Personnalisation
        sa.Column('welcome_message', sa.Text(), nullable=True),
        sa.Column('custom_system_prompt', sa.Text(), nullable=True),
        sa.Column('onboarding_steps', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        # Collection par défaut
        sa.Column('default_collection_id', postgresql.UUID(as_uuid=True), nullable=True),
        # Gestion
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('max_users', sa.Integer(), nullable=True),
        # Métadonnées
        sa.Column('contact_email', sa.String(255), nullable=True),
        sa.Column('contact_name', sa.String(200), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
        sa.ForeignKeyConstraint(['default_collection_id'], ['collections.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    )

    # Index sur le code pour recherche rapide
    op.create_index('ix_companies_code', 'companies', ['code'], unique=True)

    # Ajouter company_id à la table users
    op.add_column(
        'users',
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=True)
    )

    # Créer la foreign key
    op.create_foreign_key(
        'fk_users_company_id',
        'users', 'companies',
        ['company_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # Supprimer la foreign key
    op.drop_constraint('fk_users_company_id', 'users', type_='foreignkey')

    # Supprimer la colonne company_id
    op.drop_column('users', 'company_id')

    # Supprimer l'index
    op.drop_index('ix_companies_code', table_name='companies')

    # Supprimer la table companies
    op.drop_table('companies')
