"""
Logging structuré centralisé

Module principal du système de logs MY-IA.
Fournit un format JSON structuré, 5 catégories de logs,
enrichissement automatique via ContextVar et niveau TRACE custom.

Usage:
    from app.core.logging import setup_logging, get_category_logger, LogCategory

    # Au démarrage (remplace logging.basicConfig)
    setup_logging()

    # Dans un service
    logger = get_category_logger(__name__, LogCategory.TECHNICAL)
    logger.info("Message", extra={"context": {"key": "value"}})
"""
import asyncio
import json
import logging
import sys
import traceback
import uuid
from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# ============================================================================
# NIVEAU TRACE (custom)
# ============================================================================

TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def trace(self: logging.Logger, message: str, *args: Any, **kwargs: Any) -> None:
    """Méthode trace() ajoutée dynamiquement aux loggers."""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


# Ajouter la méthode trace() à la classe Logger
logging.Logger.trace = trace  # type: ignore[attr-defined]


# ============================================================================
# CATÉGORIES DE LOGS
# ============================================================================

class LogCategory(str, Enum):
    """
    5 catégories de logs conformes au TODO §14.2.

    Chaque catégorie répond à un objectif distinct et sera identifiable
    par le champ 'log_category' dans le JSON.
    """
    TECHNICAL = "technical"   # Exceptions, erreurs métier, appels externes
    ACCESS = "access"         # Requêtes HTTP entrantes/sortantes
    AUDIT = "audit"           # Qui a fait quoi, quand, sur quelles données
    SECURITY = "security"     # Auth, privilèges, accès interdits
    INFRA = "infra"           # Santé containers, redémarrages, déploiements


# ============================================================================
# CONTEXTE DE REQUÊTE (ContextVar)
# ============================================================================

# Variables contextuelles injectées par le middleware RequestContextMiddleware (Phase 2)
# Accessibles automatiquement par le formatter JSON dans tout le code async
request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
user_id_var: ContextVar[Optional[str]] = ContextVar("user_id", default=None)
username_var: ContextVar[Optional[str]] = ContextVar("username", default=None)
session_id_var: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
ip_address_var: ContextVar[Optional[str]] = ContextVar("ip_address", default=None)
user_agent_var: ContextVar[Optional[str]] = ContextVar("user_agent", default=None)


# ============================================================================
# FILTRE DE CATÉGORIE
# ============================================================================

class CategoryFilter(logging.Filter):
    """
    Filtre qui attache une catégorie de log à chaque LogRecord.

    Utilisé par get_category_logger() pour marquer les logs
    avec leur catégorie (technical, access, audit, security, infra).
    """

    def __init__(self, category: LogCategory) -> None:
        super().__init__()
        self.category = category.value

    def filter(self, record: logging.LogRecord) -> bool:
        """Attache la catégorie au record (ne filtre pas, retourne toujours True)."""
        if not hasattr(record, "log_category"):
            record.log_category = self.category  # type: ignore[attr-defined]
        return True


# ============================================================================
# FORMATTER JSON STRUCTURÉ
# ============================================================================

class StructuredJSONFormatter(logging.Formatter):
    """
    Formatter Python qui produit du JSON structuré conforme au TODO §14.4.

    Champs produits :
    - timestamp (ISO 8601 UTC)
    - level (TRACE, DEBUG, INFO, WARNING, ERROR, CRITICAL)
    - log_category (technical, access, audit, security, infra)
    - service (nom de l'application)
    - environment (dev, staging, prod)
    - request_id (UUID de corrélation, depuis ContextVar)
    - user_id (depuis ContextVar)
    - session_id (depuis ContextVar)
    - message (texte du log)
    - context (données métier additionnelles)
    - logger_name (nom du logger Python)
    - exc_info (stack trace si exception)
    """

    def __init__(self, service: str = "app", environment: str = "dev") -> None:
        super().__init__()
        self.service = service
        self.environment = environment

    def format(self, record: logging.LogRecord) -> str:
        """Formate le LogRecord en JSON structuré."""
        # Niveau normalisé (WARNING → WARN pour cohérence §14.3)
        level = record.levelname
        if level == "WARNING":
            level = "WARN"
        elif level == "CRITICAL":
            level = "FATAL"

        # Catégorie (défaut: technical)
        log_category = getattr(record, "log_category", LogCategory.TECHNICAL.value)

        # Contexte métier (passé via extra={"context": {...}})
        context = getattr(record, "context", None)

        # Construction du JSON
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "log_category": log_category,
            "service": self.service,
            "environment": self.environment,
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
            "username": username_var.get(),
            "session_id": session_id_var.get(),
            "message": record.getMessage(),
            "logger_name": record.name,
        }

        # Ajouter le contexte métier seulement s'il existe
        if context:
            log_entry["context"] = context

        # Ajouter la stack trace si exception
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exc_info"] = self.formatException(record.exc_info)

        # Ajouter le stack trace si record.stack_info
        if record.stack_info:
            log_entry["stack_info"] = record.stack_info

        return json.dumps(log_entry, ensure_ascii=False, default=str)


