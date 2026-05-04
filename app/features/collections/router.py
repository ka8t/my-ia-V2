"""
Router Collections User - Endpoints utilisateur pour les collections.

Endpoints:
    GET /api/collections                        - Collections disponibles
    GET /api/collections/mine                   - Stats de ma collection
    GET /api/collections/{id}/suggestions       - Suggestions de questions
"""

import logging
from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_chroma_client
from app.models import User
from app.features.auth.service import current_active_user
from app.features.collections.service import CollectionService
from app.features.collections.schemas import (
    AvailableCollectionsResponse,
    MyCollectionStatsResponse,
    SuggestionsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/collections", tags=["Collections"])


def get_collection_service(
    session: AsyncSession = Depends(get_db),
    chroma_client=Depends(get_chroma_client),
) -> CollectionService:
    """Factory pour le service collections."""
    return CollectionService(session=session, chroma_client=chroma_client)


@router.get("", response_model=AvailableCollectionsResponse)
async def get_available_collections(
    user: User = Depends(current_active_user),
    service: CollectionService = Depends(get_collection_service),
):
    """
    Liste les collections disponibles pour l'utilisateur.

    Retourne:
    - Ma bibliothèque privée (si existe)
    - Toutes les collections publiques
    """
    return await service.get_available_collections(user)


@router.get("/mine", response_model=MyCollectionStatsResponse)
async def get_my_collection(
    user: User = Depends(current_active_user),
    service: CollectionService = Depends(get_collection_service),
):
    """Stats detaillees de ma collection privee."""
    return await service.get_my_collection_stats(user)


@router.get("/{collection_id}/suggestions", response_model=SuggestionsResponse)
async def get_collection_suggestions(
    collection_id: UUID,
    refresh: bool = Query(False, description="Forcer la regeneration du cache"),
    user: User = Depends(current_active_user),
    service: CollectionService = Depends(get_collection_service),
):
    """
    Recupere les questions suggerees pour une collection.

    Les suggestions sont generees via Ollama en fonction des documents
    de la collection et mises en cache pendant 24h.

    Args:
        collection_id: ID de la collection
        refresh: Forcer la regeneration meme si le cache est valide
    """
    # Verifier l'acces a la collection
    can_access = await service.can_access_collection(user, collection_id)
    if not can_access:
        raise HTTPException(status_code=403, detail="Acces refuse a cette collection")

    suggestions = await service.get_suggestions(collection_id, force_refresh=refresh)
    return SuggestionsResponse(suggestions=suggestions)
