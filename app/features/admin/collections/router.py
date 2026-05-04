"""
Router Admin Collections — Endpoints d'administration des Bibliothèques.

NOTE TERMINOLOGIE :
    - "Bibliothèque" = concept user-facing (conteneur de documents, affiché dans l'UI)
    - "Collection"   = réservé au niveau technique ChromaDB (stockage vectoriel)
    La table PostgreSQL reste `collections` et les routes API `/api/admin/collections`
    pour rétrocompatibilité, mais l'UI affiche "Bibliothèque" / "Library".

Endpoints:
    GET    /api/admin/collections              - Liste toutes les collections
    GET    /api/admin/collections/stats        - Statistiques globales
    POST   /api/admin/collections/public       - Creer collection publique
    POST   /api/admin/collections/sync-all     - Synchroniser toutes les collections
    GET    /api/admin/collections/{id}         - Detail collection
    PATCH  /api/admin/collections/{id}         - Modifier collection
    DELETE /api/admin/collections/{id}         - Supprimer collection publique
    POST   /api/admin/collections/{id}/sync    - Synchroniser une collection
    GET    /api/admin/collections/{id}/peek    - Apercu documents
    DELETE /api/admin/collections/{id}/documents - Vider collection
    GET    /api/admin/collections/user/{user_id} - Collection d'un utilisateur

Collection Sources (liaison sources externes <-> collections):
    GET    /api/admin/collections/{id}/sources            - Liste sources assignees
    GET    /api/admin/collections/{id}/sources/available  - Sources disponibles
    POST   /api/admin/collections/{id}/sources            - Ajouter une source
    PATCH  /api/admin/collections/{id}/sources/{source_id} - Modifier liaison
    DELETE /api/admin/collections/{id}/sources/{source_id} - Retirer source

Collection Corpus (assignation d'une collection a plusieurs corpus):
    GET    /api/admin/collections/{id}/corpus            - Liste corpus de la collection
    GET    /api/admin/collections/{id}/corpus/available  - Corpus disponibles
    POST   /api/admin/collections/{id}/corpus            - Ajouter la collection a un corpus
    POST   /api/admin/collections/{id}/corpus/bulk       - Ajouter a plusieurs corpus
    DELETE /api/admin/collections/{id}/corpus/{corpus_id} - Retirer du corpus
    DELETE /api/admin/collections/{id}/corpus/bulk       - Retirer de plusieurs corpus

Provider Index Status (état d'indexation par provider LLM):
    GET    /api/admin/collections/{id}/index-status     - État d'indexation par provider
    POST   /api/admin/collections/{id}/reindex          - Réindexer pour un provider
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_chroma_client, get_current_admin_user
from app.models import User
from app.features.admin.collections.service import AdminCollectionService
from app.features.audit.service import AuditService
from app.features.admin.collections.schemas import (
    CollectionCreateRequest,
    CollectionUpdateRequest,
    CollectionDetailResponse,
    CollectionListResponse,
    CollectionPeekResponse,
    CollectionStatsResponse,
    CollectionTypeEnum,
    ClearCollectionResponse,
    BulkCollectionRequest,
    BulkCollectionResponse,
    BulkCorpusIdsRequest,
    CollectionSyncResponse,
    BulkSyncResponse,
    CollectionSourceCreate,
    CollectionSourceUpdate,
    CollectionSourceRead,
    CollectionSourcesListResponse,
    CollectionIndexStatusResponse,
    ReindexRequest,
    ReindexResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/collections", tags=["Admin Collections"])


def get_collection_service(
    session: AsyncSession = Depends(get_db),
    chroma_client=Depends(get_chroma_client),
) -> AdminCollectionService:
    """Factory pour le service admin collections."""
    from app.core.deps import get_storage_service
    storage = get_storage_service()
    return AdminCollectionService(session=session, chroma_client=chroma_client, storage=storage)


# === Liste et Stats ===

@router.get("", response_model=CollectionListResponse)
async def list_collections(
    type: Optional[CollectionTypeEnum] = Query(None, description="Filtrer par type"),
    search: Optional[str] = Query(None, min_length=2),
    page: Optional[int] = Query(None, ge=1),
    page_size: Optional[int] = Query(None, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=100),
    offset: Optional[int] = Query(None, ge=0),
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Liste toutes les collections.

    Filtres:
    - **type**: private | public
    - **search**: Recherche dans nom/display_name

    Pagination (deux formats supportés):
    - **page/page_size**: pagination classique (1-indexed)
    - **limit/offset**: pagination par décalage
    """
    return await service.list_collections(
        type_filter=type,
        search=search,
        page=page,
        page_size=page_size,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=CollectionStatsResponse)
