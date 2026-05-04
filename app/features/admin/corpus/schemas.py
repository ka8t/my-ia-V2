"""
Schemas Admin Corpus - DTOs pour l'administration des corpus.

Un corpus est un regroupement de collections et sources externes
pour creer des "domaines de connaissances" indexables.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


# =============================================================================
# REQUESTS - Corpus CRUD
# =============================================================================

class CorpusCreateRequest(BaseModel):
    """Creation d'un corpus."""
    name: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_]{2,49}$",
        description="Slug technique unique (lettres minuscules, chiffres, underscores)"
    )
    display_name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    is_active: bool = Field(default=True, description="Corpus actif par defaut")


class CorpusUpdateRequest(BaseModel):
    """Modification d'un corpus."""
    display_name: Optional[str] = Field(None, min_length=2, max_length=255)
    description: Optional[str] = None
    is_active: Optional[bool] = None


# =============================================================================
# RESPONSES - Corpus
# =============================================================================

class CorpusResponse(BaseModel):
    """Reponse corpus basique."""
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    is_active: bool
    collections_count: int = 0
    sources_count: int = 0
    documents_count: int = 0
    chunks_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CorpusDetailResponse(CorpusResponse):
    """Reponse corpus avec details des membres."""
    collections: List["CorpusCollectionRead"]
    sources: List["CorpusSourceRead"]
    documents: List["CorpusDocumentRead"] = []


