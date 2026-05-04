"""
Module de bootstrap pour charger la configuration depuis la base de donnees.

Ce module permet de charger la configuration de l'application depuis la table
system_configs de PostgreSQL au lieu des variables d'environnement traditionnelles.

Workflow:
    1. L'application demarre avec uniquement les parametres de connexion DB (.env minimal)
    2. Ce module se connecte a la BDD et charge toutes les configurations
    3. Les valeurs sont exposees comme variables d'environnement runtime
    4. L'application peut demarrer normalement

Premier deploiement:
    Si la table system_configs est vide, les valeurs par defaut sont inserees
    automatiquement depuis DEFAULT_CONFIG.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION PAR DEFAUT
# =============================================================================
# Ces valeurs sont utilisees lors du premier deploiement si la BDD est vide

DEFAULT_CONFIG: dict[str, Any] = {
    # Identite
    "app.id": "my-ia",
    "app.name_prefix": "MY-IA",
    "app.title": "MY-IA Assistant",
    "app.description": "Chatbot RAG avec gestion documentaire",
    "app.icon": "🤖",
    "app.version": "1.0.0",

    # Serveur
    "app.host": "0.0.0.0",
    "app.port": 8080,
    "app.environment": "development",
    "app.debug": False,

    # Ports externes
    "ports.frontend": 3000,
    "ports.admin": 8081,
    "ports.api": 8080,

    # Adresse publique
    "public.host": "localhost",
    "public.protocol": "http",

    # LLM Provider
    "llm.provider": "ollama",
    "llm.model": "gemma2:2b",
    "llm.embed_model": "nomic-embed-text",

    # Ollama
    "ollama.host": "ollama",
    "ollama.port": 11434,
    "ollama.timeout": 600.0,

    # Ollama - Options avancées (passées via API)
    "llm.ollama.keep_alive": "5m",        # Durée avant déchargement modèle
    "llm.ollama.num_ctx": 2048,           # Taille contexte en tokens
    "llm.ollama.num_gpu": 999,            # Couches GPU (999 = toutes)
    "llm.ollama.num_parallel": 1,         # Info seulement (config serveur)
    "llm.ollama.auto_preload": False,     # Précharger modèles au démarrage

    # llama.cpp
    "llamacpp.host": "host.docker.internal",
    "llamacpp.port": 8085,

    # ChromaDB
    "chroma.host": "chroma",
    "chroma.port": 8000,
    "chroma.collection_name": "knowledge_base",

    # Whisper
    "whisper.host": "whisper",
    "whisper.port": 8000,

    # RAG
    "rag.top_k": 4,
    "rag.chunk_size": 1000,
    "rag.chunk_overlap": 200,
    "rag.chunking_strategy": "semantic",

    # RAG Compaction - Réduction de la redondance des chunks
    "rag.compaction.enabled": False,
    "rag.compaction.similarity_threshold": 0.85,
    "rag.compaction.extract_enabled": False,
    "rag.compaction.max_sentences": 5,
    "rag.compaction.fetch_multiplier": 3,  # top_k * multiplier = chunks récupérés

    # Logging
    "logging.level": "INFO",
    "logging.format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "logging.retention_days": 30,

    # Securite (ces valeurs DOIVENT etre regenerees au premier deploiement)
    "security.jwt_algorithm": "HS256",
    "security.access_token_expire_minutes": 30,
    "security.refresh_token_expire_days": 7,

    # CORS
    "cors.origins": '["*"]',

    # Rate Limiting
    "rate_limit.chat": "30/minute",
    "rate_limit.upload": "10/minute",
    "rate_limit.stream": "20/minute",
    "rate_limit.admin": "30/minute",

    # Timeouts
    "timeout.http": 30.0,
    "timeout.health_check": 5.0,

    # Storage
    "storage.backend": "local",
    "storage.local_path": "/data/uploads",
    "storage.default_quota_mb": 100,
    "storage.max_file_size_mb": 50,

    # Geo
    "geo.default_country": "FR",
    "geo.require_city": False,
    "geo.allow_change": True,
    "geo.auto_import": False,

    # Email
    "email.backend": "console",
    "email.from": "noreply@myia.local",
    "email.from_name": "MY-IA",

    # SMS
    "sms.backend": "console",
    "sms.verification_enabled": False,
    "sms.otp_expiry_seconds": 300,
    "sms.otp_max_attempts": 3,

    # Registration
    "registration.validation_mode": "email+admin",
    "registration.oauth_auto_approve": False,
    "registration.notify_admin": True,

    # Notifications
    "notifications.email_enabled": True,
    "notifications.sms_enabled": False,
    "notifications.push_enabled": False,

    # Deploiement distant
    "deploy.remote_host": "",
    "deploy.remote_user": "debian",
    "deploy.remote_path": "/home/debian/my-ia",
    "deploy.remote_port": 22,
    "deploy.git_branch": "main",
    "deploy.auto_restart": True,
    "deploy.health_check_url": "/health",
    "deploy.config_files_to_reset": "UI-FRONT/js/config.js,UI-BACK/js/config/env.js",
}


# =============================================================================
# MAPPING CONFIG KEY -> ENV VAR
# =============================================================================
# Mapping entre les cles de config BDD et les variables d'environnement

CONFIG_TO_ENV_MAPPING: dict[str, str] = {
    "app.id": "APP_ID",
    "app.name_prefix": "APP_NAME_PREFIX",
    "app.title": "APP_TITLE",
    "app.description": "APP_DESCRIPTION",
    "app.icon": "APP_ICON",
    "app.version": "APP_VERSION",
    "app.host": "APP_HOST",
    "app.port": "APP_PORT",
    "app.environment": "ENVIRONMENT",
    "app.debug": "DEBUG",

    "ports.frontend": "FRONTEND_PORT",
    "ports.admin": "ADMIN_PORT",
    "ports.api": "APP_PORT",

    "public.host": "PUBLIC_HOST",
    "public.protocol": "PUBLIC_PROTOCOL",

    "llm.provider": "LLM_PROVIDER",
    "llm.model": "LLM_MODEL",
    "llm.embed_model": "EMBED_MODEL",

    "ollama.host": "OLLAMA_HOST",
    "ollama.port": "OLLAMA_PORT",
    "ollama.timeout": "OLLAMA_TIMEOUT",

    "llamacpp.host": "LLAMACPP_HOST",
    "llamacpp.port": "LLAMACPP_PORT",

    "chroma.host": "CHROMA_HOST",
    "chroma.port": "CHROMA_PORT",
    "chroma.collection_name": "COLLECTION_NAME",

    "whisper.host": "WHISPER_HOST",
    "whisper.port": "WHISPER_PORT",

    "rag.top_k": "TOP_K",
    "rag.chunk_size": "CHUNK_SIZE",
    "rag.chunk_overlap": "CHUNK_OVERLAP",
    "rag.chunking_strategy": "CHUNKING_STRATEGY",

    "logging.level": "LOG_LEVEL",

    "security.jwt_algorithm": "JWT_ALGORITHM",
    "security.access_token_expire_minutes": "ACCESS_TOKEN_EXPIRE_MINUTES",
    "security.refresh_token_expire_days": "REFRESH_TOKEN_EXPIRE_DAYS",

    "cors.origins": "CORS_ORIGINS",

    "rate_limit.chat": "RATE_LIMIT_CHAT",
    "rate_limit.upload": "RATE_LIMIT_UPLOAD",
    "rate_limit.stream": "RATE_LIMIT_STREAM",
    "rate_limit.admin": "RATE_LIMIT_ADMIN",

    "timeout.http": "HTTP_TIMEOUT",
    "timeout.health_check": "HEALTH_CHECK_TIMEOUT",

    "storage.backend": "STORAGE_BACKEND",
    "storage.local_path": "STORAGE_LOCAL_PATH",
    "storage.default_quota_mb": "STORAGE_DEFAULT_QUOTA_MB",
    "storage.max_file_size_mb": "STORAGE_MAX_FILE_SIZE_MB",

    "geo.default_country": "GEO_DEFAULT_COUNTRY",
    "geo.auto_import": "GEO_AUTO_IMPORT",

    "email.backend": "EMAIL_BACKEND",
    "email.from": "EMAIL_FROM",
    "email.from_name": "EMAIL_FROM_NAME",

    "sms.backend": "SMS_BACKEND",
    "sms.verification_enabled": "SMS_VERIFICATION_ENABLED",

    "deploy.remote_host": "DEPLOY_REMOTE_HOST",
    "deploy.remote_user": "DEPLOY_REMOTE_USER",
    "deploy.remote_path": "DEPLOY_REMOTE_PATH",
    "deploy.remote_port": "DEPLOY_REMOTE_PORT",
    "deploy.git_branch": "DEPLOY_GIT_BRANCH",
    "deploy.auto_restart": "DEPLOY_AUTO_RESTART",
    "deploy.health_check_url": "DEPLOY_HEALTH_CHECK_URL",
    "deploy.config_files_to_reset": "DEPLOY_CONFIG_FILES_TO_RESET",

    # SMTP / Email
    "notification.email_smtp_host": "SMTP_HOST",
    "notification.email_smtp_port": "SMTP_PORT",
    "notification.email_smtp_user": "SMTP_USERNAME",
    "notification.email_smtp_password": "SMTP_PASSWORD",
    "notification.email_smtp_tls": "SMTP_USE_TLS",
    "notification.email_from_address": "EMAIL_FROM",
    "notification.email_to_addresses": "ADMIN_EMAIL_RECIPIENTS",
    "notification.email_enabled": "NOTIFICATIONS_EMAIL_ENABLED",

    # SMS
    "sms.otp_expiry_seconds": "SMS_OTP_EXPIRY_SECONDS",
    "sms.otp_max_attempts": "SMS_OTP_MAX_ATTEMPTS",

    # Registration
    "registration.validation_mode": "REGISTRATION_VALIDATION_MODE",
    "registration.oauth_auto_approve": "OAUTH_AUTO_APPROVE",
    "registration.notify_admin": "NOTIFY_ADMIN_ON_REGISTRATION",

    # Geo
    "geo.require_city": "GEO_REQUIRE_CITY",
    "geo.allow_change": "GEO_ALLOW_CHANGE",
}


class ConfigBootstrap:
    """
    Charge la configuration depuis la base de donnees.

    Cette classe gere le chargement initial de la configuration
    depuis la table system_configs de PostgreSQL.
    """

    def __init__(self, database_url: str):
        """
        Initialise le bootstrap avec l'URL de connexion.

        Args:
            database_url: URL de connexion PostgreSQL asyncpg
        """
        self.database_url = database_url
        self.engine = None
        self.session_maker = None
        self._config_cache: dict[str, Any] = {}

    async def connect(self) -> bool:
        """
        Etablit la connexion a la base de donnees.

        Returns:
            True si la connexion est etablie, False sinon
        """
        try:
            self.engine = create_async_engine(
                self.database_url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=0,
            )
            self.session_maker = async_sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            # Test de connexion
            async with self.session_maker() as session:
                await session.execute(text("SELECT 1"))

            logger.info("Connexion BDD etablie pour bootstrap config")
            return True

        except Exception as e:
            logger.error(f"Erreur connexion BDD bootstrap: {e}")
            return False

    async def disconnect(self) -> None:
        """Ferme la connexion a la base de donnees."""
        if self.engine:
            await self.engine.dispose()
            logger.info("Connexion BDD bootstrap fermee")

    async def _table_exists(self, session: AsyncSession) -> bool:
        """Verifie si la table system_configs existe."""
        result = await session.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'system_configs'
            )
        """))
        return result.scalar()

    async def _load_all_config(self, session: AsyncSession) -> dict[str, Any]:
        """Charge toutes les configurations depuis la BDD."""
        result = await session.execute(text("""
            SELECT key, value, value_type FROM system_configs
        """))
        rows = result.fetchall()

        config = {}
        for row in rows:
            key, value, value_type = row
            # Convertir selon le type
            if value_type == "int":
                config[key] = int(value) if value else 0
            elif value_type == "float":
                config[key] = float(value) if value else 0.0
            elif value_type == "bool":
                config[key] = value.lower() in ("true", "1", "yes") if value else False
            elif value_type == "json":
                config[key] = json.loads(value) if value else None
            else:
                config[key] = value

        return config

    async def _insert_default_config(self, session: AsyncSession) -> None:
        """Insere la configuration par defaut dans la BDD."""
        logger.info("Insertion de la configuration par defaut...")

        for key, value in DEFAULT_CONFIG.items():
            # Determiner le type
            if isinstance(value, bool):
                value_type = "bool"
                str_value = "true" if value else "false"
            elif isinstance(value, int):
                value_type = "int"
                str_value = str(value)
            elif isinstance(value, float):
                value_type = "float"
                str_value = str(value)
            elif isinstance(value, (dict, list)):
                value_type = "json"
                str_value = json.dumps(value)
            else:
                value_type = "string"
                str_value = str(value)

            # Inserer ou mettre a jour
            await session.execute(text("""
                INSERT INTO system_configs (key, value, value_type, category, description)
                VALUES (:key, :value, :value_type, :category, :description)
                ON CONFLICT (key) DO NOTHING
            """), {
                "key": key,
                "value": str_value,
                "value_type": value_type,
                "category": key.split(".")[0],
                "description": f"Configuration {key}",
            })

        await session.commit()
        logger.info(f"{len(DEFAULT_CONFIG)} configurations par defaut inserees")

    async def _generate_security_keys(self, session: AsyncSession) -> None:
        """Genere les cles de securite si absentes."""
        import secrets

        security_keys = {
            "security.jwt_secret": secrets.token_hex(32),
            "security.secret_key": secrets.token_hex(32),
            "security.encryption_key": secrets.token_hex(32),
            "security.api_key": secrets.token_hex(16),
        }

        for key, value in security_keys.items():
            # Verifier si la cle existe
            result = await session.execute(text("""
                SELECT value FROM system_configs WHERE key = :key
            """), {"key": key})
            existing = result.scalar()

            if not existing:
                await session.execute(text("""
                    INSERT INTO system_configs (key, value, value_type, category, description)
                    VALUES (:key, :value, 'string', 'security', :description)
                """), {
                    "key": key,
                    "value": value,
                    "description": f"Cle de securite {key.split('.')[-1]}",
                })
                logger.info(f"Cle de securite generee: {key}")

        await session.commit()

    async def load_config(self, init_if_empty: bool = True) -> dict[str, Any]:
        """
        Charge la configuration depuis la base de donnees.

        Args:
            init_if_empty: Si True, insere la config par defaut si la table est vide

        Returns:
            Dictionnaire de configuration {key: value}
        """
        if not self.session_maker:
            await self.connect()

        async with self.session_maker() as session:
            # Verifier si la table existe
            if not await self._table_exists(session):
                logger.warning("Table system_configs n'existe pas - utilisation des valeurs par defaut")
                return DEFAULT_CONFIG.copy()

            # Charger la config
            config = await self._load_all_config(session)

            # Si vide et init_if_empty, inserer les valeurs par defaut
            if not config and init_if_empty:
                logger.info("Table system_configs vide - initialisation...")
                await self._insert_default_config(session)
                await self._generate_security_keys(session)
                config = await self._load_all_config(session)

            self._config_cache = config
            logger.info(f"Configuration chargee: {len(config)} parametres")
            return config

    def export_to_env(self, config: Optional[dict[str, Any]] = None) -> None:
        """
        Exporte la configuration vers les variables d'environnement.

        Cette methode permet a l'application de fonctionner comme avant
        en exposant les configurations comme variables d'environnement.

        Args:
            config: Configuration a exporter (utilise le cache si None)
        """
        config = config or self._config_cache

        for db_key, env_var in CONFIG_TO_ENV_MAPPING.items():
            if db_key in config:
                value = config[db_key]
                # Convertir en string pour les variables d'environnement
                if isinstance(value, bool):
                    os.environ[env_var] = "true" if value else "false"
                elif isinstance(value, (dict, list)):
                    os.environ[env_var] = json.dumps(value)
                else:
                    os.environ[env_var] = str(value)

        # Exporter les cles de securite
        security_mappings = {
            "security.jwt_secret": "JWT_SECRET_KEY",
            "security.secret_key": "SECRET_KEY",
            "security.encryption_key": "ENCRYPTION_KEY",
            "security.api_key": "API_KEY",
        }

        for db_key, env_var in security_mappings.items():
            if db_key in config:
                os.environ[env_var] = str(config[db_key])

        logger.info("Configuration exportee vers les variables d'environnement")


