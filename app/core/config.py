"""
Configuration centralisée avec pydantic-settings

Ce module centralise toute la configuration de l'application.
Il supporte deux modes de fonctionnement:

1. Mode classique: Toutes les variables sont dans .env
2. Mode BDD: Seule la connexion DB est dans .env, le reste vient de la BDD

Le mode est determine automatiquement:
- Si BOOTSTRAP_FROM_DB=true dans .env, charge depuis la BDD
- Sinon, utilise les variables d'environnement classiques
"""
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def normalize_database_url(url: str) -> str:
    """
    Normalise l'URL de connexion PostgreSQL en convertissant les identifiants en minuscules.

    PostgreSQL convertit automatiquement les identifiants non-quotés en minuscules.
    Cette fonction assure la cohérence entre les variables d'environnement et PostgreSQL.

    Format: postgresql+asyncpg://user:password@host:port/database
    Convertit: user et database en minuscules (password reste inchangé)
    """
    # Pattern pour extraire les parties de l'URL PostgreSQL asyncpg
    pattern = r'^(postgresql\+asyncpg://)([^:]+):([^@]+)@([^:]+):(\d+)/(.+)$'
    match = re.match(pattern, url)

    if not match:
        # Si le format ne correspond pas, retourner tel quel
        return url

    prefix, user, password, host, port, database = match.groups()

    # Convertir user et database en minuscules (PostgreSQL le fait automatiquement)
    user_lower = user.lower()
    database_lower = database.lower()

    return f"{prefix}{user_lower}:{password}@{host}:{port}/{database_lower}"

# Chemin vers le fichier .env à la racine du projet
# En local : /path/to/my-ia/.env
# En Docker : les variables sont passées via docker-compose env_file
ENV_FILE = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    """Configuration globale de l'application MY-IA"""

    model_config = SettingsConfigDict(
        env_file=ENV_FILE if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Application
    app_name: str = "MY-IA API"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    environment: str = "development"

    # Server
    app_host: str = "0.0.0.0"
    app_port: int = 8080

    # Database (seul champ vraiment requis depuis .env)
    database_url: str

    @field_validator("database_url")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        """Normalise l'URL PostgreSQL (identifiants en minuscules)"""
        return normalize_database_url(v)

    # LLM Provider
    llm_provider: str = "ollama"  # "ollama" | "llamacpp"

    # Ollama
    ollama_host: str = "host.docker.internal"
    ollama_port: int = 11434
    llm_model: str = "gemma2:2b"  # Nom du modèle LLM (ex: mistral, llama3)
    embed_model: str = "nomic-embed-text"

    # llama.cpp (llama-server)
    llamacpp_host: str = "host.docker.internal"
    llamacpp_port: int = 8085
    llamacpp_model: Optional[str] = None  # Fichier GGUF chargé
    llamacpp_embed_model: Optional[str] = None

    # ChromaDB
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_path: str = "/chroma/chroma"
    collection_name: str = "knowledge_base"

    # Whisper (Speech-to-Text)
    # Port interne du container = 8000 (le mapping externe 9000:8000 est pour tests)
    whisper_host: str = "whisper"
    whisper_port: int = 8000

    # RAG
    top_k: int = 4
    chunk_size: int = 1000
    chunk_overlap: int = 200
    chunking_strategy: str = "semantic"
    datasets_dir: str = "/code/datasets"

    # Static data (Geo)
    static_data_dir: str = "/code/static-datas"

    # Security (seront chargés depuis la BDD)
    api_key: str = "default-api-key-change-me"
    secret_key: str = "default-secret-key-change-me"

    # Encryption (PII)
    # Clé de chiffrement AES-256 (64 caractères hex = 32 bytes)
    # Générer avec: openssl rand -hex 32
    encryption_key: Optional[str] = None

    # JWT Configuration (seront chargés depuis la BDD)
    jwt_secret_key: str = "default-jwt-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS
    cors_origins: list[str] = ["*"]

    # Rate Limiting
    rate_limit_chat: str = "30/minute"
    rate_limit_upload: str = "10/minute"
    rate_limit_stream: str = "20/minute"
    rate_limit_admin: str = "30/minute"

    # Timeouts
    ollama_timeout: float = 600.0
    http_timeout: float = 30.0
    health_check_timeout: float = 5.0

    # === Storage ===
    storage_backend: str = "local"  # "local" | "minio" | "s3"
    storage_local_path: str = "/data/uploads"

    # Quotas
    storage_default_quota_mb: int = 100  # Quota par défaut par utilisateur (MB)
    storage_max_file_size_mb: int = 50  # Taille max par fichier (MB)
    storage_allowed_mime_types: str = (
        "application/pdf,"
        "text/plain,"
        "text/csv,"
        "text/markdown,"
        "text/html,"
        "application/json,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "application/vnd.openxmlformats-officedocument.presentationml.presentation,"
        "application/msword,"
        "application/vnd.ms-excel,"
        "application/vnd.ms-powerpoint,"
        "image/png,"
        "image/jpeg,"
        "image/gif,"
        "image/webp"
    )
    storage_blocked_extensions: str = ".exe,.bat,.sh,.cmd,.ps1,.dll,.so,.bin"

    # MinIO (futur)
    storage_minio_endpoint: Optional[str] = None
    storage_minio_access_key: Optional[str] = None
    storage_minio_secret_key: Optional[str] = None
    storage_minio_bucket: str = "documents"
    storage_minio_secure: bool = False

    # S3 (futur)
    storage_s3_bucket: Optional[str] = None
    storage_s3_region: Optional[str] = None
    storage_s3_access_key: Optional[str] = None
    storage_s3_secret_key: Optional[str] = None

    @property
    def embedding_model(self) -> str:
        """Alias pour embed_model (cohérence avec la config RAG)"""
        return self.embed_model

    @property
    def ollama_url(self) -> str:
        """URL complète pour Ollama (http://host:port)"""
        return f"http://{self.ollama_host}:{self.ollama_port}"

    @property
    def chroma_url(self) -> str:
        """URL complète pour ChromaDB (http://host:port)"""
        return f"http://{self.chroma_host}:{self.chroma_port}"


# =============================================================================
# BOOTSTRAP DEPUIS LA BDD (optionnel)
# =============================================================================

def _bootstrap_from_db_if_enabled() -> None:
    """
    Charge la configuration depuis la BDD si BOOTSTRAP_FROM_DB=true.

    Cette fonction est appelée avant l'instanciation de Settings pour
    pré-charger les variables d'environnement depuis la BDD.

    Utilise une connexion synchrone pour éviter les conflits d'event loop.
    """
    bootstrap_enabled = os.getenv("BOOTSTRAP_FROM_DB", "false").lower() == "true"

    if not bootstrap_enabled:
        return

    try:
        # Import tardif pour éviter les dépendances circulaires
        from app.core.bootstrap_sync import bootstrap_config_sync

        logger.info("Bootstrap configuration depuis la BDD (sync)...")
        config = bootstrap_config_sync()
        logger.info(f"Configuration chargée: {len(config)} paramètres")

    except ImportError as e:
        logger.warning(f"Module bootstrap non disponible: {e}")
    except Exception as e:
        logger.error(f"Erreur lors du bootstrap depuis la BDD: {e}")
        logger.warning("Utilisation des variables d'environnement par défaut")


# Tentative de bootstrap depuis la BDD (si activé)
_bootstrap_from_db_if_enabled()

# Instance globale
settings = Settings()
