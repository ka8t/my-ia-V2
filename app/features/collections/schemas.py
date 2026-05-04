"""
Schemas Collections User - DTOs pour l'acces utilisateur aux collections.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel


class CollectionSummary(BaseModel):
    """Collection resumee pour l'utilisateur."""
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    type: str
    is_mine: bool
    document_count: int
    chunk_count: int
    # Stats du corpus associé (si présent)
    corpus_id: Optional[UUID] = None
    corpus_document_count: Optional[int] = None
    corpus_source_count: Optional[int] = None
    corpus_chunk_count: Optional[int] = None


class AvailableCollectionsResponse(BaseModel):
    """Collections disponibles pour l'utilisateur."""
    my_collection: Optional[CollectionSummary]
    public_collections: List[CollectionSummary]


class MyCollectionStatsResponse(BaseModel):
    """Stats detaillees de ma collection."""
    id: UUID
    name: str
    display_name: str
    document_count: int
    chunk_count: int
    chroma_count: int
    created_at: datetime


class SuggestionsResponse(BaseModel):
    """Questions suggerees pour une collection."""
    suggestions: List[str]