async def bootstrap_config_from_db() -> dict[str, Any]:
    """
    Point d'entree principal pour charger la configuration depuis la BDD.

    Cette fonction est appelee au demarrage de l'application pour
    charger toute la configuration depuis PostgreSQL.

    Returns:
        Dictionnaire de configuration
    """
    # Lire l'URL de connexion depuis les variables d'environnement minimales
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        # Construire l'URL depuis les composants
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        user = os.getenv("APP_DB_USER", "myia_user")
        password = os.getenv("APP_DB_PASSWORD", "")
        db_name = os.getenv("APP_DB_NAME", "myia_db")
        database_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"

    bootstrap = ConfigBootstrap(database_url)

    try:
        if await bootstrap.connect():
            config = await bootstrap.load_config(init_if_empty=True)
            bootstrap.export_to_env(config)
            return config
        else:
            logger.warning("Impossible de se connecter a la BDD - utilisation des valeurs par defaut")
            return DEFAULT_CONFIG.copy()
    finally:
        await bootstrap.disconnect()


def bootstrap_sync() -> dict[str, Any]:
    """
    Version synchrone du bootstrap (pour les scripts shell).

    Returns:
        Dictionnaire de configuration
    """
    return asyncio.run(bootstrap_config_from_db())


# =============================================================================
# CLI POUR SCRIPTS SHELL
# =============================================================================

if __name__ == "__main__":
    import sys

    # Mode: dump (affiche la config JSON) ou export (exporte en shell)
    mode = sys.argv[1] if len(sys.argv) > 1 else "dump"

    config = bootstrap_sync()

    if mode == "dump":
        # Affiche la config en JSON
        print(json.dumps(config, indent=2, default=str))

    elif mode == "export":
        # Affiche les exports shell
        bootstrap = ConfigBootstrap("")
        bootstrap._config_cache = config

        for db_key, env_var in CONFIG_TO_ENV_MAPPING.items():
            if db_key in config:
                value = config[db_key]
                if isinstance(value, bool):
                    print(f'export {env_var}="{str(value).lower()}"')
                elif isinstance(value, (dict, list)):
                    print(f"export {env_var}='{json.dumps(value)}'")
                else:
                    print(f'export {env_var}="{value}"')

    elif mode == "check":
        # Verifie simplement la connexion
        if config:
            print("OK")
            sys.exit(0)
        else:
            print("FAIL")
            sys.exit(1)
