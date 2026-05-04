"""
Router Admin Documents - Endpoints d'administration des documents.

Endpoints:
    GET    /api/admin/documents              - Liste tous les documents
    GET    /api/admin/documents/stats        - Statistiques globales
    GET    /api/admin/documents/{id}         - Détail document
    GET    /api/admin/documents/{id}/download - Télécharger document
    PATCH  /api/admin/documents/{id}         - Modifier document
    DELETE /api/admin/documents/{id}         - Supprimer document
    POST   /api/admin/documents/{id}/reindex - Réindexer (async, background)
    GET    /api/admin/documents/{id}/reindex/status - Progression réindexation
    POST   /api/admin/documents/bulk/visibility - Changer visibilité en masse
    POST   /api/admin/documents/bulk/delete  - Supprimer en masse
    POST   /api/admin/documents/bulk/indexing - Toggle indexation en masse
    POST   /api/admin/documents/bulk/reindex - Réindexer en masse (async)
    GET    /api/admin/users/{id}/quota       - Quota utilisateur
    PUT    /api/admin/users/{id}/quota       - Définir quota
    DELETE /api/admin/users/{id}/quota       - Reset quota (défaut)
"""

import logging
from typing import Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.errors import ErrorCode, not_found
from app.core.deps import get_db, get_storage_service, get_chroma_client, get_current_admin_user
from app.models import User
from app.features.admin.documents.service import AdminDocumentService
from app.features.system.service import SystemConfigService
from app.common.utils.reindex import (
    get_doc_reindex_progress,
    set_doc_reindex_progress,
    clear_doc_reindex_progress,
    request_doc_cancel,
    is_doc_cancel_requested,
    clear_doc_cancel_flag,
)
from app.features.admin.documents.schemas import (
    AdminBulkDeleteRequest,
    AdminBulkOperationResponse,
    AdminBulkReindexRequest,
    AdminBulkVisibilityRequest,
    AdminDocumentDetailResponse,
    AdminDocumentListResponse,
    AdminDocumentResponse,
    AdminDocumentUpdateRequest,
    AdminQuotaUpdateRequest,
    AdminReindexRequest,
    AdminReindexResponse,
    AdminStorageStatsResponse,
    AdminUserQuotaResponse,
    DocReindexProgressResponse,
    DocReindexStartResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/documents", tags=["Admin Documents"])
quota_router = APIRouter(prefix="/api/admin/users", tags=["Admin User Quotas"])


def get_admin_document_service(
    session: AsyncSession = Depends(get_db),
    storage_service=Depends(get_storage_service),
    chroma_client=Depends(get_chroma_client),
) -> AdminDocumentService:
    """Factory pour le service admin documents."""
    return AdminDocumentService(
        session=session,
        storage_service=storage_service,
        chroma_client=chroma_client,
    )


# === Documents List & Detail ===


@router.get("", response_model=AdminDocumentListResponse)
async def list_all_documents(
    user_id: Optional[UUID] = Query(None, description="Filtrer par utilisateur"),
    collection_id: Optional[UUID] = Query(None, description="Filtrer par collection"),
    corpus_id: Optional[UUID] = Query(None, description="Filtrer par corpus"),
    visibility: Optional[str] = Query(None, pattern="^(public|private|shared)$"),
    file_type: Optional[str] = Query(None),
    is_indexed: Optional[bool] = Query(None),
    search: Optional[str] = Query(None, min_length=2),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Liste tous les documents du système (admin).

    Filtre automatiquement par provider courant (affiche uniquement les documents
    indexés avec le provider actif ou non encore indexés).

    Filtres disponibles:
    - **user_id**: Documents d'un utilisateur spécifique
    - **collection_id**: Documents d'une collection spécifique
    - **corpus_id**: Documents d'un corpus spécifique
    - **visibility**: public/private/shared
    - **file_type**: Type MIME
    - **is_indexed**: Documents indexés ou non
    - **search**: Recherche dans le nom de fichier
    """
    # Récupérer le provider courant
    config_service = SystemConfigService(db)
    current_provider = await config_service.get("llm.provider", "ollama")

    return await service.list_all_documents(
        user_id=user_id,
        collection_id=collection_id,
        corpus_id=corpus_id,
        visibility=visibility,
        file_type=file_type,
        is_indexed=is_indexed,
        search=search,
        provider_filter=current_provider,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=AdminStorageStatsResponse)
async def get_storage_stats(
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Récupère les statistiques globales de stockage.

    Inclut le top 10 des utilisateurs par usage.
    """
    return await service.get_storage_stats()


@router.get("/{document_id}", response_model=AdminDocumentDetailResponse)
async def get_document(
    document_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Récupère les détails d'un document avec historique des versions.
    """
    return await service.get_document(document_id)


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Télécharge le fichier d'un document.

    Retourne le contenu binaire du fichier avec les headers appropriés.
    """
    doc_info = await service.get_document(document_id)
    if not doc_info:
        raise not_found(ErrorCode.DOC_NOT_FOUND)

    file_stream = await service.get_document_file(document_id)
    if not file_stream:
        raise not_found(ErrorCode.DOC_FILE_NOT_FOUND)

    # Encoder le nom de fichier pour les headers HTTP (RFC 5987)
    filename_encoded = quote(doc_info.filename)

    return StreamingResponse(
        file_stream,
        media_type=doc_info.file_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}",
            "Content-Length": str(doc_info.file_size),
        }
    )


# === Document CRUD ===


@router.patch("/{document_id}", response_model=AdminDocumentResponse)
async def update_document(
    document_id: UUID,
    update: AdminDocumentUpdateRequest,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Modifie un document (admin).

    Permet de modifier:
    - **visibility**: public/private/shared
    - **is_indexed**: Active/désactive l'indexation RAG
    - **filename**: Renommer le document
    """
    return await service.update_document(
        document_id=document_id,
        visibility=update.visibility,
        is_indexed=update.is_indexed,
        filename=update.filename,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Supprime un document et tous ses fichiers.
    """
    await service.delete_document(document_id)
    return None


@router.delete("/{document_id}/index")
async def clear_document_index(
    document_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Vide uniquement l'index ChromaDB d'un document (conserve le fichier et la DB).
    """
    deleted = await service.clear_document_index(document_id)
    return {"deleted_chunks": deleted}


# === Bulk Operations ===


@router.post("/bulk/visibility", response_model=AdminBulkOperationResponse)
async def bulk_update_visibility(
    request: AdminBulkVisibilityRequest,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Change la visibilité de plusieurs documents en une seule opération.

    Maximum 100 documents par requête.
    """
    return await service.bulk_update_visibility(
        document_ids=request.document_ids,
        visibility=request.visibility,
    )


@router.post("/bulk/delete", response_model=AdminBulkOperationResponse)
async def bulk_delete_documents(
    request: AdminBulkDeleteRequest,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Supprime plusieurs documents en une seule opération.

    Maximum 100 documents par requête.
    """
    return await service.bulk_delete(request.document_ids)


@router.post("/bulk/indexing", response_model=AdminBulkOperationResponse)
async def bulk_toggle_indexing(
    document_ids: list[UUID] = Query(..., max_length=50),
    is_indexed: bool = Query(...),
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Active ou désactive l'indexation RAG de plusieurs documents.

    Maximum 50 documents par requête.
    Synchronise automatiquement ChromaDB (ajout ou suppression des chunks).
    """
    return await service.bulk_toggle_indexing(
        document_ids=document_ids,
        is_indexed=is_indexed,
    )


@router.post("/bulk/reindex", response_model=AdminBulkOperationResponse)
async def bulk_reindex_documents(
    request: AdminBulkReindexRequest,
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Réindexe plusieurs documents dans ChromaDB (asynchrone).

    Lance chaque réindexation en arrière-plan avec suivi de progression individuel.
    Maximum 50 documents par requête.
    """
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="Aucun document sélectionné")

    success_count = 0
    errors = []

    for doc_id in request.document_ids:
        # Vérifier que le document existe
        try:
            doc = await service.get_document(doc_id)
            if not doc:
                errors.append(f"Document {doc_id} non trouvé")
                continue
        except Exception:
            errors.append(f"Document {doc_id} non trouvé")
            continue

        # Vérifier qu'une réindexation n'est pas déjà en cours
        progress = get_doc_reindex_progress(str(doc_id))
        if progress.get("status") == "running":
            errors.append(f"Document {doc_id} déjà en cours de réindexation")
            continue

        # Lancer en arrière-plan
        background_tasks.add_task(
            _run_doc_reindex_in_background,
            document_id=doc_id,
        )
        success_count += 1

    return AdminBulkOperationResponse(
        success_count=success_count,
        error_count=len(errors),
        errors=errors,
    )


@router.post("/{document_id}/reindex", response_model=DocReindexStartResponse)
async def reindex_document(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    body: Optional[AdminReindexRequest] = None,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Lance la réindexation d'un document dans ChromaDB (asynchrone).

    L'opération s'exécute en arrière-plan. Utiliser GET /{document_id}/reindex/status
    pour suivre la progression.

    Args:
        body: Optionnel - spécifier le provider cible (ollama ou llamacpp)
    """
    provider = body.provider if body else None
    # Vérifier que le document existe
    doc = await service.get_document(document_id)
    if not doc:
        raise not_found(ErrorCode.DOC_NOT_FOUND)

    # Vérifier qu'une réindexation n'est pas déjà en cours
    progress = get_doc_reindex_progress(str(document_id))
    if progress.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Réindexation déjà en cours pour ce document"
        )

    # Initialiser la progression avec le nom du document AVANT de lancer la tâche
    set_doc_reindex_progress(str(document_id), 0, "starting", document_name=doc.filename)

    # Lancer en arrière-plan
    background_tasks.add_task(
        _run_doc_reindex_in_background,
        document_id=document_id,
        provider=provider,
    )

    provider_msg = f" vers {provider}" if provider else ""
    return DocReindexStartResponse(
        document_id=document_id,
        status="started",
        message=f"Réindexation lancée pour '{doc.filename}'{provider_msg}"
    )


@router.get("/{document_id}/reindex/status", response_model=DocReindexProgressResponse)
async def get_document_reindex_progress(
    document_id: UUID,
    admin: User = Depends(get_current_admin_user),
):
    """
    Retourne la progression de la réindexation en cours pour un document.
    """
    progress = get_doc_reindex_progress(str(document_id))

    return DocReindexProgressResponse(
        document_id=document_id,
        document_name=progress.get("document_name"),
        status=progress.get("status", "idle"),
        progress=progress.get("progress", 0),
        progress_message=progress.get("progress_message"),
        documents_count=progress.get("documents_count"),
        error_message=progress.get("error_message"),
    )


@router.post("/{document_id}/reindex/cancel")
async def cancel_document_reindex(
    document_id: UUID,
    admin: User = Depends(get_current_admin_user),
):
    """
    Annule la réindexation en cours pour un document.

    L'annulation est demandée mais peut ne pas être immédiate car elle est
    vérifiée entre les étapes de traitement.
    """
    doc_id_str = str(document_id)
    progress = get_doc_reindex_progress(doc_id_str)

    if progress.get("status") not in ("running", "pending", "queued"):
        raise HTTPException(
            status_code=400,
            detail="Aucune réindexation en cours pour ce document"
        )

    # Demander l'annulation
    if request_doc_cancel(doc_id_str):
        logger.info(f"Annulation demandée pour document {document_id} par admin_id={admin.id}")
        return {
            "success": True,
            "message": "Annulation demandée",
            "document_id": str(document_id)
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Impossible d'annuler - aucune réindexation active"
        )


async def _run_doc_reindex_in_background(document_id: UUID, provider: Optional[str] = None) -> None:
    """
    Tâche de fond pour la réindexation d'un document.

    Crée sa propre session DB car elle s'exécute après que la requête HTTP soit terminée.
    Vérifie périodiquement si l'annulation a été demandée.

    Args:
        document_id: UUID du document à réindexer
        provider: Provider cible (ollama ou llamacpp). Si None, utilise le provider actif.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.core.config import settings
    from app.core.deps import get_chroma_client as _get_chroma, get_storage_service as _get_storage
    from app.models import Document

    doc_id_str = str(document_id)
    # Note: Le nom du document est déjà initialisé par l'endpoint avant le lancement

    def _check_cancelled() -> bool:
        """Vérifie si l'annulation a été demandée."""
        if is_doc_cancel_requested(doc_id_str):
            set_doc_reindex_progress(
                doc_id_str, 0, "cancelled",
                status="cancelled",
                error_message="Annulé par l'utilisateur"
            )
            clear_doc_cancel_flag(doc_id_str)
            return True
        return False

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    bg_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        # Vérifier annulation avant de commencer
        if _check_cancelled():
            return

        async with bg_session_maker() as db:
            # Récupérer le document
            set_doc_reindex_progress(doc_id_str, 5, "loading_document")

            # Vérifier annulation
            if _check_cancelled():
                return

            result = await db.execute(
                select(Document)
                .options(selectinload(Document.collection))
                .where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()

            if not document:
                set_doc_reindex_progress(
                    doc_id_str, 0, "not_found",
                    status="failed", error_message="Document introuvable"
                )
                return

            # Mettre à jour avec le nom du document
            set_doc_reindex_progress(
                doc_id_str, 10, "preparing",
                document_name=document.filename
            )

            # Vérifier annulation
            if _check_cancelled():
                return

            # Créer un service avec la session de fond
            chroma_client = _get_chroma()
            storage_service = _get_storage()
            service = AdminDocumentService(
                session=db,
                storage_service=storage_service,
                chroma_client=chroma_client,
            )

            # Lancer la réindexation avec suivi de progression et callback d'annulation
            reindex_result = await service._reindex_document_internal(
                document,
                track_progress=True,
                cancel_check=lambda: is_doc_cancel_requested(doc_id_str),
                provider=provider,
            )

            # Vérifier si annulé pendant le traitement
            if is_doc_cancel_requested(doc_id_str):
                _check_cancelled()
                return

            await db.commit()

            if reindex_result["success"]:
                set_doc_reindex_progress(
                    doc_id_str, 100, "complete",
                    status="success",
                    documents_count=reindex_result["new_chunk_count"],
                )
            elif reindex_result.get("cancelled"):
                set_doc_reindex_progress(
                    doc_id_str, 0, "cancelled",
                    status="cancelled",
                    error_message="Annulé par l'utilisateur"
                )
            else:
                set_doc_reindex_progress(
                    doc_id_str, 0, "failed",
                    status="failed",
                    error_message=reindex_result["message"],
                )

    except Exception as e:
        logger.error(f"Background reindex failed for document {document_id}: {e}")
        set_doc_reindex_progress(
            doc_id_str, 0, "error",
            status="failed",
            error_message=str(e),
        )
    finally:
        clear_doc_cancel_flag(doc_id_str)
        await engine.dispose()


# === User Quotas ===


@quota_router.get("/{user_id}/quota", response_model=AdminUserQuotaResponse)
async def get_user_quota(
    user_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Récupère le quota et l'usage de stockage d'un utilisateur.
    """
    return await service.get_user_quota(user_id)


@quota_router.put("/{user_id}/quota", response_model=AdminUserQuotaResponse)
async def set_user_quota(
    user_id: UUID,
    request: AdminQuotaUpdateRequest,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Définit un quota personnalisé pour un utilisateur.

    Le quota est en bytes. Exemples:
    - 100 MB = 104857600
    - 500 MB = 524288000
    - 1 GB = 1073741824
    """
    return await service.set_user_quota(
        user_id=user_id,
        quota_bytes=request.quota_bytes,
        admin_id=admin.id,
    )


@quota_router.delete("/{user_id}/quota", status_code=204)
async def delete_user_quota(
    user_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminDocumentService = Depends(get_admin_document_service),
):
    """
    Supprime le quota personnalisé d'un utilisateur.

    L'utilisateur reviendra au quota par défaut du système.
    """
    await service.delete_user_quota(user_id)
    return None
