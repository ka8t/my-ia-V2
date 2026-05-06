"""
Router Admin Corpus - Endpoints d'administration des corpus.

Endpoints CRUD Corpus:
    GET    /api/admin/corpus              - Liste tous les corpus
    POST   /api/admin/corpus              - Creer un corpus
    POST   /api/admin/corpus/bulk/delete  - Supprimer plusieurs corpus
    POST   /api/admin/corpus/bulk/reindex - Reindexer plusieurs corpus
    GET    /api/admin/corpus/{id}         - Detail corpus
    PATCH  /api/admin/corpus/{id}         - Modifier corpus
    DELETE /api/admin/corpus/{id}         - Supprimer corpus

Gestion des collections du corpus:
    GET    /api/admin/corpus/{id}/collections            - Liste collections
    GET    /api/admin/corpus/{id}/collections/available  - Collections disponibles
    POST   /api/admin/corpus/{id}/collections            - Ajouter collection
    PATCH  /api/admin/corpus/{id}/collections/{coll_id}  - Modifier priorite
    DELETE /api/admin/corpus/{id}/collections/{coll_id}  - Retirer collection

Gestion des sources du corpus:
    GET    /api/admin/corpus/{id}/sources            - Liste sources
    GET    /api/admin/corpus/{id}/sources/available  - Sources disponibles
    POST   /api/admin/corpus/{id}/sources            - Ajouter source
    PATCH  /api/admin/corpus/{id}/sources/{src_id}   - Modifier liaison
    DELETE /api/admin/corpus/{id}/sources/{src_id}   - Retirer source

Gestion des documents du corpus:
    GET    /api/admin/corpus/{id}/documents            - Liste documents
    GET    /api/admin/corpus/{id}/documents/available  - Documents disponibles
    POST   /api/admin/corpus/{id}/documents            - Ajouter document
    DELETE /api/admin/corpus/{id}/documents/{doc_id}   - Retirer document

Réindexation:
    POST   /api/admin/corpus/{id}/reindex  - Réindexer documents et sources
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_admin_user, get_chroma_client, get_storage_service
from app.models import User
from app.features.admin.corpus.service import AdminCorpusService
from app.features.admin.corpus.reindex_tasks import (
    run_doc_reindex_in_background,
    run_source_reindex_in_background,
)
from app.features.system.service import SystemConfigService
from app.features.audit.service import AuditService
from app.features.admin.corpus.schemas import (
    CorpusCreateRequest,
    CorpusUpdateRequest,
    CorpusResponse,
    CorpusDetailResponse,
    CorpusListResponse,
    CorpusCollectionAdd,
    CorpusCollectionUpdate,
    CorpusCollectionRead,
    CorpusCollectionsListResponse,
    CorpusSourceAdd,
    CorpusSourceUpdate,
    CorpusSourceRead,
    CorpusSourcesListResponse,
    AvailableCollectionRead,
    AvailableSourceRead,
    BulkCollectionsAddRequest,
    BulkCollectionsRemoveRequest,
    BulkSourcesAddRequest,
    BulkSourcesRemoveRequest,
    BulkOperationResult,
    CorpusDocumentRead,
    CorpusDocumentsListResponse,
    AvailableDocumentRead,
    CorpusDocumentAdd,
    BulkDocumentsAddRequest,
    BulkDocumentsRemoveRequest,
    BulkCorpusDeleteRequest,
    BulkCorpusDeleteResponse,
    BulkCorpusReindexRequest,
    BulkCorpusReindexResponse,
    CorpusReindexResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/corpus", tags=["Admin Corpus"])


def get_corpus_service(
    session: AsyncSession = Depends(get_db),
    storage = Depends(get_storage_service),
    chroma = Depends(get_chroma_client),
) -> AdminCorpusService:
    """Factory pour le service admin corpus."""
    return AdminCorpusService(
        session=session,
        storage_service=storage,
        chroma_client=chroma,
    )


# =============================================================================
# CRUD Corpus
# =============================================================================

@router.get("", response_model=CorpusListResponse)
async def list_corpus(
    search: Optional[str] = Query(None, min_length=2),
    is_active: Optional[bool] = Query(None, description="Filtrer par statut actif"),
    page: Optional[int] = Query(None, ge=1),
    page_size: Optional[int] = Query(None, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=100),
    offset: Optional[int] = Query(None, ge=0),
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """
    Liste tous les corpus.

    Filtres:
    - **search**: Recherche dans nom/display_name
    - **is_active**: Filtrer par statut actif/inactif

    Pagination (deux formats supportés):
    - **page/page_size**: pagination classique (1-indexed)
    - **limit/offset**: pagination par décalage

    Note: sources_count est filtré par provider courant pour cohérence avec la modale.
    """
    # Récupérer le provider courant pour filtrer sources_count
    config_service = SystemConfigService(db)
    current_provider = await config_service.get("llm.provider", "ollama")

    return await service.list_corpus(
        search=search,
        is_active=is_active,
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
        provider_filter=current_provider,
    )


@router.post("", response_model=CorpusResponse, status_code=201)
async def create_corpus(
    data: CorpusCreateRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Cree un nouveau corpus.

    Le nom doit etre unique et suivre le format slug (lettres minuscules, chiffres, underscores).
    """
    result = await service.create_corpus(data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_created",
        resource_type_name="corpus",
        resource_id=result.id,
        details={"corpus_name": result.name, "display_name": result.display_name},
        request=request,
    )

    return result