# ============================================================================
# FACTORY DE LOGGERS PAR CATÉGORIE
# ============================================================================

def get_category_logger(name: str, category: LogCategory = LogCategory.TECHNICAL) -> logging.Logger:
    """
    Retourne un logger avec un filtre de catégorie attaché.

    Args:
        name: Nom du logger (généralement __name__)
        category: Catégorie de log (défaut: TECHNICAL)

    Returns:
        Logger Python avec le filtre de catégorie

    Example:
        from app.core.logging import get_category_logger, LogCategory

        logger = get_category_logger(__name__, LogCategory.SECURITY)
        logger.warning("Login failed", extra={"context": {"email": "user@example.com"}})
    """
    logger = logging.getLogger(name)

    # Vérifier si le filtre de catégorie est déjà attaché
    for f in logger.filters:
        if isinstance(f, CategoryFilter) and f.category == category.value:
            return logger

    logger.addFilter(CategoryFilter(category))
    return logger


# ============================================================================
# CONFIGURATION CENTRALISÉE
# ============================================================================

# Loggers externes à réduire en production
EXTERNAL_LOGGERS = [
    "httpx",
    "httpcore",
    "chromadb",
    "sqlalchemy",
    "uvicorn.access",
    "uvicorn.error",
    "watchfiles",
]


def setup_logging(
    log_level: Optional[str] = None,
    service: Optional[str] = None,
    environment: Optional[str] = None,
) -> None:
    """
    Configure le système de logging structuré JSON.

    Remplace logging.basicConfig() dans main.py.
    Tous les logs existants (logger.info, logger.error, etc.) continuent
    de fonctionner mais produisent du JSON au lieu du texte.

    Args:
        log_level: Niveau de log (défaut: depuis settings.log_level)
        service: Nom du service (défaut: depuis settings.app_name)
        environment: Environnement (défaut: depuis settings.environment)
    """
    # Import tardif pour éviter les imports circulaires
    from app.core.config import settings

    level = log_level or settings.log_level
    svc = service or settings.app_name
    env = environment or settings.environment

    # Créer le formatter JSON
    json_formatter = StructuredJSONFormatter(service=svc, environment=env)

    # Configurer le handler stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(json_formatter)
    console_handler.setLevel(level)

    # Configurer le root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Supprimer les handlers existants (éviter les doublons)
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)

    # Réduire le bruit des librairies externes
    for logger_name in EXTERNAL_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


# ============================================================================
# HANDLER BASE DE DONNÉES (ASYNC)
# ============================================================================

# Niveaux minimum par catégorie pour la persistance BDD
DEFAULT_DB_LEVELS: Dict[str, int] = {
    LogCategory.TECHNICAL.value: logging.WARNING,
    LogCategory.ACCESS.value: logging.INFO,
    LogCategory.AUDIT.value: logging.DEBUG,     # Toujours persister
    LogCategory.SECURITY.value: logging.DEBUG,  # Toujours persister
    LogCategory.INFRA.value: logging.INFO,
}


