"""
Schemas Pydantic pour la feature Documents.

Ces schemas définissent les DTOs pour les endpoints de gestion des documents.
"""

from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# === Enums ===

class DocumentVisibilityEnum(str):
    """Visibilité d'un document."""
    PUBLIC = "public"
    PRIVATE = "private"
    SHARED = "shared"


# === Request Schemas ===

class DocumentUpdateRequest(BaseModel):
    """Requête de mise à jour d'un document."""
    visibility: Optional[str] = Field(None, pattern="^(public|private)$")
    filename: Optional[str] = Field(None, min_length=1, max_length=500)


class DocumentReplaceRequest(BaseModel):
    """Requête de remplacement d'un document (nouvelle version)."""
    comment: Optional[str] = Field(None, max_length=500, description="Note pour cette version")


# === Response Schemas ===

class DocumentVersionResponse(BaseModel):
    """Réponse pour une version de document."""
    id: UUID
    version_number: int
    file_path: str
    file_size: int
    file_hash: str
    chunk_count: int
    comment: Optional[str]
    created_at: datetime
    created_by: Optional[UUID]

    class Config:
        from_attributes = True


class DocumentResponse(BaseModel):
    """Réponse pour un document."""
    id: UUID
    filename: str
    file_hash: str
    file_size: int
    file_type: str
    file_path: Optional[str]
    chunk_count: int
    current_version: int
    visibility: str
    is_indexed: bool
    created_at: datetime
    updated_at: datetime
    # Owner info (pour savoir si l'utilisateur peut modifier)
    user_id: Optional[UUID] = None
    is_owner: bool = True  # True si l'utilisateur courant est propriétaire du document
    # Collection info
    collection_id: Optional[UUID] = None
    collection_name: Optional[str] = None
    collection_type: Optional[str] = None

    class Config:
        from_attributes = True


class DocumentDetailResponse(DocumentResponse):
    """Réponse détaillée avec versions."""
    versions: List[DocumentVersionResponse] = []


class DocumentListResponse(BaseModel):
    """Réponse pour la liste des documents."""
    documents: List[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentStatsResponse(BaseModel):
    """Statistiques de stockage utilisateur."""
    used_bytes: int
    file_count: int
    quota_bytes: Optional[int]
    quota_used_percent: float
    remaining_bytes: Optional[int]


class DocumentSearchResult(BaseModel):
    """Résultat de recherche de document."""
    id: UUID
    filename: str
    file_type: str
    file_size: int
    visibility: str
    created_at: datetime
    score: Optional[float] = None  # Score de pertinence pour recherche full-text


class DocumentSearchResponse(BaseModel):
    """Réponse de recherche."""
    results: List[DocumentSearchResult]
    total: int
    query: str


class DocumentUploadResponse(BaseModel):
    """Réponse après upload."""
    id: UUID
    filename: str
    file_size: int
    file_type: str
    version: int
    message: str


class DocumentDownloadInfo(BaseModel):
    """Informations pour téléchargement."""
    filename: str
    file_size: int
    mime_type: str
    download_url: Optional[str] = None


class UploadProgressEvent(BaseModel):
    """Événement de progression d'upload (pour SSE)."""
    stage: str = Field(..., description="Étape: upload, parsing, embedding, indexing, done, error")
    progress: int = Field(..., ge=0, le=100, description="Pourcentage de progression")
    message: Optional[str] = Field(None, description="Message descriptif")
    result: Optional[DocumentUploadResponse] = Field(None, description="Résultat final si stage=done")


class BulkDeleteRequest(BaseModel):
    """Requête de suppression groupée."""
    document_ids: List[UUID] = Field(..., min_length=1, max_length=100, description="IDs des documents à supprimer")
    confirm: bool = Field(default=False, description="Confirmation de suppression")


class BulkDeleteResponse(BaseModel):
    """Réponse de suppression groupée."""
    deleted_count: int = Field(..., description="Nombre de documents supprimés")
    failed_ids: List[UUID] = Field(default_factory=list, description="IDs des documents non supprimés")
    message: str


class UploadAsyncResponse(BaseModel):
    """Réponse pour upload asynchrone (indexation en arrière-plan)."""
    id: UUID = Field(..., description="ID du document créé")
    filename: str
    file_size: int
    file_type: str
    status: str = Field(default="pending", description="Status: pending, indexing, success, failed")
    message: str


class UploadProgressResponse(BaseModel):
    """Réponse de progression d'upload/indexation."""
    status: str = Field(..., description="Status: pending, indexing, success, failed")
    progress: int = Field(default=0, ge=0, le=100)
    progress_message: Optional[str] = None
    document_name: Optional[str] = None
    chunk_count: Optional[int] = None
    error_message: Optional[str] = None
