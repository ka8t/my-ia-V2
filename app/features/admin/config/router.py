"""
Router Admin Config

Endpoints pour la gestion de la configuration système.
Tous les endpoints nécessitent le rôle admin.
"""
import logging

from fastapi import APIRouter, Request, Depends, HTTPException, Query
from typing import Optional
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.admin.config.service import ConfigService
from app.common.utils.security_logger import log_config_change
from app.features.admin.config.schemas import (
    SystemConfigRead, RAGConfigRead, RAGConfigUpdate,
    TimeoutsConfigRead, TimeoutsConfigUpdate,
    RateLimitsConfigRead, RateLimitsConfigUpdate,
    DynamicConfigResponse, DynamicConfigListResponse,
    DynamicConfigUpdateRequest, DynamicConfigCreateRequest,
    StorageConfigResponse, StorageConfigUpdateRequest,
    FileTypeResponse, FileTypesListResponse, FileTypesUpdateRequest,
    OllamaModelsListResponse, OllamaModelInfo, OllamaModelPullRequest,
    SpeechConfigRead, SpeechConfigUpdate,
    SourcesIndexationConfigRead, SourcesIndexationConfigUpdate,
    ChatConfigRead, ChatConfigUpdate,
    DebugConfigRead, DebugConfigUpdate,
    LoggingConfigRead, LoggingConfigUpdate,
    NotificationConfigRead, NotificationConfigUpdate, NotificationTestRequest,
    SmtpConfigRead, SmtpConfigUpdate, SmtpTestRequest, SmtpTestResponse,
    LLMProviderConfigRead, LLMProviderConfigUpdate,
    ModelsListResponse, GGUFDownloadRequest, ModelDeleteResponse,
    LLMStartRequest, LLMControlResponse, LLMStatusResponse,
    LlamaCppParamsRead, LlamaCppParamsUpdate, LlamaCppMetricsResponse,
    OllamaConfigRead, OllamaConfigUpdate, OllamaPreloadResponse, ServerHardwareResponse,
    RAGTestRequest, RAGTestResponse, RAGStatsResponse,
    GeoConfigRead, GeoConfigUpdate,
    AppearanceConfigRead, AppearanceConfigUpdate,
    PerfConfigRead, PerfConfigUpdate
)
from app.common.filetypes import (
    FILE_TYPES_REGISTRY,
    get_all_file_types,
    get_enabled_mime_types,
)
from app.features.system.service import SystemConfigService
from app.features.audit.service import AuditService
from app.common.metrics import REQUEST_COUNT

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# LECTURE CONFIGURATION
# =============================================================================

@router.get("", response_model=SystemConfigRead)
async def get_system_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration système complète.

    Includes:
    - Informations application (nom, version, environnement)
    - Configuration RAG (top_k, chunk_size, etc.) - depuis la BDD
    - Configuration timeouts
    - Configuration rate limits
    - Endpoints externes (Ollama, ChromaDB)

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_system_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting system config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag", response_model=RAGConfigRead)
async def get_rag_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration RAG depuis la base de données.

    Retourne la configuration du provider actif.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_rag_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting RAG config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag/stats", response_model=RAGStatsResponse)
async def get_rag_stats(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les statistiques RAG globales.

    Retourne:
    - Nombre de collections
    - Nombre de documents indexés
    - Nombre de chunks dans ChromaDB
    - Taille moyenne des chunks
    - Modèle d'embedding actif
    - Date de dernière indexation

    Requires: Admin role
    """
    try:
        result = await ConfigService.get_rag_stats(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag/stats", method="GET", status="200"
        ).inc()

        return result

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag/stats", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting RAG stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/test", response_model=RAGTestResponse)
async def test_rag_search(
    request_data: RAGTestRequest,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Teste la configuration RAG avec une requête sample.

    Permet de vérifier que les paramètres RAG produisent des résultats
    pertinents avant de sauvegarder la configuration.

    Body:
    - query: Question de test (3-500 caractères)
    - top_k: Nombre de chunks à retourner (optionnel, utilise config actuelle)
    - similarity_threshold: Seuil de similarité (optionnel)
    - collection_id: ID de collection cible (optionnel)

    Requires: Admin role
    """
    try:
        result = await ConfigService.test_rag_search(db, request_data)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag/test", method="POST", status="200"
        ).inc()

        return result

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag/test", method="POST", status="500"
        ).inc()
        logger.error(f"Error testing RAG search: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rag/{provider}", response_model=RAGConfigRead)
