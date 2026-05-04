#!/usr/bin/env python3
"""
Script de seeding pour MY-IA
============================
Ce script verifie et insere les donnees necessaires au fonctionnement de l'application:
- Tables de reference (roles, modes de conversation, types de ressources, actions d'audit)
- Utilisateurs de test (si debug.endpoints_enabled=true en BDD, ou premier install)

Execution: python scripts/docker/seed.py

Le script est idempotent: il peut etre execute plusieurs fois sans creer de doublons.
"""
import os
import re
import sys
import asyncio
from datetime import datetime, timezone

# Ajouter le chemin du code pour les imports
sys.path.insert(0, "/code")

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from fastapi_users.password import PasswordHelper

# Import des services de chiffrement
from app.common.crypto.encryption import get_encryption_service
from app.common.crypto.search import get_search_index_service


def normalize_database_url(url: str) -> str:
    """
    Normalise l'URL PostgreSQL en convertissant les identifiants en minuscules.
    PostgreSQL convertit automatiquement les identifiants non-quotes en minuscules.
    """
    pattern = r'^(postgresql\+asyncpg://)([^:]+):([^@]+)@([^:]+):(\d+)/(.+)$'
    match = re.match(pattern, url)
    if not match:
        return url
    prefix, user, password, host, port, database = match.groups()
    return f"{prefix}{user.lower()}:{password}@{host}:{port}/{database.lower()}"


# Configuration - URL normalisee pour PostgreSQL
_raw_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://my_ia_user:my_ia_db_pass@postgres:5432/my_ia_db")
DATABASE_URL = normalize_database_url(_raw_url)

# Variables d'environnement pour les utilisateurs de test
# Chaque utilisateur a son propre mot de passe et profil par defaut
# NOTE: Emails harmonises avec scripts/lib/env.sh (@test.example)
TEST_ADMIN_EMAIL = os.getenv("TEST_ADMIN_EMAIL", "admin@test.example")
TEST_ADMIN_PASSWORD = os.getenv("TEST_ADMIN_PASSWORD", "Admin123!")
TEST_ADMIN_FIRST_NAME = os.getenv("TEST_ADMIN_FIRST_NAME", "Admin")
TEST_ADMIN_LAST_NAME = os.getenv("TEST_ADMIN_LAST_NAME", "Testeur")
TEST_ADMIN_PHONE = os.getenv("TEST_ADMIN_PHONE", "+33612345001")
TEST_ADMIN_ADDRESS = os.getenv("TEST_ADMIN_ADDRESS", "1 Place de l'Hotel de Ville")

TEST_USER_EMAIL = os.getenv("TEST_USER_EMAIL", "user@test.example")
TEST_USER_PASSWORD = os.getenv("TEST_USER_PASSWORD", "User123!")
TEST_USER_FIRST_NAME = os.getenv("TEST_USER_FIRST_NAME", "Pierre")
TEST_USER_LAST_NAME = os.getenv("TEST_USER_LAST_NAME", "Dupont")
TEST_USER_PHONE = os.getenv("TEST_USER_PHONE", "+33612345002")
TEST_USER_ADDRESS = os.getenv("TEST_USER_ADDRESS", "25 Rue de la Paix")

TEST_CONTRIBUTOR_EMAIL = os.getenv("TEST_CONTRIBUTOR_EMAIL", "contributor@test.example")
TEST_CONTRIBUTOR_PASSWORD = os.getenv("TEST_CONTRIBUTOR_PASSWORD", "Contrib123!")
TEST_CONTRIBUTOR_FIRST_NAME = os.getenv("TEST_CONTRIBUTOR_FIRST_NAME", "Marie")
TEST_CONTRIBUTOR_LAST_NAME = os.getenv("TEST_CONTRIBUTOR_LAST_NAME", "Martin")
TEST_CONTRIBUTOR_PHONE = os.getenv("TEST_CONTRIBUTOR_PHONE", "+33612345003")
TEST_CONTRIBUTOR_ADDRESS = os.getenv("TEST_CONTRIBUTOR_ADDRESS", "8 Avenue des Champs-Elysees")

