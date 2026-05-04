"""Add public config keys for API and app settings

Revision ID: v3w4x5y6z7a8
Revises: aad7834aa52a
Create Date: 2026-01-22

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'v3w4x5y6z7a8'
down_revision: Union[str, None] = 'aad7834aa52a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Ajouter les cles de configuration publiques
    # Ces cles sont exposees via GET /api/config/public (sans authentification)
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive) VALUES
        ('app.api_url', 'http://localhost:8080', 'string', 'app',
         'URL de base de l''API backend', false),
        ('app.name', 'MY-IA', 'string', 'app',
         'Nom de l''application', false),
        ('app.debug', 'false', 'bool', 'app',
         'Mode debug actif', false),
        ('app.version', '1.0.0', 'string', 'app',
         'Version de l''application', false)
        ON CONFLICT (key) DO NOTHING
    """)


def downgrade() -> None:
    # Supprimer les cles ajoutees
    op.execute("""
        DELETE FROM system_configs
        WHERE key IN (
            'app.api_url',
            'app.name',
            'app.debug',
            'app.version'
        )
    """)
