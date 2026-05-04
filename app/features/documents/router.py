"""
Router Documents - Endpoints API pour la gestion des documents utilisateur.

Endpoints:
    GET    /api/user/documents              - Liste des documents
    GET    /api/user/documents/search       - Recherche
    GET    /api/user/documents/stats        - Statistiques stockage
    GET    /api/user/documents/{id}         - Détail document
    POST   /api/user/documents              - Upload nouveau document
    POST   /api/user/documents/upload-stream - Upload avec progression SSE
    POST   /api/user/documents/bulk/delete  - Suppression groupée
    PUT    /api/user/documents/{id}         - Remplacer (nouvelle version)
    PATCH  /api/user/documents/{id}         - Modifier métadonnées
    DELETE /api/user/documents/{id}         - Supprimer
    GET    /api/user/documents/{id}/download - Télécharger
"""

import json
import logging
from typing import AsyncGenerator, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_storage_service, get_chroma_client
from app.features.auth.service import current_active_user
from app.models import User
from app.features.documents.service import (
    DocumentService,
    get_upload_progress,
    set_upload_progress,
    clear_upload_progress,
)
from app.features.audit.service import AuditService
from app.features.documents.schemas import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    DocumentDetailResponse,
    DocumentListResponse,
    DocumentResponse,
    DocumentSearchResponse,
    DocumentStatsResponse,
    DocumentUploadResponse,
    DocumentUpdateRequest,
    UploadAsyncResponse,
    UploadProgressEvent,
    UploadProgressResponse,
)

logger = logging.getLogger(__name__)

# Mapping role_id -> role_name (évite de charger la relation)
ROLE_NAMES = {1: 'admin', 2: 'user', 3: 'contributor', 4: 'validator'}

def get_role_name(role_id: int) -> str:
    """Retourne le nom du rôle depuis son ID."""
    return ROLE_NAMES.get(role_id, 'unknown')

router = APIRouter(prefix="/api/user/documents", tags=["User Documents"])


def get_document_service(
    session: AsyncSession = Depends(get_db),
    storage_service=Depends(get_storage_service),
    chroma_client=Depends(get_chroma_client),
) -> DocumentService:
    """Factory pour le service documents."""
    return DocumentService(
        session=session,
        storage_service=storage_service,
        chroma_client=chroma_client,
    )


# === List & Search ===


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    visibility: Optional[str] = Query(None, pattern="^(public|private)$"),
    file_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Liste les documents de l'utilisateur connecté.

    - **visibility**: Filtrer par visibilité (public/private)
    - **file_type**: Filtrer par type MIME
    - **page**: Numéro de page (défaut: 1)
    - **page_size**: Taille de page (défaut: 20, max: 100)
    """
    return await service.list_documents(
        user_id=user.id,
        visibility=visibility,
        file_type=file_type,
        page=page,
        page_size=page_size,
    )


@router.get("/search", response_model=DocumentSearchResponse)
async def search_documents(
    q: str = Query(..., min_length=2, description="Terme de recherche"),
    visibility: Optional[str] = Query(None, pattern="^(public|private)$"),
    limit: int = Query(50, ge=1, le=100),
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Recherche dans les documents de l'utilisateur.

    Recherche sur le nom de fichier (insensible à la casse).
    """
    return await service.search_documents(
        user_id=user.id,
        query=q,
        visibility=visibility,
        limit=limit,
    )


