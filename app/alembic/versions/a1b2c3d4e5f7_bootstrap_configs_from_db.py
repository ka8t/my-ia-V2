"""Bootstrap configs from DB

Insert all missing configurations from DEFAULT_CONFIG into system_configs.
This enables BOOTSTRAP_FROM_DB mode where all config comes from the database.

Revision ID: a1b2c3d4e5f7
Revises: 369d59635d04
Create Date: 2026-02-12
"""
from alembic import op
import sqlalchemy as sa
import json
import secrets

# revision identifiers
revision = 'a1b2c3d4e5f7'
down_revision = '369d59635d04'
branch_labels = None
depends_on = None

# Configuration par defaut a inserer
DEFAULT_CONFIGS = [
    # === APP ===
    ("app.id", "my-ia", "string", "app", "Identifiant technique unique"),
    ("app.name_prefix", "MY-IA", "string", "app", "Prefixe pour containers Docker"),
    ("app.title", "MY-IA Assistant", "string", "app", "Titre affiche dans l'interface"),
    ("app.description", "Chatbot RAG avec gestion documentaire", "string", "app", "Description de l'application"),
    ("app.icon", "🤖", "string", "app", "Icone de l'application"),
    ("app.host", "0.0.0.0", "string", "app", "Adresse d'ecoute du serveur"),
    ("app.port", "8080", "int", "app", "Port du serveur API"),
    ("app.environment", "development", "string", "app", "Environnement (development/production)"),

    # === PORTS ===
    ("ports.frontend", "3000", "int", "ports", "Port du frontend"),
    ("ports.admin", "8081", "int", "ports", "Port de l'admin"),
    ("ports.api", "8080", "int", "ports", "Port de l'API"),

    # === PUBLIC ===
    ("public.host", "localhost", "string", "public", "Hostname public"),
    ("public.protocol", "http", "string", "public", "Protocole public (http/https)"),

    # === OLLAMA ===
    ("ollama.host", "ollama", "string", "ollama", "Hostname Ollama"),
    ("ollama.port", "11434", "int", "ollama", "Port Ollama"),
    ("ollama.timeout", "600.0", "float", "ollama", "Timeout Ollama en secondes"),

    # === LLAMACPP ===
    ("llamacpp.host", "host.docker.internal", "string", "llamacpp", "Hostname llama.cpp"),
    ("llamacpp.port", "8081", "int", "llamacpp", "Port llama.cpp"),

    # === CHROMA ===
    ("chroma.host", "chroma", "string", "chroma", "Hostname ChromaDB"),
    ("chroma.port", "8000", "int", "chroma", "Port ChromaDB"),
    ("chroma.collection_name", "knowledge_base", "string", "chroma", "Nom de la collection par defaut"),

    # === WHISPER ===
    ("whisper.host", "whisper", "string", "whisper", "Hostname Whisper"),
    ("whisper.port", "8000", "int", "whisper", "Port Whisper"),

    # === LOGGING ===
    ("logging.level", "INFO", "string", "logging", "Niveau de log par defaut"),
    ("logging.format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s", "string", "logging", "Format des logs"),

    # === SECURITY ===
    ("security.jwt_algorithm", "HS256", "string", "security", "Algorithme JWT"),
    ("security.access_token_expire_minutes", "30", "int", "security", "Duree de vie du token d'acces (minutes)"),
    ("security.refresh_token_expire_days", "7", "int", "security", "Duree de vie du refresh token (jours)"),

    # === CORS ===
    ("cors.origins", '["*"]', "json", "cors", "Origines CORS autorisees"),

    # === RATE LIMIT ===
    ("rate_limit.chat", "30/minute", "string", "rate_limit", "Limite de requetes chat"),
    ("rate_limit.upload", "10/minute", "string", "rate_limit", "Limite de requetes upload"),
    ("rate_limit.stream", "20/minute", "string", "rate_limit", "Limite de requetes streaming"),
    ("rate_limit.admin", "30/minute", "string", "rate_limit", "Limite de requetes admin"),

    # === TIMEOUT ===
    ("timeout.http", "30.0", "float", "timeout", "Timeout HTTP par defaut"),
    ("timeout.health_check", "5.0", "float", "timeout", "Timeout health check"),

    # === STORAGE ===
    ("storage.backend", "local", "string", "storage", "Backend de stockage (local/minio/s3)"),
    ("storage.local_path", "/data/uploads", "string", "storage", "Chemin de stockage local"),
    ("storage.default_quota_mb", "100", "int", "storage", "Quota par defaut par utilisateur (MB)"),
    ("storage.max_file_size_mb", "50", "int", "storage", "Taille max par fichier (MB)"),

    # === GEO ===
    ("geo.default_country", "FR", "string", "geo", "Pays par defaut"),
    ("geo.require_city", "false", "bool", "geo", "Ville obligatoire a l'inscription"),
    ("geo.allow_change", "true", "bool", "geo", "Autoriser le changement de localisation"),
    ("geo.auto_import", "false", "bool", "geo", "Import automatique des donnees geo"),

    # === EMAIL ===
    ("email.backend", "console", "string", "email", "Backend email (console/smtp)"),
    ("email.from", "noreply@myia.local", "string", "email", "Adresse expediteur"),
    ("email.from_name", "MY-IA", "string", "email", "Nom expediteur"),

    # === SMS ===
    ("sms.backend", "console", "string", "sms", "Backend SMS (console/twilio/ovh)"),
    ("sms.verification_enabled", "false", "bool", "sms", "Verification SMS activee"),
    ("sms.otp_expiry_seconds", "300", "int", "sms", "Duree de validite OTP (secondes)"),
    ("sms.otp_max_attempts", "3", "int", "sms", "Nombre max de tentatives OTP"),

    # === REGISTRATION ===
    ("registration.validation_mode", "email+admin", "string", "registration", "Mode de validation (email/admin/email+admin/auto)"),
    ("registration.oauth_auto_approve", "false", "bool", "registration", "Auto-approbation OAuth"),
    ("registration.allowed_roles", '["admin","validator"]', "json", "registration", "Roles autorises a valider"),
    ("registration.notify_admin", "true", "bool", "registration", "Notifier les admins a l'inscription"),
]


