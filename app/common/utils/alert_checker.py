"""
Détecteur de patterns critiques dans les logs applicatifs

Évalue périodiquement les logs récents pour détecter :
- Explosion d'erreurs (> 50 ERROR en 5 minutes)
- Échecs de login répétés (> 5 par IP en 10 minutes)
- Événements FATAL/CRITICAL (flaggés automatiquement par le handler)

Les logs correspondant aux patterns détectés sont marqués
avec is_alert=True dans la table app_logs.

Dé-duplication : chaque type d'alerte est soumis à un cooldown
configurable via l'UI admin (clé logging.alert_cooldown_minutes).
Tant que le cooldown est actif, l'alerte n'est pas re-déclenchée.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppLog

logger = logging.getLogger(__name__)

# Seuils de détection
ERROR_EXPLOSION_THRESHOLD = 50       # Nombre d'erreurs en fenêtre
ERROR_EXPLOSION_WINDOW_MINUTES = 5   # Fenêtre temporelle
LOGIN_FAILURE_THRESHOLD = 5          # Nombre d'échecs par IP
LOGIN_FAILURE_WINDOW_MINUTES = 10    # Fenêtre temporelle

# Cooldown par défaut (utilisé si la valeur BDD n'est pas disponible)
DEFAULT_ALERT_COOLDOWN_MINUTES = 15

# Tracking en mémoire des derniers déclenchements par type d'alerte
_alert_cooldowns: Dict[str, datetime] = {}


def _is_in_cooldown(alert_type: str, cooldown_minutes: int) -> bool:
    """
    Vérifie si un type d'alerte est en période de cooldown.

    Args:
        alert_type: Identifiant du type d'alerte (ex: "error_explosion", "login_brute_force:1.2.3.4")
        cooldown_minutes: Durée du cooldown en minutes

    Returns:
        True si l'alerte est en cooldown (ne doit pas être re-déclenchée)
    """
    last_fired = _alert_cooldowns.get(alert_type)
    if last_fired is None:
        return False
    return datetime.now(timezone.utc) - last_fired < timedelta(minutes=cooldown_minutes)


def _set_cooldown(alert_type: str) -> None:
    """
    Enregistre le déclenchement d'une alerte pour activer le cooldown.

    Args:
        alert_type: Identifiant du type d'alerte
    """
    _alert_cooldowns[alert_type] = datetime.now(timezone.utc)


async def _get_cooldown_minutes(db: AsyncSession) -> int:
    """
    Récupère la durée de cooldown depuis la configuration BDD.

    Returns:
        Durée du cooldown en minutes
    """
    try:
        from app.features.admin.config.system_config_service import SystemConfigService
        config_service = SystemConfigService(db)
        return int(await config_service.get("logging.alert_cooldown_minutes", DEFAULT_ALERT_COOLDOWN_MINUTES))
    except Exception:
        return DEFAULT_ALERT_COOLDOWN_MINUTES


async def check_error_explosion(db: AsyncSession, cooldown_minutes: int) -> int:
    """
    Détecte une explosion d'erreurs (> 50 ERROR/FATAL en 5 minutes).

    Marque les logs ERROR/FATAL récents non-alertés comme alertes
    si leur nombre dépasse le seuil. Soumis au cooldown de dé-duplication.

    Args:
        db: Session de base de données
        cooldown_minutes: Durée du cooldown en minutes

    Returns:
        Nombre de nouveaux logs marqués comme alertes
    """
    alert_type = "error_explosion"

    if _is_in_cooldown(alert_type, cooldown_minutes):
        logger.debug("Alert '%s' en cooldown, skip", alert_type)
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ERROR_EXPLOSION_WINDOW_MINUTES)

    # Compter les ERROR+ récents
    count_query = (
        select(func.count(AppLog.id))
        .where(
            AppLog.timestamp >= cutoff,
            AppLog.level.in_(["ERROR", "FATAL"]),
        )
    )
    result = await db.execute(count_query)
    error_count = result.scalar() or 0

    if error_count < ERROR_EXPLOSION_THRESHOLD:
        return 0

    # Marquer les logs ERROR/FATAL récents non-alertés
    stmt = (
        update(AppLog)
        .where(
            AppLog.timestamp >= cutoff,
            AppLog.level.in_(["ERROR", "FATAL"]),
            AppLog.is_alert == False,
        )
        .values(is_alert=True)
    )
    update_result = await db.execute(stmt)
    flagged = update_result.rowcount or 0

    if flagged > 0:
        _set_cooldown(alert_type)
        logger.critical(
            "ALERT: Error explosion detected — %d errors in %d minutes (%d newly flagged)",
            error_count,
            ERROR_EXPLOSION_WINDOW_MINUTES,
            flagged,
            extra={"context": {
                "alert_type": alert_type,
                "error_count": error_count,
                "window_minutes": ERROR_EXPLOSION_WINDOW_MINUTES,
                "flagged_count": flagged,
            }}
        )

    return flagged


async def check_login_failures(db: AsyncSession, cooldown_minutes: int) -> int:
    """
    Détecte des échecs de login répétés par IP (> 5 en 10 minutes).

    Recherche les logs SECURITY contenant "login_failed" dans le contexte,
    groupés par IP source. Les logs des IPs dépassant le seuil sont flaggés.
    Cooldown par IP pour éviter les alertes redondantes.

    Args:
        db: Session de base de données
        cooldown_minutes: Durée du cooldown en minutes

    Returns:
        Nombre de nouveaux logs marqués comme alertes
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=LOGIN_FAILURE_WINDOW_MINUTES)

    # Compter les échecs par IP
    ip_query = (
        select(
            AppLog.context["ip_address"].as_string().label("ip"),
            func.count(AppLog.id).label("fail_count"),
        )
        .where(
            AppLog.timestamp >= cutoff,
            AppLog.log_category == "security",
            AppLog.message.ilike("%login_failed%"),
        )
        .group_by(AppLog.context["ip_address"].as_string())
        .having(func.count(AppLog.id) >= LOGIN_FAILURE_THRESHOLD)
    )

    try:
        # Utiliser un savepoint (begin_nested) pour isoler la requête JSON path.
        # Si elle échoue, seul le savepoint est rollback, pas la transaction entière.
        async with db.begin_nested():
            result = await db.execute(ip_query)
            suspicious_ips = result.all()
    except Exception:
        # Fallback si le JSON path ne fonctionne pas
        # (dépend du dialecte PostgreSQL et du type de colonne JSON vs JSONB)
        return await _check_login_failures_fallback(db, cutoff, cooldown_minutes)

    if not suspicious_ips:
        return 0

    total_flagged = 0
    for row in suspicious_ips:
        ip = row.ip
        fail_count = row.fail_count
        alert_type = f"login_brute_force:{ip}"

        # Cooldown par IP
        if _is_in_cooldown(alert_type, cooldown_minutes):
            logger.debug("Alert '%s' en cooldown, skip", alert_type)
            continue

        # Marquer les logs de cette IP
        stmt = (
            update(AppLog)
            .where(
                AppLog.timestamp >= cutoff,
                AppLog.log_category == "security",
                AppLog.message.ilike("%login_failed%"),
                AppLog.context["ip_address"].as_string() == ip,
                AppLog.is_alert == False,
            )
            .values(is_alert=True)
        )
        update_result = await db.execute(stmt)
        flagged = update_result.rowcount or 0
        total_flagged += flagged

        if flagged > 0:
            _set_cooldown(alert_type)
            logger.critical(
                "ALERT: Repeated login failures from IP %s — %d attempts in %d minutes",
                ip,
                fail_count,
                LOGIN_FAILURE_WINDOW_MINUTES,
                extra={"context": {
                    "alert_type": "login_brute_force",
                    "ip": ip,
                    "fail_count": fail_count,
                    "window_minutes": LOGIN_FAILURE_WINDOW_MINUTES,
                }}
            )

    return total_flagged


