"""Add approval_status to users and validator role

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2025-12-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'g8h9i0j1k2l3'
down_revision: Union[str, None] = 'f7g8h9i0j1k2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Creer l'enum approval_status
    approval_status_enum = postgresql.ENUM(
        'pending', 'approved', 'rejected',
        name='approval_status',
        create_type=True
    )
    approval_status_enum.create(op.get_bind(), checkfirst=True)

    # 2. Ajouter les colonnes d'approbation a la table users
    op.add_column(
        'users',
        sa.Column(
            'approval_status',
            postgresql.ENUM('pending', 'approved', 'rejected', name='approval_status', create_type=False),
            nullable=False,
            server_default='pending'
        )
    )
    op.add_column(
        'users',
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        'users',
        sa.Column('approved_by', postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        'users',
        sa.Column('rejection_reason', sa.Text(), nullable=True)
    )

    # 3. Ajouter la FK pour approved_by
    op.create_foreign_key(
        'fk_users_approved_by',
        'users', 'users',
        ['approved_by'], ['id'],
        ondelete='SET NULL'
    )

    # 4. Mettre a jour les utilisateurs existants comme "approved"
    op.execute("UPDATE users SET approval_status = 'approved'")

    # 5. Ajouter le role "Validateur" (id=4)
    op.execute("""
        INSERT INTO roles (id, name, display_name, description)
        VALUES (4, 'validator', 'Validateur', 'Peut approuver ou refuser les inscriptions')
        ON CONFLICT (id) DO NOTHING
    """)

    # 6. Creer un index pour rechercher les users pending
    op.create_index(
        'ix_users_approval_status',
        'users',
        ['approval_status'],
        unique=False
    )


def downgrade() -> None:
    # Supprimer l'index
    op.drop_index('ix_users_approval_status', table_name='users')

    # Supprimer le role validateur
    op.execute("DELETE FROM roles WHERE name = 'validator'")

    # Supprimer la FK
    op.drop_constraint('fk_users_approved_by', 'users', type_='foreignkey')

    # Supprimer les colonnes
    op.drop_column('users', 'rejection_reason')
    op.drop_column('users', 'approved_by')
    op.drop_column('users', 'approved_at')
    op.drop_column('users', 'approval_status')

    # Supprimer l'enum
    op.execute("DROP TYPE IF EXISTS approval_status")
