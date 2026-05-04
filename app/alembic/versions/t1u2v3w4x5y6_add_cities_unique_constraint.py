"""Add unique constraint to cities table

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
Create Date: 2025-01-16

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 't1u2v3w4x5y6'
down_revision = 's0t1u2v3w4x5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_cities_name_postal_country',
        'cities',
        ['name', 'postal_code', 'country_code']
    )


def downgrade() -> None:
    op.drop_constraint('uq_cities_name_postal_country', 'cities', type_='unique')
