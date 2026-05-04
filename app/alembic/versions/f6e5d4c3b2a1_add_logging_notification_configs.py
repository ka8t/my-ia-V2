"""Add logging and notification configuration keys

Revision ID: f6e5d4c3b2a1
Revises: 5153b4e2e8ce
Create Date: 2026-02-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6e5d4c3b2a1'
down_revision: Union[str, None] = '5153b4e2e8ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Ajoute les cles de configuration logging et notification dans system_configs."""

    # --- Logging (12 cles) ---
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
        VALUES
            ('logging.level_technical', 'INFO', 'string', 'logging', 'Niveau de log pour la categorie technical', false),
            ('logging.level_access', 'INFO', 'string', 'logging', 'Niveau de log pour la categorie access', false),
            ('logging.level_audit', 'INFO', 'string', 'logging', 'Niveau de log pour la categorie audit', false),
            ('logging.level_security', 'INFO', 'string', 'logging', 'Niveau de log pour la categorie security', false),
            ('logging.level_infra', 'INFO', 'string', 'logging', 'Niveau de log pour la categorie infra', false),
            ('logging.db_enabled', 'true', 'bool', 'logging', 'Activer la persistance des logs en BDD', false),
            ('logging.retention_technical_days', '30', 'int', 'logging', 'Retention des logs technical en jours', false),
            ('logging.retention_access_days', '30', 'int', 'logging', 'Retention des logs access en jours', false),
            ('logging.retention_audit_days', '365', 'int', 'logging', 'Retention des logs audit en jours', false),
            ('logging.retention_security_days', '365', 'int', 'logging', 'Retention des logs security en jours', false),
            ('logging.retention_infra_days', '14', 'int', 'logging', 'Retention des logs infra en jours', false),
            ('logging.alert_cooldown_minutes', '15', 'int', 'logging', 'Cooldown entre alertes du meme type en minutes', false)
        ON CONFLICT (key) DO NOTHING;
    """)

    # --- Notification (13 cles) ---
    op.execute("""
        INSERT INTO system_configs (key, value, value_type, category, description, is_sensitive)
        VALUES
            ('notification.email_enabled', 'false', 'bool', 'notification', 'Activer les notifications par email', false),
            ('notification.email_smtp_host', '', 'string', 'notification', 'Serveur SMTP pour les emails', false),
            ('notification.email_smtp_port', '587', 'int', 'notification', 'Port du serveur SMTP', false),
            ('notification.email_smtp_user', '', 'string', 'notification', 'Utilisateur SMTP', false),
            ('notification.email_smtp_password', '', 'string', 'notification', 'Mot de passe SMTP', true),
            ('notification.email_smtp_tls', 'true', 'bool', 'notification', 'Activer TLS pour le SMTP', false),
            ('notification.email_from_address', '', 'string', 'notification', 'Adresse expediteur des emails', false),
            ('notification.email_to_addresses', '', 'string', 'notification', 'Adresses destinataires (separees par des virgules)', false),
            ('notification.slack_enabled', 'false', 'bool', 'notification', 'Activer les notifications Slack', false),
            ('notification.slack_webhook_url', '', 'string', 'notification', 'URL du webhook Slack', true),
            ('notification.webhook_enabled', 'false', 'bool', 'notification', 'Activer les notifications webhook generique', false),
            ('notification.webhook_url', '', 'string', 'notification', 'URL du webhook generique', false),
            ('notification.webhook_secret', '', 'string', 'notification', 'Secret HMAC pour signer les webhooks', true)
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade() -> None:
    """Supprime les cles de configuration logging et notification."""
    op.execute("""
        DELETE FROM system_configs
        WHERE key LIKE 'logging.%'
           OR key LIKE 'notification.%';
    """)
