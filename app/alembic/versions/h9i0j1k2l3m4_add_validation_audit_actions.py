"""Add validation audit actions

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2025-12-28

Ajoute les actions d'audit pour la validation des inscriptions:
- user_approved: Inscription approuvee par admin/validateur
- user_rejected: Inscription refusee par admin/validateur
- login_blocked_pending: Tentative login user en attente
- login_blocked_rejected: Tentative login user refuse
- email_verified: Email verifie par l'utilisateur
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'h9i0j1k2l3m4'
down_revision = 'g8h9i0j1k2l3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Ajouter les nouvelles actions d'audit pour la validation
    op.execute("""
        INSERT INTO audit_actions (name, display_name, severity) VALUES
            ('user_approved', 'Inscription approuvee', 'info'),
            ('user_rejected', 'Inscription refusee', 'warning'),
            ('login_blocked_pending', 'Connexion bloquee (en attente)', 'warning'),
            ('login_blocked_rejected', 'Connexion bloquee (refuse)', 'warning'),
            ('email_verified', 'Email verifie', 'info')
        ON CONFLICT (name) DO NOTHING;
    """)


def downgrade() -> None:
    # Supprimer les actions d'audit ajoutees
    op.execute("""
        DELETE FROM audit_actions
        WHERE name IN (
            'user_approved',
            'user_rejected',
            'login_blocked_pending',
            'login_blocked_rejected',
            'email_verified'
        );
    """)