@router.get("/{corpus_id}", response_model=CorpusDetailResponse)
async def get_corpus(
    corpus_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Recupere les details d'un corpus avec ses collections et sources."""
    return await service.get_corpus(corpus_id)


@router.patch("/{corpus_id}", response_model=CorpusResponse)
async def update_corpus(
    corpus_id: UUID,
    data: CorpusUpdateRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Modifie un corpus."""
    result = await service.update_corpus(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_updated",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={"changes": data.model_dump(exclude_unset=True)},
        request=request,
    )

    return result


@router.delete("/{corpus_id}", status_code=204)
async def delete_corpus(
    corpus_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Supprime un corpus avec tout son contenu (documents, sources, collections)."""
    # Recuperer le nom avant suppression pour l'audit
    corpus = await service.get_corpus(corpus_id)
    corpus_name = corpus.name

    await service.delete_corpus(corpus_id)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_deleted",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={"corpus_name": corpus_name},
        request=request,
    )


@router.delete("/{corpus_id}/index")
async def clear_corpus_index(
    corpus_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Vide uniquement les index ChromaDB d'un corpus (documents + sources).

    Ne supprime pas les fichiers ni les enregistrements DB.
    Cascade : tous les documents et sources du corpus sont vidés de ChromaDB.
    """
    result = await service.clear_corpus_index(corpus_id)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_index_cleared",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "documents_cleared": result["documents_cleared"],
            "sources_cleared": result["sources_cleared"],
            "total_chunks": result["total_chunks"],
        },
        request=request,
    )

    return result


@router.post("/bulk/delete", response_model=BulkCorpusDeleteResponse)
async def bulk_delete_corpus(
    data: BulkCorpusDeleteRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Supprime plusieurs corpus en masse.

    Body:
    - corpus_ids: Liste des UUIDs des corpus a supprimer (max 100)
    - confirm: Doit etre true pour confirmer la suppression
    """
    if not data.confirm:
        raise HTTPException(status_code=400, detail="Confirmation requise (confirm=true)")

    result = await service.bulk_delete_corpus(data.corpus_ids)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_bulk_deleted",
        resource_type_name="corpus",
        resource_id=None,
        details={
            "action": "bulk_delete_corpus",
            "requested_count": len(data.corpus_ids),
            "deleted_count": result.success_count,
            "error_count": result.error_count,
        },
        request=request,
    )

    logger.info(
        f"Bulk delete corpus: requested={len(data.corpus_ids)} "
        f"deleted={result.success_count} by {admin.email}"
    )

    return BulkCorpusDeleteResponse(
        success_count=result.success_count,
        error_count=result.error_count,
        errors=result.errors,
    )


@router.post("/bulk/reindex", response_model=BulkCorpusReindexResponse)
async def bulk_reindex_corpus(
    data: BulkCorpusReindexRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Lance la reindexation de plusieurs corpus en masse.

    Body:
    - corpus_ids: Liste des UUIDs des corpus a reindexer (max 50)

    Chaque corpus lance la reindexation de ses documents et sources.
    L'operation est asynchrone, utilisez les endpoints de statut pour suivre.
    """
    from app.common.utils.reindex import get_doc_reindex_progress, ReindexManager
    from app.features.sources.history import IndexationHistoryService

    success_count = 0
    error_count = 0
    total_documents = 0
    total_sources = 0
    corpus_results = []
    errors = []

    for corpus_id in data.corpus_ids:
        try:
            # Recuperer les elements du corpus
            items = await service.get_corpus_reindex_items(corpus_id)
            corpus = items["corpus"]
            document_ids = items["document_ids"]
            source_ids = items["source_ids"]

            if not document_ids and not source_ids:
                corpus_results.append({
                    "corpus_id": str(corpus_id),
                    "corpus_name": corpus.name,
                    "status": "skipped",
                    "message": "Aucun element a reindexer",
                    "documents_count": 0,
                    "sources_count": 0,
                })
                continue

            docs_queued = 0
            sources_queued = 0

            # Ajouter les documents a la queue
            for doc_id in document_ids:
                progress = get_doc_reindex_progress(str(doc_id))
                if progress.get("status") == "running":
                    continue
                background_tasks.add_task(
                    run_doc_reindex_in_background,
                    document_id=doc_id,
                    corpus_id=corpus_id,
                )
                docs_queued += 1

            # Ajouter les sources a la queue
            for source_id in source_ids:
                log_entry = await IndexationHistoryService.start_indexation(
                    db=db,
                    source_id=source_id,
                    trigger_type="bulk_corpus_reindex",
                    triggered_by=str(admin.id)
                )
                background_tasks.add_task(
                    run_source_reindex_in_background,
                    source_id=source_id,
                    triggered_by=str(admin.id),
                    log_id=str(log_entry.id),
                    corpus_id=corpus_id,
                )
                sources_queued += 1

            total_documents += docs_queued
            total_sources += sources_queued
            success_count += 1

            corpus_results.append({
                "corpus_id": str(corpus_id),
                "corpus_name": corpus.name,
                "status": "started",
                "documents_count": docs_queued,
                "sources_count": sources_queued,
            })

        except HTTPException as e:
            error_count += 1
            errors.append(f"{corpus_id}: {e.detail}")
        except Exception as e:
            error_count += 1
            logger.error(f"Erreur reindex corpus {corpus_id}: {e}")
            errors.append(f"{corpus_id}: {str(e)}")

    # Commit pour les entrées d'historique
    if total_sources > 0:
        await db.commit()

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_bulk_reindex_started",
        resource_type_name="corpus",
        resource_id=None,
        details={
            "action": "bulk_reindex_corpus",
            "requested_count": len(data.corpus_ids),
            "started_count": success_count,
            "total_documents": total_documents,
            "total_sources": total_sources,
        },
        request=request,
    )

    logger.info(
        f"Bulk reindex corpus: {success_count} started, "
        f"{total_documents} docs, {total_sources} sources by {admin.email}"
    )

    return BulkCorpusReindexResponse(
        success_count=success_count,
        error_count=error_count,
        total_documents=total_documents,
        total_sources=total_sources,
        corpus_results=corpus_results,
        errors=errors,
    )


# =============================================================================
# Gestion des collections du corpus
# =============================================================================

@router.get("/{corpus_id}/collections", response_model=CorpusCollectionsListResponse)
async def list_corpus_collections(
    corpus_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Liste les collections d'un corpus, ordonnees par priorite."""
    return await service.list_corpus_collections(corpus_id)


@router.get("/{corpus_id}/collections/available", response_model=List[AvailableCollectionRead])
async def list_available_collections(
    corpus_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Liste les collections publiques non encore dans le corpus."""
    return await service.list_available_collections(corpus_id)


@router.post("/{corpus_id}/collections", response_model=CorpusCollectionRead, status_code=201)
async def add_collection_to_corpus(
    corpus_id: UUID,
    data: CorpusCollectionAdd,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Ajoute une collection publique a un corpus.

    Seules les collections publiques peuvent etre ajoutees.
    """
    result = await service.add_collection_to_corpus(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_collection_added",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "collection_id": str(data.collection_id),
            "collection_name": result.collection_name,
            "priority": data.priority,
        },
        request=request,
    )

    return result


@router.patch("/{corpus_id}/collections/{collection_id}", response_model=CorpusCollectionRead)
async def update_corpus_collection(
    corpus_id: UUID,
    collection_id: UUID,
    data: CorpusCollectionUpdate,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Modifie la priorite d'une collection dans un corpus."""
    return await service.update_corpus_collection(corpus_id, collection_id, data)


@router.delete("/{corpus_id}/collections/{collection_id}", status_code=204)
async def remove_collection_from_corpus(
    corpus_id: UUID,
    collection_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Retire une collection d'un corpus."""
    await service.remove_collection_from_corpus(corpus_id, collection_id)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_collection_removed",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={"collection_id": str(collection_id)},
        request=request,
    )


# =============================================================================
# Gestion des sources du corpus
# =============================================================================

@router.get("/{corpus_id}/sources", response_model=CorpusSourcesListResponse)
async def list_corpus_sources(
    corpus_id: UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Liste les sources d'un corpus, ordonnees par priorite.

    Filtre automatiquement par provider courant.
    """
    # Récupérer le provider courant
    config_service = SystemConfigService(db)
    current_provider = await config_service.get("llm.provider", "ollama")

    return await service.list_corpus_sources(corpus_id, provider_filter=current_provider)


@router.get("/{corpus_id}/sources/available", response_model=List[AvailableSourceRead])
async def list_available_sources(
    corpus_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Liste les sources non encore dans le corpus."""
    return await service.list_available_sources(corpus_id)


@router.post("/{corpus_id}/sources", response_model=CorpusSourceRead, status_code=201)
async def add_source_to_corpus(
    corpus_id: UUID,
    data: CorpusSourceAdd,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Ajoute une source a un corpus."""
    result = await service.add_source_to_corpus(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_source_added",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "source_id": str(data.source_id),
            "source_name": result.source_name,
            "priority": data.priority,
            "is_enabled": data.is_enabled,
        },
        request=request,
    )

    return result


# -----------------------------------------------------------------------------
# Sources - Operations BULK (IMPORTANT: ces routes /bulk doivent etre AVANT
# les routes avec /{source_id} pour eviter les conflits de routage FastAPI)
# -----------------------------------------------------------------------------

@router.post("/{corpus_id}/sources/bulk", response_model=BulkOperationResult)
async def bulk_add_sources(
    corpus_id: UUID,
    data: BulkSourcesAddRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Ajoute plusieurs sources a un corpus en une seule operation.

    Chaque source est ajoutee individuellement. Les erreurs sont collectees
    mais n'empechent pas les autres ajouts.
    """
    result = await service.bulk_add_sources(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_sources_bulk_added",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "source_ids": [str(sid) for sid in data.source_ids],
            "success_count": result.success_count,
            "error_count": result.error_count,
        },
        request=request,
    )

    return result


@router.delete("/{corpus_id}/sources/bulk", response_model=BulkOperationResult)
async def bulk_remove_sources(
    corpus_id: UUID,
    data: BulkSourcesRemoveRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Retire plusieurs sources d'un corpus en une seule operation.

    Chaque source est retiree individuellement. Les erreurs sont collectees
    mais n'empechent pas les autres retraits.
    """
    result = await service.bulk_remove_sources(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_sources_bulk_removed",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "source_ids": [str(sid) for sid in data.source_ids],
            "success_count": result.success_count,
            "error_count": result.error_count,
        },
        request=request,
    )

    return result


# -----------------------------------------------------------------------------
# Sources - Operations sur une source specifique (routes avec /{source_id})
# -----------------------------------------------------------------------------

@router.patch("/{corpus_id}/sources/{source_id}", response_model=CorpusSourceRead)
async def update_corpus_source(
    corpus_id: UUID,
    source_id: UUID,
    data: CorpusSourceUpdate,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Modifie une source dans un corpus (priorite, activation)."""
    result = await service.update_corpus_source(corpus_id, source_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_source_updated",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "source_id": str(source_id),
            "changes": data.model_dump(exclude_unset=True),
        },
        request=request,
    )

    return result


@router.delete("/{corpus_id}/sources/{source_id}", status_code=204)
async def remove_source_from_corpus(
    corpus_id: UUID,
    source_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Retire une source d'un corpus."""
    await service.remove_source_from_corpus(corpus_id, source_id)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_source_removed",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={"source_id": str(source_id)},
        request=request,
    )


# =============================================================================
# Operations BULK - Collections
# =============================================================================

@router.post("/{corpus_id}/collections/bulk", response_model=BulkOperationResult)
async def bulk_add_collections(
    corpus_id: UUID,
    data: BulkCollectionsAddRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Ajoute plusieurs collections a un corpus en une seule operation.

    Chaque collection est ajoutee individuellement. Les erreurs sont collectees
    mais n'empechent pas les autres ajouts.
    """
    result = await service.bulk_add_collections(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_collections_bulk_added",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "collection_ids": [str(cid) for cid in data.collection_ids],
            "success_count": result.success_count,
            "error_count": result.error_count,
        },
        request=request,
    )

    return result


@router.delete("/{corpus_id}/collections/bulk", response_model=BulkOperationResult)
async def bulk_remove_collections(
    corpus_id: UUID,
    data: BulkCollectionsRemoveRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Retire plusieurs collections d'un corpus en une seule operation.

    Chaque collection est retiree individuellement. Les erreurs sont collectees
    mais n'empechent pas les autres retraits.
    """
    result = await service.bulk_remove_collections(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_collections_bulk_removed",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "collection_ids": [str(cid) for cid in data.collection_ids],
            "success_count": result.success_count,
            "error_count": result.error_count,
        },
        request=request,
    )

    return result


# =============================================================================
# Gestion des documents du corpus
# =============================================================================

@router.get("/{corpus_id}/documents", response_model=CorpusDocumentsListResponse)
async def list_corpus_documents(
    corpus_id: UUID,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Liste les documents d'un corpus.

    Filtre automatiquement par provider courant.
    """
    # Récupérer le provider courant
    config_service = SystemConfigService(db)
    current_provider = await config_service.get("llm.provider", "ollama")

    return await service.list_corpus_documents(corpus_id, provider_filter=current_provider)


@router.get("/{corpus_id}/documents/available", response_model=List[AvailableDocumentRead])
async def list_available_documents(
    corpus_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """Liste les documents disponibles pour ajout au corpus."""
    return await service.list_available_documents(corpus_id)


@router.post("/{corpus_id}/documents", response_model=CorpusDocumentRead, status_code=201)
async def add_document_to_corpus(
    corpus_id: UUID,
    data: CorpusDocumentAdd,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Ajoute un document a un corpus."""
    result = await service.add_document_to_corpus(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_document_added",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "document_id": str(data.document_id),
            "document_name": result.filename,
        },
        request=request,
    )

    return result


# -----------------------------------------------------------------------------
# Documents - Operations BULK (IMPORTANT: ces routes /bulk doivent etre AVANT
# les routes avec /{document_id} pour eviter les conflits de routage FastAPI)
# -----------------------------------------------------------------------------

@router.post("/{corpus_id}/documents/bulk", response_model=BulkOperationResult)
async def bulk_add_documents(
    corpus_id: UUID,
    data: BulkDocumentsAddRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Ajoute plusieurs documents a un corpus."""
    result = await service.bulk_add_documents(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_documents_bulk_added",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "document_ids": [str(did) for did in data.document_ids],
            "success_count": result.success_count,
            "error_count": result.error_count,
        },
        request=request,
    )

    return result


@router.delete("/{corpus_id}/documents/bulk", response_model=BulkOperationResult)
async def bulk_remove_documents(
    corpus_id: UUID,
    data: BulkDocumentsRemoveRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Retire plusieurs documents d'un corpus."""
    result = await service.bulk_remove_documents(corpus_id, data)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_documents_bulk_removed",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "document_ids": [str(did) for did in data.document_ids],
            "success_count": result.success_count,
            "error_count": result.error_count,
        },
        request=request,
    )

    return result


# -----------------------------------------------------------------------------
# Documents - Operations sur un document specifique (routes avec /{document_id})
# -----------------------------------------------------------------------------

@router.delete("/{corpus_id}/documents/{document_id}", status_code=204)
async def remove_document_from_corpus(
    corpus_id: UUID,
    document_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """Retire un document d'un corpus."""
    await service.remove_document_from_corpus(corpus_id, document_id)

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_document_removed",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={"document_id": str(document_id)},
        request=request,
    )


# =============================================================================
# REINDEX - Réindexation du corpus
# =============================================================================

@router.post("/{corpus_id}/reindex", response_model=CorpusReindexResponse)
async def reindex_corpus(
    corpus_id: UUID,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_current_admin_user),
    service: AdminCorpusService = Depends(get_corpus_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Lance la réindexation de tous les documents et sources d'un corpus.

    L'opération utilise le système de queue existant:
    - Chaque document est ajouté à la queue de réindexation (avec suivi de progression)
    - Chaque source est ajoutée à la queue de synchronisation (avec historique)

    Utiliser les endpoints de statut individuels pour suivre la progression.
    """
    from app.common.utils.reindex import get_doc_reindex_progress

    # Récupérer les éléments à réindexer
    items = await service.get_corpus_reindex_items(corpus_id)
    corpus = items["corpus"]
    document_ids = items["document_ids"]
    source_ids = items["source_ids"]

    if not document_ids and not source_ids:
        return CorpusReindexResponse(
            corpus_id=corpus_id,
            corpus_name=corpus.name,
            status="completed",
            documents_count=0,
            sources_count=0,
            message="Aucun élément à réindexer dans ce corpus",
        )

    # Compteurs et IDs pour le retour
    docs_queued = 0
    sources_queued = 0
    queued_doc_ids = []
    queued_source_ids = []
    errors = []

    # 1. Ajouter chaque document à la queue de réindexation
    for doc_id in document_ids:
        # Vérifier qu'une réindexation n'est pas déjà en cours
        progress = get_doc_reindex_progress(str(doc_id))
        if progress.get("status") == "running":
            errors.append(f"Document {doc_id} déjà en cours de réindexation")
            continue

        # Ajouter à la queue
        background_tasks.add_task(
            run_doc_reindex_in_background,
            document_id=doc_id,
            corpus_id=corpus_id,
        )
        docs_queued += 1
        queued_doc_ids.append(doc_id)

    # 2. Ajouter chaque source à la queue de synchronisation
    # Créer l'entrée d'historique AVANT la tâche de fond pour que le polling fonctionne
    from app.features.sources.history import IndexationHistoryService
    source_log_ids = []
    for source_id in source_ids:
        # Créer l'entrée d'historique immédiatement (status=running)
        log_entry = await IndexationHistoryService.start_indexation(
            db=db,
            source_id=source_id,
            trigger_type="corpus_reindex",
            triggered_by=str(admin.id)
        )
        source_log_ids.append((source_id, str(log_entry.id)))
        sources_queued += 1
        queued_source_ids.append(source_id)

    # Commit pour que le polling puisse voir les entrées immédiatement
    if source_log_ids:
        await db.commit()

    # Lancer les tâches de fond après le commit
    for source_id, log_id in source_log_ids:
        background_tasks.add_task(
            run_source_reindex_in_background,
            source_id=source_id,
            triggered_by=str(admin.id),
            log_id=log_id,
            corpus_id=corpus_id,
        )

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_reindex_started",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={
            "documents_queued": docs_queued,
            "sources_queued": sources_queued,
            "skipped_count": len(errors),
        },
        request=request,
    )

    status_msg = f"Réindexation lancée: {docs_queued} documents et {sources_queued} sources en queue"
    if errors:
        status_msg += f" ({len(errors)} éléments ignorés)"

    return CorpusReindexResponse(
        corpus_id=corpus_id,
        corpus_name=corpus.name,
        status="started",
        documents_count=docs_queued,
        sources_count=sources_queued,
        message=status_msg,
        document_ids=queued_doc_ids,
        source_ids=queued_source_ids,
    )


@router.post("/{corpus_id}/reindex/cancel")
async def cancel_corpus_reindex(
    corpus_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
    service: AdminCorpusService = Depends(get_corpus_service),
):
    """
    Annule la réindexation en cours pour un corpus.

    Annule en cascade tous les documents et sources du corpus qui sont
    en cours de réindexation.
    """
    from app.common.utils.reindex import ReindexManager

    # Vérifier que le corpus existe
    corpus = await service.get_corpus(corpus_id)
    if not corpus:
        raise HTTPException(status_code=404, detail="Corpus non trouvé")

    # Demander l'annulation en cascade
    cancelled_count = ReindexManager.request_corpus_cancel(str(corpus_id))

    if cancelled_count == 0:
        raise HTTPException(
            status_code=400,
            detail="Aucune réindexation en cours pour ce corpus"
        )

    # Audit
    await AuditService.log_action(
        db,
        user_id=admin.id,
        action_name="corpus_reindex_cancelled",
        resource_type_name="corpus",
        resource_id=corpus_id,
        details={"cancelled_items": cancelled_count},
        request=request,
    )

    logger.info(f"Corpus reindex cancelled: {corpus_id} ({cancelled_count} items) by admin_id={admin.id}")

    return {
        "success": True,
        "message": f"Annulation demandée pour {cancelled_count} élément(s)",
        "corpus_id": str(corpus_id),
        "cancelled_count": cancelled_count,
    }