async def get_stats(
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """Statistiques globales des collections et ChromaDB."""
    return await service.get_global_stats()


# === CRUD Collections Publiques ===

@router.post("/public", response_model=CollectionDetailResponse, status_code=201)
async def create_public_collection(
    data: CollectionCreateRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Cree une nouvelle collection publique.

    Le nom sera prefixe par 'public_' automatiquement.
    Exemple: name='legal' -> 'public_legal'
    """
    result = await service.create_public_collection(data)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_created",
        resource_type_name="collection", resource_id=result.id,
        details={"name": data.name, "display_name": data.display_name},
        request=request, username=admin.username,
    )

    return result


# =============================================================================
# BULK OPERATIONS - AVANT les routes avec {collection_id}
# =============================================================================

@router.post("/bulk/delete", response_model=BulkCollectionResponse)
async def bulk_delete_collections(
    body: BulkCollectionRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Supprime plusieurs collections en masse (publiques et privées).

    Les conversations et documents liés sont supprimés en cascade.
    """
    if not body.confirm:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.collection_ids:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Aucune collection selectionnee"
        )

    logger.info(f"Bulk delete: {len(body.collection_ids)} collections par admin_id={admin.id}")

    result = await service.bulk_delete_collections(body.collection_ids)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="bulk_collections_deleted",
        resource_type_name="collection",
        details={
            "count": len(body.collection_ids),
            "success_count": result["success_count"],
            "failed_count": result["failed_count"],
        },
        request=request, username=admin.username,
    )

    return BulkCollectionResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} collection(s) supprimee(s)"
    )