async def _check_login_failures_fallback(
    db: AsyncSession,
    cutoff: datetime,
    cooldown_minutes: int,
) -> int:
    """
    Fallback pour la détection d'échecs de login sans JSON path.

    Compte simplement le nombre total d'échecs et flagge si > seuil.
    """
    alert_type = "login_brute_force"

    if _is_in_cooldown(alert_type, cooldown_minutes):
        logger.debug("Alert '%s' (fallback) en cooldown, skip", alert_type)
        return 0

    count_query = (
        select(func.count(AppLog.id))
        .where(
            AppLog.timestamp >= cutoff,
            AppLog.log_category == "security",
            AppLog.message.ilike("%login_failed%"),
        )
    )
    result = await db.execute(count_query)
    total = result.scalar() or 0

    if total < LOGIN_FAILURE_THRESHOLD:
        return 0

    stmt = (
        update(AppLog)
        .where(
            AppLog.timestamp >= cutoff,
            AppLog.log_category == "security",
            AppLog.message.ilike("%login_failed%"),
            AppLog.is_alert == False,
        )
        .values(is_alert=True)
    )
    update_result = await db.execute(stmt)
    flagged = update_result.rowcount or 0

    if flagged > 0:
        _set_cooldown(alert_type)
        logger.critical(
            "ALERT: Multiple login failures detected — %d attempts in %d minutes",
            total,
            LOGIN_FAILURE_WINDOW_MINUTES,
            extra={"context": {
                "alert_type": "login_brute_force",
                "total_failures": total,
                "window_minutes": LOGIN_FAILURE_WINDOW_MINUTES,
            }}
        )

    return flagged


