"""
Security Logger — Utilitaire de logs catégorie SECURITY

Fournit des fonctions spécialisées pour émettre des logs de sécurité structurés.
Complète le système d'audit existant (table audit_logs) avec des logs sur stdout/JSON.

Usage:
    from app.common.utils.security_logger import log_login_success, log_login_failed

    log_login_success(user_id="uuid", ip="192.168.1.1", user_agent="Mozilla/5.0")
    log_login_failed(email="user@example.com", ip="192.168.1.1", reason="invalid_credentials")
"""
import logging
from typing import Optional

from app.core.logging import get_category_logger, LogCategory

# Logger dédié à la catégorie SECURITY
security_logger = get_category_logger("app.security", LogCategory.SECURITY)


def log_login_success(
    user_id: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """Log une connexion réussie."""
    security_logger.info(
        "Login success: user=%s",
        user_id,
        extra={
            "context": {
                "event": "login_success",
                "user_id": user_id,
                "ip_address": ip,
                "user_agent": user_agent[:200] if user_agent else None,
            }
        },
    )


def log_login_failed(
    email: Optional[str] = None,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    reason: str = "invalid_credentials",
) -> None:
    """Log un échec de connexion."""
    security_logger.warning(
        "Login failed: email=%s reason=%s",
        email,
        reason,
        extra={
            "context": {
                "event": "login_failed",
                "email": email,
                "ip_address": ip,
                "user_agent": user_agent[:200] if user_agent else None,
                "reason": reason,
            }
        },
    )


def log_logout(
    user_id: str,
    ip: Optional[str] = None,
) -> None:
    """Log une déconnexion."""
    security_logger.info(
        "Logout: user=%s",
        user_id,
        extra={
            "context": {
                "event": "logout",
                "user_id": user_id,
                "ip_address": ip,
            }
        },
    )


def log_privilege_change(
    admin_id: str,
    target_user_id: str,
    old_role: Optional[str] = None,
    new_role: Optional[str] = None,
) -> None:
    """Log un changement de privilèges."""
    security_logger.warning(
        "Privilege change: admin=%s target=%s %s→%s",
        admin_id,
        target_user_id,
        old_role,
        new_role,
        extra={
            "context": {
                "event": "privilege_change",
                "admin_id": admin_id,
                "target_user_id": target_user_id,
                "old_role": old_role,
                "new_role": new_role,
            }
        },
    )


def log_config_change(
    admin_id: str,
    config_key: str,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> None:
    """Log un changement de configuration sensible."""
    security_logger.warning(
        "Config change: admin=%s key=%s",
        admin_id,
        config_key,
        extra={
            "context": {
                "event": "config_change",
                "admin_id": admin_id,
                "config_key": config_key,
                "old_value": old_value,
                "new_value": new_value,
            }
        },
    )


def log_access_denied(
    user_id: Optional[str] = None,
    path: Optional[str] = None,
    reason: str = "forbidden",
    ip: Optional[str] = None,
) -> None:
    """Log un accès refusé."""
    security_logger.warning(
        "Access denied: user=%s path=%s reason=%s",
        user_id,
        path,
        reason,
        extra={
            "context": {
                "event": "access_denied",
                "user_id": user_id,
                "path": path,
                "reason": reason,
                "ip_address": ip,
            }
        },
    )


def log_registration(
    user_id: str,
    email: str,
    ip: Optional[str] = None,
) -> None:
    """Log une inscription."""
    security_logger.info(
        "Registration: user=%s email=%s",
        user_id,
        email,
        extra={
            "context": {
                "event": "registration",
                "user_id": user_id,
                "email": email,
                "ip_address": ip,
            }
        },
    )