@router.post("/bulk/clear", response_model=BulkCollectionResponse)
async def bulk_clear_collections(
    body: BulkCollectionRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Vide l'index ChromaDB de plusieurs collections (sans supprimer fichiers ni DB).

    Met à jour les compteurs de chunks.
    """
    if not body.confirm:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Confirmation requise (confirm=true)"
        )

    if not body.collection_ids:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Aucune collection selectionnee"
        )

    logger.info(f"Bulk clear: {len(body.collection_ids)} collections par admin_id={admin.id}")

    result = await service.bulk_clear_collections(body.collection_ids)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="bulk_collections_cleared",
        resource_type_name="collection",
        details={
            "count": len(body.collection_ids),
            "success_count": result["success_count"],
            "failed_count": result["failed_count"],
            "total_deleted_chunks": result.get("total_deleted_chunks", 0),
        },
        request=request, username=admin.username,
    )

    return BulkCollectionResponse(
        success_count=result["success_count"],
        failed_count=result["failed_count"],
        failed_ids=result["failed_ids"],
        message=f"{result['success_count']} collection(s) videe(s), {result.get('total_deleted_chunks', 0)} chunks supprimes"
    )


# =============================================================================
# SYNC OPERATIONS - Synchronisation des compteurs
# =============================================================================

@router.post("/sync-all", response_model=BulkSyncResponse)
async def sync_all_collections(
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Synchronise les compteurs de toutes les collections.

    Recalcule document_count et chunk_count depuis PostgreSQL et ChromaDB.
    """
    logger.info(f"Sync all collections demandé par admin_id={admin.id}")
    result = await service.sync_all_collections()
    return BulkSyncResponse(**result)


# =============================================================================
# USER COLLECTION
# =============================================================================

@router.get("/user/{user_id}", response_model=CollectionDetailResponse)
async def get_user_collection(
    user_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """Recupere la collection privee d'un utilisateur."""
    return await service.get_user_collection(user_id)


@router.post("/user/{user_id}")
async def create_user_collection(
    user_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Crée ou restaure la collection privée d'un utilisateur.

    Vérifie les orphelins :
    - Documents PostgreSQL sans collection valide
    - Collection ChromaDB existante avec chunks

    Les documents orphelins sont automatiquement réassociés.
    """
    result = await service.create_user_collection(user_id)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="user_collection_created",
        resource_type_name="collection", resource_id=UUID(result["collection_id"]),
        details={
            "target_user_id": str(user_id),
            "orphans_reassigned": result["orphans"]["documents_reassigned"]
        },
        request=request, username=admin.username,
    )

    return result


@router.get("/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection(
    collection_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """Recupere les details d'une collection avec stats ChromaDB live."""
    return await service.get_collection(collection_id)


@router.patch("/{collection_id}", response_model=CollectionDetailResponse)
async def update_collection(
    collection_id: UUID,
    data: CollectionUpdateRequest,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """Modifie une collection (display_name, description)."""
    result = await service.update_collection(collection_id, data)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_updated",
        resource_type_name="collection", resource_id=collection_id,
        details=data.model_dump(exclude_unset=True),
        request=request, username=admin.username,
    )

    return result


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Supprime une collection (publique ou privée).

    Les conversations et documents liés sont supprimés en cascade.
    """
    await service.delete_collection(collection_id)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_deleted",
        resource_type_name="collection", resource_id=collection_id,
        details={"collection_id": str(collection_id)},
        request=request, username=admin.username,
    )

    return None


@router.post("/{collection_id}/sync", response_model=CollectionSyncResponse)
async def sync_collection(
    collection_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Synchronise les compteurs d'une collection.

    Recalcule document_count et chunk_count depuis les données réelles.
    """
    logger.info(f"Sync collection {collection_id} demandé par admin_id={admin.id}")
    result = await service.sync_collection(collection_id)
    return CollectionSyncResponse(**result)


# === Documents dans Collection ===

@router.get("/{collection_id}/peek", response_model=CollectionPeekResponse)
async def peek_collection(
    collection_id: UUID,
    limit: int = Query(10, ge=1, le=100),
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """Apercu des premiers documents d'une collection."""
    return await service.peek_collection(collection_id, limit)


@router.delete("/{collection_id}/documents", response_model=ClearCollectionResponse)
async def clear_collection(
    collection_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Vide tous les documents d'une collection ChromaDB.

    **Attention**: Cette action est irreversible!
    """
    deleted = await service.clear_collection_documents(collection_id)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_cleared",
        resource_type_name="collection", resource_id=collection_id,
        details={"deleted_chunks": deleted},
        request=request, username=admin.username,
    )

    return ClearCollectionResponse(deleted_chunks=deleted)


@router.delete("/{collection_id}/index", response_model=ClearCollectionResponse)
async def clear_collection_index(
    collection_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Vide uniquement l'index ChromaDB d'une collection (conserve les fichiers et la DB).

    Supprime les chunks de tous les providers (ollama, llamacpp).
    """
    deleted = await service.clear_collection_index(collection_id)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_index_cleared",
        resource_type_name="collection", resource_id=collection_id,
        details={"deleted_chunks": deleted},
        request=request, username=admin.username,
    )

    return ClearCollectionResponse(deleted_chunks=deleted)


# =============================================================================
# COLLECTION SOURCES - Gestion des sources assignées aux collections
# =============================================================================

@router.get("/{collection_id}/sources", response_model=CollectionSourcesListResponse)
async def list_collection_sources(
    collection_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Liste toutes les sources assignées à une collection.

    Retourne les sources avec leur priorité et état d'activation pour cette collection.
    """
    return await service.list_collection_sources(collection_id)


@router.get("/{collection_id}/sources/available")
async def list_available_sources(
    collection_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Liste les sources disponibles (non encore assignées) pour une collection.

    Utile pour le formulaire d'ajout de source.
    """
    return await service.list_available_sources_for_collection(collection_id)


@router.post("/{collection_id}/sources", response_model=CollectionSourceRead, status_code=201)
async def add_source_to_collection(
    collection_id: UUID,
    data: CollectionSourceCreate,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Ajoute une source à une collection.

    La priorité détermine l'ordre de consultation des sources (1 = haute priorité).
    """
    result = await service.add_source_to_collection(collection_id, data)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_source_added",
        resource_type_name="collection", resource_id=collection_id,
        details={
            "source_id": str(data.source_id),
            "source_name": result.source_name,
            "priority": data.priority,
        },
        request=request, username=admin.username,
    )

    return result


@router.patch("/{collection_id}/sources/{source_id}", response_model=CollectionSourceRead)
async def update_collection_source(
    collection_id: UUID,
    source_id: UUID,
    data: CollectionSourceUpdate,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Met à jour une liaison source-collection.

    Permet de modifier la priorité et l'état d'activation.
    """
    result = await service.update_collection_source(collection_id, source_id, data)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_source_updated",
        resource_type_name="collection", resource_id=collection_id,
        details={
            "source_id": str(source_id),
            "changes": data.model_dump(exclude_unset=True),
        },
        request=request, username=admin.username,
    )

    return result


@router.delete("/{collection_id}/sources/{source_id}", status_code=204)
async def remove_source_from_collection(
    collection_id: UUID,
    source_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Retire une source d'une collection.

    La source reste active globalement, seule la liaison est supprimée.
    """
    await service.remove_source_from_collection(collection_id, source_id)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_source_removed",
        resource_type_name="collection", resource_id=collection_id,
        details={"source_id": str(source_id)},
        request=request, username=admin.username,
    )

    return None


# =============================================================================
# COLLECTION CORPUS - Gestion des corpus auxquels appartient la collection
# =============================================================================

@router.get("/{collection_id}/corpus")
async def list_collection_corpus(
    collection_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Liste tous les corpus auxquels appartient une collection.

    Une collection peut appartenir a plusieurs corpus thematiques.
    """
    return await service.list_collection_corpus(collection_id)


@router.get("/{collection_id}/corpus/available")
async def list_available_corpus(
    collection_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Liste les corpus disponibles (non encore assignes) pour une collection.

    Utile pour le formulaire d'ajout de corpus.
    """
    return await service.list_available_corpus_for_collection(collection_id)


@router.post("/{collection_id}/corpus", status_code=201)
async def add_collection_to_corpus(
    collection_id: UUID,
    corpus_id: UUID = Query(..., description="ID du corpus"),
    priority: int = Query(100, ge=1, le=1000, description="Priorite (1=haute, 1000=basse)"),
    request: Request = None,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Ajoute une collection a un corpus.

    La priorite determine l'ordre de consultation des collections dans le corpus.
    """
    result = await service.add_collection_to_corpus(collection_id, corpus_id, priority)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_added_to_corpus",
        resource_type_name="collection", resource_id=collection_id,
        details={
            "corpus_id": str(corpus_id),
            "corpus_name": result.get("corpus_name"),
            "priority": priority,
        },
        request=request, username=admin.username,
    )

    return result


@router.post("/{collection_id}/corpus/bulk")
async def bulk_add_collection_to_corpus(
    collection_id: UUID,
    data: BulkCorpusIdsRequest,
    request: Request = None,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Ajoute une collection a plusieurs corpus en masse.
    """
    result = await service.bulk_add_collection_to_corpus(collection_id, data.corpus_ids, data.priority)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_bulk_added_to_corpus",
        resource_type_name="collection", resource_id=collection_id,
        details={
            "corpus_count": len(data.corpus_ids),
            "success_count": result["success_count"],
            "error_count": result["error_count"],
        },
        request=request, username=admin.username,
    )

    return result


@router.delete("/{collection_id}/corpus/bulk")
async def bulk_remove_collection_from_corpus(
    collection_id: UUID,
    data: BulkCorpusIdsRequest,
    request: Request = None,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Retire une collection de plusieurs corpus en masse.
    """
    result = await service.bulk_remove_collection_from_corpus(collection_id, data.corpus_ids)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_bulk_removed_from_corpus",
        resource_type_name="collection", resource_id=collection_id,
        details={
            "corpus_count": len(data.corpus_ids),
            "success_count": result["success_count"],
            "error_count": result["error_count"],
        },
        request=request, username=admin.username,
    )

    return result


@router.delete("/{collection_id}/corpus/{corpus_id}", status_code=204)
async def remove_collection_from_corpus(
    collection_id: UUID,
    corpus_id: UUID,
    request: Request,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Retire une collection d'un corpus.

    La collection reste intacte, seule la liaison est supprimee.
    """
    await service.remove_collection_from_corpus(collection_id, corpus_id)

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_removed_from_corpus",
        resource_type_name="collection", resource_id=collection_id,
        details={"corpus_id": str(corpus_id)},
        request=request, username=admin.username,
    )

    return None


# === Provider Index Status ===

@router.get("/{collection_id}/index-status", response_model=CollectionIndexStatusResponse)
async def get_collection_index_status(
    collection_id: UUID,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
):
    """
    Retourne l'état d'indexation d'une collection par provider.

    Affiche le nombre de chunks indexés pour chaque provider LLM
    (ollama, llamacpp) et indique le provider actuellement actif.
    """
    return await service.get_collection_index_status(collection_id)


@router.post("/{collection_id}/reindex", response_model=ReindexResponse)
async def reindex_collection_for_provider(
    collection_id: UUID,
    request_body: ReindexRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    admin: User = Depends(get_current_admin_user),
    service: AdminCollectionService = Depends(get_collection_service),
    db: AsyncSession = Depends(get_db),
):
    """
    Lance la réindexation d'une collection pour un provider spécifique.

    Permet d'indexer les documents avec un provider différent du provider actif,
    ou de forcer une réindexation si les embeddings sont obsolètes.

    La réindexation est asynchrone : utilisez l'endpoint index-status pour suivre
    la progression.
    """
    # Préparer les données pour la réindexation
    result = await service.prepare_collection_reindex(
        collection_id, request_body.provider, request_body.force
    )

    # Si des documents ou sources à réindexer, lancer en background
    total_items = result.documents_count + result.sources_count
    if result.status == "started" and total_items > 0:
        background_tasks.add_task(
            _run_collection_reindex_in_background,
            collection_id=collection_id,
            provider=request_body.provider,
            document_ids=result.document_ids or [],
            source_ids=result.source_ids or [],
            collection_name=result.collection_name,
        )

    await AuditService.log_action(
        db=db, user_id=admin.id, action_name="collection_reindex_requested",
        resource_type_name="collection", resource_id=collection_id,
        details={
            "provider": request_body.provider,
            "force": request_body.force,
            "status": result.status,
            "documents_count": result.documents_count,
            "sources_count": result.sources_count,
        },
        request=request, username=admin.username,
    )

    return result


async def _run_collection_reindex_in_background(
    collection_id: UUID,
    provider: str,
    document_ids: list,
    source_ids: list,
    collection_name: str,
) -> None:
    """
    Tâche de fond pour la réindexation d'une collection vers un provider spécifique.

    Utilise ReindexManager pour le suivi de progression et support d'annulation.
    Réindexe les documents ET les sources du corpus de la collection.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    from app.core.config import settings
    from app.core.deps import get_chroma_client as _get_chroma, get_storage_service as _get_storage
    from app.features.admin.documents.service import AdminDocumentService
    from app.features.sources.scheduler import reindex_source
    from app.common.utils.reindex import ReindexManager, set_doc_reindex_progress, is_doc_cancel_requested, is_source_cancel_requested
    from app.models import Document, ContextSource

    collection_id_str = str(collection_id)
    total_docs = len(document_ids)
    total_sources = len(source_ids)
    total_items = total_docs + total_sources

    logger.info(
        f"Démarrage réindexation collection {collection_name} "
        f"vers provider {provider}: {total_docs} documents, {total_sources} sources"
    )

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    bg_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    success_count = 0
    error_count = 0

    try:
        async with bg_session_maker() as db:
            # Créer le service documents
            chroma_client = _get_chroma()
            storage_service = _get_storage()
            doc_service = AdminDocumentService(
                session=db,
                storage_service=storage_service,
                chroma_client=chroma_client,
            )

            for idx, doc_id in enumerate(document_ids):
                doc_id_str = str(doc_id)

                # Vérifier annulation
                if is_doc_cancel_requested(doc_id_str):
                    logger.info(f"Réindexation annulée pour document {doc_id}")
                    continue

                try:
                    # Mettre à jour la progression
                    progress = int((idx / total_docs) * 100)
                    set_doc_reindex_progress(
                        doc_id_str, progress, f"reindexing_{provider}",
                        corpus_id=collection_id_str
                    )

                    # Charger le document
                    result = await db.execute(
                        select(Document)
                        .options(selectinload(Document.collection))
                        .where(Document.id == doc_id)
                    )
                    document = result.scalar_one_or_none()

                    if not document:
                        logger.warning(f"Document {doc_id} non trouvé")
                        error_count += 1
                        continue

                    # Réindexer avec le provider spécifique
                    reindex_result = await doc_service._reindex_document_internal(
                        document,
                        track_progress=True,
                        cancel_check=lambda did=doc_id_str: is_doc_cancel_requested(did),
                        provider=provider,
                    )

                    if reindex_result.get("success"):
                        success_count += 1
                        set_doc_reindex_progress(
                            doc_id_str, 100, "complete",
                            status="success",
                            documents_count=reindex_result.get("new_chunk_count", 0),
                            corpus_id=collection_id_str
                        )
                    elif reindex_result.get("cancelled"):
                        logger.info(f"Document {doc_id} annulé")
                    else:
                        error_count += 1
                        set_doc_reindex_progress(
                            doc_id_str, 0, "failed",
                            status="failed",
                            error_message=reindex_result.get("message", "Erreur inconnue"),
                            corpus_id=collection_id_str
                        )

                except Exception as e:
                    error_count += 1
                    logger.error(f"Erreur réindexation document {doc_id}: {e}")
                    set_doc_reindex_progress(
                        doc_id_str, 0, "error",
                        status="failed",
                        error_message=str(e),
                        corpus_id=collection_id_str
                    )

            await db.commit()

            # === Réindexation des sources ===
            for idx, source_id in enumerate(source_ids):
                source_id_str = str(source_id)

                # Vérifier annulation
                if is_source_cancel_requested(source_id_str):
                    logger.info(f"Réindexation annulée pour source {source_id}")
                    continue

                try:
                    # Charger la source
                    result = await db.execute(
                        select(ContextSource).where(ContextSource.id == source_id)
                    )
                    source = result.scalar_one_or_none()

                    if not source:
                        logger.warning(f"Source {source_id} non trouvée")
                        error_count += 1
                        continue

                    # Réindexer la source
                    await reindex_source(
                        db=db,
                        source=source,
                        trigger_type="manual",
                        triggered_by=None
                    )
                    success_count += 1

                except Exception as e:
                    error_count += 1
                    logger.error(f"Erreur réindexation source {source_id}: {e}")

            await db.commit()

        logger.info(
            f"Réindexation collection {collection_name} terminée: "
            f"{success_count} succès, {error_count} erreurs"
        )

    except Exception as e:
        logger.error(f"Erreur réindexation collection {collection_id}: {e}")
    finally:
        await engine.dispose()
