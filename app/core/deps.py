"""
Dépendances injectables FastAPI

Ce module centralise toutes les dépendances injectables
pour éviter les imports circulaires et améliorer la testabilité.
"""
import logging
from typing import Optional, AsyncGenerator

import chromadb
from fastapi import Header, HTTPException, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import username_var
from app.db import get_async_session
from app.models import User
from app.features.auth.service import current_active_user
from app.ingest_v2 import AdvancedIngestionPipeline
from app.common.i18n import t
from app.common.utils.security_logger import log_access_denied

logger = logging.getLogger(__name__)


# ============================================================================
# ChromaDB Client (Singleton Pattern)
# ============================================================================

_chroma_client: Optional[chromadb.ClientAPI] = None
_ingestion_pipeline: Optional[AdvancedIngestionPipeline] = None


def get_chroma_client() -> Optional[chromadb.ClientAPI]:
    """
    Retourne le client ChromaDB (singleton)

    Returns:
        Client ChromaDB ou None si l'initialisation a échoué
    """
    global _chroma_client

    if _chroma_client is None:
        try:
            # ChromaDB 1.0.0+ API
            _chroma_client = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
            )
            logger.info(f"ChromaDB client initialized at {settings.chroma_url}")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB client: {e}")
            _chroma_client = None

    return _chroma_client


def get_ingestion_pipeline() -> Optional[AdvancedIngestionPipeline]:
    """
    Retourne le pipeline d'ingestion (singleton)

    Returns:
        Pipeline d'ingestion ou None si l'initialisation a échoué
    """
    global _ingestion_pipeline

    if _ingestion_pipeline is None:
        chroma_client = get_chroma_client()
        if chroma_client:
            try:
                _ingestion_pipeline = AdvancedIngestionPipeline(chroma_client=chroma_client)
                logger.info("Advanced Ingestion Pipeline v2 initialized")
            except Exception as e:
                logger.error(f"Failed to initialize ingestion pipeline: {e}")
                _ingestion_pipeline = None

    return _ingestion_pipeline


# ============================================================================
# Security Dependencies
# ============================================================================

async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> bool:
    """
    Vérifie la clé API

    Args:
        x_api_key: Clé API dans le header X-API-Key

    Returns:
        True si la clé est valide

    Raises:
        HTTPException: Si la clé est invalide
    """
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail=t("error_invalid_api_key"))
    return True


async def verify_jwt_or_api_key(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None)
) -> bool:
    """
    Vérifie l'authentification JWT (par défaut) ou API key (fallback)

    Permet l'accès via:
    - Header Authorization: Bearer <token> (pour le frontend - défaut)
    - Header X-API-Key (pour les clients API externes)

    Returns:
        True si l'un des deux est valide

    Raises:
        HTTPException: Si aucune authentification valide
    """
    # Essayer d'abord le JWT (méthode par défaut)
    if authorization and authorization.startswith("Bearer "):
        try:
            from app.features.auth.service import verify_jwt_token
            token = authorization.split(" ")[1]
            payload = await verify_jwt_token(token)
            if payload:
                return True
        except Exception as e:
            logger.debug(f"JWT verification failed: {e}")

    # Fallback sur la clé API (pour clients externes)
    if x_api_key and x_api_key == settings.api_key:
        return True

    raise HTTPException(status_code=401, detail=t("error_invalid_authentication"))


