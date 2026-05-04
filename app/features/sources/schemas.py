"""
Schemas Pydantic pour le module Sources
"""
from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class SourceType(str, Enum):
    MCP = "mcp"  # Model Context Protocol - prioritaire
    WEB = "web"
    DATABASE = "database"
    API = "api"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


# === Creation / Update ===

class SourceCreate(BaseModel):
    """Schema pour creer une source"""
    name: str = Field(..., min_length=2, max_length=100, pattern=r'^[a-z0-9_]+$')
    display_name: str = Field(..., min_length=2, max_length=255)
    description: Optional[str] = None
    source_type: SourceType
    config: Dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    timeout_seconds: int = Field(default=30, ge=5, le=300)
    max_results: int = Field(default=5, ge=1, le=50)
    priority: int = Field(default=100, ge=1, le=1000)
    # Indexation
    index_enabled: bool = Field(default=False, description="Activer l'indexation pour cette source")
    index_ttl_hours: Optional[int] = Field(default=None, ge=1, le=720, description="TTL en heures (NULL = config globale)")
    auto_refresh: bool = Field(default=False, description="Ré-indexation automatique")
    refresh_interval_hours: Optional[int] = Field(default=None, ge=1, le=720, description="Intervalle de rafraîchissement")
    replace_on_refresh: bool = Field(default=True, description="Remplacer l'index à chaque refresh")


class SourceUpdate(BaseModel):
    """Schema pour mettre a jour une source"""
    display_name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = Field(default=None, ge=5, le=300)
    max_results: Optional[int] = Field(default=None, ge=1, le=50)
    priority: Optional[int] = Field(default=None, ge=1, le=1000)
    # Indexation
    index_enabled: Optional[bool] = None
    index_ttl_hours: Optional[int] = Field(default=None, ge=1, le=720)
    auto_refresh: Optional[bool] = None
    refresh_interval_hours: Optional[int] = Field(default=None, ge=1, le=720)
    replace_on_refresh: Optional[bool] = None


# === Lecture ===

class SourceRead(BaseModel):
    """Schema pour lire une source"""
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    source_type: SourceType
    config: Dict[str, Any]
    is_enabled: bool
    timeout_seconds: int
    max_results: int
    priority: int
    health_status: HealthStatus
    last_health_check: Optional[datetime]
    last_latency_ms: Optional[int] = None
    # Indexation
    index_enabled: bool = False
    index_ttl_hours: Optional[int] = None
    auto_refresh: bool = False
    refresh_interval_hours: Optional[int] = None
    replace_on_refresh: bool = True
    last_indexed_at: Optional[datetime] = None
    last_content_hash: Optional[str] = None
    chunk_count: int = 0  # Nombre de chunks indexés
    indexed_provider: Optional[str] = None  # Provider utilisé pour l'indexation (ollama/llamacpp)
    # Corpus N-N relation
    corpus_count: int = 0  # Nombre de corpus auxquels cette source appartient
    corpus_names: List[str] = []  # Noms des corpus pour le tooltip
    # Timestamps
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# === Schema public (pour utilisateurs) ===

class SourcePublic(BaseModel):
    """Schema public pour les utilisateurs (sans config sensible)"""
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    source_type: SourceType

    class Config:
        from_attributes = True


class SourcesPublicResponse(BaseModel):
    """Liste des sources disponibles pour les utilisateurs"""
    sources: List[SourcePublic]
    total: int
    use_corpus: bool = False  # Si True, sources gérées par l'admin via corpus (pas de sélection manuelle)


# === Reponses API ===

class SourcesListResponse(BaseModel):
    """Liste des sources"""
    sources: List[SourceRead]
    total: int


class HealthCheckResponse(BaseModel):
    """Resultat d'un health check"""
    source_id: UUID
    source_name: str
    status: HealthStatus
    latency_ms: Optional[int]
    error: Optional[str]


class SourceTestResponse(BaseModel):
    """Resultat d'un test de source"""
    success: bool
    results: List[Dict[str, Any]]
    latency_ms: int
    error: Optional[str]


class SourceIndexStats(BaseModel):
    """Statistiques d'indexation d'une source"""
    source_id: UUID
    source_name: str
    indexed_count: int = Field(0, description="Nombre total de chunks indexés")
    valid_count: int = Field(0, description="Nombre de chunks non expirés")
    expired_count: int = Field(0, description="Nombre de chunks expirés")
    last_indexed_at: Optional[str] = Field(None, description="Date de dernière indexation (ISO)")
    index_enabled: bool = Field(False, description="Indexation activée globalement")
    ttl_hours: int = Field(24, description="Durée de vie des chunks indexés (heures)")


