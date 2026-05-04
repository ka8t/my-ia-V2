"""
Schemas Admin Config

Schémas Pydantic pour la configuration système.
"""
from typing import Any, Optional, Dict, List

from pydantic import BaseModel, Field


# =============================================================================
# CONFIG LLM PROVIDER
# =============================================================================

class LLMProviderConfigRead(BaseModel):
    """Lecture de la configuration du provider LLM."""
    provider: str = Field(..., description="Provider actif pour le chat (ollama ou llamacpp)")
    embedding_provider: str = Field("", description="Provider pour les embeddings (si différent du provider principal)")
    # Ollama - connexion
    ollama_host: str = Field(..., description="Hôte Ollama")
    ollama_port: int = Field(..., description="Port Ollama")
    # Ollama - modèles configurés
    ollama_llm_model: str = Field("", description="Modèle LLM configuré pour Ollama")
    ollama_embedding_model: str = Field("", description="Modèle embedding configuré pour Ollama")
    # llama.cpp - connexion
    llamacpp_host: str = Field(..., description="Hôte llama-server")
    llamacpp_port: int = Field(..., description="Port llama-server")
    # llama.cpp - modèles configurés
    llamacpp_llm_model: str = Field("", description="Modèle LLM configuré pour llama.cpp (GGUF)")
    llamacpp_embedding_model: str = Field("", description="Modèle embedding configuré pour llama.cpp")
    # Status
    provider_status: str = Field("unknown", description="État du provider (healthy/unhealthy)")
    provider_info: dict = Field(default_factory=dict, description="Informations du provider")


class LLMProviderConfigUpdate(BaseModel):
    """Mise à jour de la configuration du provider LLM."""
    provider: Optional[str] = Field(
        None,
        pattern="^(ollama|llamacpp)$",
        description="Provider LLM à utiliser pour le chat"
    )
    embedding_provider: Optional[str] = Field(
        None,
        pattern="^(ollama|llamacpp)$",
        description="Provider pour les embeddings (si différent du provider principal)"
    )
    # Ollama - connexion
    ollama_host: Optional[str] = Field(None, max_length=255, description="Hôte Ollama")
    ollama_port: Optional[int] = Field(None, ge=1, le=65535, description="Port Ollama")
    # Ollama - modèles
    ollama_llm_model: Optional[str] = Field(None, max_length=255, description="Modèle LLM Ollama")
    ollama_embedding_model: Optional[str] = Field(None, max_length=255, description="Modèle embedding Ollama")
    # llama.cpp - connexion
    llamacpp_host: Optional[str] = Field(None, max_length=255, description="Hôte llama-server")
    llamacpp_port: Optional[int] = Field(None, ge=1, le=65535, description="Port llama-server")
    # llama.cpp - modèles
    llamacpp_llm_model: Optional[str] = Field(None, max_length=255, description="Modèle LLM llama.cpp (GGUF)")
    llamacpp_embedding_model: Optional[str] = Field(None, max_length=255, description="Modèle embedding llama.cpp")


# =============================================================================
# CONTROLE LLM PROVIDER (Start/Stop/Status)
# =============================================================================

class LLMStartRequest(BaseModel):
    """Requête de démarrage du provider LLM (llama.cpp uniquement)."""
    model: Optional[str] = Field(
        None,
        description="Modèle GGUF à charger (chemin relatif dans models/gguf/)"
    )
    port: Optional[int] = Field(
        None,
        ge=1,
        le=65535,
        description="Port d'écoute (défaut: 8085)"
    )
    ctx_size: Optional[int] = Field(
        None,
        ge=512,
        le=131072,
        description="Taille du contexte en tokens (défaut: 4096)"
    )
    gpu_layers: Optional[int] = Field(
        None,
        ge=0,
        le=999,
        description="Nombre de couches GPU (défaut: 99 = toutes)"
    )
    embedding: Optional[bool] = Field(
        None,
        description="Activer l'endpoint d'embeddings"
    )


class LLMControlResponse(BaseModel):
    """Réponse aux opérations de contrôle LLM (start/stop)."""
    status: str = Field(..., description="Statut: started, stopped, already_running, already_stopped, error, already_managed")
    provider: str = Field(..., description="Provider concerné")
    message: str = Field(..., description="Message descriptif")
    output: Optional[str] = Field(None, description="Sortie du script (si applicable)")
    pid: Optional[int] = Field(None, description="PID du processus (si démarré)")


class LLMStatusResponse(BaseModel):
    """Réponse détaillée du statut du provider LLM."""
    provider: str = Field(..., description="Provider actif (ollama ou llamacpp)")
    status: str = Field(..., description="Statut: running, stopped, unknown, managed")
    healthy: bool = Field(..., description="Provider répond aux requêtes")
    # Informations de connexion
    host: str = Field(..., description="Hôte du provider")
    port: int = Field(..., description="Port du provider")
    url: str = Field(..., description="URL complète du provider")
    # Informations du modèle
    model_loaded: Optional[str] = Field(None, description="Modèle actuellement chargé")
    model_configured: str = Field("", description="Modèle configuré en BDD")
    # Informations système (llama.cpp uniquement)
    pid: Optional[int] = Field(None, description="PID du processus llama-server")
    uptime: Optional[str] = Field(None, description="Temps de fonctionnement")
    # Métriques (si disponibles)
    memory_usage: Optional[str] = Field(None, description="Utilisation mémoire")
    gpu_layers: Optional[int] = Field(None, description="Couches GPU utilisées")
    ctx_size: Optional[int] = Field(None, description="Taille du contexte")


class LlamaCppMetricsResponse(BaseModel):
    """Métriques Prometheus de llama.cpp."""
    available: bool = Field(..., description="Métriques disponibles")
    # Compteurs de tokens
    prompt_tokens_total: int = Field(0, description="Tokens prompt traités (total)")
    tokens_predicted_total: int = Field(0, description="Tokens générés (total)")
    # Temps de traitement
    prompt_seconds_total: float = Field(0.0, description="Temps total traitement prompt (s)")
    tokens_predicted_seconds_total: float = Field(0.0, description="Temps total génération (s)")
    # Throughput (tokens/s)
    prompt_tokens_per_second: float = Field(0.0, description="Débit prompt (tokens/s)")
    predicted_tokens_per_second: float = Field(0.0, description="Débit génération (tokens/s)")
    # État du serveur
    n_decode_total: int = Field(0, description="Appels llama_decode() total")
    requests_processing: int = Field(0, description="Requêtes en cours")
    requests_deferred: int = Field(0, description="Requêtes en attente")
    slots_idle: int = Field(0, description="Slots disponibles")
    slots_processing: int = Field(0, description="Slots occupés")
    # Erreur éventuelle
    error: Optional[str] = Field(None, description="Erreur lors de la récupération")


