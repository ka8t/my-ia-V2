"""
Schemas Pydantic pour l'administration des documents.

Schemas spécifiques aux opérations admin sur les documents.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# === Request Schemas ===

class AdminDocumentUpdateRequest(BaseModel):
    """Requête admin de mise à jour d'un document."""
    visibility: Optional[str] = Field(None, pattern="^(public|private|shared)$")
    is_indexed: Optional[bool] = None
    filename: Optional[str] = Field(None, min_length=1, max_length=500)


class AdminQuotaUpdateRequest(BaseModel):
    """Requête de mise à jour du quota d'un utilisateur."""
    quota_bytes: int = Field(..., gt=0, description="Quota en bytes")


class AdminBulkVisibilityRequest(BaseModel):
    """Requête de changement de visibilité en masse."""
    document_ids: List[UUID] = Field(..., min_length=1, max_length=100)
    visibility: str = Field(..., pattern="^(public|private)$")


class AdminBulkDeleteRequest(BaseModel):
    """Requête de suppression en masse."""
    document_ids: List[UUID] = Field(..., min_length=1, max_length=100)


class AdminReindexRequest(BaseModel):
    """Requête de réindexation d'un document."""
    provider: Optional[str] = Field(None, pattern=r"^(ollama|llamacpp)$", description="Provider cible (ollama ou llamacpp). Si non spécifié, utilise le provider actif.")


class AdminBulkReindexRequest(BaseModel):
    """Requête de réindexation en masse."""
    document_ids: List[UUID] = Field(..., min_length=1, max_length=50)
    provider: Optional[str] = Field(None, pattern=r"^(ollama|llamacpp)$", description="Provider cible")


class AdminReindexResponse(BaseModel):
    """Réponse pour une réindexation de document."""
    document_id: UUID
    filename: str
    old_chunk_count: int
    new_chunk_count: int
    success: bool
    message: str


# === Response Schemas ===

class AdminDocumentResponse(BaseModel):
    """Réponse admin pour un document (avec infos utilisateur, corpus et collection)."""
    id: UUID
    user_id: UUID
    username: Optional[str] = None
    # Document dans N corpus (relation N à N)
    corpus_count: int = 0
    corpus_names: List[str] = []  # Pour le tooltip
    # Document dans une collection privée (docs privés utilisateur)
    collection_id: Optional[UUID] = None
    collection_name: Optional[str] = None
    collection_embedding_model: Optional[str] = None
    filename: str
    file_hash: str
    file_size: int
    file_type: str
    file_path: Optional[str]
    chunk_count: int
    embedding_count: int = 0  # Nombre d'embeddings dans ChromaDB
    indexed_provider: Optional[str] = None  # Provider utilisé pour l'indexation (ollama/llamacpp)
    current_version: int
    visibility: str
    is_indexed: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AdminDocumentListResponse(BaseModel):
    """Réponse pour la liste admin des documents."""
    documents: List[AdminDocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    current_embedding_model: str = ""


class AdminUserQuotaResponse(BaseModel):
    """Réponse pour le quota d'un utilisateur."""
    user_id: UUID
    username: str
    used_bytes: int
    quota_bytes: int
    quota_used_percent: float
    file_count: int
    is_custom_quota: bool


class AdminStorageStatsResponse(BaseModel):
    """Statistiques globales de stockage."""
    total_bytes: int
    used_bytes: int
    free_bytes: int
    total_files: int
    total_users: int
    avg_file_size: float
    top_users: List[AdminUserQuotaResponse]


class AdminBulkOperationResponse(BaseModel):
    """Réponse pour une opération en masse."""
    success_count: int
    error_count: int
    errors: List[str] = []


class AdminDocumentVersionResponse(BaseModel):
    """Réponse admin pour une version de document."""
    id: UUID
    document_id: UUID
    version_number: int
    file_path: str
    file_size: int
    file_hash: str
    chunk_count: int
    comment: Optional[str]
    created_at: datetime
    created_by: Optional[UUID]
    created_by_username: Optional[str] = None

    class Config:
        from_attributes = True


class AdminDocumentDetailResponse(AdminDocumentResponse):
    """Réponse détaillée admin avec versions."""
    versions: List[AdminDocumentVersionResponse] = []


# === Réindexation asynchrone ===

class DocReindexStartResponse(BaseModel):
    """Réponse au lancement d'une réindexation asynchrone."""
    document_id: UUID
    status: str = "started"
    message: str


class DocReindexProgressResponse(BaseModel):
    """Réponse de progression d'une réindexation de document."""
    document_id: UUID
    document_name: Optional[str] = None
    status: str  # 'running', 'success', 'failed', 'idle'
    progress: int = 0  # 0-100
    progress_message: Optional[str] = None
    documents_count: Optional[int] = None
    error_message: Optional[str] = None
