"""
Module de bootstrap SYNCHRONE pour charger la configuration depuis PostgreSQL.

Ce module utilise psycopg2 (synchrone) au lieu de asyncpg pour éviter
les conflits d'event loop lors du démarrage de l'application.
"""

import json
import logging
import os
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


# Mapping entre les clés de config BDD et les variables d'environnement
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
    "storage.allowed_mime_types": "STORAGE_ALLOWED_MIME_TYPES",
    "storage.blocked_extensions": "STORAGE_BLOCKED_EXTENSIONS",

    "geo.default_country": "GEO_DEFAULT_COUNTRY",
    "geo.auto_import": "GEO_AUTO_IMPORT",
    "geo.require_city": "GEO_REQUIRE_CITY",
    "geo.allow_change": "GEO_ALLOW_CHANGE",

    "email.backend": "EMAIL_BACKEND",
    "email.from": "EMAIL_FROM",
    "email.from_name": "EMAIL_FROM_NAME",

    "sms.backend": "SMS_BACKEND",
    "sms.verification_enabled": "SMS_VERIFICATION_ENABLED",
    "sms.otp_expiry_seconds": "SMS_OTP_EXPIRY_SECONDS",
    "sms.otp_max_attempts": "SMS_OTP_MAX_ATTEMPTS",

    "registration.validation_mode": "REGISTRATION_VALIDATION_MODE",
    "registration.oauth_auto_approve": "OAUTH_AUTO_APPROVE",
    "registration.notify_admin": "NOTIFY_ADMIN_ON_REGISTRATION",

    "notification.email_smtp_host": "SMTP_HOST",
    "notification.email_smtp_port": "SMTP_PORT",
    "notification.email_smtp_user": "SMTP_USERNAME",
    "notification.email_smtp_password": "SMTP_PASSWORD",
    "notification.email_smtp_tls": "SMTP_USE_TLS",
    "notification.email_from_address": "EMAIL_FROM",
    "notification.email_enabled": "NOTIFICATIONS_EMAIL_ENABLED",

    "deploy.remote_host": "DEPLOY_REMOTE_HOST",
    "deploy.remote_user": "DEPLOY_REMOTE_USER",
    "deploy.remote_path": "DEPLOY_REMOTE_PATH",
    "deploy.remote_port": "DEPLOY_REMOTE_PORT",
    "deploy.git_branch": "DEPLOY_GIT_BRANCH",
    "deploy.auto_restart": "DEPLOY_AUTO_RESTART",
    "deploy.health_check_url": "DEPLOY_HEALTH_CHECK_URL",
    "deploy.config_files_to_reset": "DEPLOY_CONFIG_FILES_TO_RESET",
}

# Clés de sécurité (mapping séparé)
SECURITY_MAPPINGS: dict[str, str] = {
    "security.jwt_secret": "JWT_SECRET_KEY",
    "security.secret_key": "SECRET_KEY",
    "security.encryption_key": "ENCRYPTION_KEY",
    "security.api_key": "API_KEY",
}


def _get_db_connection_params() -> dict:
    """
    Extrait les paramètres de connexion PostgreSQL depuis l'environnement.

    Supporte deux formats :
    - DATABASE_URL (postgresql+asyncpg://user:pass@host:port/db)
    - Variables séparées (APP_DB_USER, APP_DB_PASSWORD, etc.)
    """
    database_url = os.getenv("DATABASE_URL", "")

    if database_url:
        # Parser l'URL asyncpg pour psycopg2
        # Format: postgresql+asyncpg://user:password@host:port/database
        import re
        pattern = r'postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
        match = re.match(pattern, database_url)

        if match:
            user, password, host, port, dbname = match.groups()
            return {
                "host": host,
                "port": int(port),
                "user": user,
                "password": password,
                "dbname": dbname,
            }

    # Fallback vers variables séparées
    return {
        "host": os.getenv("POSTGRES_HOST", "postgres"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("APP_DB_USER", "my_ia_db_user"),
        "password": os.getenv("APP_DB_PASSWORD", ""),
        "dbname": os.getenv("APP_DB_NAME", "my_ia_db"),
    }


def _load_config_from_db(conn) -> dict[str, Any]:
    """Charge toutes les configurations depuis la table system_configs."""
    config = {}

    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        # Vérifier si la table existe
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'system_configs'
            )
        """)
        if not cursor.fetchone()["exists"]:
            logger.warning("Table system_configs n'existe pas")
            return config

        # Charger toutes les configs
        cursor.execute("SELECT key, value, value_type FROM system_configs")
        rows = cursor.fetchall()

        for row in rows:
            key = row["key"]
            value = row["value"]
            value_type = row["value_type"]

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


def _export_to_env(config: dict[str, Any]) -> None:
    """Exporte la configuration vers les variables d'environnement."""
    exported = 0

    # Exporter les configs normales
    for db_key, env_var in CONFIG_TO_ENV_MAPPING.items():
        if db_key in config:
            value = config[db_key]
            if isinstance(value, bool):
                os.environ[env_var] = "true" if value else "false"
            elif isinstance(value, (dict, list)):
                os.environ[env_var] = json.dumps(value)
            else:
                os.environ[env_var] = str(value)
            exported += 1

    # Exporter les clés de sécurité
    for db_key, env_var in SECURITY_MAPPINGS.items():
        if db_key in config:
            os.environ[env_var] = str(config[db_key])
            exported += 1

    logger.info(f"Configuration exportée: {exported} variables")


def bootstrap_config_sync() -> dict[str, Any]:
    """
    Point d'entrée principal pour charger la configuration depuis PostgreSQL.

    Utilise une connexion synchrone (psycopg2) pour éviter les conflits
    d'event loop avec uvicorn/asyncio.

    Returns:
        Dictionnaire de configuration {key: value}
    """
    config = {}
    conn = None

    try:
        # Connexion à PostgreSQL
        params = _get_db_connection_params()
        logger.info(f"Bootstrap: connexion à PostgreSQL {params['host']}:{params['port']}/{params['dbname']}")

        conn = psycopg2.connect(**params, connect_timeout=5)

        # Charger la config
        config = _load_config_from_db(conn)

        if config:
            logger.info(f"Bootstrap: {len(config)} paramètres chargés depuis la BDD")
            _export_to_env(config)
        else:
            logger.warning("Bootstrap: aucune configuration trouvée en BDD")

    except psycopg2.OperationalError as e:
        logger.error(f"Bootstrap: impossible de se connecter à PostgreSQL: {e}")
    except Exception as e:
        logger.error(f"Bootstrap: erreur lors du chargement: {e}")
    finally:
        if conn:
            conn.close()

    return config


if __name__ == "__main__":
    # Test standalone
    import sys
    logging.basicConfig(level=logging.INFO)

    config = bootstrap_config_sync()

    if "--dump" in sys.argv:
        print(json.dumps(config, indent=2, default=str))
    else:
        print(f"Loaded {len(config)} config entries")