# =============================================================================
# PARAMETRES LLAMA.CPP
# =============================================================================

class LlamaCppParamsRead(BaseModel):
    """Lecture des paramètres spécifiques llama.cpp."""
    # GPU / Performance
    gpu_layers: int = Field(99, ge=0, description="Couches GPU (0 = CPU only, 99 = toutes)")
    ctx_size: int = Field(4096, ge=512, le=131072, description="Taille du contexte en tokens")
    threads: int = Field(-1, ge=-1, description="Threads CPU (-1 = auto)")
    batch_size: int = Field(2048, ge=1, le=8192, description="Taille du batch de traitement")
    flash_attn: str = Field("auto", description="Flash Attention (on/off/auto)")
    # Serveur
    parallel: int = Field(-1, ge=-1, le=32, description="Slots parallèles (-1 = auto)")
    port: int = Field(8085, ge=1, le=65535, description="Port d'écoute")
    embedding_mode: bool = Field(False, description="Mode embedding uniquement")
    metrics_enabled: bool = Field(False, description="Activer métriques Prometheus")
    # Mémoire
    mlock: bool = Field(False, description="Verrouiller le modèle en RAM")
    mmap: bool = Field(True, description="Memory-map du modèle")


class LlamaCppParamsUpdate(BaseModel):
    """Mise à jour partielle des paramètres llama.cpp."""
    gpu_layers: Optional[int] = Field(None, ge=0, le=999, description="Couches GPU")
    ctx_size: Optional[int] = Field(None, ge=512, le=131072, description="Taille du contexte")
    threads: Optional[int] = Field(None, ge=-1, description="Threads CPU")
    batch_size: Optional[int] = Field(None, ge=1, le=8192, description="Taille du batch")
    flash_attn: Optional[str] = Field(None, pattern="^(on|off|auto)$", description="Flash Attention")
    parallel: Optional[int] = Field(None, ge=-1, le=32, description="Slots parallèles")
    port: Optional[int] = Field(None, ge=1, le=65535, description="Port d'écoute")
    embedding_mode: Optional[bool] = Field(None, description="Mode embedding")
    metrics_enabled: Optional[bool] = Field(None, description="Métriques Prometheus")
    mlock: Optional[bool] = Field(None, description="Verrouiller en RAM")
    mmap: Optional[bool] = Field(None, description="Memory-map")


# =============================================================================
# PARAMETRES OLLAMA
# =============================================================================

class OllamaConfigRead(BaseModel):
    """Lecture des paramètres Ollama (passés via API à chaque requête)."""
    # Gestion mémoire modèle
    keep_alive: str = Field("5m", description="Durée maintien modèle en mémoire (ex: 5m, 1h, -1)")
    # Performance
    num_ctx: int = Field(2048, ge=512, le=131072, description="Taille du contexte en tokens")
    num_gpu: int = Field(999, ge=0, le=999, description="Couches GPU (0 = CPU only, 999 = toutes)")
    # Note: num_parallel est une config serveur, non modifiable via API
    num_parallel: int = Field(1, ge=1, le=32, description="Requêtes parallèles (lecture seule - config serveur)")
    # Comportement au démarrage
    auto_preload: bool = Field(False, description="Précharger modèles au démarrage de l'application")


class OllamaConfigUpdate(BaseModel):
    """Mise à jour partielle des paramètres Ollama."""
    keep_alive: Optional[str] = Field(
        None,
        pattern=r"^(-1|\d+[smh]?)$",
        description="Durée maintien (ex: 5m, 1h, 30s, -1 = infini)"
    )
    num_ctx: Optional[int] = Field(None, ge=512, le=131072, description="Taille du contexte")
    num_gpu: Optional[int] = Field(None, ge=0, le=999, description="Couches GPU")
    auto_preload: Optional[bool] = Field(None, description="Précharger modèles au démarrage")


class OllamaPreloadResponse(BaseModel):
    """Réponse du préchargement Ollama."""
    success: bool = Field(..., description="Succès de l'opération")
    llm_model: Optional[str] = Field(None, description="Modèle LLM préchargé")
    embed_model: Optional[str] = Field(None, description="Modèle embedding préchargé")
    llm_status: Optional[str] = Field(None, description="Statut du préchargement LLM")
    embed_status: Optional[str] = Field(None, description="Statut du préchargement embedding")
    error: Optional[str] = Field(None, description="Erreur éventuelle")


class ServerHardwareResponse(BaseModel):
    """Informations hardware du serveur (GPU, OS)."""
    has_gpu: bool = Field(False, description="Serveur avec GPU disponible")
    gpu_type: Optional[str] = Field(None, description="Type de GPU (nvidia, amd, apple, none)")
    gpu_name: Optional[str] = Field(None, description="Nom du GPU détecté")
    gpu_memory: Optional[str] = Field(None, description="Mémoire GPU disponible")
    os: str = Field("unknown", description="Système d'exploitation")
    platform: str = Field("unknown", description="Plateforme (linux, darwin, windows)")
    recommended_preset: str = Field("cpu", description="Preset recommandé (mac, gpu8, gpu16, cpu)")
    detection_source: Optional[str] = Field(None, description="Source de détection (ollama, llamacpp)")


# =============================================================================
# MODELES LLM UNIFIES (tous providers)
# =============================================================================

class ModelInfo(BaseModel):
    """Information sur un modèle LLM (unifié tous providers)."""
    name: str = Field(..., description="Nom du modèle")
    size: Optional[int] = Field(None, description="Taille en octets")
    size_human: Optional[str] = Field(None, description="Taille lisible (ex: 4.1 GB)")
    modified_at: Optional[str] = Field(None, description="Date de modification")
    # Métadonnées spécifiques
    digest: Optional[str] = Field(None, description="Hash du modèle (Ollama)")
    path: Optional[str] = Field(None, description="Chemin fichier (llama.cpp)")


