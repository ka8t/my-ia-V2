"""
Router Admin Sources - Gestion des sources de contexte

Endpoints pour configurer les sources externes depuis le backoffice.
"""
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_admin_user, get_db
from app.models import User
from app.features.sources.service import SourceService
from app.features.system.service import SystemConfigService
from app.features.sources.schemas import (
    SourceCreate, SourceUpdate, SourceRead,
    SourcesListResponse, HealthCheckResponse, SourceTestResponse,
    BulkSourceRequest, BulkSourceResponse,
    SourceIndexStats, ClearIndexResponse
)
from app.features.audit.service import AuditService
from app.features.sources.history import IndexationHistoryService
from app.features.sources.repository import SourceRepository
from app.common.i18n import t

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/sources", tags=["Admin - Sources"])


@router.get("", response_model=SourcesListResponse)
async def list_sources(
    is_enabled: Optional[bool] = None,
    source_type: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 25,
    offset: int = 0,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Liste toutes les sources de contexte avec pagination.

    Filtre automatiquement par provider courant (affiche uniquement les sources
    indexées avec le provider actif ou non encore indexées).
    """
    # Récupérer le provider courant
    config_service = SystemConfigService(db)
    current_provider = await config_service.get("llm.provider", "ollama")

    sources, total = await SourceService.list_sources(
        db, is_enabled, source_type, search,
        provider_filter=current_provider, limit=limit, offset=offset
    )
    return SourcesListResponse(sources=sources, total=total)


# =============================================================================
# BULK OPERATIONS - AVANT les routes avec {source_id}
# =============================================================================

@router.post("/bulk/enable", response_model=BulkSourceResponse)
async def bulk_enable_sources(
    body: BulkSourceRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Active plusieurs sources en masse."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirm=true)")

    if not body.source_ids:
        raise HTTPException(status_code=400, detail="Aucune source sélectionnée")

    logger.info(f"Bulk enable: {len(body.source_ids)} sources par admin_id={admin_user.id}")

    result = await SourceService.bulk_enable_sources(db, body.source_ids)

    await AuditService.log_action(
        db=db,
        action_name='sources_bulk_enabled',
        user_id=admin_user.id,
        resource_type_name='context_source',
        details={
            'count': len(body.source_ids),
            'success_count': result['success_count'],
            'failed_count': result['failed_count']
        },
        request=request
    )

    return BulkSourceResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} source(s) activée(s)"
    )


@router.post("/bulk/disable", response_model=BulkSourceResponse)
async def bulk_disable_sources(
    body: BulkSourceRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Désactive plusieurs sources en masse."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirm=true)")

    if not body.source_ids:
        raise HTTPException(status_code=400, detail="Aucune source sélectionnée")

    logger.info(f"Bulk disable: {len(body.source_ids)} sources par admin_id={admin_user.id}")

    result = await SourceService.bulk_disable_sources(db, body.source_ids)

    await AuditService.log_action(
        db=db,
        action_name='sources_bulk_disabled',
        user_id=admin_user.id,
        resource_type_name='context_source',
        details={
            'count': len(body.source_ids),
            'success_count': result['success_count'],
            'failed_count': result['failed_count']
        },
        request=request
    )

    return BulkSourceResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} source(s) désactivée(s)"
    )


@router.post("/bulk/delete", response_model=BulkSourceResponse)
async def bulk_delete_sources(
    body: BulkSourceRequest,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Supprime plusieurs sources en masse."""
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirm=true)")

    if not body.source_ids:
        raise HTTPException(status_code=400, detail="Aucune source sélectionnée")

    logger.info(f"Bulk delete: {len(body.source_ids)} sources par admin_id={admin_user.id}")

    result = await SourceService.bulk_delete_sources(db, body.source_ids)

    await AuditService.log_action(
        db=db,
        action_name='sources_bulk_deleted',
        user_id=admin_user.id,
        resource_type_name='context_source',
        details={
            'count': len(body.source_ids),
            'success_count': result['success_count'],
            'failed_count': result['failed_count']
        },
        request=request
    )

    return BulkSourceResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} source(s) supprimée(s)"
    )