async def get_rag_config_for_provider(
    provider: str,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration RAG pour un provider spécifique.

    Permet de prévisualiser la configuration d'un provider sans changer
    le provider actif. Utile lors du changement de provider dans l'UI.

    Args:
        provider: Provider LLM (ollama ou llamacpp)

    Requires: Admin role
    """
    if provider not in ("ollama", "llamacpp"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {provider}. Must be 'ollama' or 'llamacpp'"
        )

    try:
        config = await ConfigService.get_rag_config(db, provider=provider)

        REQUEST_COUNT.labels(
            endpoint=f"/admin/config/rag/{provider}", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint=f"/admin/config/rag/{provider}", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting RAG config for provider {provider}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm-provider", response_model=LLMProviderConfigRead)
async def get_llm_provider_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration du provider LLM depuis la base de données.

    Retourne le provider actif (ollama ou llamacpp) et son statut de santé.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_llm_provider_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm-provider", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm-provider", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting LLM provider config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/llm-provider", response_model=LLMProviderConfigRead)
async def update_llm_provider_config(
    config_data: LLMProviderConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration du provider LLM en base de données.

    Note: Le changement de provider nécessite un redémarrage pour prendre
    effet complètement. Le provider sera réinitialisé automatiquement.

    Requires: Admin role
    """
    try:
        config = await ConfigService.update_llm_provider_config(
            db,
            config_data,
            updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name="config.llm_provider.update",
            user_id=admin_user.id,
            resource_type_name="config",
            details={
                "changes": config_data.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.email
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm-provider", method="PATCH", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm-provider", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating LLM provider config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/timeouts", response_model=TimeoutsConfigRead)
async def get_timeouts_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration des timeouts depuis la BDD.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_timeouts_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/timeouts", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/timeouts", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting timeouts config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/rate-limits", response_model=RateLimitsConfigRead)
async def get_rate_limits_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration des rate limits depuis la BDD.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_rate_limits_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/rate-limits", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/rate-limits", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting rate limits config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/rate-limits", response_model=RateLimitsConfigRead)
async def update_rate_limits_config(
    config_data: RateLimitsConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration des rate limits en BDD.

    Body (format: "N/period" où period = second|minute|hour|day):
    - chat: Rate limit pour /chat (ex: "60/minute")
    - upload: Rate limit pour /upload (ex: "10/minute")
    - stream: Rate limit pour /chat/stream (ex: "30/minute")
    - admin: Rate limit pour /admin (ex: "30/minute")

    Note: Les modifications nécessitent un redémarrage de l'application
    pour être appliquées (SlowAPI initialise les limites au démarrage).

    Requires: Admin role
    """
    try:
        # Récupérer l'ancienne config pour l'audit
        old_config = await ConfigService.get_rate_limits_config(db)

        new_config = await ConfigService.update_rate_limits_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'rate_limits',
                'old_values': old_config.model_dump(),
                'new_values': config_data.model_dump(exclude_unset=True),
                'note': 'Restart required to apply changes'
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/rate-limits", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/rate-limits", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating rate limits config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# MISE À JOUR CONFIGURATION
# =============================================================================

@router.patch("/rag", response_model=RAGConfigRead)
async def update_rag_config(
    config_data: RAGConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration RAG en base de données.

    Body:
    - top_k: Nombre de résultats (1-20)
    - similarity_threshold: Seuil de similarité (0-1)
    - temperature: Température du LLM (0-2)
    - chunk_size: Taille des chunks (100-4000)
    - chunk_overlap: Overlap (0-500)
    - chunking_strategy: Stratégie de chunking

    Note: Ces modifications sont persistées en base de données.

    Requires: Admin role
    """
    try:
        # Récupérer l'ancienne config pour l'audit
        old_config = await ConfigService.get_rag_config(db)

        new_config = await ConfigService.update_rag_config(db, config_data, admin_user.id)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'rag',
                'old_values': old_config.model_dump(),
                'new_values': config_data.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/rag", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating RAG config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/timeouts", response_model=TimeoutsConfigRead)
async def update_timeouts_config(
    config_data: TimeoutsConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration des timeouts en BDD.

    Body:
    - ollama_timeout: Timeout Ollama (5-600s)
    - http_timeout: Timeout HTTP (1-120s)
    - health_check_timeout: Timeout health check (1-30s)

    Les modifications sont persistées en BDD et appliquées immédiatement.

    Requires: Admin role
    """
    try:
        # Récupérer l'ancienne config pour l'audit
        old_config = await ConfigService.get_timeouts_config(db)

        new_config = await ConfigService.update_timeouts_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'timeouts',
                'old_values': old_config.model_dump(),
                'new_values': config_data.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/timeouts", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/timeouts", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating timeouts config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# RELOAD CONFIGURATION
# =============================================================================

@router.post("/reload", response_model=SystemConfigRead)
async def reload_config(
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recharge la configuration depuis les valeurs par défaut.

    Efface les overrides runtime des timeouts.
    Note: La configuration RAG en base de données n'est pas affectée.

    Requires: Admin role
    """
    try:
        # Récupérer les overrides actuels pour l'audit
        overrides = ConfigService.get_runtime_overrides()

        config = await ConfigService.reload_config(db)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_reloaded',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'cleared_overrides': overrides
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/reload", method="POST", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/reload", method="POST", status="500"
        ).inc()
        logger.error(f"Error reloading config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONFIGURATION DYNAMIQUE (stockee en base de donnees)
# =============================================================================

@router.get("/dynamic", response_model=DynamicConfigListResponse)
async def get_dynamic_configs(
    category: str = None,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recupere toutes les configurations dynamiques stockees en base.

    Query Parameters:
    - category: Filtrer par categorie (storage, rag, security, general)

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)

        if category:
            configs_dict = await config_service.get_by_category(category)
            configs = [
                {
                    "id": 0,
                    "key": key,
                    "value": value,
                    "raw_value": str(value),
                    "value_type": "string",
                    "category": category,
                    "description": None,
                    "is_sensitive": False,
                    "updated_at": None
                }
                for key, value in configs_dict.items()
            ]
            categories = [category]
        else:
            configs = await config_service.get_all()
            categories = await config_service.get_categories()

        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="GET", status="200"
        ).inc()

        return DynamicConfigListResponse(configs=configs, categories=categories)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting dynamic configs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dynamic/{key:path}", response_model=DynamicConfigResponse)
async def get_dynamic_config(
    key: str,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recupere une configuration dynamique par sa cle.

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)
        configs = await config_service.get_all()

        config = next((c for c in configs if c["key"] == key), None)
        if not config:
            raise HTTPException(status_code=404, detail=f"Config key not found: {key}")

        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="GET", status="200"
        ).inc()

        return config

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting dynamic config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/dynamic/{key:path}", response_model=DynamicConfigResponse)
async def update_dynamic_config(
    key: str,
    config_data: DynamicConfigUpdateRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met a jour une configuration dynamique.

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)

        # Recuperer l'ancienne valeur pour l'audit
        old_value = await config_service.get(key)

        success = await config_service.set(
            key=key,
            value=config_data.value,
            updated_by=admin_user.id
        )

        if not success:
            raise HTTPException(status_code=404, detail=f"Config key not found: {key}")

        # Recuperer la nouvelle config
        configs = await config_service.get_all()
        config = next((c for c in configs if c["key"] == key), None)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_key': key,
                'old_value': str(old_value)[:100] if old_value else None,
                'new_value': str(config_data.value)[:100]
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="PATCH", status="200"
        ).inc()

        return config

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating dynamic config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dynamic", response_model=DynamicConfigResponse, status_code=201)
async def create_dynamic_config(
    config_data: DynamicConfigCreateRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cree une nouvelle configuration dynamique.

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)

        new_config = await config_service.create(
            key=config_data.key,
            value=config_data.value,
            value_type=config_data.value_type,
            category=config_data.category,
            description=config_data.description,
            is_sensitive=config_data.is_sensitive,
            updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_created',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_key': config_data.key,
                'category': config_data.category,
                'value_type': config_data.value_type
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="POST", status="201"
        ).inc()

        return {
            "id": new_config.id,
            "key": new_config.key,
            "value": config_service._convert_value(new_config.value, new_config.value_type),
            "raw_value": new_config.value,
            "value_type": new_config.value_type,
            "category": new_config.category,
            "description": new_config.description,
            "is_sensitive": new_config.is_sensitive,
            "updated_at": new_config.updated_at.isoformat() if new_config.updated_at else None
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="POST", status="500"
        ).inc()
        logger.error(f"Error creating dynamic config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/dynamic/{key:path}", status_code=204)
async def delete_dynamic_config(
    key: str,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime une configuration dynamique.

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)

        success = await config_service.delete(key)

        if not success:
            raise HTTPException(status_code=404, detail=f"Config key not found: {key}")

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_deleted',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={'config_key': key},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="DELETE", status="204"
        ).inc()

        from starlette.responses import Response
        return Response(status_code=204)

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/config/dynamic", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error deleting dynamic config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONFIGURATION STORAGE (raccourcis pour les parametres de stockage)
# =============================================================================