class ModelsListResponse(BaseModel):
    """Liste des modèles disponibles pour un provider."""
    provider: str = Field(..., description="Provider (ollama ou llamacpp)")
    models: List[ModelInfo] = Field(default_factory=list, description="Liste des modèles")
    current_llm_model: str = Field("", description="Modèle LLM actuellement configuré")
    current_embedding_model: str = Field("", description="Modèle embedding actuellement configuré")


class GGUFDownloadRequest(BaseModel):
    """Requête de téléchargement d'un modèle GGUF pour llama.cpp."""
    url: str = Field(
        ...,
        min_length=10,
        description="URL du fichier GGUF à télécharger (ex: https://huggingface.co/.../model.gguf)"
    )
    filename: Optional[str] = Field(
        None,
        max_length=255,
        description="Nom du fichier de destination (optionnel, déduit de l'URL si absent)"
    )


class GGUFDownloadResponse(BaseModel):
    """Réponse après téléchargement d'un modèle GGUF."""
    status: str = Field(..., description="Statut: downloading, complete, error")
    filename: Optional[str] = Field(None, description="Nom du fichier téléchargé")
    path: Optional[str] = Field(None, description="Chemin complet du fichier")
    size: Optional[int] = Field(None, description="Taille en octets")
    size_human: Optional[str] = Field(None, description="Taille lisible")
    error: Optional[str] = Field(None, description="Message d'erreur si échec")


class ModelDeleteResponse(BaseModel):
    """Réponse après suppression d'un modèle."""
    status: str = Field(..., description="Statut: deleted, error")
    provider: str = Field(..., description="Provider du modèle supprimé")
    filename: str = Field(..., description="Nom du fichier supprimé")
    message: Optional[str] = Field(None, description="Message additionnel")


# =============================================================================
# CONFIG RAG
# =============================================================================

class RAGConfigRead(BaseModel):
    """Lecture de la configuration RAG"""
    top_k: int = Field(..., description="Nombre de chunks retournés par recherche")
    max_context_items: int = Field(..., description="Nombre max de résultats de contexte total")
    similarity_threshold: float = Field(..., description="Seuil de similarité (0-1)")
    temperature: float = Field(..., description="Température du LLM (0-2)")
    llm_model: str = Field(..., description="Modèle LLM utilisé pour la génération")
    embedding_model: str = Field(..., description="Modèle d'embedding pour la vectorisation")
    chunk_size: int = Field(..., description="Taille des chunks en caractères")
    chunk_overlap: int = Field(..., description="Overlap entre chunks")
    chunking_strategy: str = Field(..., description="Stratégie de chunking")
    # Recherche hybride
    min_chunk_length: int = Field(..., description="Longueur minimale d'un chunk")
    keyword_boost: float = Field(..., description="Bonus de similarité pour mots-clés (0-1)")
    stopwords_language: str = Field(..., description="Langue des stopwords (fr/en/none)")
    # Corpus de sources
    use_corpus: bool = Field(..., description="Utiliser les corpus de sources pour le RAG")
    # Comportement sans sources
    require_sources: bool = Field(False, description="Refuser de répondre si aucune source trouvée")


class RAGConfigUpdate(BaseModel):
    """Mise à jour de la configuration RAG"""
    top_k: Optional[int] = Field(None, ge=1, le=100, description="Nombre de chunks (1-100)")
    max_context_items: Optional[int] = Field(None, ge=1, le=500, description="Max résultats contexte (1-500)")
    similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="Seuil similarité (0-1)")
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="Température LLM (0-2)")
    llm_model: Optional[str] = Field(None, min_length=1, description="Modèle LLM à utiliser")
    embedding_model: Optional[str] = Field(None, min_length=1, description="Modèle d'embedding à utiliser")
    chunk_size: Optional[int] = Field(None, ge=100, le=4000, description="Taille chunks (100-4000)")
    chunk_overlap: Optional[int] = Field(None, ge=0, le=500, description="Overlap (0-500)")
    chunking_strategy: Optional[str] = Field(None, description="Stratégie de chunking")
    # Recherche hybride
    min_chunk_length: Optional[int] = Field(None, ge=10, le=500, description="Longueur min chunk (10-500)")
    keyword_boost: Optional[float] = Field(None, ge=0.0, le=1.0, description="Bonus mots-clés (0-1)")
    stopwords_language: Optional[str] = Field(None, pattern="^(fr|en|none)$", description="Langue stopwords")
    # Corpus de sources
    use_corpus: Optional[bool] = Field(None, description="Utiliser les corpus de sources pour le RAG")
    # Comportement sans sources
    require_sources: Optional[bool] = Field(None, description="Refuser de répondre si aucune source trouvée")


# =============================================================================
# CONFIG TIMEOUTS
# =============================================================================

class TimeoutsConfigRead(BaseModel):
    """Lecture de la configuration des timeouts"""
    ollama_timeout: float = Field(..., description="Timeout Ollama en secondes")
    http_timeout: float = Field(..., description="Timeout HTTP en secondes")
    health_check_timeout: float = Field(..., description="Timeout health check en secondes")


class TimeoutsConfigUpdate(BaseModel):
    """Mise à jour de la configuration des timeouts"""
    ollama_timeout: Optional[float] = Field(
        None, ge=5.0, le=600.0,
        description="Timeout Ollama (5-600s)"
    )
    http_timeout: Optional[float] = Field(
        None, ge=1.0, le=120.0,
        description="Timeout HTTP (1-120s)"
    )
    health_check_timeout: Optional[float] = Field(
        None, ge=1.0, le=30.0,
        description="Timeout health check (1-30s)"
    )


# =============================================================================
# CONFIG RATE LIMITS
# =============================================================================

class RateLimitsConfigRead(BaseModel):
    """Lecture de la configuration des rate limits"""
    chat: str = Field(..., description="Rate limit pour /chat")
    upload: str = Field(..., description="Rate limit pour /upload")
    stream: str = Field(..., description="Rate limit pour /chat/stream")
    admin: str = Field(..., description="Rate limit pour /admin")