TEST_VALIDATOR_EMAIL = os.getenv("TEST_VALIDATOR_EMAIL", "validator@test.example")
TEST_VALIDATOR_PASSWORD = os.getenv("TEST_VALIDATOR_PASSWORD", "Valid123!")
TEST_VALIDATOR_FIRST_NAME = os.getenv("TEST_VALIDATOR_FIRST_NAME", "Jean")
TEST_VALIDATOR_LAST_NAME = os.getenv("TEST_VALIDATOR_LAST_NAME", "Valideur")
TEST_VALIDATOR_PHONE = os.getenv("TEST_VALIDATOR_PHONE", "+33612345004")
TEST_VALIDATOR_ADDRESS = os.getenv("TEST_VALIDATOR_ADDRESS", "15 Boulevard Haussmann")

# Ville par defaut pour les utilisateurs de test (Paris = 29583)
TEST_USERS_CITY_ID = int(os.getenv("TEST_USERS_CITY_ID", "29583"))


# Password hasher (meme instance que FastAPI Users : pwdlib/argon2id)
password_helper = PasswordHelper()


# =============================================================================
# DONNEES DE REFERENCE
# =============================================================================

ROLES = [
    {"id": 1, "name": "admin", "display_name": "Administrateur", "description": "Acces complet a toutes les fonctionnalites"},
    {"id": 2, "name": "user", "display_name": "Utilisateur", "description": "Utilisateur standard avec acces limite"},
    {"id": 3, "name": "contributor", "display_name": "Contributeur", "description": "Peut uploader des documents publics"},
    {"id": 4, "name": "validator", "display_name": "Validateur", "description": "Peut valider les inscriptions utilisateurs"},
]

CONVERSATION_MODES = [
    {"id": 1, "name": "chatbot", "display_name": "Chatbot", "description": "Mode conversationnel standard",
     "system_prompt": "Tu es un assistant IA serviable et precis. Reponds aux questions en te basant sur le contexte fourni."},
    {"id": 2, "name": "assistant", "display_name": "Assistant", "description": "Mode oriente taches",
     "system_prompt": "Tu es un assistant oriente taches. Aide l'utilisateur a accomplir ses objectifs de maniere efficace."},
]

RESOURCE_TYPES = [
    {"id": 1, "name": "user", "display_name": "Utilisateur"},
    {"id": 2, "name": "document", "display_name": "Document"},
    {"id": 3, "name": "conversation", "display_name": "Conversation"},
    {"id": 4, "name": "message", "display_name": "Message"},
    {"id": 5, "name": "collection", "display_name": "Collection"},
    {"id": 6, "name": "role", "display_name": "Role"},
    {"id": 7, "name": "system_config", "display_name": "Configuration systeme"},
]

AUDIT_ACTIONS = [
    {"name": "login", "display_name": "Connexion", "severity": "info"},
    {"name": "logout", "display_name": "Déconnexion", "severity": "info"},
    {"name": "login_failed", "display_name": "Tentative de connexion échouée", "severity": "warning"},
    {"name": "password_changed", "display_name": "Mot de passe modifié", "severity": "info"},
    {"name": "password_reset", "display_name": "Réinitialisation mot de passe", "severity": "info"},
    {"name": "profile_updated", "display_name": "Profil mis à jour", "severity": "info"},
    {"name": "document_created", "display_name": "Document créé", "severity": "info"},
    {"name": "document_deleted", "display_name": "Document supprimé", "severity": "info"},
    {"name": "document_indexed", "display_name": "Document indexé", "severity": "info"},
    {"name": "conversation_created", "display_name": "Conversation créée", "severity": "info"},
    {"name": "conversation_deleted", "display_name": "Conversation supprimée", "severity": "info"},
    {"name": "user_created", "display_name": "Utilisateur créé", "severity": "info"},
    {"name": "user_updated", "display_name": "Utilisateur modifié", "severity": "info"},
    {"name": "user_deleted", "display_name": "Utilisateur supprimé", "severity": "warning"},
    {"name": "role_changed", "display_name": "Rôle modifié", "severity": "warning"},
    {"name": "collection_created", "display_name": "Collection créée", "severity": "info"},
    {"name": "collection_deleted", "display_name": "Collection supprimée", "severity": "warning"},
    {"name": "config_updated", "display_name": "Configuration modifiée", "severity": "info"},
    {"name": "registration_approved", "display_name": "Inscription approuvée", "severity": "info"},
    {"name": "registration_rejected", "display_name": "Inscription rejetée", "severity": "warning"},
]