@router.post("/bulk/reindex", response_model=BulkSourceResponse)
async def bulk_reindex_sources(
    body: BulkSourceRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Réindexe plusieurs sources en masse.

    Lance les réindexations en arrière-plan.
    """
    if not body.source_ids:
        raise HTTPException(status_code=400, detail="Aucune source sélectionnée")

    logger.info(f"Bulk reindex: {len(body.source_ids)} sources par admin_id={admin_user.id}")

    # Vérifier que les sources existent et ont l'indexation activée
    success_count = 0
    failed_count = 0
    failed_ids = []

    for source_id in body.source_ids:
        source = await SourceRepository.get_by_id(db, source_id)
        if not source:
            failed_ids.append(source_id)
            failed_count += 1
            continue

        if not source.index_enabled:
            failed_ids.append(source_id)
            failed_count += 1
            continue

        # Créer l'entrée de log AVANT de lancer la tâche en arrière-plan
        log_entry = await IndexationHistoryService.start_indexation(
            db=db,
            source_id=source_id,
            trigger_type="manual",
            triggered_by=admin_user.id
        )

        # Lancer la réindexation en arrière-plan avec le log_id créé
        background_tasks.add_task(
            _run_reindex_in_background,
            source_id=source_id,
            triggered_by=admin_user.id,
            replace_existing=True,
            log_id=str(log_entry.id)
        )
        success_count += 1

    # Commit tous les logs créés
    await db.commit()

    await AuditService.log_action(
        db=db,
        action_name='sources_bulk_reindex',
        user_id=admin_user.id,
        resource_type_name='context_source',
        details={
            'count': len(body.source_ids),
            'success_count': success_count,
            'failed_count': failed_count
        },
        request=request
    )

    return BulkSourceResponse(
        success_count=success_count,
        failed_count=failed_count,
        failed_ids=failed_ids,
        message=f"{success_count} source(s) en cours de réindexation"
    )


# =============================================================================
# ALERTES ET MAINTENANCE - AVANT les routes avec {source_id}
# =============================================================================

from app.features.sources.schemas import (
    IndexationLogRead, IndexationHistoryResponse,
    TriggerIndexationRequest, TriggerIndexationResponse,
    ReindexProgressResponse,
    SourceFreshnessResponse, StaleSourcesResponse, StaleSourceAlert,
    FreshnessStatus
)


@router.get("/alerts/stale", response_model=StaleSourcesResponse)
async def get_stale_sources_alerts(
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Récupère la liste des sources périmées ou bientôt périmées"""
    stale_sources = await IndexationHistoryService.get_stale_sources(db)

    alerts = []
    total_warning = 0
    total_expired = 0

    for source_data in stale_sources:
        status = source_data["status"]
        if status == "warning":
            total_warning += 1
            freshness_status = FreshnessStatus.WARNING
        elif status == "expired":
            total_expired += 1
            freshness_status = FreshnessStatus.EXPIRED
        else:
            freshness_status = FreshnessStatus.NEVER_INDEXED

        alerts.append(StaleSourceAlert(
            source_id=source_data["source_id"],
            source_name=source_data["source_name"],
            display_name=source_data["display_name"],
            status=freshness_status,
            ttl_hours=source_data["ttl_hours"],
            last_indexed_at=source_data.get("last_indexed_at"),
            expires_at=source_data.get("expires_at"),
            freshness_percent=source_data.get("freshness_percent", 0)
        ))

    return StaleSourcesResponse(
        alerts=alerts,
        total_stale=len(alerts),
        total_warning=total_warning,
        total_expired=total_expired
    )


@router.post("/cleanup/logs")
async def cleanup_old_indexation_logs(
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Nettoie les vieux logs d'indexation selon la rétention configurée"""
    deleted_count = await IndexationHistoryService.cleanup_old_logs(db)

    await AuditService.log_action(
        db=db,
        action_name='indexation_logs_cleaned',
        user_id=admin_user.id,
        resource_type_name='context_source',
        details={'deleted_count': deleted_count},
        request=request
    )

    return {"deleted_count": deleted_count, "message": f"{deleted_count} log(s) supprimé(s)"}


@router.get("/scheduler/status")
async def get_scheduler_status(
    admin_user: User = Depends(get_current_admin_user)
):
    """Récupère le statut du scheduler de ré-indexation"""
    from app.features.sources.scheduler import get_scheduler_status
    return get_scheduler_status()


# =============================================================================
# GET BY ID
# =============================================================================

@router.get("/{source_id}", response_model=SourceRead)
async def get_source(
    source_id: UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Recupere les details d'une source"""
    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))
    return source


@router.post("", response_model=SourceRead, status_code=201)
async def create_source(
    data: SourceCreate,
    request: Request,
    background_tasks: BackgroundTasks,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Cree une nouvelle source de contexte (indexation en arrière-plan)"""
    try:
        source = await SourceService.create_source(db, data)

        await AuditService.log_action(
            db=db,
            action_name='source_created',
            user_id=admin_user.id,
            resource_type_name='context_source',
            resource_id=source.id,
            details={'name': data.name, 'type': data.source_type.value},
            request=request
        )

        # Lancer l'indexation en arrière-plan si index_enabled
        if data.index_enabled:
            import asyncio
            asyncio.create_task(SourceService.trigger_initial_indexation(source.id))
            logger.info(f"Indexation initiale déclenchée en arrière-plan pour '{source.name}'")

        return source
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{source_id}", response_model=SourceRead)
async def update_source(
    source_id: UUID,
    data: SourceUpdate,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Met a jour une source"""
    source = await SourceService.update_source(db, source_id, data)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    await AuditService.log_action(
        db=db,
        action_name='source_updated',
        user_id=admin_user.id,
        resource_type_name='context_source',
        resource_id=source_id,
        details=data.model_dump(exclude_unset=True),
        request=request
    )

    return source


@router.delete("/{source_id}")
async def delete_source(
    source_id: UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Supprime une source et son contenu indexé dans ChromaDB"""
    from app.common.errors import ErrorCode, api_error

    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    try:
        result = await SourceService.delete_source(db, source_id)
    except RuntimeError as e:
        logger.error(f"ChromaDB delete failed for source {source_id}: {e}")
        raise api_error(500, ErrorCode.CHROMADB_DELETE_FAILED, {"source": source.name})

    await AuditService.log_action(
        db=db,
        action_name='source_deleted',
        user_id=admin_user.id,
        resource_type_name='context_source',
        resource_id=source_id,
        details={'name': source.name},
        request=request
    )

    return {"deleted": True}


@router.delete("/{source_id}/index")
async def clear_source_index(
    source_id: UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Vide uniquement l'index ChromaDB d'une source (conserve la source en BDD).
    """
    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    deleted = await SourceService.clear_source_index(db, source_id)

    await AuditService.log_action(
        db=db,
        action_name='source_index_cleared',
        user_id=admin_user.id,
        resource_type_name='context_source',
        resource_id=source_id,
        details={'name': source.name, 'deleted_chunks': deleted},
        request=request
    )

    return {"deleted_chunks": deleted}


@router.post("/{source_id}/toggle", response_model=SourceRead)
async def toggle_source(
    source_id: UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Active/desactive une source"""
    source = await SourceService.toggle_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    await AuditService.log_action(
        db=db,
        action_name='source_toggled',
        user_id=admin_user.id,
        resource_type_name='context_source',
        resource_id=source_id,
        details={'is_enabled': source.is_enabled},
        request=request
    )

    return source


@router.post("/{source_id}/health", response_model=HealthCheckResponse)
async def check_source_health(
    source_id: UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Verifie la sante d'une source"""
    result = await SourceService.health_check(db, source_id)
    if not result:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))
    return result


@router.post("/{source_id}/test", response_model=SourceTestResponse)
async def test_source(
    source_id: UUID,
    query: str = Query(..., min_length=1, description="Requete de test"),
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Teste une source avec une requete"""
    result = await SourceService.test_source(db, source_id, query)
    if not result:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))
    return result


# =============================================================================
# INDEXATION
# =============================================================================

@router.get("/{source_id}/index", response_model=SourceIndexStats)
async def get_source_index_stats(
    source_id: UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Récupère les statistiques d'indexation d'une source"""
    stats = await SourceService.get_source_index_stats(db, source_id)
    if not stats:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))
    return stats


@router.delete("/{source_id}/index", response_model=ClearIndexResponse)
async def clear_source_index(
    source_id: UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Vide l'index d'une source (supprime tous les documents indexés)"""
    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    deleted_count = await SourceService.clear_source_index(db, source_id)
    if deleted_count is None:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    await AuditService.log_action(
        db=db,
        action_name='source_index_cleared',
        user_id=admin_user.id,
        resource_type_name='context_source',
        resource_id=source_id,
        details={'name': source.name, 'deleted_count': deleted_count},
        request=request
    )

    return ClearIndexResponse(
        source_id=source_id,
        source_name=source.display_name,
        deleted_count=deleted_count,
        message=f"{deleted_count} document(s) supprimé(s) de l'index"
    )


# =============================================================================
# HISTORIQUE D'INDEXATION
# =============================================================================

@router.get("/{source_id}/history", response_model=IndexationHistoryResponse)
async def get_source_indexation_history(
    source_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Récupère l'historique des indexations d'une source"""
    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    offset = (page - 1) * page_size
    logs = await IndexationHistoryService.get_source_history(db, source_id, limit=page_size, offset=offset)
    total = await IndexationHistoryService.get_source_history_count(db, source_id)

    # Convertir en schema avec email du déclencheur
    log_reads = []
    for log in logs:
        log_read = IndexationLogRead(
            id=log.id,
            source_id=log.source_id,
            indexed_at=log.indexed_at,
            documents_count=log.documents_count,
            replaced_count=log.replaced_count,
            trigger_type=log.trigger_type,
            triggered_by=log.triggered_by,
            triggered_by_email=log.triggered_by_user.email if log.triggered_by_user else None,
            content_hash=log.content_hash,
            content_changed=log.content_changed,
            status=log.status,
            error_message=log.error_message,
            duration_ms=log.duration_ms
        )
        log_reads.append(log_read)

    return IndexationHistoryResponse(
        logs=log_reads,
        total=total,
        page=page,
        page_size=page_size
    )


@router.get("/{source_id}/freshness", response_model=SourceFreshnessResponse)
async def get_source_freshness(
    source_id: UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Récupère le statut de fraîcheur d'une source"""
    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    freshness = await IndexationHistoryService.get_freshness_status(db, source)

    return SourceFreshnessResponse(
        source_id=source.id,
        source_name=source.display_name,
        status=FreshnessStatus(freshness["status"]),
        freshness_percent=freshness.get("freshness_percent"),
        ttl_hours=freshness["ttl_hours"],
        last_indexed_at=freshness.get("last_indexed_at"),
        expires_at=freshness.get("expires_at"),
        hours_until_expiry=freshness.get("hours_until_expiry")
    )


async def _run_reindex_in_background(
    source_id: UUID,
    triggered_by: UUID,
    replace_existing: bool,
    log_id: Optional[str] = None,
    provider: Optional[str] = None
):
    """
    Exécute la ré-indexation en arrière-plan.

    Cette fonction crée sa propre session DB car elle s'exécute
    après que la requête HTTP soit terminée.

    Args:
        source_id: ID de la source à réindexer
        triggered_by: ID de l'utilisateur ayant déclenché l'action
        replace_existing: Force le remplacement des documents existants
        log_id: ID du log créé en amont (pour le polling immédiat)
        provider: Provider cible (ollama ou llamacpp). Si None, utilise le provider actif.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.core.config import settings
    from app.features.sources.scheduler import reindex_source

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session_maker() as db:
            # Récupérer la source
            source = await SourceRepository.get_by_id(db, source_id)
            if not source:
                logger.error(f"Background reindex: Source {source_id} not found")
                return

            # Si replace_existing, on force replace_on_refresh temporairement
            original_replace = source.replace_on_refresh
            if replace_existing:
                source.replace_on_refresh = True

            # Déclencher l'indexation
            await reindex_source(
                db=db,
                source=source,
                trigger_type="manual",
                triggered_by=str(triggered_by),
                log_id=log_id,
                provider=provider
            )

            # Restaurer la valeur originale si modifiée
            if replace_existing and not original_replace:
                source.replace_on_refresh = original_replace
                await db.commit()

    except Exception as e:
        logger.error(f"Background reindex failed for source {source_id}: {e}")
    finally:
        await engine.dispose()


@router.get("/{source_id}/reindex/status", response_model=ReindexProgressResponse)
async def get_reindex_progress(
    source_id: UUID,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Retourne la progression de la réindexation en cours pour une source"""
    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    # Chercher une indexation en cours
    running = await IndexationHistoryService.get_running_indexation(db, source_id)
    if running:
        return ReindexProgressResponse(
            source_id=source_id,
            source_name=source.display_name,
            status="running",
            progress=running.progress,
            progress_message=running.progress_message,
            documents_count=running.documents_count,
            duration_ms=running.duration_ms,
            error_message=None
        )

    # Sinon, retourner la dernière indexation terminée
    latest = await IndexationHistoryService.get_latest_indexation(db, source_id)
    if latest:
        return ReindexProgressResponse(
            source_id=source_id,
            source_name=source.display_name,
            status=latest.status,
            progress=latest.progress,
            progress_message=latest.progress_message,
            documents_count=latest.documents_count,
            duration_ms=latest.duration_ms,
            error_message=latest.error_message
        )

    # Aucune indexation trouvée
    return ReindexProgressResponse(
        source_id=source_id,
        source_name=source.display_name,
        status="idle",
        progress=0,
        progress_message=None,
        documents_count=None,
        duration_ms=None,
        error_message=None
    )


@router.post("/{source_id}/reindex/cancel")
async def cancel_source_reindex(
    source_id: UUID,
    request: Request,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Annule la réindexation en cours pour une source.

    L'annulation est demandée mais peut ne pas être immédiate car elle est
    vérifiée entre les étapes de traitement.
    """
    from app.common.utils.reindex import request_source_cancel

    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    # Vérifier qu'une indexation est en cours
    running = await IndexationHistoryService.get_running_indexation(db, source_id)
    if not running:
        raise HTTPException(
            status_code=400,
            detail="Aucune réindexation en cours pour cette source"
        )

    # Demander l'annulation
    request_source_cancel(str(source_id))

    await AuditService.log_action(
        db=db,
        action_name='source_reindex_cancelled',
        user_id=admin_user.id,
        resource_type_name='context_source',
        resource_id=source_id,
        details={'name': source.name},
        request=request
    )

    logger.info(f"Annulation demandée pour source {source_id} par admin_id={admin_user.id}")

    return {
        "success": True,
        "message": "Annulation demandée",
        "source_id": str(source_id)
    }


@router.post("/{source_id}/reindex", response_model=TriggerIndexationResponse)
async def trigger_source_reindex(
    source_id: UUID,
    body: TriggerIndexationRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin_user: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Déclenche une ré-indexation manuelle d'une source"""
    source = await SourceService.get_source(db, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=t("error_source_not_found"))

    # Vérifier que l'indexation est activée pour cette source
    if not source.index_enabled:
        raise HTTPException(
            status_code=400,
            detail=t("error_source_indexation_disabled")
        )

    # Créer l'entrée de log AVANT de lancer la tâche en arrière-plan
    # pour que le polling puisse immédiatement trouver un statut "running"
    log_entry = await IndexationHistoryService.start_indexation(
        db=db,
        source_id=source_id,
        trigger_type="manual",
        triggered_by=admin_user.id
    )
    await db.commit()

    await AuditService.log_action(
        db=db,
        action_name='source_reindex_triggered',
        user_id=admin_user.id,
        resource_type_name='context_source',
        resource_id=source_id,
        details={
            'name': source.name,
            'replace_existing': body.replace_existing,
            'log_id': str(log_entry.id),
            'provider': body.provider
        },
        request=request
    )

    # Déclencher l'indexation en arrière-plan avec le log_id créé
    background_tasks.add_task(
        _run_reindex_in_background,
        source_id=source_id,
        triggered_by=admin_user.id,
        replace_existing=body.replace_existing,
        log_id=str(log_entry.id),
        provider=body.provider
    )

    provider_msg = f" vers {body.provider}" if body.provider else ""
    return TriggerIndexationResponse(
        source_id=source_id,
        source_name=source.display_name,
        log_id=log_entry.id,
        status="running",
        message=f"Indexation démarrée pour la source '{source.display_name}'{provider_msg}"
    )


# =============================================================================
# PUBLIC ROUTER - Endpoints pour les utilisateurs
# =============================================================================

from app.features.sources.schemas import SourcePublic, SourcesPublicResponse
from app.features.auth.router import optional_current_user

public_router = APIRouter(prefix="/sources", tags=["Sources"])


@public_router.get("/available", response_model=SourcesPublicResponse)
async def list_available_sources(
    user: User = Depends(optional_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Liste les sources disponibles pour l'utilisateur.

    Retourne uniquement les sources actives, sans les informations
    de configuration sensibles.

    Filtre par provider courant : seules les sources indexées avec le
    provider actif (ou non encore indexées) sont retournées.

    Si use_corpus=true (corpus actifs), retourne une liste vide car
    les sources sont gérées automatiquement par l'admin via les corpus.
    """
    from app.features.system.service import SystemConfigService

    config_service = SystemConfigService(db)
    use_corpus = await config_service.get("rag.use_corpus", True)

    # Si les corpus sont actifs, pas de sélection manuelle
    if use_corpus:
        return SourcesPublicResponse(sources=[], total=0, use_corpus=True)

    # Récupérer le provider courant pour filtrer
    current_provider = await config_service.get("llm.provider", "ollama")

    # Lister les sources disponibles filtrées par provider
    sources, _ = await SourceService.list_sources(
        db,
        is_enabled=True,
        provider_filter=current_provider
    )

    # Convertir en schema public (sans config)
    public_sources = [
        SourcePublic(
            id=s.id,
            name=s.name,
            display_name=s.display_name,
            description=s.description,
            source_type=s.source_type
        )
        for s in sources
    ]

    return SourcesPublicResponse(sources=public_sources, total=len(public_sources), use_corpus=False)