class AsyncDatabaseLogHandler(logging.Handler):
    """
    Handler Python logging qui persiste les logs dans la table app_logs.

    Fonctionnement :
    - Buffer en mémoire (deque) avec flush périodique
    - Flush déclenché toutes les 5 secondes OU quand 100 entrées sont en attente
    - Écriture batch async dans PostgreSQL via SQLAlchemy
    - Filtre par catégorie : seuls les logs >= niveau configuré sont persistés

    Note : Ce handler ne doit PAS loguer lui-même pour éviter les boucles infinies.
    """

    def __init__(
        self,
        flush_interval: float = 5.0,
        max_buffer_size: int = 100,
        db_levels: Optional[Dict[str, int]] = None,
        service: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._buffer: deque = deque()
        self._flush_interval = flush_interval
        self._max_buffer_size = max_buffer_size
        self._db_levels = db_levels or DEFAULT_DB_LEVELS.copy()
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        self._service = service
        self._environment = environment

    def start(self) -> None:
        """Démarre la tâche de flush périodique. Appeler depuis le lifespan."""
        if self._running:
            return
        self._running = True
        try:
            loop = asyncio.get_running_loop()
            self._flush_task = loop.create_task(self._periodic_flush())
        except RuntimeError:
            pass  # Pas de boucle asyncio — ignore (sera démarré plus tard)

    async def stop(self) -> None:
        """Arrête le handler et flush les logs restants."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        # Flush final
        await self._flush_to_db()

    def emit(self, record: logging.LogRecord) -> None:
        """
        Ajoute le log au buffer si le niveau est suffisant pour sa catégorie.

        Ne fait PAS d'I/O — le flush est asynchrone.
        """
        # Éviter les boucles infinies (ne pas loguer les logs de sqlalchemy/asyncpg)
        if record.name.startswith(("sqlalchemy", "asyncpg", "app.core.logging")):
            return

        category = getattr(record, "log_category", LogCategory.TECHNICAL.value)
        min_level = self._db_levels.get(category, logging.WARNING)

        if record.levelno < min_level:
            return

        # Normaliser le niveau
        level = record.levelname
        if level == "WARNING":
            level = "WARN"
        elif level == "CRITICAL":
            level = "FATAL"

        # FATAL/CRITICAL → alerte automatique (Phase 9)
        is_alert = record.levelno >= logging.CRITICAL

        entry = {
            "timestamp": datetime.now(timezone.utc),
            "level": level,
            "log_category": category,
            "service": self._service,
            "environment": self._environment,
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
            "username": username_var.get(),
            "session_id": session_id_var.get(),
            "ip_address": ip_address_var.get(),
            "user_agent": user_agent_var.get(),
            "message": record.getMessage(),
            "context": getattr(record, "context", None),
            "logger_name": record.name,
            "is_alert": is_alert,
        }

        self._buffer.append(entry)

        # Flush si le buffer est plein
        if len(self._buffer) >= self._max_buffer_size:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._flush_to_db())
            except RuntimeError:
                pass

    async def _periodic_flush(self) -> None:
        """Tâche asyncio qui flush le buffer périodiquement."""
        while self._running:
            await asyncio.sleep(self._flush_interval)
            if self._buffer:
                await self._flush_to_db()

    async def _flush_to_db(self) -> None:
        """Écrit les logs du buffer dans la table app_logs en batch."""
        if not self._buffer:
            return

        # Extraire tous les logs du buffer
        entries: List[Dict[str, Any]] = []
        while self._buffer:
            entries.append(self._buffer.popleft())

        try:
            # Import tardif pour éviter les imports circulaires
            from app.db import async_session_maker
            from app.models import AppLog

            async with async_session_maker() as session:
                for entry in entries:
                    # Convertir user_id string en UUID si nécessaire
                    uid = entry.get("user_id")
                    if uid and isinstance(uid, str):
                        try:
                            uid = uuid.UUID(uid)
                        except ValueError:
                            uid = None

                    log_record = AppLog(
                        timestamp=entry["timestamp"],
                        level=entry["level"],
                        log_category=entry["log_category"],
                        service=entry.get("service"),
                        environment=entry.get("environment"),
                        request_id=entry.get("request_id"),
                        user_id=uid,
                        username=entry.get("username"),
                        session_id=entry.get("session_id"),
                        ip_address=entry.get("ip_address"),
                        user_agent=entry.get("user_agent"),
                        message=entry["message"],
                        context=entry.get("context"),
                        logger_name=entry.get("logger_name"),
                        is_alert=entry.get("is_alert", False),
                    )
                    session.add(log_record)

                await session.commit()
        except Exception:
            # Ne PAS loguer ici (boucle infinie). Silencieux en cas d'erreur DB.
            # Remettre les logs dans le buffer pour retry
            for entry in reversed(entries):
                self._buffer.appendleft(entry)
            # Limiter la taille du buffer pour éviter l'accumulation mémoire
            while len(self._buffer) > self._max_buffer_size * 5:
                self._buffer.popleft()


# Instance globale du handler BDD (initialisée par setup_db_logging)
_db_handler: Optional[AsyncDatabaseLogHandler] = None


def setup_db_logging() -> Optional[AsyncDatabaseLogHandler]:
    """
    Active la persistance des logs en BDD.

    Crée un AsyncDatabaseLogHandler et l'attache au root logger.
    Doit être appelé depuis le lifespan APRÈS l'initialisation de la BDD.

    Returns:
        Le handler créé (pour pouvoir l'arrêter proprement au shutdown)
    """
    global _db_handler

    if _db_handler is not None:
        return _db_handler

    # Import tardif pour éviter les imports circulaires
    from app.core.config import settings

    _db_handler = AsyncDatabaseLogHandler(
        service=settings.app_name,
        environment=settings.environment,
    )
    _db_handler.start()

    root_logger = logging.getLogger()
    root_logger.addHandler(_db_handler)

    return _db_handler


async def stop_db_logging() -> None:
    """Arrête le handler BDD et flush les logs restants."""
    global _db_handler
    if _db_handler:
        await _db_handler.stop()
        logging.getLogger().removeHandler(_db_handler)
        _db_handler = None