class RateLimitsConfigUpdate(BaseModel):
    """Mise à jour de la configuration des rate limits"""
    chat: Optional[str] = Field(
        None,
        pattern=r"^\d+/(second|minute|hour|day)$",
        description="Rate limit chat (ex: 60/minute)"
    )
    upload: Optional[str] = Field(
        None,
        pattern=r"^\d+/(second|minute|hour|day)$",
        description="Rate limit upload (ex: 10/minute)"
    )
    stream: Optional[str] = Field(
        None,
        pattern=r"^\d+/(second|minute|hour|day)$",
        description="Rate limit stream (ex: 30/minute)"
    )
    admin: Optional[str] = Field(
        None,
        pattern=r"^\d+/(second|minute|hour|day)$",
        description="Rate limit admin (ex: 30/minute)"
    )


# =============================================================================
# CONFIG SYSTÈME COMPLÈTE
# =============================================================================

class SystemConfigRead(BaseModel):
    """Lecture de la configuration système complète"""
    app_name: str = Field(..., description="Nom de l'application")
    app_version: str = Field(..., description="Version de l'application")
    environment: str = Field(..., description="Environnement (dev, prod)")
    debug: bool = Field(..., description="Mode debug")
    rag: RAGConfigRead
    timeouts: TimeoutsConfigRead
    rate_limits: RateLimitsConfigRead
    ollama_host: str = Field(..., description="Host Ollama")
    ollama_model: str = Field(..., description="Modèle LLM")
    chroma_host: str = Field(..., description="Host ChromaDB")
    collection_name: str = Field(..., description="Nom de la collection")


# =============================================================================
# CONFIG DYNAMIQUE (base de donnees)
# =============================================================================

class DynamicConfigResponse(BaseModel):
    """Reponse pour une configuration dynamique."""
    id: int
    key: str
    value: Any
    raw_value: str
    value_type: str
    category: str
    description: Optional[str] = None
    is_sensitive: bool = False
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class DynamicConfigListResponse(BaseModel):
    """Liste des configurations dynamiques."""
    configs: List[DynamicConfigResponse]
    categories: List[str]


class DynamicConfigUpdateRequest(BaseModel):
    """Requete de mise a jour d'une configuration dynamique."""
    value: Any = Field(..., description="Nouvelle valeur")


class DynamicConfigCreateRequest(BaseModel):
    """Requete de creation d'une configuration dynamique."""
    key: str = Field(..., min_length=1, max_length=100)
    value: Any
    value_type: str = Field(default="string", pattern="^(string|int|float|bool|json|list)$")
    category: str = Field(default="general", max_length=50)
    description: Optional[str] = None
    is_sensitive: bool = False


class StorageConfigResponse(BaseModel):
    """Configuration du storage."""
    # Provider
    backend: str = Field(default="local", description="Backend de stockage (local, s3)")
    local_path: str = Field(default="/data/uploads", description="Chemin local pour le stockage")
    # S3 config (si backend = s3)
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None
    s3_endpoint: Optional[str] = None
    s3_access_key_configured: bool = Field(default=False, description="Indique si la clé S3 est configurée")
    s3_secret_key_configured: bool = Field(default=False, description="Indique si le secret S3 est configuré")
    # Limites
    allowed_mime_types: List[str]
    blocked_extensions: List[str]
    max_file_size_mb: int
    default_quota_mb: int


class StorageConfigUpdateRequest(BaseModel):
    """Mise a jour de la configuration storage."""
    # Provider
    backend: Optional[str] = Field(None, pattern="^(local|s3)$")
    local_path: Optional[str] = Field(None, min_length=1, max_length=500)
    # S3 config
    s3_bucket: Optional[str] = Field(None, min_length=1, max_length=255)
    s3_region: Optional[str] = Field(None, min_length=1, max_length=50)
    s3_endpoint: Optional[str] = Field(None, min_length=1, max_length=500)
    s3_access_key: Optional[str] = Field(None, min_length=1, max_length=255)
    s3_secret_key: Optional[str] = Field(None, min_length=1, max_length=255)
    # Limites
    allowed_mime_types: Optional[List[str]] = None
    blocked_extensions: Optional[List[str]] = None
    max_file_size_mb: Optional[int] = Field(None, ge=1, le=500)
    default_quota_mb: Optional[int] = Field(None, ge=1, le=10240)


# =============================================================================
# TYPES DE FICHIERS SUPPORTES
# =============================================================================

class FileTypeResponse(BaseModel):
    """Information sur un type de fichier supporte."""
    id: str = Field(..., description="Identifiant unique du type (ex: pdf, docx)")
    extension: str = Field(..., description="Extension avec point (ex: .pdf)")
    mime_type: str = Field(..., description="Type MIME (ex: application/pdf)")
    name: str = Field(..., description="Nom affiche (ex: PDF)")
    description: str = Field(..., description="Description du type")
    parser: str = Field(..., description="Librairie de parsing utilisee")
    category: str = Field(..., description="Categorie: documents, images, data")
    enabled: bool = Field(..., description="Type active ou non")


class FileTypesListResponse(BaseModel):
    """Liste des types de fichiers avec leur statut."""
    file_types: List[FileTypeResponse]
    categories: List[str] = Field(
        default=["documents", "images", "data"],
        description="Categories disponibles"
    )


class FileTypesUpdateRequest(BaseModel):
    """Mise a jour des types de fichiers actives."""
    enabled_types: List[str] = Field(
        ...,
        description="Liste des IDs de types a activer (ex: ['pdf', 'docx', 'txt'])"
    )


# =============================================================================
# MODELES LLM (Ollama)
# =============================================================================

class OllamaModelInfo(BaseModel):
    """Information sur un modele Ollama."""
    name: str = Field(..., description="Nom du modele (ex: mistral:latest)")
    size: Optional[int] = Field(None, description="Taille en octets")
    digest: Optional[str] = Field(None, description="Hash du modele")
    modified_at: Optional[str] = Field(None, description="Date de modification")


class OllamaModelsListResponse(BaseModel):
    """Liste des modeles Ollama installes."""
    models: List[OllamaModelInfo]
    current_model: str = Field(..., description="Modele actuellement configure")


class OllamaModelPullRequest(BaseModel):
    """Requete pour telecharger un modele."""
    model_name: str = Field(..., min_length=1, description="Nom du modele a telecharger")


# =============================================================================
# CONFIG SPEECH (Speech-to-Text)
# =============================================================================