# Configuration RAG par defaut (recherche hybride)
RAG_CONFIGS = [
    {"key": "rag.min_chunk_length", "value": "50", "value_type": "int", "category": "rag",
     "description": "Longueur minimale d'un chunk (exclut les noms isolés)"},
    {"key": "rag.keyword_boost", "value": "0.15", "value_type": "float", "category": "rag",
     "description": "Bonus de similarité pour les mots-clés trouvés (0-1)"},
    {"key": "rag.stopwords_language", "value": "fr", "value_type": "string", "category": "rag",
     "description": "Langue des stopwords pour la recherche hybride (fr/en/none)"},
]

# Configuration LLM Provider par defaut
LLM_CONFIGS = [
    {"key": "llm.provider", "value": "ollama", "value_type": "string", "category": "llm",
     "description": "Provider LLM actif (ollama ou llamacpp)"},

    {"key": "llm.ollama_host", "value": "ollama", "value_type": "string", "category": "llm",
     "description": "Host du serveur Ollama"},
    {"key": "llm.ollama_port", "value": "11434", "value_type": "int", "category": "llm",
     "description": "Port du serveur Ollama"},
    {"key": "llm.llamacpp_host", "value": "host.docker.internal", "value_type": "string", "category": "llm",
     "description": "Host du serveur llama.cpp"},
    {"key": "llm.llamacpp_port", "value": "8081", "value_type": "int", "category": "llm",
     "description": "Port du serveur llama.cpp"},
    {"key": "llm.ollama.llm_model", "value": "mistral", "value_type": "string", "category": "llm",
     "description": "Modèle LLM par défaut pour Ollama"},
    {"key": "llm.ollama.embedding_model", "value": "nomic-embed-text:latest", "value_type": "string", "category": "llm",
     "description": "Modèle d'embedding par défaut pour Ollama"},
    {"key": "llm.llamacpp.llm_model", "value": "", "value_type": "string", "category": "llm",
     "description": "Modèle LLM configuré pour llama.cpp"},
    {"key": "llm.llamacpp.embedding_model", "value": "", "value_type": "string", "category": "llm",
     "description": "Modèle d'embedding configuré pour llama.cpp"},
    # Ollama advanced config
    {"key": "llm.ollama.keep_alive", "value": "24h", "value_type": "string", "category": "llm",
     "description": "Durée avant déchargement modèle Ollama"},
    {"key": "llm.ollama.num_ctx", "value": "4096", "value_type": "int", "category": "llm",
     "description": "Taille contexte en tokens pour Ollama"},
    {"key": "llm.ollama.num_gpu", "value": "999", "value_type": "int", "category": "llm",
     "description": "Couches GPU pour Ollama (999 = toutes)"},
    {"key": "llm.ollama.auto_preload", "value": "true", "value_type": "bool", "category": "llm",
     "description": "Précharger modèles au démarrage de l'app"},
    {"key": "llm.ollama.num_parallel", "value": "4", "value_type": "int", "category": "llm",
     "description": "Info seulement (config serveur Ollama)"},
]

