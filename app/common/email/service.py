"""
Service Email - Envoi d'emails via SendGrid ou SMTP.

Utilise SendGrid en production, SMTP en developpement.
"""

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any

from app.common.i18n import t

logger = logging.getLogger(__name__)

# Nom de l'application (configure via env)
APP_NAME = os.getenv("APP_NAME", "MY-IA")


class EmailBackend(ABC):
    """Interface abstraite pour les backends email."""

    @abstractmethod
    async def send(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        """Envoie un email."""
        pass


class SendGridBackend(EmailBackend):
    """Backend SendGrid pour la production."""

    def __init__(self, api_key: str, from_email: str, from_name: str):
        self.api_key = api_key
        self.from_email = from_email
        self.from_name = from_name

    async def send(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "personalizations": [{"to": [{"email": to_email}]}],
                        "from": {"email": self.from_email, "name": self.from_name},
                        "subject": subject,
                        "content": [
                            {"type": "text/plain", "value": text_content or subject},
                            {"type": "text/html", "value": html_content},
                        ],
                    },
                )

                if response.status_code in (200, 201, 202):
                    logger.info(f"Email envoye a {to_email} via SendGrid")
                    return True
                else:
                    logger.error(f"SendGrid error: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"Erreur envoi email SendGrid: {e}")
            return False


class SMTPBackend(EmailBackend):
    """Backend SMTP pour le developpement."""

    def __init__(
        self,
        host: str,
        port: int,
        username: Optional[str],
        password: Optional[str],
        from_email: str,
        from_name: str,
        use_tls: bool = True,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        self.use_tls = use_tls

    async def send(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        try:
            import aiosmtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{self.from_name} <{self.from_email}>"
            msg["To"] = to_email

            if text_content:
                msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            # Port 587 = STARTTLS, Port 465 = SSL direct
            if self.port == 587:
                await aiosmtplib.send(
                    msg,
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    start_tls=self.use_tls,
                )
            else:
                await aiosmtplib.send(
                    msg,
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    use_tls=self.use_tls,
                )

            logger.info(f"Email envoye a {to_email} via SMTP")
            return True

        except Exception as e:
            logger.error(f"Erreur envoi email SMTP: {e}")
            return False


class ConsoleBackend(EmailBackend):
    """Backend console pour les tests (affiche dans les logs)."""

    async def send(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
    ) -> bool:
        logger.info("=" * 60)
        logger.info(f"EMAIL TO: {to_email}")
        logger.info(f"SUBJECT: {subject}")
        logger.info("-" * 60)
        logger.info(text_content or html_content[:500])
        logger.info("=" * 60)
        return True


class EmailService:
    """Service principal d'envoi d'emails."""

    def __init__(self, backend: EmailBackend, frontend_url: str):
        self.backend = backend
        self.frontend_url = frontend_url.rstrip("/")
        self.templates_dir = Path(__file__).parent / "templates"

    def _load_template(self, name: str, variables: Dict[str, Any]) -> str:
        """Charge et interpole un template HTML."""
        template_path = self.templates_dir / f"{name}.html"

        if not template_path.exists():
            logger.warning(f"Template {name}.html non trouve, utilisation template par defaut")
            return self._default_template(variables)

        content = template_path.read_text(encoding="utf-8")

        for key, value in variables.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))

        return content

    def _default_template(self, variables: Dict[str, Any], lang: str = "fr") -> str:
        """Template par defaut si le fichier n'existe pas."""
        action_text = variables.get('action_text', t("email_btn_default", lang))
        footer_sent = t("email_footer_sent_by", lang, app_name=APP_NAME)
        footer_ignore = t("email_footer_ignore", lang)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .button {{
                    display: inline-block;
                    padding: 12px 24px;
                    background-color: #4f46e5;
                    color: white;
                    text-decoration: none;
                    border-radius: 6px;
                    margin: 20px 0;
                }}
                .footer {{ margin-top: 40px; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>{variables.get('title', APP_NAME)}</h1>
                <p>{variables.get('message', '')}</p>
                {f'<a href="{variables.get("action_url", "#")}" class="button">{action_text}</a>' if variables.get('action_url') else ''}
                <div class="footer">
                    <p>{footer_sent}</p>
                    <p>{footer_ignore}</p>
                </div>
            </div>
        </body>
        </html>
        """

    async def send_verification_email(
        self, to_email: str, username: str, token: str, lang: str = "fr"
    ) -> bool:
        """Envoie l'email de verification de compte."""
        verification_url = f"{self.frontend_url}/verify?token={token}"

        html_content = self._load_template(
            "verification",
            {
                "username": username,
                "verification_url": verification_url,
                "title": t("email_title_verify", lang),
                "message": t("email_body_verify", lang, username=username),
                "action_url": verification_url,
                "action_text": t("email_btn_verify", lang),
            },
        )

        text_content = t(
            "email_text_verify", lang,
            username=username,
            verification_url=verification_url,
            app_name=APP_NAME
        )

        return await self.backend.send(
            to_email=to_email,
            subject=t("email_subject_verify", lang, app_name=APP_NAME),
            html_content=html_content,
            text_content=text_content,
        )

    async def send_password_reset_email(
        self, to_email: str, username: str, token: str, lang: str = "fr"
    ) -> bool:
        """Envoie l'email de reinitialisation de mot de passe."""
        reset_url = f"{self.frontend_url}/reset-password?token={token}"

        html_content = self._load_template(
            "password_reset",
            {
                "username": username,
                "reset_url": reset_url,
                "title": t("email_title_reset", lang),
                "message": t("email_body_reset", lang, username=username),
                "action_url": reset_url,
                "action_text": t("email_btn_reset", lang),
            },
        )

        text_content = t(
            "email_text_reset", lang,
            username=username,
            reset_url=reset_url,
            app_name=APP_NAME
        )

        return await self.backend.send(
            to_email=to_email,
            subject=t("email_subject_reset", lang, app_name=APP_NAME),
            html_content=html_content,
            text_content=text_content,
        )

    async def send_welcome_email(
        self, to_email: str, username: str, lang: str = "fr"
    ) -> bool:
        """Envoie l'email de bienvenue apres verification."""
        html_content = self._load_template(
            "welcome",
            {
                "username": username,
                "login_url": f"{self.frontend_url}/login",
                "title": t("email_title_welcome", lang, app_name=APP_NAME),
                "message": t("email_body_welcome", lang, username=username),
                "action_url": f"{self.frontend_url}/login",
                "action_text": t("email_btn_login", lang),
            },
        )

        text_content = t(
            "email_text_welcome", lang,
            username=username,
            app_name=APP_NAME
        )

        return await self.backend.send(
            to_email=to_email,
            subject=t("email_subject_welcome", lang, app_name=APP_NAME),
            html_content=html_content,
            text_content=text_content,
        )

    async def send_pending_approval_email(
        self, to_email: str, username: str, lang: str = "fr"
    ) -> bool:
        """Envoie l'email de confirmation d'inscription en attente de validation."""
        html_content = self._load_template(
            "pending_approval",
            {
                "username": username,
                "title": t("email_title_pending", lang),
                "message": t("email_body_pending", lang, username=username),
            },
        )

        text_content = t(
            "email_text_pending", lang,
            username=username,
            app_name=APP_NAME
        )

        return await self.backend.send(
            to_email=to_email,
            subject=t("email_subject_pending", lang, app_name=APP_NAME),
            html_content=html_content,
            text_content=text_content,
        )

    async def send_rejection_email(
        self, to_email: str, username: str, reason: str, lang: str = "fr"
    ) -> bool:
        """Envoie l'email de refus d'inscription."""
        html_content = self._load_template(
            "rejected",
            {
                "username": username,
                "reason": reason,
                "title": t("email_title_rejected", lang),
                "message": t("email_body_rejected", lang, username=username),
            },
        )

        text_content = t(
            "email_text_rejected", lang,
            username=username,
            reason=reason,
            app_name=APP_NAME
        )

        return await self.backend.send(
            to_email=to_email,
            subject=t("email_subject_rejected", lang, app_name=APP_NAME),
            html_content=html_content,
            text_content=text_content,
        )

    async def send_new_registration_notification(
        self,
        to_email: str,
        user_email: str,
        username: str,
        registration_date: str,
        registration_method: str,
        is_verified: bool,
        dashboard_url: str,
        lang: str = "fr"
    ) -> bool:
        """Envoie la notification de nouvelle inscription aux admins."""
        verified_text = t("email_admin_new_registration_verified_yes", lang) if is_verified else t("email_admin_new_registration_verified_no", lang)

        html_content = self._load_template(
            "new_registration",
            {
                "user_email": user_email,
                "username": username,
                "registration_date": registration_date,
                "registration_method": registration_method,
                "is_verified": verified_text,
                "dashboard_url": dashboard_url,
            },
        )

        text_content = f"""{t("email_admin_new_registration_title", lang)}

{t("email_admin_new_registration_email", lang, user_email=user_email)}
{t("email_admin_new_registration_username", lang, username=username)}
{t("email_admin_new_registration_date", lang, registration_date=registration_date)}
{t("email_admin_new_registration_method", lang, registration_method=registration_method)}
{t("email_admin_new_registration_verified", lang, verified=verified_text)}

{t("email_admin_new_registration_action", lang)}
        """

        return await self.backend.send(
            to_email=to_email,
            subject=t("email_subject_new_registration", lang, user_email=user_email),
            html_content=html_content,
            text_content=text_content,
        )


def get_email_service() -> EmailService:
    """Factory pour creer le service email selon la configuration."""
    sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
    smtp_host = os.getenv("SMTP_HOST")
    email_backend = os.getenv("EMAIL_BACKEND", "console")

    from_email = os.getenv("EMAIL_FROM", "noreply@myia.local")
    from_name = os.getenv("EMAIL_FROM_NAME", "MY-IA")
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

    if email_backend == "sendgrid" and sendgrid_api_key:
        backend = SendGridBackend(
            api_key=sendgrid_api_key,
            from_email=from_email,
            from_name=from_name,
        )
        logger.info("Email backend: SendGrid")

    elif email_backend == "smtp" and smtp_host:
        backend = SMTPBackend(
            host=smtp_host,
            port=int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USERNAME"),
            password=os.getenv("SMTP_PASSWORD"),
            from_email=from_email,
            from_name=from_name,
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
        )
        logger.info("Email backend: SMTP")

    else:
        backend = ConsoleBackend()
        logger.info("Email backend: Console (developpement)")

    return EmailService(backend=backend, frontend_url=frontend_url)
