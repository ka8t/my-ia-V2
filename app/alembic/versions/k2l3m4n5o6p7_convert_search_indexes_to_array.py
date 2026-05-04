"""Convert search indexes to ARRAY type with GIN index

Revision ID: k2l3m4n5o6p7
Revises: i0j1k2l3m4n5
Create Date: 2026-01-04

Convertit les colonnes first_name_search et last_name_search de TEXT (CSV)
vers TEXT[] (ARRAY PostgreSQL) pour permettre l'utilisation d'index GIN
et de l'operateur @> pour la recherche.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'k2l3m4n5o6p7'
down_revision: Union[str, None] = 'i0j1k2l3m4n5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Creer les nouvelles colonnes ARRAY
    op.add_column('users', sa.Column(
        'first_name_search_new',
        postgresql.ARRAY(sa.String(16)),
        nullable=True
    ))
    op.add_column('users', sa.Column(
        'last_name_search_new',
        postgresql.ARRAY(sa.String(16)),
        nullable=True
    ))

    # 2. Migrer les donnees (convertir CSV en ARRAY)
    op.execute("""
        UPDATE users
        SET first_name_search_new = CASE
            WHEN first_name_search IS NOT NULL AND first_name_search != ''
            THEN string_to_array(first_name_search, ',')
            ELSE NULL
        END,
        last_name_search_new = CASE
            WHEN last_name_search IS NOT NULL AND last_name_search != ''
            THEN string_to_array(last_name_search, ',')
            ELSE NULL
        END
    """)

    # 3. Supprimer les anciennes colonnes
    op.drop_column('users', 'first_name_search')
    op.drop_column('users', 'last_name_search')

    # 4. Renommer les nouvelles colonnes
    op.alter_column('users', 'first_name_search_new', new_column_name='first_name_search')
    op.alter_column('users', 'last_name_search_new', new_column_name='last_name_search')

    # 5. Creer les index GIN pour la recherche rapide avec @>
    op.create_index(
        'ix_users_first_name_search_gin',
        'users',
        ['first_name_search'],
        postgresql_using='gin'
    )
    op.create_index(
        'ix_users_last_name_search_gin',
        'users',
        ['last_name_search'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    # 1. Supprimer les index GIN
    op.drop_index('ix_users_first_name_search_gin', table_name='users')
    op.drop_index('ix_users_last_name_search_gin', table_name='users')

    # 2. Creer les anciennes colonnes TEXT
    op.add_column('users', sa.Column(
        'first_name_search_old',
        sa.Text(),
        nullable=True
    ))
    op.add_column('users', sa.Column(
        'last_name_search_old',
        sa.Text(),
        nullable=True
    ))

    # 3. Migrer les donnees (convertir ARRAY en CSV)
    op.execute("""
        UPDATE users
        SET first_name_search_old = CASE
            WHEN first_name_search IS NOT NULL
            THEN array_to_string(first_name_search, ',')
            ELSE NULL
        END,
        last_name_search_old = CASE
            WHEN last_name_search IS NOT NULL
            THEN array_to_string(last_name_search, ',')
            ELSE NULL
        END
    """)

    # 4. Supprimer les colonnes ARRAY
    op.drop_column('users', 'first_name_search')
    op.drop_column('users', 'last_name_search')

    # 5. Renommer les colonnes
    op.alter_column('users', 'first_name_search_old', new_column_name='first_name_search')
    op.alter_column('users', 'last_name_search_old', new_column_name='last_name_search')