# Configuration Performance par defaut
PERF_CONFIGS = [
    # Cache RAG Config
    {"key": "perf.rag_config_cache_ttl", "value": "30.0", "value_type": "float", "category": "perf",
     "description": "TTL du cache de configuration RAG (secondes)"},
    # Cache Embeddings
    {"key": "perf.embedding_cache_size", "value": "1000", "value_type": "int", "category": "perf",
     "description": "Taille max du cache LRU pour embeddings"},
    # Parallélisation Embedding
    {"key": "perf.embedding_batch_size", "value": "100", "value_type": "int", "category": "perf",
     "description": "Taille des batches pour génération embeddings"},
    {"key": "perf.embedding_max_concurrent", "value": "3", "value_type": "int", "category": "perf",
     "description": "Nombre max de batches en parallèle"},
    # Cache Query Results
    {"key": "perf.query_cache_size", "value": "500", "value_type": "int", "category": "perf",
     "description": "Taille max du cache de résultats de recherche"},
    {"key": "perf.query_cache_ttl", "value": "300.0", "value_type": "float", "category": "perf",
     "description": "TTL du cache de résultats (secondes)"},
    # Cache Pinned Docs
    {"key": "perf.pinned_cache_size", "value": "100", "value_type": "int", "category": "perf",
     "description": "Nombre max de chunks pinned en mémoire"},
    {"key": "perf.pin_access_threshold", "value": "5", "value_type": "int", "category": "perf",
     "description": "Seuil d'accès pour pin un chunk"},
    # Métriques
    {"key": "perf.metrics_window_size", "value": "1000", "value_type": "int", "category": "perf",
     "description": "Taille de la fenêtre pour calcul P50/P95"},
    # Reranker
    {"key": "perf.rerank_timeout_ms", "value": "100", "value_type": "int", "category": "perf",
     "description": "Timeout max pour le reranking (ms)"},
    {"key": "perf.rerank_top_k", "value": "5", "value_type": "int", "category": "perf",
     "description": "Nombre de résultats après reranking"},
]

# Configuration Mode RAG (Fast vs Full)
RAG_MODE_CONFIGS = [
    # Mode Fast (latence prioritaire)
    {"key": "rag.mode.fast.top_k", "value": "5", "value_type": "int", "category": "rag",
     "description": "Mode Fast: nombre de chunks à récupérer"},
    {"key": "rag.mode.fast.rerank_enabled", "value": "false", "value_type": "bool", "category": "rag",
     "description": "Mode Fast: activer le reranking"},
    {"key": "rag.mode.fast.max_context_tokens", "value": "1000", "value_type": "int", "category": "rag",
     "description": "Mode Fast: limite de tokens pour le contexte"},
    {"key": "rag.mode.fast.temperature", "value": "0.1", "value_type": "float", "category": "rag",
     "description": "Mode Fast: température LLM"},
    # Mode Full (qualité prioritaire)
    {"key": "rag.mode.full.top_k", "value": "10", "value_type": "int", "category": "rag",
     "description": "Mode Full: nombre de chunks à récupérer"},
    {"key": "rag.mode.full.rerank_enabled", "value": "true", "value_type": "bool", "category": "rag",
     "description": "Mode Full: activer le reranking"},
    {"key": "rag.mode.full.max_context_tokens", "value": "2500", "value_type": "int", "category": "rag",
     "description": "Mode Full: limite de tokens pour le contexte"},
    {"key": "rag.mode.full.temperature", "value": "0.3", "value_type": "float", "category": "rag",
     "description": "Mode Full: température LLM"},
]


# =============================================================================
# FONCTIONS DE SEEDING
# =============================================================================