async def get_current_admin_user(
    request: Request,
    user: User = Depends(current_active_user),
) -> User:
    """
    Vérifie que l'utilisateur actuel est un administrateur

    Args:
        request: Requête HTTP (injectée par FastAPI)
        user: Utilisateur authentifié

    Returns:
        L'utilisateur si c'est un admin

    Raises:
        HTTPException: Si l'utilisateur n'est pas admin
    """
    if user.role_id != 1:  # 1 = role admin
        log_access_denied(
            user_id=str(user.id),
            path=request.url.path,
            reason="admin_required",
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(
            status_code=403,
            detail=t("error_admin_required")
        )

    # Enrichir les logs applicatifs avec le username de l'admin
    username_var.set(user.username)

    return user


async def get_current_user(
    user: User = Depends(current_active_user),
) -> User:
    """
    Dépendance pour les routes utilisateur authentifié.

    Enrichit les logs applicatifs avec le username via ContextVar.

    Args:
        user: Utilisateur authentifié (via FastAPI Users)

    Returns:
        L'utilisateur authentifié
    """
    # Enrichir les logs applicatifs avec le username
    username_var.set(user.username)

    return user


# ============================================================================
# Database Dependencies
# ============================================================================

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Générateur de session de base de données

    Yields:
        AsyncSession: Session de base de données

    Note:
        Utilise get_async_session de db.py pour la compatibilité
    """
    async for session in get_async_session():
        yield session


# ============================================================================
# Storage Dependencies
# ============================================================================

_storage_backend = None
_storage_service = None


def _parse_list_config(value: str) -> list[str]:
    """
    Parse une valeur de config qui peut être JSON array ou CSV.

    Args:
        value: Chaîne JSON array ou CSV

    Returns:
        Liste de chaînes
    """
    if not value:
        return []

    value = value.strip()

    # Si c'est un JSON array
    if value.startswith("["):
        import json
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed]
        except json.JSONDecodeError:
            pass

    # Fallback: CSV
    return [t.strip() for t in value.split(",") if t.strip()]


def get_quota_config():
    """
    Retourne la configuration des quotas depuis settings (fallback statique).

    Returns:
        QuotaConfig: Configuration des quotas
    """
    from app.common.storage.schemas import QuotaConfig

    return QuotaConfig(
        default_quota_bytes=settings.storage_default_quota_mb * 1024 * 1024,
        max_file_size_bytes=settings.storage_max_file_size_mb * 1024 * 1024,
        allowed_mime_types=_parse_list_config(settings.storage_allowed_mime_types),
        blocked_extensions=_parse_list_config(settings.storage_blocked_extensions),
    )


async def get_dynamic_quota_config(db: AsyncSession) -> "QuotaConfig":
    """
    Retourne la configuration des quotas depuis la base de donnees.

    Args:
        db: Session de base de donnees

    Returns:
        QuotaConfig: Configuration des quotas depuis la DB
    """
    from app.common.storage.schemas import QuotaConfig
    from app.features.system.service import SystemConfigService

    try:
        config_service = SystemConfigService(db)

        # Recuperer les valeurs depuis la base
        allowed_mime_types = await config_service.get_allowed_mime_types()
        blocked_extensions = await config_service.get_blocked_extensions()
        max_file_size_bytes = await config_service.get_max_file_size_bytes()
        default_quota_bytes = await config_service.get_default_quota_bytes()

        return QuotaConfig(
            default_quota_bytes=default_quota_bytes,
            max_file_size_bytes=max_file_size_bytes,
            allowed_mime_types=allowed_mime_types,
            blocked_extensions=blocked_extensions,
        )
    except Exception as e:
        logger.warning(f"Failed to get dynamic quota config, using static: {e}")
        return get_quota_config()


def get_storage_backend():
    """
    Factory pour le backend de stockage (singleton).

    Returns:
        StorageBackend: Backend de stockage

    Raises:
        NotImplementedError: Si le backend n'est pas implémenté
        ValueError: Si le backend est inconnu
    """
    global _storage_backend

    if _storage_backend is None:
        if settings.storage_backend == "local":
            from app.common.storage.backends.local import LocalStorageBackend

            _storage_backend = LocalStorageBackend(settings.storage_local_path)
            logger.info(
                f"LocalStorageBackend initialized at {settings.storage_local_path}"
            )
        elif settings.storage_backend == "minio":
            # Futur: from app.common.storage.backends.minio import MinIOStorageBackend
            raise NotImplementedError("MinIO backend not implemented yet")
        elif settings.storage_backend == "s3":
            # Futur: from app.common.storage.backends.s3 import S3StorageBackend
            raise NotImplementedError("S3 backend not implemented yet")
        else:
            raise ValueError(f"Unknown storage backend: {settings.storage_backend}")

    return _storage_backend


def get_storage_service():
    """
    Retourne le service de stockage avec quotas (singleton).

    Returns:
        StorageService: Service de stockage
    """
    global _storage_service

    if _storage_service is None:
        from app.common.storage.service import StorageService

        _storage_service = StorageService(
            backend=get_storage_backend(),
            quota_config=get_quota_config(),
        )
        logger.info("StorageService initialized")

    return _storage_service