async def run_all_checks(db: AsyncSession) -> Dict[str, int]:
    """
    Exécute tous les checks d'alerting.

    Récupère le cooldown configuré en BDD puis exécute chaque check
    avec la dé-duplication active.

    Returns:
        Dictionnaire avec le nombre de nouveaux logs flaggés par check
    """
    cooldown_minutes = await _get_cooldown_minutes(db)
    results: Dict[str, int] = {}

    results["error_explosion"] = await check_error_explosion(db, cooldown_minutes)
    results["login_failures"] = await check_login_failures(db, cooldown_minutes)

    await db.commit()

    total = sum(results.values())
    if total > 0:
        logger.warning(
            "Alert checker: %d new alerts flagged — %s",
            total,
            results,
        )

        # Dispatcher les notifications vers les canaux configurés
        await _dispatch_notifications(db, results)

    return results


async def _dispatch_notifications(db: AsyncSession, results: Dict[str, int]) -> None:
    """
    Envoie les notifications pour les alertes détectées.

    Args:
        db: Session de base de données
        results: Dictionnaire {type_alerte: nombre_flaggés}
    """
    try:
        from app.common.utils.notifier import NotificationService

        for alert_type, count in results.items():
            if count <= 0:
                continue

            if alert_type == "error_explosion":
                subject = f"[MY-IA] Explosion d'erreurs ({count} logs flaggés)"
                body = (
                    f"Plus de {ERROR_EXPLOSION_THRESHOLD} erreurs détectées "
                    f"en {ERROR_EXPLOSION_WINDOW_MINUTES} minutes.\n"
                    f"{count} nouveaux logs marqués comme alertes."
                )
            elif alert_type == "login_failures":
                subject = f"[MY-IA] Échecs de login répétés ({count} logs flaggés)"
                body = (
                    f"Échecs de login suspects détectés "
                    f"(seuil : {LOGIN_FAILURE_THRESHOLD} en {LOGIN_FAILURE_WINDOW_MINUTES} min).\n"
                    f"{count} nouveaux logs marqués comme alertes."
                )
            else:
                subject = f"[MY-IA] Alerte : {alert_type} ({count} logs)"
                body = f"{count} nouveaux logs marqués comme alertes pour le pattern '{alert_type}'."

            await NotificationService.notify_alert(
                db=db,
                alert_type=alert_type,
                subject=subject,
                body=body,
                details={"flagged_count": count},
            )

    except Exception as e:
        logger.error("Failed to dispatch alert notifications: %s", e, exc_info=True)