class SpeechConfigRead(BaseModel):
    """Lecture de la configuration Speech-to-Text."""
    enabled: bool = Field(..., description="Service active globalement")
    model: str = Field(..., description="Modele Whisper (tiny/base/small/medium)")
    default_language: str = Field(..., description="Langue par defaut")
    max_duration: int = Field(..., description="Duree max audio en secondes")
    timeout: int = Field(..., description="Timeout transcription en secondes")
    # Auto-envoi (STT)
    auto_send_enabled: bool = Field(True, description="Auto-envoi apres silence active globalement")
    silence_duration_ms: int = Field(1500, description="Duree de silence avant arret (ms)")
    silence_threshold: float = Field(0.01, description="Seuil RMS de detection du silence")
    # TTS
    tts_enabled: bool = Field(True, description="Lecture vocale TTS active globalement")
    tts_mode: str = Field("native", description="Mode TTS : native ou server")
    tts_default_rate: float = Field(1.0, description="Vitesse de lecture TTS par defaut")
    # Info lecture seule
    current_model_loaded: Optional[str] = Field(None, description="Modele actuellement charge dans le container")
    model_change_warning: Optional[str] = Field(None, description="Avertissement si changement de modele")


class SpeechConfigUpdate(BaseModel):
    """Mise a jour de la configuration Speech-to-Text."""
    enabled: Optional[bool] = Field(None, description="Activer/desactiver le service")
    model: Optional[str] = Field(
        None,
        pattern="^(tiny|base|small|medium)$",
        description="Modele Whisper"
    )
    default_language: Optional[str] = Field(
        None,
        pattern="^(fr|en|es|de|it|pt|nl|pl|ru|zh|ja|ko)$",
        description="Langue par defaut"
    )
    max_duration: Optional[int] = Field(
        None,
        ge=10,
        le=300,
        description="Duree max audio (10-300s)"
    )
    timeout: Optional[int] = Field(
        None,
        ge=30,
        le=600,
        description="Timeout transcription (30-600s)"
    )
    # Auto-envoi (STT)
    auto_send_enabled: Optional[bool] = Field(None, description="Activer/desactiver l'auto-envoi")
    silence_duration_ms: Optional[int] = Field(
        None, ge=500, le=5000,
        description="Duree silence (500-5000 ms)"
    )
    silence_threshold: Optional[float] = Field(
        None, ge=0.001, le=0.1,
        description="Seuil RMS (0.001-0.1)"
    )
    # TTS
    tts_enabled: Optional[bool] = Field(None, description="Activer/desactiver le TTS")
    tts_mode: Optional[str] = Field(
        None,
        pattern="^(native|server)$",
        description="Mode TTS"
    )
    tts_default_rate: Optional[float] = Field(
        None, ge=0.5, le=2.0,
        description="Vitesse TTS (0.5-2.0)"
    )


# =============================================================================
# CONFIG SOURCES INDEXATION
# =============================================================================

class SourcesIndexationConfigRead(BaseModel):
    """Lecture de la configuration d'indexation des sources."""
    # Scheduler
    scheduler_enabled: bool = Field(..., description="Scheduler actif")
    scheduler_check_interval_minutes: int = Field(..., description="Intervalle de verification des sources (minutes)")
    scheduler_cleanup_docs_interval_hours: int = Field(..., description="Intervalle de nettoyage des documents expires (heures)")
    scheduler_cleanup_logs_interval_days: int = Field(..., description="Intervalle de nettoyage des logs (jours)")
    # Retention
    log_retention_days: int = Field(..., description="Retention des logs d'indexation (jours)")
    # Freshness thresholds
    freshness_warning_percent: int = Field(..., description="Seuil d'avertissement fraicheur (0-100)")
    freshness_expired_percent: int = Field(..., description="Seuil d'expiration fraicheur (0-100)")
    # Info lecture seule
    scheduler_status: Optional[dict] = Field(None, description="Statut actuel du scheduler")


class SourcesIndexationConfigUpdate(BaseModel):
    """Mise a jour de la configuration d'indexation des sources."""
    # Scheduler
    scheduler_enabled: Optional[bool] = Field(None, description="Activer/desactiver le scheduler")
    scheduler_check_interval_minutes: Optional[int] = Field(
        None,
        ge=1,
        le=1440,
        description="Intervalle de verification (1-1440 min)"
    )
    scheduler_cleanup_docs_interval_hours: Optional[int] = Field(
        None,
        ge=1,
        le=168,
        description="Intervalle nettoyage docs (1-168 h)"
    )
    scheduler_cleanup_logs_interval_days: Optional[int] = Field(
        None,
        ge=1,
        le=30,
        description="Intervalle nettoyage logs (1-30 jours)"
    )
    # Retention
    log_retention_days: Optional[int] = Field(
        None,
        ge=1,
        le=365,
        description="Retention des logs (1-365 jours)"
    )
    # Freshness thresholds
    freshness_warning_percent: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Seuil avertissement (0-100%)"
    )
    freshness_expired_percent: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Seuil expiration (0-100%)"
    )


# =============================================================================
# CONFIG CHAT (MÉMOIRE CONVERSATIONNELLE)
# =============================================================================

class ChatConfigRead(BaseModel):
    """Lecture de la configuration chat (mémoire conversationnelle)."""
    history_enabled: bool = Field(..., description="Injection de l'historique dans le prompt LLM")
    history_max_turns: int = Field(..., description="Nombre max de tours (1 tour = 1 user + 1 assistant)")
    history_max_tokens: int = Field(..., description="Budget tokens max pour l'historique")
    topic_detection_enabled: bool = Field(..., description="Détection de changement de sujet")
    topic_similarity_threshold: float = Field(..., description="Seuil cosine pour détection de sujet (0.0-1.0)")
    summary_enabled: bool = Field(..., description="Résumé automatique des conversations longues")
    summary_trigger_messages: int = Field(..., description="Nombre de messages déclenchant le résumé")
    rag_reinjection_enabled: bool = Field(..., description="Réinjection des sources RAG précédentes")
    contextualization_enabled: bool = Field(..., description="Contextualisation des questions de suivi")