@router.get("/stats", response_model=DocumentStatsResponse)
async def get_storage_stats(
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Récupère les statistiques de stockage de l'utilisateur.

    Retourne l'espace utilisé, le quota et le pourcentage.
    """
    return await service.get_user_stats(user.id)


# === CRUD ===


@router.get("/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: UUID,
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Récupère les détails d'un document avec l'historique des versions.
    """
    return await service.get_document(user.id, document_id)


@router.post("", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    visibility: str = Form(default="public", pattern="^(public|private)$"),
    collection_id: Optional[UUID] = Form(default=None),
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
    session: AsyncSession = Depends(get_db),
):
    """
    Upload un nouveau document.

    - **file**: Fichier à uploader
    - **visibility**: Visibilité du document (public/private, défaut: public)
    - **collection_id**: ID de la collection cible (defaut: ma collection privee)
    """
    result = await service.upload_document(
        user_id=user.id,
        file=file,
        visibility=visibility,
        collection_id=collection_id,
    )

    # Audit
    try:
        await AuditService.log_action(
            db=session,
            action_name='document_uploaded',
            user_id=user.id,
            resource_type_name='document',
            resource_id=result.id,
            details={'filename': result.filename, 'visibility': visibility},
            request=request,
            user_role=get_role_name(user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging document upload: {e}")

    return result


@router.post("/upload-stream")
async def upload_document_stream(
    request: Request,
    file: UploadFile = File(...),
    visibility: str = Form(default="public", pattern="^(public|private)$"),
    collection_id: Optional[UUID] = Form(default=None),
    replace_if_exists: bool = Form(default=False),
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
    session: AsyncSession = Depends(get_db),
):
    """
    Upload un document avec progression en temps réel via SSE.

    Retourne un flux Server-Sent Events avec les étapes:
    - upload: Réception du fichier (10%)
    - parsing: Analyse du contenu (30%)
    - embedding: Génération des embeddings (70%)
    - indexing: Indexation dans ChromaDB (90%)
    - done: Terminé avec succès (100%)
    - error: En cas d'erreur

    Exemple d'événement SSE:
    ```
    data: {"stage": "parsing", "progress": 30, "message": "Analyse du document..."}
    ```
    """
    # IMPORTANT: Lire le fichier AVANT de créer le générateur
    # car FastAPI ferme le fichier après le return
    file_content = await file.read()
    file_name = file.filename
    file_content_type = file.content_type

    async def event_generator() -> AsyncGenerator[str, None]:
        """Générateur d'événements SSE pour la progression."""
        try:
            async for event in service.upload_document_with_progress(
                user_id=user.id,
                file_content=file_content,
                file_name=file_name,
                file_content_type=file_content_type,
                visibility=visibility,
                collection_id=collection_id,
                replace_if_exists=replace_if_exists,
            ):
                yield f"data: {json.dumps(event.model_dump(), default=str)}\n\n"

                # Si c'est le dernier événement (done ou error), on log l'audit
                if event.stage == "done" and event.result:
                    try:
                        await AuditService.log_action(
                            db=session,
                            action_name='document_uploaded',
                            user_id=user.id,
                            resource_type_name='document',
                            resource_id=event.result.id,
                            details={'filename': event.result.filename, 'visibility': visibility},
                            request=request,
                            user_role=get_role_name(user.role_id)
                        )
                    except Exception as e:
                        logger.error(f"Error logging document upload: {e}")

        except Exception as e:
            logger.error(f"Erreur SSE upload: {e}")
            error_event = UploadProgressEvent(
                stage="error",
                progress=0,
                message=str(e)
            )
            yield f"data: {json.dumps(error_event.model_dump(), default=str)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Désactive le buffering nginx
        }
    )


@router.post("/upload-async", response_model=UploadAsyncResponse)
async def upload_document_async(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    visibility: str = Form(default="public", pattern="^(public|private)$"),
    collection_id: Optional[UUID] = Form(default=None),
    replace_if_exists: bool = Form(default=False),
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
    session: AsyncSession = Depends(get_db),
):
    """
    Upload un document avec indexation en arrière-plan.

    Le fichier est sauvegardé immédiatement, l'indexation ChromaDB
    est lancée en tâche de fond. Utiliser GET /{id}/upload/status
    pour suivre la progression.

    Returns:
        UploadAsyncResponse avec l'ID du document et status "pending"
    """
    # Lire le fichier avant de retourner la réponse
    file_content = await file.read()
    file_name = file.filename
    file_content_type = file.content_type

    # Upload sans indexation
    result = await service.upload_document_deferred(
        user_id=user.id,
        file_content=file_content,
        file_name=file_name,
        file_content_type=file_content_type,
        visibility=visibility,
        collection_id=collection_id,
        replace_if_exists=replace_if_exists,
    )

    # Lancer l'indexation en arrière-plan
    background_tasks.add_task(
        _run_upload_indexing_in_background,
        document_id=result.id,
        user_id=user.id,
        collection_id=collection_id,
        visibility=visibility,
    )

    # Audit log
    try:
        await AuditService.log_action(
            db=session,
            action_name='document_uploaded',
            user_id=user.id,
            resource_type_name='document',
            resource_id=result.id,
            details={'filename': result.filename, 'visibility': visibility, 'async': True},
            request=request,
            user_role=get_role_name(user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging document upload: {e}")

    return result


@router.get("/{document_id}/upload/status", response_model=UploadProgressResponse)
async def get_upload_status(
    document_id: UUID,
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Récupère la progression d'indexation d'un document uploadé en mode async.

    Returns:
        UploadProgressResponse avec status, progress, message
    """
    # Vérifier que l'utilisateur a accès au document
    doc = await service.get_document(user.id, document_id)
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document non trouvé")

    progress = get_upload_progress(str(document_id))
    return UploadProgressResponse(
        status=progress.get("status", "idle"),
        progress=progress.get("progress", 0),
        progress_message=progress.get("progress_message"),
        document_name=progress.get("document_name"),
        chunk_count=progress.get("chunk_count"),
        error_message=progress.get("error_message"),
    )


async def _run_upload_indexing_in_background(
    document_id: UUID,
    user_id: UUID,
    collection_id: Optional[UUID],
    visibility: str,
) -> None:
    """
    Tâche de fond pour l'indexation d'un document uploadé.

    Crée sa propre session DB car elle s'exécute après que la requête HTTP soit terminée.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.core.config import settings
    from app.core.deps import get_chroma_client as _get_chroma, get_storage_service as _get_storage, get_ingestion_pipeline
    from app.common.utils.rag_config import get_rag_config
    from app.models import Document

    doc_id_str = str(document_id)
    set_upload_progress(doc_id_str, 5, "starting", status="indexing")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    bg_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with bg_session_maker() as db:
            # Récupérer le document
            set_upload_progress(doc_id_str, 10, "loading_document", status="indexing")
            result = await db.execute(
                select(Document)
                .options(selectinload(Document.collection))
                .where(Document.id == document_id)
            )
            document = result.scalar_one_or_none()

            if not document:
                set_upload_progress(
                    doc_id_str, 0, "not_found",
                    status="failed", error_message="Document introuvable"
                )
                return

            set_upload_progress(
                doc_id_str, 20, "loading_config",
                status="indexing", document_name=document.filename
            )

            # Charger la configuration RAG
            rag_config = await get_rag_config(db)

            # Obtenir le pipeline d'ingestion
            pipeline = get_ingestion_pipeline()
            if not pipeline:
                set_upload_progress(
                    doc_id_str, 0, "pipeline_unavailable",
                    status="failed", error_message="Pipeline d'ingestion non disponible"
                )
                return

            set_upload_progress(doc_id_str, 30, "ingesting", status="indexing")

            # Construire le chemin complet
            full_path = f"{settings.storage_local_path}/{document.file_path}"

            # Récupérer le nom de la collection
            collection_name = document.collection.name if document.collection else None
            if not collection_name:
                set_upload_progress(
                    doc_id_str, 0, "no_collection",
                    status="failed", error_message="Collection non trouvée"
                )
                return

            logger.info(f"Background indexing document {document_id} into collection {collection_name}")

            set_upload_progress(doc_id_str, 50, "embedding", status="indexing")

            # Appeler le pipeline
            ingest_result = await pipeline.ingest_file(
                file_path=full_path,
                parsing_strategy="auto",
                skip_duplicates=False,
                user_id=str(user_id),
                visibility=visibility,
                collection_name=collection_name,
                chunk_size=rag_config.chunk_size,
                chunk_overlap=rag_config.chunk_overlap,
                chunking_strategy=rag_config.chunking_strategy,
                original_filename=document.filename,
            )

            set_upload_progress(doc_id_str, 80, "updating_counters", status="indexing")

            if ingest_result["status"] == "success":
                chunk_count = ingest_result.get("chunks_indexed", 0)

                # Récupérer le provider actif
                from app.features.system.service import SystemConfigService
                config_service = SystemConfigService(db)
                current_provider = await config_service.get("llm.provider", "ollama")

                # Mettre à jour le document
                document.chunk_count = chunk_count
                document.embedding_count = chunk_count
                document.is_indexed = True
                document.indexed_provider = current_provider

                # Mettre à jour les compteurs de la collection
                if document.collection:
                    document.collection.document_count = (document.collection.document_count or 0) + 1
                    document.collection.chunk_count = (document.collection.chunk_count or 0) + chunk_count

                await db.commit()

                set_upload_progress(
                    doc_id_str, 100, "complete",
                    status="success", chunk_count=chunk_count
                )
                logger.info(f"Document {document_id} indexed successfully: {chunk_count} chunks")
            else:
                error_msg = ingest_result.get("message", "Erreur d'indexation")
                set_upload_progress(
                    doc_id_str, 0, "indexing_failed",
                    status="failed", error_message=error_msg
                )
                logger.error(f"Document {document_id} indexing failed: {error_msg}")

    except Exception as e:
        logger.error(f"Background indexing failed for document {document_id}: {e}")
        set_upload_progress(
            doc_id_str, 0, "error",
            status="failed", error_message=str(e),
        )
    finally:
        await engine.dispose()


@router.put("/{document_id}", response_model=DocumentUploadResponse)
async def replace_document(
    document_id: UUID,
    file: UploadFile = File(...),
    comment: Optional[str] = Form(None, max_length=500),
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Remplace un document par une nouvelle version.

    L'ancienne version est conservée dans l'historique.

    - **file**: Nouveau fichier
    - **comment**: Note optionnelle pour cette version
    """
    return await service.replace_document(
        user_id=user.id,
        document_id=document_id,
        file=file,
        comment=comment,
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
async def update_document(
    document_id: UUID,
    update: DocumentUpdateRequest,
    request: Request,
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
    session: AsyncSession = Depends(get_db),
):
    """
    Modifie les métadonnées d'un document.

    - **visibility**: Nouvelle visibilité (public/private)
    - **filename**: Nouveau nom de fichier
    """
    result = await service.update_document(
        user_id=user.id,
        document_id=document_id,
        visibility=update.visibility,
        filename=update.filename,
    )

    # Audit
    try:
        details = {}
        if update.visibility:
            details['visibility'] = update.visibility
        if update.filename:
            details['filename'] = update.filename
        await AuditService.log_action(
            db=session,
            action_name='document_updated',
            user_id=user.id,
            resource_type_name='document',
            resource_id=document_id,
            details=details,
            request=request,
            user_role=get_role_name(user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging document update: {e}")

    return result


# === Bulk Delete ===


@router.post("/bulk/delete", response_model=BulkDeleteResponse)
async def bulk_delete_documents(
    body: BulkDeleteRequest,
    request: Request,
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
    session: AsyncSession = Depends(get_db),
):
    """
    Supprime plusieurs documents en une seule opération.

    - **document_ids**: Liste des IDs de documents à supprimer (max 100)
    - **confirm**: Doit être True pour confirmer la suppression
    """
    if not body.confirm:
        return BulkDeleteResponse(
            deleted_count=0,
            failed_ids=[],
            message="Confirmation requise (confirm=true)"
        )

    deleted_count, failed_ids = await service.bulk_delete_documents(
        user.id, body.document_ids
    )

    # Audit
    try:
        await AuditService.log_action(
            db=session,
            action_name='documents_bulk_deleted',
            user_id=user.id,
            resource_type_name='document',
            request=request,
            user_role=get_role_name(user.role_id),
            details={"count": deleted_count, "failed": len(failed_ids)}
        )
    except Exception as e:
        logger.error(f"Error logging bulk delete: {e}")

    return BulkDeleteResponse(
        deleted_count=deleted_count,
        failed_ids=failed_ids,
        message=f"{deleted_count} document(s) supprimé(s)"
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    request: Request,
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
    session: AsyncSession = Depends(get_db),
):
    """
    Supprime un document et toutes ses versions.

    Cette action est irréversible.
    """
    await service.delete_document(user.id, document_id)

    # Audit
    try:
        await AuditService.log_action(
            db=session,
            action_name='document_deleted',
            user_id=user.id,
            resource_type_name='document',
            resource_id=document_id,
            request=request,
            user_role=get_role_name(user.role_id)
        )
    except Exception as e:
        logger.error(f"Error logging document deletion: {e}")

    return None


# === Download ===


@router.get("/{document_id}/download")
async def download_document(
    document_id: UUID,
    version: Optional[int] = Query(None, description="Version spécifique à télécharger"),
    user: User = Depends(current_active_user),
    service: DocumentService = Depends(get_document_service),
):
    """
    Télécharge un document.

    Par défaut, télécharge la version actuelle.
    Spécifiez **version** pour une version spécifique.
    """
    content, filename, mime_type = await service.get_download_content(
        user_id=user.id,
        document_id=document_id,
        version=version,
    )

    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )
