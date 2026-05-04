"""
Service de notification multi-canal

Dispatche les alertes vers les canaux configurés :
- Email (SMTP via aiosmtplib)
- Slack (webhook)
- Webhook générique (POST HTTP avec signature HMAC optionnelle)

La configuration est lue dynamiquement depuis la table system_configs.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aiosmtplib
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class NotificationService:
    """Service d'envoi de notifications multi-canal."""

    @staticmethod
    async def _get_config(db: AsyncSession) -> Dict[str, Any]:
        """
        Récupère la configuration des notifications depuis la BDD.

        Returns:
            Dictionnaire avec toutes les clés notification.*
        """
        from app.features.system.service import SystemConfigService
        config_service = SystemConfigService(db)

        return {
            "email_enabled": bool(await config_service.get("notification.email_enabled", False)),
            "email_smtp_host": str(await config_service.get("notification.email_smtp_host", "")),
            "email_smtp_port": int(await config_service.get("notification.email_smtp_port", 587)),
            "email_smtp_user": str(await config_service.get("notification.email_smtp_user", "")),
            "email_smtp_password": str(await config_service.get("notification.email_smtp_password", "")),
            "email_smtp_tls": bool(await config_service.get("notification.email_smtp_tls", True)),
            "email_from_address": str(await config_service.get("notification.email_from_address", "")),
            "email_to_addresses": str(await config_service.get("notification.email_to_addresses", "")),
            "slack_enabled": bool(await config_service.get("notification.slack_enabled", False)),
            "slack_webhook_url": str(await config_service.get("notification.slack_webhook_url", "")),
            "webhook_enabled": bool(await config_service.get("notification.webhook_enabled", False)),
            "webhook_url": str(await config_service.get("notification.webhook_url", "")),
            "webhook_secret": str(await config_service.get("notification.webhook_secret", "")),
        }

    @staticmethod
    async def send_email(
        config: Dict[str, Any],
        subject: str,
        body: str,
    ) -> bool:
        """
        Envoie un email via SMTP.

        Args:
            config: Configuration notification
            subject: Sujet de l'email
            body: Corps du message (texte brut)

        Returns:
            True si l'envoi a réussi
        """
        if not config.get("email_smtp_host") or not config.get("email_to_addresses"):
            logger.warning("Email notification skipped: SMTP host or recipients not configured")
            return False

        recipients = [addr.strip() for addr in config["email_to_addresses"].split(",") if addr.strip()]
        if not recipients:
            return False

        msg = MIMEMultipart()
        msg["From"] = config.get("email_from_address", config.get("email_smtp_user", "noreply@myia.local"))
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        try:
            await aiosmtplib.send(
                msg,
                hostname=config["email_smtp_host"],
                port=config.get("email_smtp_port", 587),
                username=config.get("email_smtp_user") or None,
                password=config.get("email_smtp_password") or None,
                start_tls=config.get("email_smtp_tls", True),
                timeout=10,
            )
            logger.info("Email notification sent to %s: %s", recipients, subject)
            return True
        except Exception as e:
            logger.error("Failed to send email notification: %s", e, exc_info=True)
            return False

    @staticmethod
    async def send_slack(
        config: Dict[str, Any],
        subject: str,
        body: str,
    ) -> bool:
        """
        Envoie une notification via webhook Slack.

        Args:
            config: Configuration notification
            subject: Titre de la notification
            body: Détail du message

        Returns:
            True si l'envoi a réussi
        """
        webhook_url = config.get("slack_webhook_url", "")
        if not webhook_url:
            logger.warning("Slack notification skipped: webhook URL not configured")
            return False

        payload = {
            "text": f"*{subject}*\n{body}",
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": subject, "emoji": True}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": body}
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"MY-IA Alert | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        }
                    ]
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json=payload)
                response.raise_for_status()
            logger.info("Slack notification sent: %s", subject)
            return True
        except Exception as e:
            logger.error("Failed to send Slack notification: %s", e, exc_info=True)
            return False

    @staticmethod
    async def send_webhook(
        config: Dict[str, Any],
        subject: str,
        body: str,
        alert_type: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Envoie une notification via webhook HTTP générique.

        Le payload JSON contient subject, body, alert_type, details et timestamp.
        Si un secret est configuré, le header X-Signature contient le HMAC-SHA256.

        Args:
            config: Configuration notification
            subject: Titre de la notification
            body: Détail du message
            alert_type: Type d'alerte (ex: "error_explosion")
            details: Données supplémentaires

        Returns:
            True si l'envoi a réussi
        """
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            logger.warning("Webhook notification skipped: URL not configured")
            return False

        payload = {
            "subject": subject,
            "body": body,
            "alert_type": alert_type,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "my-ia",
        }

        headers = {"Content-Type": "application/json"}

        # Signature HMAC si secret configuré
        secret = config.get("webhook_secret", "")
        if secret:
            payload_bytes = json.dumps(payload, sort_keys=True).encode("utf-8")
            signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
            headers["X-Signature"] = f"sha256={signature}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(webhook_url, json=payload, headers=headers)
                response.raise_for_status()
            logger.info("Webhook notification sent to %s: %s", webhook_url, subject)
            return True
        except Exception as e:
            logger.error("Failed to send webhook notification: %s", e, exc_info=True)
            return False

    @staticmethod
    async def notify_alert(
        db: AsyncSession,
        alert_type: str,
        subject: str,
        body: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, bool]:
        """
        Dispatche une alerte vers tous les canaux activés.

        Args:
            db: Session de base de données
            alert_type: Type d'alerte (ex: "error_explosion", "login_brute_force")
            subject: Titre de l'alerte
            body: Description détaillée
            details: Données supplémentaires

        Returns:
            Dictionnaire avec le résultat de chaque canal
        """
        config = await NotificationService._get_config(db)
        results: Dict[str, bool] = {}

        if config.get("email_enabled"):
            results["email"] = await NotificationService.send_email(config, subject, body)

        if config.get("slack_enabled"):
            results["slack"] = await NotificationService.send_slack(config, subject, body)

        if config.get("webhook_enabled"):
            results["webhook"] = await NotificationService.send_webhook(
                config, subject, body, alert_type, details
            )

        if results:
            logger.info(
                "Alert notifications dispatched for '%s': %s",
                alert_type,
                results,
            )

        return results

    @staticmethod
    async def test_channel(
        db: AsyncSession,
        channel: str,
    ) -> bool:
        """
        Envoie une notification de test pour un canal spécifique.

        Args:
            db: Session de base de données
            channel: Canal à tester ("email", "slack", "webhook")

        Returns:
            True si le test a réussi
        """
        config = await NotificationService._get_config(db)
        subject = "[MY-IA] Test de notification"
        body = "Ceci est un message de test envoyé depuis le backoffice MY-IA."

        if channel == "email":
            return await NotificationService.send_email(config, subject, body)
        elif channel == "slack":
            return await NotificationService.send_slack(config, subject, body)
        elif channel == "webhook":
            return await NotificationService.send_webhook(
                config, subject, body, alert_type="test", details={"test": True}
            )
        else:
            logger.warning("Unknown notification channel: %s", channel)
            return False