class ChatConfigUpdate(BaseModel):
    """Mise à jour de la configuration chat (mémoire conversationnelle)."""
    history_enabled: Optional[bool] = Field(None, description="Activer/désactiver l'historique")
    history_max_turns: Optional[int] = Field(None, ge=1, le=50, description="Nombre max de tours")
    history_max_tokens: Optional[int] = Field(None, ge=256, le=32768, description="Budget tokens max")
    topic_detection_enabled: Optional[bool] = Field(None, description="Activer/désactiver la détection de sujet")
    topic_similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="Seuil de similarité")
    summary_enabled: Optional[bool] = Field(None, description="Activer/désactiver le résumé automatique")
    summary_trigger_messages: Optional[int] = Field(None, ge=4, le=100, description="Seuil de déclenchement du résumé")
    rag_reinjection_enabled: Optional[bool] = Field(None, description="Activer/désactiver la réinjection RAG")
    contextualization_enabled: Optional[bool] = Field(None, description="Activer/désactiver la contextualisation")


# =============================================================================
# CONFIG DEBUG
# =============================================================================

class DebugConfigRead(BaseModel):
    """Lecture de la configuration debug."""
    verbose_logging: bool = Field(..., description="Logging verbeux actif")
    timing_headers_enabled: bool = Field(..., description="Headers X-Debug-* actifs")
    debug_endpoints_enabled: bool = Field(..., description="Endpoints debug accessibles")
    current_log_level: str = Field(..., description="Niveau de log effectif (lecture seule)")


class DebugConfigUpdate(BaseModel):
    """Mise a jour de la configuration debug."""
    verbose_logging: Optional[bool] = Field(None, description="Activer/desactiver le logging verbeux")
    timing_headers_enabled: Optional[bool] = Field(None, description="Activer/desactiver les headers X-Debug-*")
    debug_endpoints_enabled: Optional[bool] = Field(None, description="Activer/desactiver les endpoints debug")


# =============================================================================
# CONFIG LOGGING STRUCTURÉ
# =============================================================================

class LoggingConfigRead(BaseModel):
    """Lecture de la configuration logging structuré."""
    # Niveaux par catégorie
    log_level_technical: str = Field("INFO", description="Niveau pour les logs techniques")
    log_level_access: str = Field("INFO", description="Niveau pour les logs d'accès")
    log_level_audit: str = Field("INFO", description="Niveau pour les logs d'audit")
    log_level_security: str = Field("INFO", description="Niveau pour les logs de sécurité")
    log_level_infra: str = Field("INFO", description="Niveau pour les logs d'infrastructure")
    # Persistance BDD
    log_db_enabled: bool = Field(True, description="Persistance des logs en BDD activée")
    # Rétention par catégorie (jours)
    log_retention_technical_days: int = Field(30, description="Rétention logs techniques (jours)")
    log_retention_access_days: int = Field(30, description="Rétention logs d'accès (jours)")
    log_retention_audit_days: int = Field(365, description="Rétention logs d'audit (jours)")
    log_retention_security_days: int = Field(365, description="Rétention logs de sécurité (jours)")
    log_retention_infra_days: int = Field(14, description="Rétention logs d'infrastructure (jours)")
    # Alerting
    alert_cooldown_minutes: int = Field(15, description="Cooldown de dé-duplication des alertes (minutes)")


class LoggingConfigUpdate(BaseModel):
    """Mise à jour de la configuration logging structuré."""
    # Niveaux par catégorie
    log_level_technical: Optional[str] = Field(
        None, pattern="^(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)$",
        description="Niveau logs techniques"
    )
    log_level_access: Optional[str] = Field(
        None, pattern="^(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)$",
        description="Niveau logs d'accès"
    )
    log_level_audit: Optional[str] = Field(
        None, pattern="^(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)$",
        description="Niveau logs d'audit"
    )
    log_level_security: Optional[str] = Field(
        None, pattern="^(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)$",
        description="Niveau logs de sécurité"
    )
    log_level_infra: Optional[str] = Field(
        None, pattern="^(TRACE|DEBUG|INFO|WARN|ERROR|FATAL)$",
        description="Niveau logs d'infrastructure"
    )
    # Persistance BDD
    log_db_enabled: Optional[bool] = Field(None, description="Activer/désactiver la persistance BDD")
    # Rétention par catégorie (jours)
    log_retention_technical_days: Optional[int] = Field(None, ge=1, le=365, description="Rétention technique (1-365)")
    log_retention_access_days: Optional[int] = Field(None, ge=1, le=365, description="Rétention accès (1-365)")
    log_retention_audit_days: Optional[int] = Field(None, ge=1, le=3650, description="Rétention audit (1-3650)")
    log_retention_security_days: Optional[int] = Field(None, ge=1, le=3650, description="Rétention sécurité (1-3650)")
    log_retention_infra_days: Optional[int] = Field(None, ge=1, le=365, description="Rétention infra (1-365)")
    # Alerting
    alert_cooldown_minutes: Optional[int] = Field(None, ge=1, le=1440, description="Cooldown dé-duplication alertes (1-1440 min)")


# =============================================================================
# NOTIFICATIONS
# =============================================================================

class NotificationConfigRead(BaseModel):
    """Lecture de la configuration des notifications."""
    # Email
    email_enabled: bool = Field(False, description="Notifications email activées")
    email_smtp_host: str = Field("", description="Hôte SMTP")
    email_smtp_port: int = Field(587, description="Port SMTP")
    email_smtp_user: str = Field("", description="Utilisateur SMTP")
    email_smtp_password: str = Field("", description="Mot de passe SMTP")
    email_smtp_tls: bool = Field(True, description="TLS activé")
    email_from_address: str = Field("", description="Adresse expéditeur")
    email_to_addresses: str = Field("", description="Destinataires (séparés par des virgules)")
    # Slack
    slack_enabled: bool = Field(False, description="Notifications Slack activées")
    slack_webhook_url: str = Field("", description="URL du webhook Slack")
    # Webhook
    webhook_enabled: bool = Field(False, description="Notifications webhook activées")
    webhook_url: str = Field("", description="URL du webhook")
    webhook_secret: str = Field("", description="Secret HMAC pour la signature")