async def seed_roles(session: AsyncSession) -> int:
    """Insere les roles s'ils n'existent pas."""
    count = 0
    for role in ROLES:
        result = await session.execute(
            text("SELECT id FROM roles WHERE id = :id"),
            {"id": role["id"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO roles (id, name, display_name, description)
                    VALUES (:id, :name, :display_name, :description)
                """),
                role
            )
            count += 1
            print(f"  [+] Role: {role['name']}")
    return count


async def seed_conversation_modes(session: AsyncSession) -> int:
    """Insere les modes de conversation s'ils n'existent pas."""
    count = 0
    for mode in CONVERSATION_MODES:
        result = await session.execute(
            text("SELECT id FROM conversation_modes WHERE id = :id"),
            {"id": mode["id"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO conversation_modes (id, name, display_name, description, system_prompt)
                    VALUES (:id, :name, :display_name, :description, :system_prompt)
                """),
                mode
            )
            count += 1
            print(f"  [+] Mode: {mode['name']}")
    return count


async def seed_resource_types(session: AsyncSession) -> int:
    """Insere les types de ressources s'ils n'existent pas."""
    count = 0
    for rt in RESOURCE_TYPES:
        result = await session.execute(
            text("SELECT id FROM resource_types WHERE id = :id"),
            {"id": rt["id"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO resource_types (id, name, display_name)
                    VALUES (:id, :name, :display_name)
                """),
                rt
            )
            count += 1
            print(f"  [+] Resource type: {rt['name']}")
    return count


async def seed_audit_actions(session: AsyncSession) -> int:
    """Insere les actions d'audit s'elles n'existent pas."""
    count = 0
    for action in AUDIT_ACTIONS:
        result = await session.execute(
            text("SELECT name FROM audit_actions WHERE name = :name"),
            {"name": action["name"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO audit_actions (name, display_name, severity)
                    VALUES (:name, :display_name, :severity)
                """),
                action
            )
            count += 1
            print(f"  [+] Audit action: {action['name']}")
    return count


async def seed_rag_configs(session: AsyncSession) -> int:
    """Insere les configurations RAG par defaut si elles n'existent pas."""
    count = 0
    for config in RAG_CONFIGS:
        result = await session.execute(
            text("SELECT id FROM system_configs WHERE key = :key"),
            {"key": config["key"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO system_configs (key, value, value_type, category, description)
                    VALUES (:key, :value, :value_type, :category, :description)
                """),
                config
            )
            count += 1
            print(f"  [+] RAG config: {config['key']} = {config['value']}")
        else:
            print(f"  [=] RAG config existe deja: {config['key']}")
    return count


async def seed_llm_configs(session: AsyncSession) -> int:
    """Insere les configurations LLM provider par defaut si elles n'existent pas."""
    count = 0
    for config in LLM_CONFIGS:
        result = await session.execute(
            text("SELECT id FROM system_configs WHERE key = :key"),
            {"key": config["key"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO system_configs (key, value, value_type, category, description)
                    VALUES (:key, :value, :value_type, :category, :description)
                """),
                config
            )
            count += 1
            print(f"  [+] LLM config: {config['key']} = {config['value']}")
        else:
            print(f"  [=] LLM config existe deja: {config['key']}")
    return count


async def seed_perf_configs(session: AsyncSession) -> int:
    """Insere les configurations de performance par defaut si elles n'existent pas."""
    count = 0
    for config in PERF_CONFIGS:
        result = await session.execute(
            text("SELECT id FROM system_configs WHERE key = :key"),
            {"key": config["key"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO system_configs (key, value, value_type, category, description)
                    VALUES (:key, :value, :value_type, :category, :description)
                """),
                config
            )
            count += 1
            print(f"  [+] Perf config: {config['key']} = {config['value']}")
        else:
            print(f"  [=] Perf config existe deja: {config['key']}")
    return count


async def seed_rag_mode_configs(session: AsyncSession) -> int:
    """Insere les configurations de mode RAG (fast/full) si elles n'existent pas."""
    count = 0
    for config in RAG_MODE_CONFIGS:
        result = await session.execute(
            text("SELECT id FROM system_configs WHERE key = :key"),
            {"key": config["key"]}
        )
        if result.fetchone() is None:
            await session.execute(
                text("""
                    INSERT INTO system_configs (key, value, value_type, category, description)
                    VALUES (:key, :value, :value_type, :category, :description)
                """),
                config
            )
            count += 1
            print(f"  [+] RAG mode config: {config['key']} = {config['value']}")
        else:
            print(f"  [=] RAG mode config existe deja: {config['key']}")
    return count




async def seed_test_users(session: AsyncSession) -> int:
    """
    Cree les utilisateurs de test si debug.endpoints_enabled=true en BDD,
    ou si aucun utilisateur n'existe (securite premier install).
    Utilise les variables d'environnement pour email/password.
    """
    # Lire debug.endpoints_enabled depuis la BDD (table system_configs)
    result = await session.execute(
        text("SELECT value FROM system_configs WHERE key = 'debug.endpoints_enabled'")
    )
    row = result.scalar_one_or_none()
    debug_enabled = row is not None and str(row).lower() in ("true", "1", "yes", "on")

    # Securite premier install : si aucun utilisateur n'existe, creer quand meme
    user_count_result = await session.execute(text("SELECT COUNT(*) FROM users"))
    user_count = user_count_result.scalar()

    if not debug_enabled and user_count > 0:
        print("  [i] debug.endpoints_enabled=false et utilisateurs existants : test users non crees")
        return 0

    if not debug_enabled and user_count == 0:
        print("  [!] Premier install detecte (aucun utilisateur) : creation des test users par securite")

    count = 0
    import uuid

    # Services de chiffrement
    encryption_service = get_encryption_service()
    search_service = get_search_index_service()

    # Verifier si la ville de test existe (peut ne pas etre importee)
    city_result = await session.execute(
        text("SELECT id FROM cities WHERE id = :city_id"),
        {"city_id": TEST_USERS_CITY_ID}
    )
    city_exists = city_result.scalar_one_or_none()
    city_id_to_use = TEST_USERS_CITY_ID if city_exists else None

    if not city_exists:
        print(f"  [!] Ville ID {TEST_USERS_CITY_ID} non trouvee - city_id sera NULL")
    else:
        print(f"  [i] Ville ID {TEST_USERS_CITY_ID} trouvee")

    # 4 utilisateurs de test (un par role) avec profil complet
    test_users = [
        {
            "email": TEST_ADMIN_EMAIL,
            "username": TEST_ADMIN_EMAIL.split("@")[0].replace(".", "_"),
            "password": TEST_ADMIN_PASSWORD,
            "first_name": TEST_ADMIN_FIRST_NAME,
            "last_name": TEST_ADMIN_LAST_NAME,
            "phone": TEST_ADMIN_PHONE,
            "address": TEST_ADMIN_ADDRESS,
            "role_id": 1,  # admin
            "role_name": "admin",
            "is_superuser": True,
        },
        {
            "email": TEST_USER_EMAIL,
            "username": TEST_USER_EMAIL.split("@")[0].replace(".", "_"),
            "password": TEST_USER_PASSWORD,
            "first_name": TEST_USER_FIRST_NAME,
            "last_name": TEST_USER_LAST_NAME,
            "phone": TEST_USER_PHONE,
            "address": TEST_USER_ADDRESS,
            "role_id": 2,  # user
            "role_name": "user",
            "is_superuser": False,
        },
        {
            "email": TEST_CONTRIBUTOR_EMAIL,
            "username": TEST_CONTRIBUTOR_EMAIL.split("@")[0].replace(".", "_"),
            "password": TEST_CONTRIBUTOR_PASSWORD,
            "first_name": TEST_CONTRIBUTOR_FIRST_NAME,
            "last_name": TEST_CONTRIBUTOR_LAST_NAME,
            "phone": TEST_CONTRIBUTOR_PHONE,
            "address": TEST_CONTRIBUTOR_ADDRESS,
            "role_id": 3,  # contributor
            "role_name": "contributor",
            "is_superuser": False,
        },
        {
            "email": TEST_VALIDATOR_EMAIL,
            "username": TEST_VALIDATOR_EMAIL.split("@")[0].replace(".", "_"),
            "password": TEST_VALIDATOR_PASSWORD,
            "first_name": TEST_VALIDATOR_FIRST_NAME,
            "last_name": TEST_VALIDATOR_LAST_NAME,
            "phone": TEST_VALIDATOR_PHONE,
            "address": TEST_VALIDATOR_ADDRESS,
            "role_id": 4,  # validator
            "role_name": "validator",
            "is_superuser": False,
        },
    ]

    for user_data in test_users:
        # Verifier si l'utilisateur existe deja
        result = await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": user_data["email"]}
        )
        if result.fetchone() is not None:
            print(f"  [=] Utilisateur existe deja: {user_data['email']}")
            continue

        # Hasher le mot de passe
        hashed_password = password_helper.hash(user_data["password"])
        user_id = str(uuid.uuid4())

        # Chiffrer les donnees personnelles (PII)
        encrypted_first_name = encryption_service.encrypt(user_data["first_name"])
        encrypted_last_name = encryption_service.encrypt(user_data["last_name"])
        encrypted_phone = encryption_service.encrypt(user_data["phone"])
        encrypted_address = encryption_service.encrypt(user_data["address"])

        # Creer les index de recherche
        first_name_search = search_service.create_trigram_index(user_data["first_name"])
        last_name_search = search_service.create_trigram_index(user_data["last_name"])
        phone_blind_index = search_service.create_blind_index(user_data["phone"])

        # Garder les listes Python (asyncpg les convertit automatiquement en ARRAY)
        first_name_search_list = list(first_name_search) if first_name_search else []
        last_name_search_list = list(last_name_search) if last_name_search else []

        await session.execute(
            text("""
                INSERT INTO users (
                    id, email, username, hashed_password,
                    is_active, is_superuser, is_verified,
                    role_id, approval_status, country_code,
                    first_name, first_name_search,
                    last_name, last_name_search,
                    phone, phone_blind_index,
                    address_line1, city_id
                ) VALUES (
                    :id, :email, :username, :hashed_password,
                    true, :is_superuser, true,
                    :role_id, 'approved', 'FR',
                    :first_name, :first_name_search,
                    :last_name, :last_name_search,
                    :phone, :phone_blind_index,
                    :address_line1, :city_id
                )
            """),
            {
                "id": user_id,
                "email": user_data["email"],
                "username": user_data["username"],
                "hashed_password": hashed_password,
                "is_superuser": user_data["is_superuser"],
                "role_id": user_data["role_id"],
                "first_name": encrypted_first_name,
                "first_name_search": first_name_search_list,
                "last_name": encrypted_last_name,
                "last_name_search": last_name_search_list,
                "phone": encrypted_phone,
                "phone_blind_index": phone_blind_index,
                "address_line1": encrypted_address,
                "city_id": city_id_to_use,
            }
        )
        count += 1
        print(f"  [+] Utilisateur cree: {user_data['email']} ({user_data['first_name']} {user_data['last_name']}, role: {user_data['role_name']})")

    if count > 0:
        print(f"\n  Identifiants de test:")
        print(f"    - Admin:       {TEST_ADMIN_EMAIL} / {TEST_ADMIN_PASSWORD}")
        print(f"    - User:        {TEST_USER_EMAIL} / {TEST_USER_PASSWORD}")
        print(f"    - Contributor: {TEST_CONTRIBUTOR_EMAIL} / {TEST_CONTRIBUTOR_PASSWORD}")
        print(f"    - Validator:   {TEST_VALIDATOR_EMAIL} / {TEST_VALIDATOR_PASSWORD}")

    return count


# =============================================================================
# MAIN
# =============================================================================

async def main():
    """Fonction principale de seeding."""
    print("\n" + "=" * 60)
    print("        MY-IA - Seeding de la base de donnees")
    print("=" * 60)
    print(f"\nDatabase: {DATABASE_URL[:50]}...")
    print(f"Test user: {TEST_USER_EMAIL}")
    print(f"Test admin: {TEST_ADMIN_EMAIL}")
    print(f"(debug.endpoints_enabled lu depuis la BDD)")
    print()

    # Creer le moteur de base de donnees
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    total_inserted = 0

    try:
        async with async_session() as session:
            # 1. Tables de reference
            print("[1/9] Roles...")
            total_inserted += await seed_roles(session)

            print("[2/9] Modes de conversation...")
            total_inserted += await seed_conversation_modes(session)

            print("[3/9] Types de ressources...")
            total_inserted += await seed_resource_types(session)

            print("[4/9] Actions d'audit...")
            total_inserted += await seed_audit_actions(session)

            print("[5/9] Configuration RAG...")
            total_inserted += await seed_rag_configs(session)

            print("[6/9] Configuration LLM Provider...")
            total_inserted += await seed_llm_configs(session)

            print("[7/9] Configuration Performance...")
            total_inserted += await seed_perf_configs(session)

            print("[8/9] Configuration Mode RAG (fast/full)...")
            total_inserted += await seed_rag_mode_configs(session)

            # 2. Utilisateurs de test (si debug.endpoints_enabled en BDD ou premier install)
            print("[9/9] Utilisateurs de test...")
            total_inserted += await seed_test_users(session)

            # Commit
            await session.commit()

            print()
            print("=" * 60)
            if total_inserted > 0:
                print(f"  Seeding termine: {total_inserted} enregistrement(s) insere(s)")
            else:
                print("  Seeding termine: base de donnees deja a jour")
            print("=" * 60)
            print()

    except Exception as e:
        print(f"\n[ERREUR] Echec du seeding: {e}")
        raise
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