class ClearIndexResponse(BaseModel):
    """Résultat du vidage de l'index d'une source"""
    source_id: UUID
    source_name: str
    deleted_count: int = Field(..., description="Nombre de documents supprimés")
    message: str


# === Contexte RAG ===

class ContextResult(BaseModel):
    """Resultat de contexte d'une source externe"""
    source_name: str
    display_name: Optional[str] = None  # Nom d'affichage (pour l'UI)
    source_type: SourceType
    content: str
    source_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# =============================================================================
# BULK OPERATIONS
# =============================================================================

class BulkSourceRequest(BaseModel):
    """Requete pour operations en masse sur les sources"""
    source_ids: List[UUID] = Field(..., min_length=1, description="Liste des IDs de sources")
    confirm: bool = Field(False, description="Confirmation requise pour l'operation")


class BulkSourceResponse(BaseModel):
    """Reponse pour operations en masse sur les sources"""
    success_count: int = Field(..., description="Nombre d'operations reussies")
    failed_count: int = Field(..., description="Nombre d'operations echouees")
    failed_ids: List[UUID] = Field(default_factory=list, description="IDs des sources en echec")
    message: str = Field(..., description="Message de resultat")
    warning: Optional[str] = Field(None, description="Avertissement si le nettoyage ChromaDB a partiellement échoué")


# =============================================================================
# HISTORIQUE D'INDEXATION
# =============================================================================

class IndexationTriggerType(str, Enum):
    """Type de déclencheur d'indexation"""
    MANUAL = "manual"
    SCHEDULED = "scheduled"
    ON_CREATE = "on_create"


class IndexationStatusType(str, Enum):
    """Statut d'une indexation"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class IndexationLogRead(BaseModel):
    """Entrée d'historique d'indexation"""
    id: UUID
    source_id: UUID
    indexed_at: datetime
    documents_count: int
    replaced_count: int
    trigger_type: str
    triggered_by: Optional[UUID] = None
    triggered_by_email: Optional[str] = None  # Pour affichage
    content_hash: Optional[str] = None
    content_changed: bool = False
    status: str
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    progress: int = 0
    progress_message: Optional[str] = None

    class Config:
        from_attributes = True


class IndexationHistoryResponse(BaseModel):
    """Réponse paginée de l'historique d'indexation"""
    logs: List[IndexationLogRead]
    total: int
    page: int = 1
    page_size: int = 20


class TriggerIndexationRequest(BaseModel):
    """Requête pour déclencher une indexation manuelle"""
    replace_existing: bool = Field(default=True, description="Remplacer les documents existants")
    provider: Optional[str] = Field(None, pattern=r"^(ollama|llamacpp)$", description="Provider cible (ollama ou llamacpp). Si non spécifié, utilise le provider actif.")


class TriggerIndexationResponse(BaseModel):
    """Réponse après déclenchement d'indexation"""
    source_id: UUID
    source_name: str
    log_id: Optional[UUID] = None  # Sera rempli par la tâche de fond
    status: str
    message: str


class ReindexProgressResponse(BaseModel):
    """Réponse de progression de réindexation (polling)"""
    source_id: UUID
    source_name: Optional[str] = None
    status: str  # 'running', 'success', 'failed', 'idle'
    progress: int = 0  # 0-100
    progress_message: Optional[str] = None
    documents_count: Optional[int] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None


# =============================================================================
# FRAÎCHEUR
# =============================================================================

class FreshnessStatus(str, Enum):
    """Statut de fraîcheur d'une source"""
    FRESH = "fresh"          # Indexation récente
    WARNING = "warning"      # Bientôt périmée
    EXPIRED = "expired"      # Périmée
    NEVER_INDEXED = "never_indexed"  # Jamais indexée
    DISABLED = "disabled"    # Indexation désactivée


class SourceFreshnessResponse(BaseModel):
    """Statut de fraîcheur d'une source"""
    source_id: UUID
    source_name: str
    status: FreshnessStatus
    freshness_percent: Optional[float] = Field(None, description="Pourcentage de fraîcheur (100=frais, 0=expiré)")
    ttl_hours: int
    last_indexed_at: Optional[str] = None
    expires_at: Optional[str] = None
    hours_until_expiry: Optional[float] = None


class StaleSourceAlert(BaseModel):
    """Alerte pour une source périmée ou bientôt périmée"""
    source_id: UUID
    source_name: str
    display_name: str
    status: FreshnessStatus
    ttl_hours: int
    last_indexed_at: Optional[str] = None
    expires_at: Optional[str] = None
    freshness_percent: float


class StaleSourcesResponse(BaseModel):
    """Liste des sources périmées ou bientôt périmées"""
    alerts: List[StaleSourceAlert]
    total_stale: int
    total_warning: int
    total_expired: int