class NotificationConfigUpdate(BaseModel):
    """Mise à jour de la configuration des notifications."""
    # Email
    email_enabled: Optional[bool] = Field(None, description="Activer/désactiver les notifications email")
    email_smtp_host: Optional[str] = Field(None, max_length=255, description="Hôte SMTP")
    email_smtp_port: Optional[int] = Field(None, ge=1, le=65535, description="Port SMTP")
    email_smtp_user: Optional[str] = Field(None, max_length=255, description="Utilisateur SMTP")
    email_smtp_password: Optional[str] = Field(None, max_length=255, description="Mot de passe SMTP")
    email_smtp_tls: Optional[bool] = Field(None, description="TLS activé")
    email_from_address: Optional[str] = Field(None, max_length=255, description="Adresse expéditeur")
    email_to_addresses: Optional[str] = Field(None, max_length=1000, description="Destinataires (virgules)")
    # Slack
    slack_enabled: Optional[bool] = Field(None, description="Activer/désactiver Slack")
    slack_webhook_url: Optional[str] = Field(None, max_length=500, description="URL webhook Slack")
    # Webhook
    webhook_enabled: Optional[bool] = Field(None, description="Activer/désactiver webhook")
    webhook_url: Optional[str] = Field(None, max_length=500, description="URL webhook")
    webhook_secret: Optional[str] = Field(None, max_length=255, description="Secret HMAC")


class NotificationTestRequest(BaseModel):
    """Requête de test d'un canal de notification."""
    channel: str = Field(..., pattern="^(email|slack|webhook)$", description="Canal à tester")


# =============================================================================
# CONFIG SMTP (Email Service)
# =============================================================================

class SmtpConfigRead(BaseModel):
    """Lecture de la configuration SMTP pour l'envoi d'emails."""
    # Provider
    provider: str = Field("smtp", description="Provider actif: smtp, sendgrid, mailjet")
    enabled: bool = Field(False, description="Service email activé")
    # SMTP classique
    host: str = Field("", description="Serveur SMTP")
    port: int = Field(587, description="Port SMTP")
    username: str = Field("", description="Identifiant SMTP")
    use_tls: bool = Field(True, description="Utiliser TLS (STARTTLS)")
    use_ssl: bool = Field(False, description="Utiliser SSL")
    password_configured: bool = Field(False, description="Mot de passe SMTP configuré")
    # Expéditeur
    from_email: str = Field("", description="Adresse expéditeur")
    from_name: str = Field("MY-IA", description="Nom expéditeur")
    reply_to: str = Field("", description="Adresse de réponse (optionnel)")
    # APIs alternatives (masquées)
    sendgrid_configured: bool = Field(False, description="SendGrid API configurée")
    mailjet_configured: bool = Field(False, description="Mailjet API configurée")
    # Statut
    last_test_at: Optional[str] = Field(None, description="Date du dernier test")
    last_test_success: Optional[bool] = Field(None, description="Résultat du dernier test")


class SmtpConfigUpdate(BaseModel):
    """Mise à jour de la configuration SMTP."""
    # Provider
    provider: Optional[str] = Field(
        None,
        pattern="^(smtp|sendgrid|mailjet)$",
        description="Provider email"
    )
    enabled: Optional[bool] = Field(None, description="Activer/désactiver le service")
    # SMTP classique
    host: Optional[str] = Field(None, max_length=255, description="Serveur SMTP")
    port: Optional[int] = Field(None, ge=1, le=65535, description="Port SMTP")
    username: Optional[str] = Field(None, max_length=255, description="Identifiant SMTP")
    password: Optional[str] = Field(None, max_length=255, description="Mot de passe SMTP")
    use_tls: Optional[bool] = Field(None, description="Utiliser TLS")
    use_ssl: Optional[bool] = Field(None, description="Utiliser SSL")
    # Expéditeur
    from_email: Optional[str] = Field(None, max_length=255, description="Adresse expéditeur")
    from_name: Optional[str] = Field(None, max_length=255, description="Nom expéditeur")
    reply_to: Optional[str] = Field(None, max_length=255, description="Adresse de réponse")
    # APIs alternatives
    sendgrid_api_key: Optional[str] = Field(None, max_length=255, description="Clé API SendGrid")
    mailjet_api_key: Optional[str] = Field(None, max_length=255, description="Clé API Mailjet")
    mailjet_secret_key: Optional[str] = Field(None, max_length=255, description="Secret Mailjet")


class SmtpTestRequest(BaseModel):
    """Requête de test SMTP."""
    recipient_email: Optional[str] = Field(
        None,
        max_length=255,
        description="Email destinataire (défaut: email de l'admin connecté)"
    )


class SmtpTestResponse(BaseModel):
    """Résultat du test SMTP."""
    success: bool = Field(..., description="Test réussi")
    message: str = Field(..., description="Message descriptif")
    provider: str = Field(..., description="Provider testé")
    recipient: str = Field(..., description="Destinataire du test")
    duration_ms: Optional[int] = Field(None, description="Durée du test en ms")


# =============================================================================
# TEST ET STATISTIQUES RAG
# =============================================================================

class RAGTestRequest(BaseModel):
    """Requête de test RAG."""
    query: str = Field(..., min_length=3, max_length=500, description="Question de test")
    # Overrides optionnels (sinon utilise config actuelle)
    top_k: Optional[int] = Field(None, ge=1, le=50, description="Nombre de chunks à retourner")
    similarity_threshold: Optional[float] = Field(None, ge=0.0, le=1.0, description="Seuil de similarité")
    collection_id: Optional[int] = Field(None, description="Collection cible (défaut: toutes)")


class RAGTestChunk(BaseModel):
    """Chunk retourné par le test RAG."""
    content: str = Field(..., description="Contenu du chunk")
    score: float = Field(..., description="Score de similarité")
    source: str = Field(..., description="Source du chunk (nom du document)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées du chunk")


class RAGTestResponse(BaseModel):
    """Résultat du test RAG."""
    query: str = Field(..., description="Question testée")
    chunks: List[RAGTestChunk] = Field(default_factory=list, description="Chunks retournés")
    stats: Dict[str, Any] = Field(default_factory=dict, description="Statistiques (total_found, filtered, latency_ms)")
    config_used: Dict[str, Any] = Field(default_factory=dict, description="Configuration utilisée (top_k, threshold, embedding_model)")


