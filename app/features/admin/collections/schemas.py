"""
Schemas Admin Collections - DTOs pour l'administration des collections ChromaDB.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum


class CollectionTypeEnum(str, Enum):
    """Type de collection."""
    PRIVATE = "private"
    PUBLIC = "public"


class SpaceTypeEnum(str, Enum):
    """Type d'espace vectoriel ChromaDB."""
    COSINE = "cosine"
    L2 = "l2"
    IP = "ip"


# === Requests ===

class CollectionCreateRequest(BaseModel):
    """Creation d'une collection publique."""
    name: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_]{2,49}$",
        description="Slug technique (sans 'public_')"
    )
    display_name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    space: SpaceTypeEnum = SpaceTypeEnum.COSINE


class CollectionUpdateRequest(BaseModel):
    """Modification d'une collection."""
    display_name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    corpus_id: Optional[UUID] = Field(None, description="ID du corpus assigne (null pour retirer)")


# === Responses ===

class CollectionResponse(BaseModel):
    """Reponse collection basique."""
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    type: CollectionTypeEnum
    owner_id: Optional[UUID]
    owner_username: Optional[str] = None
    space: str
    document_count: int
    chunk_count: int
    embedding_model: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Relation 1-1 : corpus assigne via Collection.corpus_id
    corpus_id: Optional[UUID] = None
    corpus_name: Optional[str] = None
    corpus_display_name: Optional[str] = None
    # Stats du corpus assigne (totaux documents + sources)
    corpus_document_count: Optional[int] = None
    corpus_source_count: Optional[int] = None
    corpus_chunk_count: Optional[int] = None

    class Config:
        from_attributes = True


class CollectionDetailResponse(CollectionResponse):
    """Reponse collection avec stats ChromaDB live."""
    chroma_count: int
    chroma_available: bool


class CollectionListResponse(BaseModel):
    """Liste paginee de collections."""
    collections: List[CollectionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    current_embedding_model: str = ""
    active_provider: str = "ollama"  # Provider actif (ollama/llamacpp)


class CollectionPeekResponse(BaseModel):
    """Apercu des documents d'une collection."""
    collection_id: UUID
    collection_name: str
    total_chunks: int
    samples: List[dict]


class CollectionStatsResponse(BaseModel):
    """Statistiques globales collections."""
    total_collections: int
    public_collections: int
    private_collections: int
    total_chunks: int
    chroma_version: str
    chroma_heartbeat: int


class ClearCollectionResponse(BaseModel):
    """Reponse apres vidage d'une collection."""
    deleted_chunks: int


# =============================================================================
# BULK OPERATIONS
# =============================================================================

class BulkCollectionRequest(BaseModel):
    """Requete pour operations en masse sur les collections."""
    collection_ids: List[UUID] = Field(..., min_length=1, description="Liste des IDs de collections")
    confirm: bool = Field(False, description="Confirmation requise pour l'operation")


class BulkCorpusIdsRequest(BaseModel):
    """Requete pour operations bulk avec liste de corpus IDs."""
    corpus_ids: List[UUID] = Field(..., min_length=1, description="Liste des IDs de corpus")
    priority: int = Field(100, ge=1, le=1000, description="Priorite pour tous (ajout seulement)")


class BulkCollectionResponse(BaseModel):
    """Reponse pour operations en masse sur les collections."""
    success_count: int = Field(..., description="Nombre d'operations reussies")
    failed_count: int = Field(..., description="Nombre d'operations echouees")
    failed_ids: List[UUID] = Field(default_factory=list, description="IDs des collections en echec")
    message: str = Field(..., description="Message de resultat")


# =============================================================================
# SYNC OPERATIONS
# =============================================================================

class CollectionSyncResponse(BaseModel):
    """Reponse apres synchronisation d'une collection."""
    collection_id: UUID
    collection_name: str
    old_document_count: int
    new_document_count: int
    old_chunk_count: int
    new_chunk_count: int
    synced: bool = True


class BulkSyncResponse(BaseModel):
    """Reponse pour synchronisation en masse."""
    synced_count: int = Field(..., description="Nombre de collections synchronisées")
    failed_count: int = Field(..., description="Nombre d'échecs")
    failed_ids: List[UUID] = Field(default_factory=list, description="IDs en échec")
    total_documents_delta: int = Field(..., description="Différence totale documents")
    total_chunks_delta: int = Field(..., description="Différence totale chunks")
    message: str


# =============================================================================
# COLLECTION SOURCES - Liaison sources externes <-> collections
# =============================================================================

class CollectionSourceCreate(BaseModel):
    """Ajout d'une source a une collection."""
    source_id: UUID = Field(..., description="ID de la source a ajouter")
    priority: int = Field(default=100, ge=1, le=1000, description="Priorite (1=haute, 1000=basse)")
    is_enabled: bool = Field(default=True, description="Source active pour cette collection")


class CollectionSourceUpdate(BaseModel):
    """Modification d'une liaison source-collection."""
    priority: Optional[int] = Field(None, ge=1, le=1000, description="Nouvelle priorite")
    is_enabled: Optional[bool] = Field(None, description="Activer/desactiver")


class CollectionSourceRead(BaseModel):
    """Lecture d'une liaison source-collection."""
    id: UUID
    collection_id: UUID
    source_id: UUID
    source_name: str
    source_display_name: str
    source_type: str
    priority: int
    is_enabled: bool
    source_health_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class CollectionSourcesListResponse(BaseModel):
    """Liste des sources d'une collection."""
    collection_id: UUID
    collection_name: str
    sources: List[CollectionSourceRead]
    total: int


class SourceCollectionsListResponse(BaseModel):
    """Liste des collections d'une source."""
    source_id: UUID
    source_name: str
    collections: List[dict]  # {id, name, display_name, type, priority, is_enabled}
    total: int


# === Provider Index Status ===

class ProviderIndexStatus(BaseModel):
    """État d'indexation pour un provider LLM."""
    provider: str  # "ollama" ou "llamacpp"
    collection_exists: bool  # La collection ChromaDB existe
    chunk_count: int  # Nombre de chunks indexés
    embedding_model: Optional[str] = None  # Modèle d'embedding utilisé


class CollectionIndexStatusResponse(BaseModel):
    """État d'indexation d'une collection par provider."""
    collection_id: UUID
    collection_name: str
    display_name: str
    providers: List[ProviderIndexStatus]
    active_provider: str  # Provider actuellement actif


class ReindexRequest(BaseModel):
    """Demande de réindexation pour un provider."""
    provider: str = Field(..., pattern=r"^(ollama|llamacpp)$")
    force: bool = False  # Forcer même si déjà indexé


class ReindexResponse(BaseModel):
    """Réponse de réindexation."""
    collection_id: UUID
    collection_name: Optional[str] = None
    provider: str
    status: str  # "started", "completed", "skipped", "failed"
    documents_count: int
    sources_count: int = 0
    message: str
    document_ids: Optional[List[UUID]] = None  # IDs des documents en cours de réindexation
    source_ids: Optional[List[UUID]] = None  # IDs des sources en cours de réindexation