class CorpusListResponse(BaseModel):
    """Liste paginee de corpus."""
    corpus: List[CorpusResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# =============================================================================
# MEMBERS - Collections du corpus
# =============================================================================

class CorpusCollectionAdd(BaseModel):
    """Ajout d'une collection a un corpus."""
    collection_id: UUID = Field(..., description="ID de la collection publique a ajouter")
    priority: int = Field(default=100, ge=1, le=1000, description="Priorite (1=haute, 1000=basse)")


class CorpusCollectionUpdate(BaseModel):
    """Modification d'une liaison corpus-collection."""
    priority: int = Field(..., ge=1, le=1000, description="Nouvelle priorite")


class CorpusCollectionRead(BaseModel):
    """Lecture d'une collection assignee a un corpus."""
    collection_id: UUID
    collection_name: str
    collection_display_name: str
    collection_type: str
    document_count: int
    chunk_count: int
    priority: Optional[int] = None  # Rempli si via table de liaison CorpusCollection

    class Config:
        from_attributes = True


class CorpusCollectionsListResponse(BaseModel):
    """Liste des collections d'un corpus."""
    corpus_id: UUID
    corpus_name: str
    collections: List[CorpusCollectionRead]
    total: int


# =============================================================================
# MEMBERS - Sources du corpus
# =============================================================================

class CorpusSourceAdd(BaseModel):
    """Ajout d'une source a un corpus."""
    source_id: UUID = Field(..., description="ID de la source a ajouter")
    priority: int = Field(default=100, ge=1, le=1000, description="Priorite (1=haute, 1000=basse)")
    is_enabled: bool = Field(default=True, description="Source active pour ce corpus")


class CorpusSourceUpdate(BaseModel):
    """Modification d'une liaison corpus-source."""
    priority: Optional[int] = Field(None, ge=1, le=1000, description="Nouvelle priorite")
    is_enabled: Optional[bool] = Field(None, description="Activer/desactiver")


class CorpusSourceRead(BaseModel):
    """Lecture d'une source dans un corpus."""
    id: UUID  # ID de la liaison
    source_id: UUID
    source_name: str
    source_display_name: str
    source_type: str
    priority: int
    is_enabled: bool
    source_health_status: str
    source_chunk_count: int = 0  # Nombre de chunks indexés
    created_at: datetime

    class Config:
        from_attributes = True


class CorpusSourcesListResponse(BaseModel):
    """Liste des sources d'un corpus."""
    corpus_id: UUID
    corpus_name: str
    sources: List[CorpusSourceRead]
    total: int


# =============================================================================
# AVAILABLE - Elements disponibles pour ajout
# =============================================================================

class AvailableCollectionRead(BaseModel):
    """Collection publique disponible pour ajout a un corpus."""
    id: UUID
    name: str
    display_name: str
    document_count: int
    chunk_count: int


class AvailableSourceRead(BaseModel):
    """Source disponible pour ajout a un corpus."""
    id: UUID
    name: str
    display_name: str
    source_type: str
    is_enabled: bool
    health_status: str


# =============================================================================
# BULK - Operations en masse
# =============================================================================

class BulkCollectionsAddRequest(BaseModel):
    """Ajout de plusieurs collections a un corpus."""
    collection_ids: List[UUID] = Field(..., min_length=1, description="IDs des collections a ajouter")
    priority: int = Field(default=100, ge=1, le=1000, description="Priorite pour toutes")


class BulkCollectionsRemoveRequest(BaseModel):
    """Retrait de plusieurs collections d'un corpus."""
    collection_ids: List[UUID] = Field(..., min_length=1, description="IDs des collections a retirer")


class BulkSourcesAddRequest(BaseModel):
    """Ajout de plusieurs sources a un corpus."""
    source_ids: List[UUID] = Field(..., min_length=1, description="IDs des sources a ajouter")
    priority: int = Field(default=100, ge=1, le=1000, description="Priorite pour toutes")
    is_enabled: bool = Field(default=True, description="Sources actives par defaut")


class BulkSourcesRemoveRequest(BaseModel):
    """Retrait de plusieurs sources d'un corpus."""
    source_ids: List[UUID] = Field(..., min_length=1, description="IDs des sources a retirer")


class BulkOperationResult(BaseModel):
    """Resultat d'une operation bulk."""
    success_count: int = Field(..., description="Nombre d'operations reussies")
    error_count: int = Field(..., description="Nombre d'erreurs")
    errors: List[str] = Field(default_factory=list, description="Messages d'erreur")


# =============================================================================
# DOCUMENTS - Documents du corpus
# =============================================================================

class CorpusDocumentRead(BaseModel):
    """Document appartenant a un corpus."""
    id: UUID
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    visibility: str
    is_indexed: bool
    username: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class CorpusDocumentsListResponse(BaseModel):
    """Liste des documents d'un corpus."""
    corpus_id: UUID
    corpus_name: str
    documents: List[CorpusDocumentRead]
    total: int


class AvailableDocumentRead(BaseModel):
    """Document disponible pour ajout a un corpus."""
    id: UUID
    filename: str
    file_type: str
    file_size: int
    chunk_count: int
    visibility: str
    username: Optional[str] = None
    collection_name: Optional[str] = None


class CorpusDocumentAdd(BaseModel):
    """Ajout d'un document a un corpus."""
    document_id: UUID = Field(..., description="ID du document a ajouter")


class BulkDocumentsAddRequest(BaseModel):
    """Ajout de plusieurs documents a un corpus."""
    document_ids: List[UUID] = Field(..., min_length=1, description="IDs des documents a ajouter")


class BulkDocumentsRemoveRequest(BaseModel):
    """Retrait de plusieurs documents d'un corpus."""
    document_ids: List[UUID] = Field(..., min_length=1, description="IDs des documents a retirer")


class BulkCorpusDeleteRequest(BaseModel):
    """Suppression de plusieurs corpus."""
    corpus_ids: List[UUID] = Field(..., min_length=1, max_length=100, description="IDs des corpus a supprimer")
    confirm: bool = Field(..., description="Confirmation requise")


class BulkCorpusDeleteResponse(BaseModel):
    """Resultat de suppression en masse de corpus."""
    success_count: int = Field(..., description="Nombre de corpus supprimes")
    error_count: int = Field(..., description="Nombre d'erreurs")
    errors: List[str] = Field(default_factory=list, description="Messages d'erreur")


class BulkCorpusReindexRequest(BaseModel):
    """Reindexation de plusieurs corpus."""
    corpus_ids: List[UUID] = Field(..., min_length=1, max_length=50, description="IDs des corpus a reindexer")


class BulkCorpusReindexResponse(BaseModel):
    """Resultat de reindexation en masse de corpus."""
    success_count: int = Field(..., description="Nombre de corpus lances")
    error_count: int = Field(..., description="Nombre d'erreurs")
    total_documents: int = Field(default=0, description="Total de documents en queue")
    total_sources: int = Field(default=0, description="Total de sources en queue")
    corpus_results: List[dict] = Field(default_factory=list, description="Details par corpus")
    errors: List[str] = Field(default_factory=list, description="Messages d'erreur")


# =============================================================================
# REINDEX - Réindexation du corpus
# =============================================================================

class CorpusReindexResponse(BaseModel):
    """Réponse de réindexation d'un corpus."""
    corpus_id: UUID
    corpus_name: str
    status: str = Field(..., description="started, completed, failed")
    documents_count: int = Field(..., description="Nombre de documents à réindexer")
    sources_count: int = Field(..., description="Nombre de sources à synchroniser")
    message: str
    document_ids: List[UUID] = Field(default_factory=list, description="IDs des documents en réindexation")
    source_ids: List[UUID] = Field(default_factory=list, description="IDs des sources en réindexation")


# Forward references update
CorpusDetailResponse.model_rebuild()