class RAGStatsResponse(BaseModel):
    """Statistiques RAG globales."""
    collections_count: int = Field(..., description="Nombre de collections")
    documents_count: int = Field(..., description="Nombre de documents")
    chunks_count: int = Field(..., description="Nombre de chunks indexés")
    avg_chunk_size: int = Field(0, description="Taille moyenne des chunks en caractères")
    embedding_model: str = Field(..., description="Modèle d'embedding actif")
    last_indexation: Optional[str] = Field(None, description="Date de dernière indexation")


# =============================================================================
# GEO CONFIG
# =============================================================================

class GeoConfigRead(BaseModel):
    """Lecture de la configuration géographique."""
    default_country: str = Field("FR", description="Code pays par défaut (ISO 3166-1 alpha-2)")
    require_city: bool = Field(False, description="Exiger une ville lors de l'inscription")
    allow_change: bool = Field(True, description="Permettre le changement de pays/ville")


class GeoConfigUpdate(BaseModel):
    """Mise à jour de la configuration géographique."""
    default_country: Optional[str] = Field(
        None,
        min_length=2,
        max_length=2,
        description="Code pays par défaut (ISO 3166-1 alpha-2)"
    )
    require_city: Optional[bool] = Field(None, description="Exiger une ville lors de l'inscription")
    allow_change: Optional[bool] = Field(None, description="Permettre le changement de pays/ville")


# =============================================================================
# APPEARANCE CONFIG
# =============================================================================

class AppearanceConfigRead(BaseModel):
    """Lecture de la configuration d'apparence."""
    global_theme: str = Field("default", description="Thème global (default, dark, corporate, corporate-dark, nature, nature-dark, sunset, sunset-dark, royal, royal-dark)")


class AppearanceConfigUpdate(BaseModel):
    """Mise à jour de la configuration d'apparence."""
    global_theme: Optional[str] = Field(
        None,
        pattern="^(default|dark|corporate|corporate-dark|nature|nature-dark|sunset|sunset-dark|royal|royal-dark)$",
        description="Thème global (default, dark, corporate, corporate-dark, nature, nature-dark, sunset, sunset-dark, royal, royal-dark)"
    )


# =============================================================================
# PERFORMANCE CONFIG
# =============================================================================

class PerfConfigRead(BaseModel):
    """Lecture de la configuration des performances."""
    # Cache RAG Config
    rag_config_cache_ttl: float = Field(30.0, description="TTL du cache de configuration RAG (secondes)")
    # Cache Embeddings
    embedding_cache_size: int = Field(1000, description="Taille max du cache LRU pour embeddings")
    # Parallélisation Embedding
    embedding_batch_size: int = Field(100, description="Taille des batches pour génération embeddings")
    embedding_max_concurrent: int = Field(3, description="Nombre max de batches en parallèle")
    # Cache Query Results
    query_cache_size: int = Field(500, description="Taille max du cache de résultats de recherche")
    query_cache_ttl: float = Field(300.0, description="TTL du cache de résultats (secondes)")
    # Reranker
    rerank_timeout_ms: int = Field(100, description="Timeout max pour le reranking (ms)")
    rerank_top_k: int = Field(5, description="Nombre de résultats après reranking")
    # Métriques
    metrics_window_size: int = Field(1000, description="Taille de la fenêtre pour calcul P50/P95")
    # Mode RAG Fast
    mode_fast_top_k: int = Field(5, description="Mode Fast: chunks récupérés")
    mode_fast_rerank_enabled: bool = Field(False, description="Mode Fast: reranking actif")
    mode_fast_max_context_tokens: int = Field(1000, description="Mode Fast: limite tokens contexte")
    mode_fast_temperature: float = Field(0.1, description="Mode Fast: température LLM")
    # Mode RAG Full
    mode_full_top_k: int = Field(10, description="Mode Full: chunks récupérés")
    mode_full_rerank_enabled: bool = Field(True, description="Mode Full: reranking actif")
    mode_full_max_context_tokens: int = Field(2500, description="Mode Full: limite tokens contexte")
    mode_full_temperature: float = Field(0.3, description="Mode Full: température LLM")


class PerfConfigUpdate(BaseModel):
    """Mise à jour de la configuration des performances."""
    # Cache RAG Config
    rag_config_cache_ttl: Optional[float] = Field(None, ge=0, le=3600, description="TTL du cache de configuration RAG (secondes)")
    # Cache Embeddings
    embedding_cache_size: Optional[int] = Field(None, ge=100, le=10000, description="Taille max du cache LRU pour embeddings")
    # Parallélisation Embedding
    embedding_batch_size: Optional[int] = Field(None, ge=10, le=500, description="Taille des batches pour génération embeddings")
    embedding_max_concurrent: Optional[int] = Field(None, ge=1, le=10, description="Nombre max de batches en parallèle")
    # Cache Query Results
    query_cache_size: Optional[int] = Field(None, ge=100, le=5000, description="Taille max du cache de résultats de recherche")
    query_cache_ttl: Optional[float] = Field(None, ge=0, le=3600, description="TTL du cache de résultats (secondes)")
    # Reranker
    rerank_timeout_ms: Optional[int] = Field(None, ge=10, le=1000, description="Timeout max pour le reranking (ms)")
    rerank_top_k: Optional[int] = Field(None, ge=1, le=20, description="Nombre de résultats après reranking")
    # Métriques
    metrics_window_size: Optional[int] = Field(None, ge=100, le=10000, description="Taille de la fenêtre pour calcul P50/P95")
    # Mode RAG Fast
    mode_fast_top_k: Optional[int] = Field(None, ge=1, le=20, description="Mode Fast: chunks récupérés")
    mode_fast_rerank_enabled: Optional[bool] = Field(None, description="Mode Fast: reranking actif")
    mode_fast_max_context_tokens: Optional[int] = Field(None, ge=500, le=8000, description="Mode Fast: limite tokens contexte")
    mode_fast_temperature: Optional[float] = Field(None, ge=0, le=2, description="Mode Fast: température LLM")
    # Mode RAG Full
    mode_full_top_k: Optional[int] = Field(None, ge=1, le=50, description="Mode Full: chunks récupérés")
    mode_full_rerank_enabled: Optional[bool] = Field(None, description="Mode Full: reranking actif")
    mode_full_max_context_tokens: Optional[int] = Field(None, ge=500, le=8000, description="Mode Full: limite tokens contexte")
    mode_full_temperature: Optional[float] = Field(None, ge=0, le=2, description="Mode Full: température LLM")
