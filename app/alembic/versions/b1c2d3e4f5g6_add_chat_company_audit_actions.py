"""Add chat and company audit actions

Revision ID: b1c2d3e4f5g6
Revises: a8b9c0d1e2f3
Create Date: 2026-01-24 15:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5g6'
down_revision: Union[str, None] = 'a8b9c0d1e2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les actions d'audit pour chat et companies."""

    # Nouvelles actions pour le chat
    chat_actions = [
        ('chat_message', 'Message chat envoye', 'info'),
        ('chat_stream', 'Chat stream demarre', 'info'),
        ('assistant_message', 'Message assistant envoye', 'info'),
    ]

    # Nouvelles actions pour les companies
    company_actions = [
        ('company_created', 'Entreprise creee', 'info'),
        ('company_updated', 'Entreprise mise a jour', 'info'),
        ('company_deleted', 'Entreprise supprimee', 'warning'),
        ('company_joined', 'Utilisateur a rejoint une entreprise', 'info'),
        ('company_left', 'Utilisateur a quitte une entreprise', 'info'),
    ]

    # Nouvelles actions pour les sources externes
    source_actions = [
        ('source_created', 'Source externe creee', 'info'),
        ('source_updated', 'Source externe mise a jour', 'info'),
        ('source_deleted', 'Source externe supprimee', 'warning'),
        ('source_indexed', 'Source externe indexee', 'info'),
        ('source_health_check', 'Verification sante source', 'info'),
    ]

    # Nouveau type de ressource - company
    op.execute("""
        INSERT INTO resource_types (name, display_name)
        VALUES ('company', 'Entreprise')
        ON CONFLICT (name) DO NOTHING;
    """)

    # Nouveau type de ressource - source
    op.execute("""
        INSERT INTO resource_types (name, display_name)
        VALUES ('source', 'Source externe')
        ON CONFLICT (name) DO NOTHING;
    """)

    # Insérer les actions (avec ON CONFLICT)
    all_actions = chat_actions + company_actions + source_actions
    for name, display_name, severity in all_actions:
        op.execute(f"""
            INSERT INTO audit_actions (name, display_name, severity)
            VALUES ('{name}', '{display_name}', '{severity}')
            ON CONFLICT (name) DO NOTHING;
        """)


def downgrade() -> None:
    """Supprime les actions d'audit pour chat et companies."""

    actions_to_remove = [
        'chat_message', 'chat_stream', 'assistant_message',
        'company_created', 'company_updated', 'company_deleted',
        'company_joined', 'company_left',
        'source_created', 'source_updated', 'source_deleted',
        'source_indexed', 'source_health_check'
    ]

    for action in actions_to_remove:
        op.execute(f"DELETE FROM audit_actions WHERE name = '{action}';")

    op.execute("DELETE FROM resource_types WHERE name = 'company';")
    op.execute("DELETE FROM resource_types WHERE name = 'source';")
