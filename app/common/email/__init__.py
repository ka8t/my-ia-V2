"""
Module Email - Service d'envoi d'emails.

Supporte SendGrid (production) et SMTP (developpement).
"""

from app.common.email.service import EmailService, get_email_service

__all__ = ["EmailService", "get_email_service"]