def upgrade() -> None:
    # Connexion pour executer les requetes
    conn = op.get_bind()

    # Inserer chaque config si elle n'existe pas
    for key, value, value_type, category, description in DEFAULT_CONFIGS:
        # Verifier si existe deja
        result = conn.execute(
            sa.text("SELECT 1 FROM system_configs WHERE key = :key"),
            {"key": key}
        )
        if result.fetchone() is None:
            conn.execute(
                sa.text("""
                    INSERT INTO system_configs (key, value, value_type, category, description)
                    VALUES (:key, :value, :value_type, :category, :description)
                """),
                {
                    "key": key,
                    "value": value,
                    "value_type": value_type,
                    "category": category,
                    "description": description
                }
            )

    # Generer les cles de securite si absentes
    security_keys = [
        ("security.jwt_secret", "Cle secrete JWT"),
        ("security.secret_key", "Cle secrete application"),
        ("security.encryption_key", "Cle de chiffrement PII"),
        ("security.api_key", "Cle API"),
    ]

    for key, description in security_keys:
        result = conn.execute(
            sa.text("SELECT 1 FROM system_configs WHERE key = :key"),
            {"key": key}
        )
        if result.fetchone() is None:
            conn.execute(
                sa.text("""
                    INSERT INTO system_configs (key, value, value_type, category, description)
                    VALUES (:key, :value, 'string', 'security', :description)
                """),
                {
                    "key": key,
                    "value": secrets.token_hex(32),
                    "description": description
                }
            )


def downgrade() -> None:
    # Ne pas supprimer les configs au downgrade
    # Les configs ajoutees restent en place
    pass