@router.get("/storage", response_model=StorageConfigResponse)
async def get_storage_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recupere la configuration de stockage.

    Includes:
    - Backend (local, s3)
    - Chemin local
    - Configuration S3
    - Types MIME autorises
    - Extensions bloquees
    - Taille max de fichier
    - Quota par defaut

    Requires: Admin role
    """
    from app.common.utils.crypto import is_encrypted

    try:
        config_service = SystemConfigService(db)

        # Provider config
        backend = await config_service.get("storage.backend", "local")
        local_path = await config_service.get("storage.local_path", "/data/uploads")

        # S3 config
        s3_bucket = await config_service.get("storage.s3_bucket", None)
        s3_region = await config_service.get("storage.s3_region", None)
        s3_endpoint = await config_service.get("storage.s3_endpoint", None)
        s3_access_key = await config_service.get("storage.s3_access_key", None)
        s3_secret_key = await config_service.get("storage.s3_secret_key", None)

        # Limites
        allowed_mime_types = await config_service.get_allowed_mime_types()
        blocked_extensions = await config_service.get_blocked_extensions()
        max_file_size_mb = await config_service.get("storage.max_file_size_mb", 50)
        default_quota_mb = await config_service.get("storage.default_quota_mb", 100)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/storage", method="GET", status="200"
        ).inc()

        return StorageConfigResponse(
            backend=backend,
            local_path=local_path,
            s3_bucket=s3_bucket,
            s3_region=s3_region,
            s3_endpoint=s3_endpoint,
            s3_access_key_configured=bool(s3_access_key and is_encrypted(s3_access_key)),
            s3_secret_key_configured=bool(s3_secret_key and is_encrypted(s3_secret_key)),
            allowed_mime_types=allowed_mime_types,
            blocked_extensions=blocked_extensions,
            max_file_size_mb=int(max_file_size_mb),
            default_quota_mb=int(default_quota_mb)
        )

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/storage", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting storage config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/storage", response_model=StorageConfigResponse)
async def update_storage_config(
    config_data: StorageConfigUpdateRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met a jour la configuration de stockage.

    Body (tous optionnels):
    - backend: Backend de stockage (local, s3)
    - local_path: Chemin local pour le stockage
    - s3_bucket, s3_region, s3_endpoint: Config S3
    - s3_access_key, s3_secret_key: Credentials S3 (chiffres)
    - allowed_mime_types: Liste des types MIME autorises
    - blocked_extensions: Liste des extensions bloquees
    - max_file_size_mb: Taille max par fichier (1-500 Mo)
    - default_quota_mb: Quota par defaut (1-10240 Mo)

    Requires: Admin role
    """
    from app.common.utils.crypto import encrypt_secret, is_encrypted

    try:
        config_service = SystemConfigService(db)
        updated_keys = []

        # Provider config
        if config_data.backend is not None:
            await config_service.set(
                "storage.backend",
                config_data.backend,
                updated_by=admin_user.id
            )
            updated_keys.append("backend")

        if config_data.local_path is not None:
            await config_service.set(
                "storage.local_path",
                config_data.local_path,
                updated_by=admin_user.id
            )
            updated_keys.append("local_path")

        # S3 config
        if config_data.s3_bucket is not None:
            await config_service.set(
                "storage.s3_bucket",
                config_data.s3_bucket,
                updated_by=admin_user.id
            )
            updated_keys.append("s3_bucket")

        if config_data.s3_region is not None:
            await config_service.set(
                "storage.s3_region",
                config_data.s3_region,
                updated_by=admin_user.id
            )
            updated_keys.append("s3_region")

        if config_data.s3_endpoint is not None:
            await config_service.set(
                "storage.s3_endpoint",
                config_data.s3_endpoint,
                updated_by=admin_user.id
            )
            updated_keys.append("s3_endpoint")

        # S3 credentials (chiffres)
        if config_data.s3_access_key is not None:
            encrypted_key = encrypt_secret(config_data.s3_access_key)
            await config_service.set(
                "storage.s3_access_key",
                encrypted_key,
                updated_by=admin_user.id,
                is_sensitive=True
            )
            updated_keys.append("s3_access_key")

        if config_data.s3_secret_key is not None:
            encrypted_secret = encrypt_secret(config_data.s3_secret_key)
            await config_service.set(
                "storage.s3_secret_key",
                encrypted_secret,
                updated_by=admin_user.id,
                is_sensitive=True
            )
            updated_keys.append("s3_secret_key")

        # Limites
        if config_data.allowed_mime_types is not None:
            await config_service.set(
                "storage.allowed_mime_types",
                config_data.allowed_mime_types,
                updated_by=admin_user.id
            )
            updated_keys.append("allowed_mime_types")

        if config_data.blocked_extensions is not None:
            await config_service.set(
                "storage.blocked_extensions",
                config_data.blocked_extensions,
                updated_by=admin_user.id
            )
            updated_keys.append("blocked_extensions")

        if config_data.max_file_size_mb is not None:
            await config_service.set(
                "storage.max_file_size_mb",
                config_data.max_file_size_mb,
                updated_by=admin_user.id
            )
            updated_keys.append("max_file_size_mb")

        if config_data.default_quota_mb is not None:
            await config_service.set(
                "storage.default_quota_mb",
                config_data.default_quota_mb,
                updated_by=admin_user.id
            )
            updated_keys.append("default_quota_mb")

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'storage',
                'updated_keys': updated_keys
            },
            request=request,
            username=admin_user.username
        )

        # Recuperer la config mise a jour
        backend = await config_service.get("storage.backend", "local")
        local_path = await config_service.get("storage.local_path", "/data/uploads")
        s3_bucket = await config_service.get("storage.s3_bucket", None)
        s3_region = await config_service.get("storage.s3_region", None)
        s3_endpoint = await config_service.get("storage.s3_endpoint", None)
        s3_access_key = await config_service.get("storage.s3_access_key", None)
        s3_secret_key = await config_service.get("storage.s3_secret_key", None)
        allowed_mime_types = await config_service.get_allowed_mime_types()
        blocked_extensions = await config_service.get_blocked_extensions()
        max_file_size_mb = await config_service.get("storage.max_file_size_mb", 50)
        default_quota_mb = await config_service.get("storage.default_quota_mb", 100)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/storage", method="PATCH", status="200"
        ).inc()

        return StorageConfigResponse(
            backend=backend,
            local_path=local_path,
            s3_bucket=s3_bucket,
            s3_region=s3_region,
            s3_endpoint=s3_endpoint,
            s3_access_key_configured=bool(s3_access_key and is_encrypted(s3_access_key)),
            s3_secret_key_configured=bool(s3_secret_key and is_encrypted(s3_secret_key)),
            allowed_mime_types=allowed_mime_types,
            blocked_extensions=blocked_extensions,
            max_file_size_mb=int(max_file_size_mb),
            default_quota_mb=int(default_quota_mb)
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/config/storage", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating storage config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TYPES DE FICHIERS SUPPORTES
# =============================================================================

@router.get("/file-types", response_model=FileTypesListResponse)
async def get_file_types(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recupere la liste des types de fichiers supportes avec leur statut.

    Retourne tous les types de fichiers que le systeme peut parser,
    avec indication de ceux qui sont actuellement actives.

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)

        # Recuperer les types actives depuis la config
        enabled_types = await config_service.get("storage.enabled_file_types", None)

        # Si pas de config, utiliser les types actives par defaut
        if enabled_types is None:
            enabled_types = [
                key for key, info in FILE_TYPES_REGISTRY.items()
                if info.enabled_by_default
            ]

        # Construire la liste avec le statut
        all_types = get_all_file_types()
        file_types = [
            FileTypeResponse(
                id=ft["id"],
                extension=ft["extension"],
                mime_type=ft["mime_type"],
                name=ft["name"],
                description=ft["description"],
                parser=ft["parser"],
                category=ft["category"],
                enabled=ft["id"] in enabled_types
            )
            for ft in all_types
        ]

        REQUEST_COUNT.labels(
            endpoint="/admin/config/file-types", method="GET", status="200"
        ).inc()

        return FileTypesListResponse(
            file_types=file_types,
            categories=["documents", "images", "data"]
        )

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/file-types", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting file types: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/file-types", response_model=FileTypesListResponse)
async def update_file_types(
    data: FileTypesUpdateRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met a jour les types de fichiers actives.

    Body:
    - enabled_types: Liste des IDs de types a activer (ex: ['pdf', 'docx', 'txt'])

    Seuls les types dans cette liste seront acceptes a l'upload.
    Les types MIME et extensions seront automatiquement synchronises.

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)

        # Valider que tous les types existent
        invalid_types = [t for t in data.enabled_types if t not in FILE_TYPES_REGISTRY]
        if invalid_types:
            raise HTTPException(
                status_code=400,
                detail=f"Types de fichiers inconnus: {', '.join(invalid_types)}"
            )

        # Recuperer les anciens types pour l'audit
        old_enabled = await config_service.get("storage.enabled_file_types", [])

        # Sauvegarder les nouveaux types actives
        await config_service.set(
            "storage.enabled_file_types",
            data.enabled_types,
            updated_by=admin_user.id
        )

        # Calculer et sauvegarder les types MIME correspondants
        enabled_mime_types = get_enabled_mime_types(data.enabled_types)
        await config_service.set(
            "storage.allowed_mime_types",
            enabled_mime_types,
            updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'file_types',
                'old_enabled': old_enabled,
                'new_enabled': data.enabled_types,
                'mime_types_count': len(enabled_mime_types)
            },
            request=request,
            username=admin_user.username
        )

        # Construire la reponse
        all_types = get_all_file_types()
        file_types = [
            FileTypeResponse(
                id=ft["id"],
                extension=ft["extension"],
                mime_type=ft["mime_type"],
                name=ft["name"],
                description=ft["description"],
                parser=ft["parser"],
                category=ft["category"],
                enabled=ft["id"] in data.enabled_types
            )
            for ft in all_types
        ]

        REQUEST_COUNT.labels(
            endpoint="/admin/config/file-types", method="PATCH", status="200"
        ).inc()

        return FileTypesListResponse(
            file_types=file_types,
            categories=["documents", "images", "data"]
        )

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        REQUEST_COUNT.labels(
            endpoint="/admin/config/file-types", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating file types: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# MODELES LLM (Unifies - Ollama et llama.cpp)
# =============================================================================

@router.get("/models", response_model=ModelsListResponse)
async def list_models(
    provider: Optional[str] = Query(
        None,
        description="Provider à interroger (ollama ou llamacpp). Si non spécifié, utilise le provider actif."
    ),
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Liste les modèles LLM disponibles pour un provider.

    Query Parameters:
    - provider: "ollama" ou "llamacpp" (optionnel, défaut = provider actif)

    Pour Ollama : interroge l'API /api/tags
    Pour llama.cpp : liste les fichiers GGUF dans models/gguf/

    Retourne la liste des modèles disponibles avec leurs métadonnées
    et indique les modèles actuellement configurés.

    Requires: Admin role
    """
    try:
        # Valider le provider si spécifié
        if provider and provider not in ("ollama", "llamacpp"):
            raise HTTPException(
                status_code=400,
                detail=f"Provider inconnu: {provider}. Valeurs acceptées: ollama, llamacpp"
            )

        result = await ConfigService.list_models_for_provider(db, provider)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/models", method="GET", status="200"
        ).inc()

        return result

    except HTTPException:
        raise
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models", method="GET", status="500"
        ).inc()
        logger.error(f"Error listing models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint de compatibilité pour l'ancien format Ollama
@router.get("/models/ollama", response_model=OllamaModelsListResponse)
async def list_ollama_models_legacy(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Liste les modèles Ollama (endpoint de compatibilité).

    Utiliser GET /models?provider=ollama de préférence.

    Requires: Admin role
    """
    from app.core.config import settings

    try:
        result = await ConfigService.list_ollama_models(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/ollama", method="GET", status="200"
        ).inc()

        return OllamaModelsListResponse(
            models=[
                OllamaModelInfo(
                    name=m.name,
                    size=m.size,
                    digest=m.digest,
                    modified_at=m.modified_at
                )
                for m in result.models
            ],
            current_model=result.current_llm_model
        )

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/ollama", method="GET", status="500"
        ).inc()
        logger.error(f"Error listing Ollama models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/llamacpp", response_model=ModelsListResponse)
async def list_llamacpp_models(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Liste les modèles GGUF disponibles pour llama.cpp.

    Scanne le dossier models/gguf/ pour les fichiers .gguf.

    Requires: Admin role
    """
    try:
        result = await ConfigService.list_llamacpp_models(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/llamacpp", method="GET", status="200"
        ).inc()

        return result

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/llamacpp", method="GET", status="500"
        ).inc()
        logger.error(f"Error listing llama.cpp models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/llamacpp/download")
async def download_gguf_model(
    data: GGUFDownloadRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Télécharge un modèle GGUF depuis une URL.

    Le téléchargement est fait en streaming (SSE) pour permettre
    d'afficher la progression en temps réel.

    Body:
    - url: URL directe vers le fichier .gguf (ex: Hugging Face)
    - filename: Nom du fichier de destination (optionnel)

    Exemple URL Hugging Face:
    https://huggingface.co/TheBloke/Mistral-7B-v0.1-GGUF/resolve/main/mistral-7b-v0.1.Q4_K_M.gguf

    Requires: Admin role
    """
    # Log de l'action
    logger.info(f"GGUF download requested: {data.url} -> {data.filename or 'auto'}")

    REQUEST_COUNT.labels(
        endpoint="/admin/config/models/llamacpp/download", method="POST", status="200"
    ).inc()

    return StreamingResponse(
        ConfigService.download_gguf_stream(data.url, data.filename),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ============================================================================
# TELECHARGEMENT GGUF AVEC POLLING (alternative à SSE pour navigateurs)
# ============================================================================

@router.post("/models/llamacpp/download/start")
async def start_gguf_download(
    data: GGUFDownloadRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Démarre un téléchargement GGUF en arrière-plan et retourne un task_id.
    Utiliser GET /models/llamacpp/download/{task_id} pour suivre la progression.
    """
    if not data.url:
        raise HTTPException(status_code=400, detail="URL requise")

    log_config_change(
        admin_id=str(admin_user.id),
        config_key="models.gguf.download",
        old_value=None,
        new_value=f"{data.url} -> {data.filename or 'auto'}"
    )

    logger.info(f"GGUF download started: {data.url} -> {data.filename or 'auto'}")
    task_id = ConfigService.start_gguf_download(data.url, data.filename)

    return {"task_id": task_id, "message": "Téléchargement démarré"}


@router.get("/models/llamacpp/download/{task_id}")
async def get_gguf_download_progress(
    task_id: str,
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Retourne la progression d'un téléchargement GGUF en cours.
    Polling: appeler cet endpoint toutes les 500ms jusqu'à status='complete' ou 'error'.
    """
    progress = ConfigService.get_download_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")

    return progress


@router.post("/models/llamacpp/download/{task_id}/cancel")
async def cancel_gguf_download(
    task_id: str,
    admin_user: User = Depends(get_current_admin_user)
):
    """Annule un téléchargement GGUF en cours."""
    success = ConfigService.cancel_download(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tâche non trouvée ou déjà terminée")
    return {"message": "Annulation demandée", "task_id": task_id}


@router.delete("/models/llamacpp/download/{task_id}")
async def cleanup_gguf_download(
    task_id: str,
    admin_user: User = Depends(get_current_admin_user)
):
    """Supprime une tâche de téléchargement terminée."""
    ConfigService.cleanup_download_task(task_id)
    return {"message": "Tâche supprimée"}


@router.delete("/models/llamacpp/{filename:path}", response_model=ModelDeleteResponse)
async def delete_gguf_model(
    filename: str,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime un modèle GGUF du dossier models/gguf/.

    Path Parameters:
    - filename: Chemin relatif du fichier .gguf à supprimer (ex: "chat/model.gguf")

    Requires: Admin role
    """
    try:
        result = await ConfigService.delete_gguf_model(filename)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='model.llamacpp.deleted',
            user_id=admin_user.id,
            resource_type_name='model',
            resource_id=None,
            details={'provider': 'llamacpp', 'filename': filename},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/llamacpp", method="DELETE", status="200"
        ).inc()

        return ModelDeleteResponse(**result)

    except FileNotFoundError as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/llamacpp", method="DELETE", status="404"
        ).inc()
        raise HTTPException(status_code=404, detail=str(e))

    except ValueError as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/llamacpp", method="DELETE", status="400"
        ).inc()
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models/llamacpp", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error deleting GGUF model {filename}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# OLLAMA PULL (Polling API)
# =============================================================================

@router.post("/models/ollama/pull/start")
async def start_ollama_pull(
    data: OllamaModelPullRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Démarre un pull Ollama en arrière-plan et retourne un task_id.
    Utiliser GET /models/ollama/pull/{task_id} pour suivre la progression.
    """
    if not data.model_name:
        raise HTTPException(status_code=400, detail="Nom de modèle requis")

    log_config_change(
        admin_id=str(admin_user.id),
        config_key="models.ollama.pull",
        old_value=None,
        new_value=data.model_name
    )

    logger.info(f"Ollama pull started: {data.model_name}")
    task_id = ConfigService.start_ollama_pull(data.model_name)

    return {"task_id": task_id, "message": "Pull démarré"}


@router.get("/models/ollama/pull/{task_id}")
async def get_ollama_pull_progress(
    task_id: str,
    admin_user: User = Depends(get_current_admin_user)
):
    """Retourne la progression d'un pull Ollama."""
    progress = ConfigService.get_ollama_pull_progress(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    return progress


@router.post("/models/ollama/pull/{task_id}/cancel")
async def cancel_ollama_pull(
    task_id: str,
    admin_user: User = Depends(get_current_admin_user)
):
    """Annule un pull Ollama en cours."""
    success = ConfigService.cancel_ollama_pull(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="Tâche non trouvée ou déjà terminée")
    return {"message": "Annulation demandée", "task_id": task_id}


@router.delete("/models/ollama/pull/{task_id}")
async def cleanup_ollama_pull(
    task_id: str,
    admin_user: User = Depends(get_current_admin_user)
):
    """Supprime une tâche de pull Ollama terminée."""
    ConfigService.cleanup_ollama_pull_task(task_id)
    return {"message": "Tâche supprimée"}


@router.post("/models/pull")
async def pull_ollama_model(
    data: OllamaModelPullRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Telecharge un modele LLM depuis le registre Ollama.

    Le telechargement est fait en streaming (SSE) pour permettre
    d'afficher la progression en temps reel.

    Body:
    - model_name: Nom du modele a telecharger (ex: mistral, llama3, phi3)

    Requires: Admin role
    """
    import json as json_lib
    from app.core.config import settings

    model_name = data.model_name

    def format_size(size_bytes):
        """Formate une taille en bytes en format lisible."""
        if not size_bytes:
            return "0 B"
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"

    async def stream_progress():
        """Generateur SSE pour le streaming de progression."""
        import asyncio

        download_complete = False
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{settings.ollama_url}/api/pull",
                    json={"name": model_name, "stream": True}
                ) as response:
                    if response.status_code != 200:
                        error_msg = f"Ollama returned status {response.status_code}"
                        yield f'data: {{"event": "error", "error": "{error_msg}"}}\n\n'
                        return

                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue

                        try:
                            ollama_data = json_lib.loads(line)
                            status = ollama_data.get("status", "")

                            # Calculer la progression si disponible
                            total = ollama_data.get("total", 0)
                            completed = ollama_data.get("completed", 0)
                            progress = 0
                            if total > 0:
                                progress = int((completed / total) * 100)

                            # Traduire les statuts Ollama
                            status_map = {
                                "pulling manifest": "Recuperation du manifest...",
                                "verifying sha256 digest": "Verification...",
                                "writing manifest": "Ecriture du manifest...",
                                "removing any unused layers": "Nettoyage...",
                                "success": "Telechargement termine !"
                            }

                            message = status_map.get(status, status)
                            if "downloading" in status.lower():
                                message = f"Telechargement... ({format_size(completed)}/{format_size(total)})"

                            # Format attendu par streamWithProgress
                            event_data = {
                                "progress": progress,
                                "status": "downloading" if "downloading" in status.lower() else "processing",
                                "message": message,
                                "current": completed,
                                "total": total
                            }

                            # Detecter la fin
                            if status == "success":
                                download_complete = True
                                event_data["event"] = "complete"
                                event_data["success"] = True
                                event_data["message"] = f"Modele {model_name} telecharge avec succes"

                            yield f"data: {json_lib.dumps(event_data)}\n\n"

                        except json_lib.JSONDecodeError:
                            continue

            # Audit log apres succes
            if download_complete:
                try:
                    await AuditService.log_action(
                        db=db,
                        action_name='model_downloaded',
                        user_id=admin_user.id,
                        resource_type_name='config',
                        resource_id=None,
                        details={'model_name': model_name},
                        request=request,
                        username=admin_user.username
                    )
                except Exception as audit_err:
                    logger.warning(f"Failed to log audit: {audit_err}")

        except asyncio.CancelledError:
            # Client disconnected (page refresh, cancel button, etc.)
            logger.info(f"Model pull cancelled by client for {model_name}")
            return
        except httpx.ConnectError as e:
            logger.error(f"Cannot connect to Ollama: {e}")
            yield f'data: {{"event": "error", "error": "Impossible de contacter Ollama"}}\n\n'
        except GeneratorExit:
            # Client disconnected
            logger.info(f"Client disconnected during model pull for {model_name}")
            return
        except Exception as e:
            logger.error(f"Error pulling model {model_name}: {e}")
            yield f'data: {{"event": "error", "error": "{str(e)}"}}\n\n'

    REQUEST_COUNT.labels(
        endpoint="/admin/config/models/pull", method="POST", status="200"
    ).inc()

    return StreamingResponse(
        stream_progress(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.delete("/models/{model_name}")
async def delete_ollama_model(
    model_name: str,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Supprime un modele LLM d'Ollama.

    Permet de nettoyer les telechargements partiels ou de supprimer
    un modele inutilise pour liberer de l'espace disque.

    Path Parameters:
    - model_name: Nom du modele a supprimer (ex: mistral, llama3:8b)

    Requires: Admin role
    """
    from app.core.config import settings

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout) as client:
            # httpx.delete() n'accepte pas json=, utiliser request() à la place
            response = await client.request(
                "DELETE",
                f"{settings.ollama_url}/api/delete",
                json={"name": model_name}
            )

            if response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Modele '{model_name}' non trouve")

            response.raise_for_status()

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='model_deleted',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={'model_name': model_name},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/models", method="DELETE", status="200"
        ).inc()

        return {"success": True, "message": f"Modele '{model_name}' supprime"}

    except HTTPException:
        raise
    except httpx.HTTPError as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models", method="DELETE", status="503"
        ).inc()
        logger.error(f"Error deleting model from Ollama: {e}")
        raise HTTPException(status_code=503, detail="Impossible de contacter Ollama")
    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/models", method="DELETE", status="500"
        ).inc()
        logger.error(f"Error deleting model {model_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONFIGURATION SPEECH (Speech-to-Text)
# =============================================================================

@router.get("/speech", response_model=SpeechConfigRead)
async def get_speech_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recupere la configuration Speech-to-Text.

    Retourne les parametres de configuration du service de transcription vocale
    ainsi que des informations sur le modele actuellement charge.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_speech_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/speech", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/speech", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting speech config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/speech", response_model=SpeechConfigRead)
async def update_speech_config(
    config: SpeechConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met a jour la configuration Speech-to-Text.

    Note: Le changement de modele Whisper necessite un redemarrage
    du container pour prendre effet.

    Body:
    - enabled: Activer/desactiver le service globalement
    - model: Modele Whisper (tiny/base/small/medium)
    - default_language: Langue par defaut (fr/en/...)
    - max_duration: Duree max audio en secondes
    - timeout: Timeout transcription en secondes

    Requires: Admin role
    """
    try:
        updated = await ConfigService.update_speech_config(
            db, config, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'speech',
                'changes': config.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/speech", method="PATCH", status="200"
        ).inc()

        return updated

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/speech", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating speech config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONFIGURATION SOURCES INDEXATION
# =============================================================================

@router.get("/sources-indexation", response_model=SourcesIndexationConfigRead)
async def get_sources_indexation_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Recupere la configuration d'indexation des sources externes.

    Retourne les parametres du scheduler de re-indexation automatique,
    les seuils de fraicheur et la configuration de retention des logs.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_sources_indexation_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/sources-indexation", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/sources-indexation", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting sources indexation config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/sources-indexation", response_model=SourcesIndexationConfigRead)
async def update_sources_indexation_config(
    config: SourcesIndexationConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met a jour la configuration d'indexation des sources externes.

    Body (tous optionnels):
    - scheduler_enabled: Activer/desactiver le scheduler automatique
    - scheduler_check_interval_minutes: Intervalle de verification (1-1440 min)
    - scheduler_cleanup_docs_interval_hours: Intervalle nettoyage docs (1-168 h)
    - scheduler_cleanup_logs_interval_days: Intervalle nettoyage logs (1-30 jours)
    - log_retention_days: Retention des logs (1-365 jours)
    - freshness_warning_percent: Seuil avertissement (0-100%)
    - freshness_expired_percent: Seuil expiration (0-100%)

    Note: Les modifications des intervalles du scheduler necessitent
    un redemarrage de l'application pour prendre effet.

    Requires: Admin role
    """
    try:
        updated = await ConfigService.update_sources_indexation_config(
            db, config, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'sources_indexation',
                'changes': config.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/sources-indexation", method="PATCH", status="200"
        ).inc()

        return updated

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/sources-indexation", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating sources indexation config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONFIGURATION CHAT (MÉMOIRE CONVERSATIONNELLE)
# =============================================================================

@router.get("/chat", response_model=ChatConfigRead)
async def get_chat_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration chat (mémoire conversationnelle).

    Retourne les 9 paramètres de mémoire :
    - Historique (activation, tours max, budget tokens)
    - Détection de sujet (activation, seuil)
    - Résumé automatique (activation, seuil de déclenchement)
    - Réinjection RAG et contextualisation
    """
    try:
        config = await ConfigService.get_chat_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/chat", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/chat", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting chat config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/chat", response_model=ChatConfigRead)
async def update_chat_config(
    config: ChatConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration chat (mémoire conversationnelle).

    Les changements sont pris en compte immédiatement par le service de chat
    (lecture dynamique, pas de cache).
    """
    try:
        updated = await ConfigService.update_chat_config(
            db, config, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'chat',
                'changes': config.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/chat", method="PATCH", status="200"
        ).inc()

        return updated

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/chat", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating chat config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONFIGURATION DEBUG
# =============================================================================

@router.get("/debug", response_model=DebugConfigRead)
async def get_debug_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration debug.

    Retourne l'état des fonctionnalités debug :
    - Logging verbeux (runtime)
    - Headers de timing (runtime)
    - Endpoints debug (persisté en BDD)

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_debug_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/debug", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/debug", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting debug config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/debug", response_model=DebugConfigRead)
async def update_debug_config(
    config_data: DebugConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration debug.

    Body (tous optionnels) :
    - verbose_logging: Activer/désactiver le logging verbeux (runtime)
    - timing_headers_enabled: Activer/désactiver les headers X-Debug-* (runtime)
    - debug_endpoints_enabled: Activer/désactiver les endpoints /auth/debug/* (persisté)

    Note: verbose_logging et timing_headers sont perdus au redémarrage.
    debug_endpoints_enabled est persisté en base de données.

    Requires: Admin role
    """
    try:
        # Récupérer l'ancienne config pour l'audit
        old_config = await ConfigService.get_debug_config(db)

        new_config = await ConfigService.update_debug_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'debug',
                'old_values': old_config.model_dump(),
                'new_values': config_data.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/debug", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/debug", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating debug config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONFIGURATION LOGGING STRUCTURÉ
# =============================================================================

@router.get("/logging", response_model=LoggingConfigRead)
async def get_logging_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration logging structuré.

    Retourne les niveaux par catégorie (5), l'état de la persistance BDD
    et les durées de rétention par catégorie.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_logging_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/logging", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/logging", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting logging config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/logging", response_model=LoggingConfigRead)
async def update_logging_config(
    config_data: LoggingConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration logging structuré.

    Body (tous optionnels) :
    - log_level_technical/access/audit/security/infra : Niveau par catégorie
    - log_db_enabled : Persistance des logs en BDD
    - log_retention_*_days : Rétention par catégorie (en jours)

    Les niveaux sont appliqués immédiatement au handler BDD.

    Requires: Admin role
    """
    try:
        old_config = await ConfigService.get_logging_config(db)

        new_config = await ConfigService.update_logging_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'logging',
                'old_values': old_config.model_dump(),
                'new_values': config_data.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/logging", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/logging", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating logging config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# NOTIFICATIONS
# =============================================================================

@router.get("/notifications", response_model=NotificationConfigRead)
async def get_notification_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration des canaux de notification.

    Retourne l'état et les paramètres de chaque canal (email, Slack, webhook).

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_notification_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/notifications", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/notifications", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting notification config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/notifications", response_model=NotificationConfigRead)
async def update_notification_config(
    config_data: NotificationConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration des canaux de notification.

    Body (tous optionnels) :
    - email_*: Configuration SMTP
    - slack_*: Configuration Slack webhook
    - webhook_*: Configuration webhook générique

    Requires: Admin role
    """
    try:
        old_config = await ConfigService.get_notification_config(db)

        new_config = await ConfigService.update_notification_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log (masquer les valeurs sensibles)
        update_values = config_data.model_dump(exclude_unset=True)
        safe_values = {
            k: "***" if "password" in k or "secret" in k else v
            for k, v in update_values.items()
        }

        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'notifications',
                'updated_fields': list(safe_values.keys()),
                'new_values': safe_values,
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/notifications", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/notifications", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating notification config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/notifications/test")
async def test_notification_channel(
    data: NotificationTestRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Envoie une notification de test sur le canal spécifié.

    Body :
    - channel: "email", "slack" ou "webhook"

    Requires: Admin role
    """
    from app.common.utils.notifier import NotificationService

    try:
        success = await NotificationService.test_channel(db, data.channel)

        await AuditService.log_action(
            db=db,
            action_name='notification_tested',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'channel': data.channel,
                'success': success,
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/notifications/test", method="POST", status="200"
        ).inc()

        return {"channel": data.channel, "success": success}

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/notifications/test", method="POST", status="500"
        ).inc()
        logger.error(f"Error testing notification channel '{data.channel}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# SMTP (Email Service)
# =============================================================================

@router.get("/smtp", response_model=SmtpConfigRead)
async def get_smtp_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration SMTP pour l'envoi d'emails.

    Les mots de passe et clés API ne sont pas retournés,
    seul leur état de configuration est indiqué.

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_smtp_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/smtp", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/smtp", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting SMTP config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/smtp", response_model=SmtpConfigRead)
async def update_smtp_config(
    config_data: SmtpConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration SMTP.

    Les secrets (password, API keys) sont chiffrés avant stockage.

    Body (tous optionnels) :
    - provider: "smtp", "sendgrid" ou "mailjet"
    - enabled: Activer/désactiver le service email
    - host, port, username, password: Configuration SMTP
    - use_tls, use_ssl: Options de chiffrement
    - from_email, from_name, reply_to: Paramètres expéditeur
    - sendgrid_api_key: Clé API SendGrid
    - mailjet_api_key, mailjet_secret_key: Clés Mailjet

    Requires: Admin role
    """
    try:
        new_config = await ConfigService.update_smtp_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log (masquer les secrets)
        update_values = config_data.model_dump(exclude_unset=True)
        safe_values = {
            k: "***" if "password" in k or "key" in k else v
            for k, v in update_values.items()
        }

        await AuditService.log_action(
            db=db,
            action_name='config_updated',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'config_type': 'smtp',
                'updated_fields': list(safe_values.keys()),
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/smtp", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/smtp", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating SMTP config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/smtp/test", response_model=SmtpTestResponse)
async def test_smtp_connection(
    data: SmtpTestRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Teste la configuration SMTP en envoyant un email de test.

    Body (optionnel) :
    - recipient_email: Email destinataire (défaut: email de l'admin connecté)

    Requires: Admin role
    """
    try:
        result = await ConfigService.test_smtp_connection(
            db,
            recipient_email=data.recipient_email or "",
            admin_user_email=admin_user.email,
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='smtp_tested',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'provider': result.provider,
                'recipient': result.recipient,
                'success': result.success,
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/smtp/test", method="POST", status="200"
        ).inc()

        return result

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/smtp/test", method="POST", status="500"
        ).inc()
        logger.error(f"Error testing SMTP: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# CONTROLE LLM PROVIDER (Start/Stop/Status)
# =============================================================================

@router.post("/llm/start", response_model=LLMControlResponse)
async def start_llm_provider(
    data: LLMStartRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Démarre le provider LLM llama.cpp.

    Note: Cette opération n'est disponible que pour llama.cpp.
    Ollama est géré par Docker et ne peut pas être démarré depuis l'API.

    Body (tous optionnels):
    - model: Modèle GGUF à charger (chemin relatif dans models/gguf/)
    - port: Port d'écoute (défaut: 8085)
    - ctx_size: Taille du contexte (512-131072)
    - gpu_layers: Nombre de layers GPU (0-999)
    - embedding: Activer le mode embedding

    Requires: Admin role
    """
    try:
        result = await ConfigService.start_llamacpp(
            db=db,
            model=data.model,
            port=data.port,
            ctx_size=data.ctx_size,
            gpu_layers=data.gpu_layers,
            embedding=data.embedding
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='llm.llamacpp.start',
            user_id=admin_user.id,
            resource_type_name='llm',
            resource_id=None,
            details={
                'provider': 'llamacpp',
                'model': data.model,
                'port': data.port,
                'status': result.get('status')
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/start", method="POST", status="200"
        ).inc()

        return LLMControlResponse(**result)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/start", method="POST", status="500"
        ).inc()
        logger.error(f"Error starting LLM provider: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/stop", response_model=LLMControlResponse)
async def stop_llm_provider(
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Arrête le provider LLM llama.cpp.

    Note: Cette opération n'est disponible que pour llama.cpp.
    Ollama est géré par Docker et ne peut pas être arrêté depuis l'API.

    Requires: Admin role
    """
    try:
        result = await ConfigService.stop_llamacpp()

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='llm.llamacpp.stop',
            user_id=admin_user.id,
            resource_type_name='llm',
            resource_id=None,
            details={
                'provider': 'llamacpp',
                'status': result.get('status')
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/stop", method="POST", status="200"
        ).inc()

        return LLMControlResponse(**result)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/stop", method="POST", status="500"
        ).inc()
        logger.error(f"Error stopping LLM provider: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/status", response_model=LLMStatusResponse)
async def get_llm_provider_status(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère le statut détaillé du provider LLM actif.

    Retourne les informations de santé, le modèle chargé,
    et pour llama.cpp, le PID du processus.

    Pour Ollama: statut = "managed" (géré par Docker)
    Pour llama.cpp: statut = "running" ou "stopped"

    Requires: Admin role
    """
    try:
        result = await ConfigService.get_llm_status(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/status", method="GET", status="200"
        ).inc()

        return LLMStatusResponse(**result)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/status", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting LLM status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/health/{provider}")
async def get_provider_health(
    provider: str,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère le statut de santé d'un provider spécifique.

    Permet de checker le health de n'importe quel provider,
    pas seulement celui qui est actif.

    Args:
        provider: "ollama" ou "llamacpp"

    Requires: Admin role
    """
    if provider not in ("ollama", "llamacpp"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider: {provider}. Must be 'ollama' or 'llamacpp'"
        )

    try:
        result = await ConfigService.get_provider_health(db, provider)

        REQUEST_COUNT.labels(
            endpoint=f"/admin/config/llm/health/{provider}", method="GET", status="200"
        ).inc()

        return result

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint=f"/admin/config/llm/health/{provider}", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting provider health: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/llamacpp/params", response_model=LlamaCppParamsRead)
async def get_llamacpp_params(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les paramètres de configuration llama.cpp.

    Retourne les paramètres GPU, contexte, serveur et mémoire
    utilisés lors du démarrage de llama-server.

    Requires: Admin role
    """
    try:
        params = await ConfigService.get_llamacpp_params(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/params", method="GET", status="200"
        ).inc()

        return LlamaCppParamsRead(**params)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/params", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting llama.cpp params: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/llm/llamacpp/params", response_model=LlamaCppParamsRead)
async def update_llamacpp_params(
    params: LlamaCppParamsUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour les paramètres de configuration llama.cpp.

    Note: Les changements nécessitent un redémarrage de llama-server
    pour prendre effet. Utilisez POST /llm/stop puis POST /llm/start.

    Body (tous optionnels):
    - gpu_layers: Couches GPU (0-999, 99 = toutes)
    - ctx_size: Taille du contexte (512-131072)
    - threads: Threads CPU (-1 = auto)
    - batch_size: Taille du batch (1-8192)
    - flash_attn: Flash Attention (on/off/auto)
    - parallel: Slots parallèles (-1 = auto)
    - port: Port d'écoute (1-65535)
    - embedding_mode: Mode embedding uniquement
    - metrics_enabled: Métriques Prometheus
    - mlock: Verrouiller en RAM
    - mmap: Memory-map du modèle

    Requires: Admin role
    """
    try:
        updated = await ConfigService.update_llamacpp_params(
            db, params, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config.llamacpp.params.update',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'changes': params.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/params", method="PATCH", status="200"
        ).inc()

        return LlamaCppParamsRead(**updated)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/params", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating llama.cpp params: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/llamacpp/restart")
async def restart_llamacpp_server(
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Redémarre llama-server avec la configuration actuelle de la BDD.

    Le serveur est arrêté puis relancé avec les paramètres depuis system_configs:
    - llm.llamacpp.llm_model (modèle GGUF)
    - llm.llamacpp.ctx_size
    - llm.llamacpp.gpu_layers
    - llm.llamacpp.parallel
    - llm.llamacpp.embedding_mode
    - etc.

    Retourne:
        success: True si restart réussi
        message: Message descriptif
        server_status: État du serveur après restart

    Requires: Admin role
    """
    try:
        result = await ConfigService.restart_llamacpp_server(db)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='llm.llamacpp.restart',
            user_id=admin_user.id,
            resource_type_name='llm',
            resource_id=None,
            details={
                'provider': 'llamacpp',
                'success': result.get('success'),
                'status': result.get('status')
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/restart", method="POST", status="200"
        ).inc()

        return result

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/restart", method="POST", status="500"
        ).inc()
        logger.error(f"Error restarting llama-server: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/llamacpp/sync-status")
async def get_llamacpp_sync_status(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Vérifie si la config BDD est synchronisée avec le serveur llama-server.

    Compare la configuration stockée en BDD (system_configs) avec celle
    du serveur llama-server en cours d'exécution (via /props).

    Retourne:
        in_sync: True si configurations identiques
        restart_required: True si restart nécessaire
        differences: Liste des paramètres différents
        server_running: True si serveur accessible
        db_config: Configuration depuis BDD
        running_config: Configuration du serveur

    Requires: Admin role
    """
    try:
        result = await ConfigService.compare_llamacpp_configs(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/sync-status", method="GET", status="200"
        ).inc()

        return result

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/sync-status", method="GET", status="500"
        ).inc()
        logger.error(f"Error checking llama.cpp sync status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/llamacpp/metrics", response_model=LlamaCppMetricsResponse)
async def get_llamacpp_metrics(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les métriques Prometheus de llama-server.

    Métriques disponibles:
    - prompt_tokens_total: Tokens prompt traités (total)
    - tokens_predicted_total: Tokens générés (total)
    - prompt_tokens_per_second: Débit prompt (tokens/s)
    - predicted_tokens_per_second: Débit génération (tokens/s)
    - requests_processing: Requêtes en cours
    - slots_idle/slots_processing: État des slots

    Requires: Admin role
    """
    try:
        metrics = await ConfigService.get_llamacpp_metrics(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/metrics", method="GET", status="200"
        ).inc()

        return LlamaCppMetricsResponse(**metrics)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/llamacpp/metrics", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting llama.cpp metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# OLLAMA CONFIG
# =============================================================================

@router.get("/llm/ollama/config", response_model=OllamaConfigRead)
async def get_ollama_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère les paramètres de configuration Ollama.

    Ces paramètres sont passés via l'API Ollama à chaque requête:
    - keep_alive: Durée maintien modèle en mémoire (5m, 1h, -1 = infini)
    - num_ctx: Taille du contexte en tokens (512-131072)
    - num_gpu: Couches GPU (0 = CPU only, 999 = toutes)
    - num_parallel: Requêtes parallèles (lecture seule - config serveur)
    - auto_preload: Précharger modèles au démarrage

    Requires: Admin role
    """
    try:
        params = await ConfigService.get_ollama_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/ollama/config", method="GET", status="200"
        ).inc()

        return OllamaConfigRead(**params)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/ollama/config", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting Ollama config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/llm/ollama/config", response_model=OllamaConfigRead)
async def update_ollama_config(
    params: OllamaConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour les paramètres de configuration Ollama.

    Les changements sont appliqués immédiatement à la prochaine requête.
    Le cache de configuration est automatiquement invalidé.

    Body (tous optionnels):
    - keep_alive: Durée maintien (5m, 1h, 30s, -1 = infini)
    - num_ctx: Taille du contexte (512-131072)
    - num_gpu: Couches GPU (0-999)
    - auto_preload: Précharger modèles au démarrage

    Note: num_parallel est une config serveur Ollama (OLLAMA_NUM_PARALLEL),
    non modifiable via l'API.

    Requires: Admin role
    """
    try:
        updated = await ConfigService.update_ollama_config(
            db, params, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config.ollama.params.update',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'changes': params.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/ollama/config", method="PATCH", status="200"
        ).inc()

        return OllamaConfigRead(**updated)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/ollama/config", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating Ollama config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/llm/ollama/preload", response_model=OllamaPreloadResponse)
async def preload_ollama_models(
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Précharge les modèles Ollama en mémoire VRAM.

    Envoie une requête minimale pour charger les modèles LLM et embedding
    configurés avec keep_alive=-1 pour les maintenir en mémoire.

    Utile pour:
    - Éviter le temps de chargement à la première requête utilisateur
    - Maintenir les modèles chauds en production
    - Tester la disponibilité des modèles

    Requires: Admin role
    """
    try:
        result = await ConfigService.preload_ollama_models(db)

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config.ollama.preload',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'llm_model': result.get('llm_model'),
                'embed_model': result.get('embed_model'),
                'success': result.get('success'),
            },
            request=request,
            username=admin_user.username
        )

        status = "200" if result.get("success") else "500"
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/ollama/preload", method="POST", status=status
        ).inc()

        return OllamaPreloadResponse(**result)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/ollama/preload", method="POST", status="500"
        ).inc()
        logger.error(f"Error preloading Ollama models: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/server/hardware", response_model=ServerHardwareResponse)
async def get_server_hardware(
    db: AsyncSession = Depends(get_db),
    admin_user: User = Depends(get_current_admin_user)
):
    """
    Détecte le hardware du serveur (GPU, OS).

    Interroge les providers LLM actifs (Ollama, llama.cpp) pour détecter :
    - VRAM utilisée via Ollama /api/ps
    - GPU layers via llama.cpp /health
    - Apple Silicon (Metal) sur Mac

    Retourne :
    - has_gpu: true si GPU disponible
    - gpu_type: nvidia, amd, apple ou none
    - gpu_name: Nom du GPU détecté
    - gpu_memory: Mémoire GPU (si disponible)
    - recommended_preset: Preset recommandé (mac, gpu8, gpu16, cpu)

    Requires: Admin role
    """
    try:
        result = await ConfigService.get_server_hardware(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/server/hardware", method="GET", status="200"
        ).inc()

        return ServerHardwareResponse(**result)

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/llm/server/hardware", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting server hardware: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# GEO CONFIG
# =============================================================================

@router.get("/geo", response_model=GeoConfigRead)
async def get_geo_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration géographique.

    Retourne:
    - default_country: Code pays par défaut (ISO 3166-1 alpha-2)
    - require_city: Exiger une ville lors de l'inscription
    - allow_change: Permettre le changement de pays/ville

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_geo_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/geo", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/geo", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting geo config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/geo", response_model=GeoConfigRead)
async def update_geo_config(
    config_data: GeoConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration géographique.

    Body (tous optionnels) :
    - default_country: Code pays par défaut (ISO 3166-1 alpha-2)
    - require_city: Exiger une ville lors de l'inscription
    - allow_change: Permettre le changement de pays/ville

    Requires: Admin role
    """
    try:
        new_config = await ConfigService.update_geo_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config.geo.update',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'changes': config_data.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/geo", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/geo", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating geo config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# APPEARANCE CONFIG
# =============================================================================

@router.get("/appearance", response_model=AppearanceConfigRead)
async def get_appearance_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration d'apparence.

    Retourne :
    - global_theme: Thème global (light, dark)

    Requires: Admin role
    """
    try:
        config = await ConfigService.get_appearance_config(db)

        REQUEST_COUNT.labels(
            endpoint="/admin/config/appearance", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/appearance", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting appearance config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/appearance", response_model=AppearanceConfigRead)
async def update_appearance_config(
    config_data: AppearanceConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration d'apparence.

    Body (tous optionnels) :
    - global_theme: Thème global (light ou dark)

    Requires: Admin role
    """
    try:
        new_config = await ConfigService.update_appearance_config(
            db, config_data, updated_by=admin_user.id
        )

        # Audit log
        await AuditService.log_action(
            db=db,
            action_name='config.appearance.update',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={
                'changes': config_data.model_dump(exclude_unset=True)
            },
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/appearance", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/appearance", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating appearance config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# PERFORMANCE CONFIG
# =============================================================================

@router.get("/perf", response_model=PerfConfigRead)
async def get_perf_config(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Récupère la configuration des performances.

    Includes:
    - Cache RAG Config (TTL)
    - Cache Embeddings (taille)
    - Parallélisation (batch size, concurrence)
    - Cache Query Results (taille, TTL)
    - Reranker (timeout, top_k)
    - Modes RAG (fast/full)

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)

        # Charger toutes les clés perf.* et rag.mode.*
        perf_configs = await config_service.get_by_prefix("perf.")
        mode_fast = await config_service.get_by_prefix("rag.mode.fast.")
        mode_full = await config_service.get_by_prefix("rag.mode.full.")

        config = PerfConfigRead(
            # Cache RAG Config
            rag_config_cache_ttl=float(perf_configs.get("perf.rag_config_cache_ttl", 30.0)),
            # Cache Embeddings
            embedding_cache_size=int(perf_configs.get("perf.embedding_cache_size", 1000)),
            # Parallélisation
            embedding_batch_size=int(perf_configs.get("perf.embedding_batch_size", 100)),
            embedding_max_concurrent=int(perf_configs.get("perf.embedding_max_concurrent", 3)),
            # Cache Query Results
            query_cache_size=int(perf_configs.get("perf.query_cache_size", 500)),
            query_cache_ttl=float(perf_configs.get("perf.query_cache_ttl", 300.0)),
            # Reranker
            rerank_timeout_ms=int(perf_configs.get("perf.rerank_timeout_ms", 100)),
            rerank_top_k=int(perf_configs.get("perf.rerank_top_k", 5)),
            # Métriques
            metrics_window_size=int(perf_configs.get("perf.metrics_window_size", 1000)),
            # Mode Fast
            mode_fast_top_k=int(mode_fast.get("rag.mode.fast.top_k", 5)),
            mode_fast_rerank_enabled=mode_fast.get("rag.mode.fast.rerank_enabled", False) in (True, "true", "True", 1, "1"),
            mode_fast_max_context_tokens=int(mode_fast.get("rag.mode.fast.max_context_tokens", 1000)),
            mode_fast_temperature=float(mode_fast.get("rag.mode.fast.temperature", 0.1)),
            # Mode Full
            mode_full_top_k=int(mode_full.get("rag.mode.full.top_k", 10)),
            mode_full_rerank_enabled=mode_full.get("rag.mode.full.rerank_enabled", True) in (True, "true", "True", 1, "1"),
            mode_full_max_context_tokens=int(mode_full.get("rag.mode.full.max_context_tokens", 2500)),
            mode_full_temperature=float(mode_full.get("rag.mode.full.temperature", 0.3)),
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/perf", method="GET", status="200"
        ).inc()

        return config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/perf", method="GET", status="500"
        ).inc()
        logger.error(f"Error getting perf config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/perf", response_model=PerfConfigRead)
async def update_perf_config(
    config_data: PerfConfigUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Met à jour la configuration des performances.

    Requires: Admin role
    """
    try:
        config_service = SystemConfigService(db)
        updates = config_data.model_dump(exclude_unset=True)

        # Mapping des champs vers les clés BDD
        key_mapping = {
            "rag_config_cache_ttl": "perf.rag_config_cache_ttl",
            "embedding_cache_size": "perf.embedding_cache_size",
            "embedding_batch_size": "perf.embedding_batch_size",
            "embedding_max_concurrent": "perf.embedding_max_concurrent",
            "query_cache_size": "perf.query_cache_size",
            "query_cache_ttl": "perf.query_cache_ttl",
            "rerank_timeout_ms": "perf.rerank_timeout_ms",
            "rerank_top_k": "perf.rerank_top_k",
            "metrics_window_size": "perf.metrics_window_size",
            "mode_fast_top_k": "rag.mode.fast.top_k",
            "mode_fast_rerank_enabled": "rag.mode.fast.rerank_enabled",
            "mode_fast_max_context_tokens": "rag.mode.fast.max_context_tokens",
            "mode_fast_temperature": "rag.mode.fast.temperature",
            "mode_full_top_k": "rag.mode.full.top_k",
            "mode_full_rerank_enabled": "rag.mode.full.rerank_enabled",
            "mode_full_max_context_tokens": "rag.mode.full.max_context_tokens",
            "mode_full_temperature": "rag.mode.full.temperature",
        }

        for field, value in updates.items():
            if field in key_mapping:
                db_key = key_mapping[field]
                # Convertir les booléens en string pour la BDD
                if isinstance(value, bool):
                    value = "true" if value else "false"
                await config_service.set(db_key, value, updated_by=admin_user.id)
                logger.info(f"Perf config updated: {db_key} = {value}")

        # Invalider les caches concernés
        from app.common.utils.rag_config import invalidate_rag_config_cache
        invalidate_rag_config_cache()

        # Recharger et retourner la nouvelle config
        new_config = await get_perf_config(admin_user, db)

        # Log audit
        await AuditService.log(
            db,
            action_name='config.perf.update',
            user_id=admin_user.id,
            resource_type_name='config',
            resource_id=None,
            details={'changes': updates},
            request=request,
            username=admin_user.username
        )

        REQUEST_COUNT.labels(
            endpoint="/admin/config/perf", method="PATCH", status="200"
        ).inc()

        return new_config

    except Exception as e:
        REQUEST_COUNT.labels(
            endpoint="/admin/config/perf", method="PATCH", status="500"
        ).inc()
        logger.error(f"Error updating perf config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
