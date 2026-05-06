#!/bin/bash
# =============================================================================
# MY-IA - Fonctions de generation de fichier .env
# =============================================================================
# Ce fichier contient les fonctions pour generer le fichier .env.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/env.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier (pour generate_key, sanitize)
#
# =============================================================================

# =============================================================================
# GENERATION DES IDENTIFIANTS POSTGRESQL
# =============================================================================
# Genere les identifiants PostgreSQL a partir du prefixe.
#
# Usage:
#   generate_pg_identifiers "my_ia_v2"
#
# Resultat:
#   Definit les variables globales:
#     - POSTGRES_USER
#     - APP_DB_USER
#     - APP_DB_NAME
# =============================================================================

generate_pg_identifiers() {
    local prefix="$1"
    log_debug "[generate_pg_identifiers] Entree avec prefix='$prefix'"

    local prefix_sanitized
    prefix_sanitized=$(sanitize "$prefix" false)
    log_debug "[generate_pg_identifiers] Prefix sanitize: '$prefix' -> '$prefix_sanitized'"

    POSTGRES_USER=$(sanitize "${prefix_sanitized}_postgres_admin" false)
    log_debug "[generate_pg_identifiers] POSTGRES_USER: '${prefix_sanitized}_postgres_admin' -> '$POSTGRES_USER'"

    APP_DB_USER=$(sanitize "${prefix_sanitized}_db_user" false)
    log_debug "[generate_pg_identifiers] APP_DB_USER: '${prefix_sanitized}_db_user' -> '$APP_DB_USER'"

    APP_DB_NAME=$(sanitize "${prefix_sanitized}_db" false)
    log_debug "[generate_pg_identifiers] APP_DB_NAME: '${prefix_sanitized}_db' -> '$APP_DB_NAME'"

    # Exporter pour utilisation dans les heredocs
    export POSTGRES_USER APP_DB_USER APP_DB_NAME
    log_debug "[generate_pg_identifiers] Variables exportees"
}

# =============================================================================
# GENERATION DES CLES DE SECURITE
# =============================================================================
# Genere toutes les cles de securite.
#
# Usage:
#   generate_security_keys
#
# Resultat:
#   Definit les variables globales:
#     - JWT_SECRET_KEY (64 hex)
#     - ENCRYPTION_KEY (64 hex)
#     - SECRET_KEY (64 hex)
#     - API_KEY (32 hex)
# =============================================================================

generate_security_keys() {
    log_debug "[generate_security_keys] Debut de la generation des cles"

    # Preserve existing keys if already set, otherwise generate new ones
    if [[ -z "$JWT_SECRET_KEY" ]]; then
        JWT_SECRET_KEY=$(generate_key 32)
        log_debug "[generate_security_keys] JWT_SECRET_KEY: NOUVELLE cle generee (${#JWT_SECRET_KEY} chars)"
    else
        log_debug "[generate_security_keys] JWT_SECRET_KEY: cle EXISTANTE conservee (${#JWT_SECRET_KEY} chars)"
    fi

    if [[ -z "$ENCRYPTION_KEY" ]]; then
        ENCRYPTION_KEY=$(generate_key 32)
        log_debug "[generate_security_keys] ENCRYPTION_KEY: NOUVELLE cle generee (${#ENCRYPTION_KEY} chars)"
    else
        log_debug "[generate_security_keys] ENCRYPTION_KEY: cle EXISTANTE conservee (${#ENCRYPTION_KEY} chars)"
    fi

    if [[ -z "$SECRET_KEY" ]]; then
        SECRET_KEY=$(generate_key 32)
        log_debug "[generate_security_keys] SECRET_KEY: NOUVELLE cle generee (${#SECRET_KEY} chars)"
    else
        log_debug "[generate_security_keys] SECRET_KEY: cle EXISTANTE conservee (${#SECRET_KEY} chars)"
    fi

    if [[ -z "$API_KEY" ]]; then
        API_KEY=$(generate_key 16)
        log_debug "[generate_security_keys] API_KEY: NOUVELLE cle generee (${#API_KEY} chars)"
    else
        log_debug "[generate_security_keys] API_KEY: cle EXISTANTE conservee (${#API_KEY} chars)"
    fi

    # Cle de chiffrement N8N (pour credentials stockes dans N8N)
    if [[ -z "$N8N_ENCRYPTION_KEY" ]]; then
        N8N_ENCRYPTION_KEY=$(generate_key 32)
        log_debug "[generate_security_keys] N8N_ENCRYPTION_KEY: NOUVELLE cle generee (${#N8N_ENCRYPTION_KEY} chars)"
    else
        log_debug "[generate_security_keys] N8N_ENCRYPTION_KEY: cle EXISTANTE conservee (${#N8N_ENCRYPTION_KEY} chars)"
    fi

    # Exporter pour utilisation dans les heredocs
    export JWT_SECRET_KEY ENCRYPTION_KEY SECRET_KEY API_KEY N8N_ENCRYPTION_KEY
    log_debug "[generate_security_keys] Toutes les cles exportees"
}

# =============================================================================
# BACKUP DU FICHIER .ENV
# =============================================================================
# Sauvegarde le fichier .env actuel avant modification.
#
# Usage:
#   backup_env_file "/path/to/.env"
#
# Resultat:
#   Cree une copie du fichier .env dans .env.backup
#   Retourne 0 si backup effectue, 1 si pas de fichier a sauvegarder
# =============================================================================

backup_env_file() {
    local env_file="$1"
    local backup_file="${env_file}.backup"

    log_debug "[backup_env_file] Tentative de backup: $env_file -> $backup_file"

    if [[ -f "$env_file" ]]; then
        cp "$env_file" "$backup_file"
        log_debug "[backup_env_file] Backup cree avec succes"
        log_info "Backup cree: $backup_file"
        return 0
    else
        log_debug "[backup_env_file] Fichier source inexistant, pas de backup"
        return 1
    fi
}

# =============================================================================
# CHARGEMENT DES VARIABLES POUR COMPARAISON
# =============================================================================
# Charge les variables d'un fichier .env dans des variables prefixees.
#
# Usage:
#   load_env_vars_prefixed "/path/to/.env" "OLD"
#
# Resultat:
#   Definit des variables comme OLD_APP_NAME_PREFIX, OLD_POSTGRES_PASSWORD, etc.
# =============================================================================

load_env_vars_prefixed() {
    local env_file="$1"
    local prefix="$2"

    if [[ ! -f "$env_file" ]]; then
        return 1
    fi

    # Note: "|| true" empeche set -e de quitter quand read atteint EOF
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
        # Ignorer les commentaires et lignes vides
        [[ -z "$key" || "$key" =~ ^# ]] && continue
        # Nettoyer la cle (enlever espaces)
        key=$(echo "$key" | tr -d ' ')
        # Enlever les guillemets de la valeur
        value=$(echo "$value" | sed 's/^["'"'"']//;s/["'"'"']$//')
        # Definir la variable prefixee
        eval "${prefix}_${key}=\"\$value\""
    done < "$env_file"

    return 0
}

# =============================================================================
# ECRITURE DU FICHIER .ENV
# =============================================================================
# Ecrit le fichier .env complet.
#
# Usage:
#   write_env_file "/path/to/.env"
#
# Prerequis:
#   Les variables suivantes doivent etre definies:
#     - APP_NAME_PREFIX, POSTGRES_USER, POSTGRES_PASSWORD, etc.
#     - JWT_SECRET_KEY, ENCRYPTION_KEY, etc.
#
# Parametre:
#   $1 : Chemin du fichier .env a ecrire
# =============================================================================

write_env_file() {
    local output_file="$1"
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    log_debug "[write_env_file] Debut de l'ecriture vers: $output_file"
    log_debug "[write_env_file] Timestamp: $timestamp"
    log_debug "[write_env_file] Variables principales:"
    log_debug "[write_env_file]   APP_NAME_PREFIX=$APP_NAME_PREFIX"
    log_debug "[write_env_file]   SANITIZED_PREFIX=$SANITIZED_PREFIX"
    log_debug "[write_env_file]   POSTGRES_USER=$POSTGRES_USER"
    log_debug "[write_env_file]   APP_DB_USER=$APP_DB_USER"
    log_debug "[write_env_file]   APP_DB_NAME=$APP_DB_NAME"
    log_debug "[write_env_file]   FRONTEND_PORT=$FRONTEND_PORT"
    log_debug "[write_env_file]   ADMIN_PORT=$ADMIN_PORT"
    log_debug "[write_env_file]   APP_PORT=$APP_PORT"
    log_debug "[write_env_file]   POSTGRES_PORT=$POSTGRES_PORT"
    log_debug "[write_env_file]   CHROMA_PORT=$CHROMA_PORT"
    log_debug "[write_env_file]   OLLAMA_PORT=$OLLAMA_PORT"
    log_debug "[write_env_file]   LLM_MODEL=$LLM_MODEL"
    log_debug "[write_env_file]   EMBED_MODEL=$EMBED_MODEL"
    log_debug "[write_env_file]   DEBUG=$DEBUG"
    log_debug "[write_env_file]   CORS_ORIGINS=$CORS_ORIGINS"
    log_debug "[write_env_file]   EMAIL_BACKEND=$EMAIL_BACKEND"
    log_debug "[write_env_file]   SMS_BACKEND=$SMS_BACKEND"

    # Utiliser un sous-shell avec fd 3 pour isoler le heredoc de stdin
    # Necessaire pour compatibilite avec stdin pipe (ex: echo "q" | script.sh)
    log_debug "[write_env_file] Ouverture du descripteur de fichier 3"
    log_debug "[write_env_file] Ecriture du contenu heredoc..."
    exec 3>&1
    {
    cat << ENVEOF
# ============================================
# MY-IA - Variables d'environnement
# ============================================
# FICHIER GENERE AUTOMATIQUEMENT - ${timestamp}
# Source: .env.example
# Script: scripts/generate-env.sh
#
# Pour regenerer: ./scripts/generate-env.sh --force
# ============================================

# =============================================================================
# IDENTITE DE L'APPLICATION
# =============================================================================
APP_ID=${APP_ID:-my-ia}
APP_NAME_PREFIX=${APP_NAME_PREFIX}
SANITIZED_PREFIX=${SANITIZED_PREFIX}
APP_TITLE="${APP_TITLE:-MY-IA Assistant}"
APP_DESCRIPTION="${APP_DESCRIPTION:-Chatbot RAG avec gestion documentaire}"
APP_ICON=${APP_ICON:-🤖}
APP_VERSION=${APP_VERSION:-1.0.0}
APP_INSTANCE_ID=${APP_INSTANCE_ID}

# =============================================================================
# PORTS RESEAU
# =============================================================================
FRONTEND_PORT=${FRONTEND_PORT:-3000}
ADMIN_PORT=${ADMIN_PORT:-8081}
APP_PORT=${APP_PORT:-8080}
POSTGRES_PORT=${POSTGRES_PORT:-5432}

# =============================================================================
# ADRESSE PUBLIQUE
# =============================================================================
PUBLIC_HOST=${PUBLIC_HOST:-localhost}
PUBLIC_PROTOCOL=${PUBLIC_PROTOCOL:-http}

# =============================================================================
# APPLICATION (FastAPI)
# =============================================================================
APP_NAME="\${APP_NAME_PREFIX} API"
APP_VERSION=1.0.0
APP_HOST=0.0.0.0
FRONTEND_HOST=${PUBLIC_HOST:-localhost}
API_URL=${PUBLIC_PROTOCOL:-http}://${PUBLIC_HOST:-localhost}:${APP_PORT:-8080}
ENVIRONMENT=${ENVIRONMENT:-development}
LOG_LEVEL=${LOG_LEVEL:-INFO}

# =============================================================================
# ENVIRONNEMENT DE DEPLOIEMENT
# =============================================================================
DEPLOY_ENV=${DEPLOY_ENV:-dev}
UVICORN_WORKERS=${UVICORN_WORKERS:-2}

# =============================================================================
# MODE DEBUG
# =============================================================================
DEBUG=${DEBUG:-true}

# =============================================================================
# JWT AUTHENTICATION
# =============================================================================
JWT_SECRET_KEY=${JWT_SECRET_KEY}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# =============================================================================
# DATABASE (PostgreSQL)
# =============================================================================
# Identifiants normalises selon les regles PostgreSQL (minuscules, pas de tirets)
# Voir CLAUDE.md section "Regles de Nommage PostgreSQL"
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
APP_DB_USER=${APP_DB_USER}
APP_DB_PASSWORD=${APP_DB_PASSWORD}
APP_DB_NAME=${APP_DB_NAME}
DATABASE_URL=postgresql+asyncpg://\${APP_DB_USER}:\${APP_DB_PASSWORD}@postgres:5432/\${APP_DB_NAME}

# =============================================================================
# OLLAMA (LLM)
# =============================================================================
OLLAMA_HOST=${OLLAMA_HOST:-ollama}
OLLAMA_PORT=${OLLAMA_PORT:-11434}
LLM_MODEL=${LLM_MODEL:-gemma2:2b}
EMBED_MODEL=${EMBED_MODEL:-nomic-embed-text}

# =============================================================================
# CHROMADB
# =============================================================================
CHROMA_HOST=chroma
CHROMA_PORT=${CHROMA_PORT:-8000}
COLLECTION_NAME=knowledge_base

# =============================================================================
# SECURITE
# =============================================================================
API_KEY=${API_KEY}
SECRET_KEY=${SECRET_KEY}
ENCRYPTION_KEY=${ENCRYPTION_KEY}

# =============================================================================
# CORS
# =============================================================================
CORS_ORIGINS=${CORS_ORIGINS}

# =============================================================================
# RAG CONFIGURATION
# =============================================================================
TOP_K=${TOP_K:-4}
CHUNK_SIZE=${CHUNK_SIZE:-1000}
CHUNK_OVERLAP=${CHUNK_OVERLAP:-200}
CHUNKING_STRATEGY=${CHUNKING_STRATEGY:-semantic}
DATASETS_DIR=/code/datasets

# =============================================================================
# DONNEES STATIQUES (Geo)
# =============================================================================
STATIC_DATA_DIR=${STATIC_DATA_DIR:-/code/static-datas}

# =============================================================================
# RATE LIMITING
# =============================================================================
RATE_LIMIT_CHAT=${RATE_LIMIT_CHAT:-30/minute}
RATE_LIMIT_UPLOAD=${RATE_LIMIT_UPLOAD:-10/minute}
RATE_LIMIT_STREAM=${RATE_LIMIT_STREAM:-20/minute}

# =============================================================================
# TIMEOUTS
# =============================================================================
OLLAMA_TIMEOUT=${OLLAMA_TIMEOUT:-600.0}
HTTP_TIMEOUT=${HTTP_TIMEOUT:-30.0}
HEALTH_CHECK_TIMEOUT=${HEALTH_CHECK_TIMEOUT:-5.0}

# =============================================================================
# DONNEES GEOGRAPHIQUES
# =============================================================================
GEO_DEFAULT_COUNTRY=${GEO_DEFAULT_COUNTRY:-FR}
GEO_AUTO_IMPORT=${GEO_AUTO_IMPORT:-false}
GEO_CITIES_SOURCE=${GEO_CITIES_SOURCE:-file}

# =============================================================================
# EMAIL
# =============================================================================
EMAIL_BACKEND=${EMAIL_BACKEND:-console}
EMAIL_FROM=${EMAIL_FROM:-noreply@myia.local}
EMAIL_FROM_NAME=${EMAIL_FROM_NAME:-MY-IA}
FRONTEND_URL=${PUBLIC_PROTOCOL:-http}://${PUBLIC_HOST:-localhost}:${FRONTEND_PORT:-3000}
SENDGRID_API_KEY=${SENDGRID_API_KEY}
SMTP_HOST=${SMTP_HOST}
SMTP_PORT=${SMTP_PORT:-587}
SMTP_USERNAME=${SMTP_USERNAME}
SMTP_PASSWORD=${SMTP_PASSWORD}
SMTP_USE_TLS=${SMTP_USE_TLS:-true}

# =============================================================================
# SMS
# =============================================================================
SMS_BACKEND=${SMS_BACKEND:-console}
SMS_VERIFICATION_ENABLED=${SMS_VERIFICATION_ENABLED:-false}
SMS_OTP_EXPIRY_SECONDS=${SMS_OTP_EXPIRY_SECONDS:-300}
SMS_OTP_MAX_ATTEMPTS=${SMS_OTP_MAX_ATTEMPTS:-3}
TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID}
TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN}
TWILIO_PHONE_NUMBER=${TWILIO_PHONE_NUMBER}
OVH_SMS_ACCOUNT=${OVH_SMS_ACCOUNT}
OVH_SMS_LOGIN=${OVH_SMS_LOGIN}
OVH_SMS_PASSWORD=${OVH_SMS_PASSWORD}
OVH_SMS_SENDER=${OVH_SMS_SENDER:-MY-IA}
VONAGE_API_KEY=${VONAGE_API_KEY}
VONAGE_API_SECRET=${VONAGE_API_SECRET}
VONAGE_FROM=${VONAGE_FROM:-MY-IA}
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}
AWS_REGION=${AWS_REGION:-eu-west-1}
MESSAGEBIRD_API_KEY=${MESSAGEBIRD_API_KEY}
MESSAGEBIRD_ORIGINATOR=${MESSAGEBIRD_ORIGINATOR:-MY-IA}

# =============================================================================
# OAUTH2
# =============================================================================
API_BASE_URL=${PUBLIC_PROTOCOL:-http}://${PUBLIC_HOST:-localhost}:${APP_PORT:-8080}
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET}
GITHUB_CLIENT_ID=${GITHUB_CLIENT_ID}
GITHUB_CLIENT_SECRET=${GITHUB_CLIENT_SECRET}

# =============================================================================
# PGADMIN
# =============================================================================
PGADMIN_PORT=${PGADMIN_PORT:-5050}
PGADMIN_EMAIL=${PGADMIN_EMAIL:-admin@local.dev}
PGADMIN_PASSWORD=${PGADMIN_PASSWORD:-admin123}

# =============================================================================
# N8N WORKFLOW AUTOMATION
# =============================================================================
N8N_PORT=${N8N_PORT:-5678}
N8N_HOST=${N8N_HOST:-localhost}
N8N_PROTOCOL=${N8N_PROTOCOL:-http}
N8N_WEBHOOK_URL=${N8N_PROTOCOL:-http}://${N8N_HOST:-localhost}:${N8N_PORT:-5678}/
N8N_DB_USER=${N8N_DB_USER:-n8n_user}
N8N_DB_PASSWORD=${N8N_DB_PASSWORD}
N8N_DB_NAME=${N8N_DB_NAME:-n8n_db}
N8N_ADMIN_USER=${N8N_ADMIN_USER:-admin}
N8N_ADMIN_PASSWORD=${N8N_ADMIN_PASSWORD}
N8N_ENCRYPTION_KEY=${N8N_ENCRYPTION_KEY}
N8N_MCP_DOCS_PORT=${N8N_MCP_DOCS_PORT:-3100}

# =============================================================================
# VALIDATION INSCRIPTIONS
# =============================================================================
REGISTRATION_VALIDATION_MODE=${REGISTRATION_VALIDATION_MODE:-email+admin}
OAUTH_AUTO_APPROVE=${OAUTH_AUTO_APPROVE:-false}
VALIDATION_ALLOWED_ROLES=${VALIDATION_ALLOWED_ROLES:-admin,validator}
NOTIFY_ADMIN_ON_REGISTRATION=${NOTIFY_ADMIN_ON_REGISTRATION:-true}
ADMIN_DASHBOARD_URL=${PUBLIC_PROTOCOL:-http}://${PUBLIC_HOST:-localhost}:${ADMIN_PORT:-8081}

# =============================================================================
# UTILISATEURS DE TEST (DEBUG=true uniquement)
# =============================================================================
TEST_ADMIN_EMAIL=${TEST_ADMIN_EMAIL:-admin@test.example}
TEST_ADMIN_PASSWORD="${TEST_ADMIN_PASSWORD:-0vpFCb^8BYbM@%w^Q#75p6.1}"
TEST_ADMIN_FIRST_NAME=${TEST_ADMIN_FIRST_NAME:-Admin}
TEST_ADMIN_LAST_NAME=${TEST_ADMIN_LAST_NAME:-Testeur}
TEST_ADMIN_PHONE=${TEST_ADMIN_PHONE:-+33612345001}
TEST_ADMIN_ADDRESS="${TEST_ADMIN_ADDRESS:-1 Place de l Hotel de Ville}"

TEST_USER_EMAIL=${TEST_USER_EMAIL:-user@test.example}
TEST_USER_PASSWORD="${TEST_USER_PASSWORD:-5#d%o3x3^7%uOwrZw_UIRS60}"
TEST_USER_FIRST_NAME=${TEST_USER_FIRST_NAME:-Pierre}
TEST_USER_LAST_NAME=${TEST_USER_LAST_NAME:-Dupont}
TEST_USER_PHONE=${TEST_USER_PHONE:-+33612345002}
TEST_USER_ADDRESS="${TEST_USER_ADDRESS:-25 Rue de la Paix}"

TEST_CONTRIBUTOR_EMAIL=${TEST_CONTRIBUTOR_EMAIL:-contributor@test.example}
TEST_CONTRIBUTOR_PASSWORD=${TEST_CONTRIBUTOR_PASSWORD:-Contrib123!}
TEST_CONTRIBUTOR_FIRST_NAME=${TEST_CONTRIBUTOR_FIRST_NAME:-Marie}
TEST_CONTRIBUTOR_LAST_NAME=${TEST_CONTRIBUTOR_LAST_NAME:-Martin}
TEST_CONTRIBUTOR_PHONE=${TEST_CONTRIBUTOR_PHONE:-+33612345003}
TEST_CONTRIBUTOR_ADDRESS="${TEST_CONTRIBUTOR_ADDRESS:-8 Avenue des Champs-Elysees}"

TEST_VALIDATOR_EMAIL=${TEST_VALIDATOR_EMAIL:-validator@test.example}
TEST_VALIDATOR_PASSWORD=${TEST_VALIDATOR_PASSWORD:-Valid123!}
TEST_VALIDATOR_FIRST_NAME=${TEST_VALIDATOR_FIRST_NAME:-Jean}
TEST_VALIDATOR_LAST_NAME=${TEST_VALIDATOR_LAST_NAME:-Valideur}
TEST_VALIDATOR_PHONE=${TEST_VALIDATOR_PHONE:-+33612345004}
TEST_VALIDATOR_ADDRESS="${TEST_VALIDATOR_ADDRESS:-15 Boulevard Haussmann}"

TEST_USERS_CITY_ID=${TEST_USERS_CITY_ID:-29583}
ENVEOF
    } > "$output_file"
    exec 3>&-

    log_debug "[write_env_file] Descripteur de fichier 3 ferme"
    log_debug "[write_env_file] Fichier ecrit avec succes: $output_file"

    # Verification du fichier ecrit
    if [[ -f "$output_file" ]]; then
        local file_size=$(wc -c < "$output_file")
        local line_count=$(wc -l < "$output_file")
        log_debug "[write_env_file] Verification: $file_size bytes, $line_count lignes"
    else
        log_debug "[write_env_file] ERREUR: Le fichier n'a pas ete cree!"
    fi
}

# =============================================================================
# LECTURE DES VARIABLES DEPUIS UN TEMPLATE
# =============================================================================
# Lit toutes les variables depuis un fichier template et les definit.
#
# Usage:
#   read_template_vars "/path/to/.env.example"
#
# Prerequis:
#   - read_env_var() de common.sh doit etre disponible
# =============================================================================

read_template_vars() {
    local template_file="$1"

    log_debug "[read_template_vars] Lecture du fichier: $template_file"
    log_debug "[read_template_vars] === Variables d'identite ==="

    # Variables d'identite
    APP_ID=$(read_env_var "APP_ID" "$template_file")
    APP_ID="${APP_ID:-my-ia}"
    log_debug "[read_template_vars] APP_ID=$APP_ID"

    APP_NAME_PREFIX=$(read_env_var "APP_NAME_PREFIX" "$template_file")
    APP_NAME_PREFIX="${APP_NAME_PREFIX:-MY-IA}"
    log_debug "[read_template_vars] APP_NAME_PREFIX=$APP_NAME_PREFIX"

    APP_TITLE=$(read_env_var "APP_TITLE" "$template_file")
    APP_TITLE="${APP_TITLE:-MY-IA Assistant}"
    log_debug "[read_template_vars] APP_TITLE=$APP_TITLE"

    APP_DESCRIPTION=$(read_env_var "APP_DESCRIPTION" "$template_file")
    APP_DESCRIPTION="${APP_DESCRIPTION:-Chatbot RAG avec gestion documentaire}"
    log_debug "[read_template_vars] APP_DESCRIPTION=$APP_DESCRIPTION"

    APP_ICON=$(read_env_var "APP_ICON" "$template_file")
    APP_ICON="${APP_ICON:-🤖}"
    log_debug "[read_template_vars] APP_ICON=$APP_ICON"

    APP_VERSION=$(read_env_var "APP_VERSION" "$template_file")
    APP_VERSION="${APP_VERSION:-1.0.0}"
    log_debug "[read_template_vars] APP_VERSION=$APP_VERSION"

    APP_INSTANCE_ID=$(read_env_var "APP_INSTANCE_ID" "$template_file")
    log_debug "[read_template_vars] APP_INSTANCE_ID=$APP_INSTANCE_ID"
    # APP_INSTANCE_ID sera genere si vide par generate_security_keys ou load_instance_id

    log_debug "[read_template_vars] === Mots de passe PostgreSQL ==="
    # Mots de passe PostgreSQL (avec valeurs par defaut si vides)
    POSTGRES_PASSWORD=$(read_env_var "POSTGRES_PASSWORD" "$template_file")
    POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-change-me-postgres-password}"
    log_debug "[read_template_vars] POSTGRES_PASSWORD=[MASQUE] (${#POSTGRES_PASSWORD} chars)"

    APP_DB_PASSWORD=$(read_env_var "APP_DB_PASSWORD" "$template_file")
    APP_DB_PASSWORD="${APP_DB_PASSWORD:-change-me-app-password}"
    log_debug "[read_template_vars] APP_DB_PASSWORD=[MASQUE] (${#APP_DB_PASSWORD} chars)"

    log_debug "[read_template_vars] === Ports reseau ==="
    # Ports (avec valeurs par defaut)
    FRONTEND_PORT=$(read_env_var "FRONTEND_PORT" "$template_file")
    FRONTEND_PORT="${FRONTEND_PORT:-3000}"
    log_debug "[read_template_vars] FRONTEND_PORT=$FRONTEND_PORT"

    ADMIN_PORT=$(read_env_var "ADMIN_PORT" "$template_file")
    ADMIN_PORT="${ADMIN_PORT:-8081}"
    log_debug "[read_template_vars] ADMIN_PORT=$ADMIN_PORT"

    APP_PORT=$(read_env_var "APP_PORT" "$template_file")
    APP_PORT="${APP_PORT:-8080}"
    log_debug "[read_template_vars] APP_PORT=$APP_PORT"

    POSTGRES_PORT=$(read_env_var "POSTGRES_PORT" "$template_file")
    POSTGRES_PORT="${POSTGRES_PORT:-5432}"
    log_debug "[read_template_vars] POSTGRES_PORT=$POSTGRES_PORT"

    CHROMA_PORT=$(read_env_var "CHROMA_PORT" "$template_file")
    CHROMA_PORT="${CHROMA_PORT:-8000}"
    log_debug "[read_template_vars] CHROMA_PORT=$CHROMA_PORT"

    OLLAMA_PORT=$(read_env_var "OLLAMA_PORT" "$template_file")
    OLLAMA_PORT="${OLLAMA_PORT:-11434}"
    log_debug "[read_template_vars] OLLAMA_PORT=$OLLAMA_PORT"

    log_debug "[read_template_vars] === Modeles Ollama ==="
    # Modeles Ollama (avec valeurs par defaut)
    LLM_MODEL=$(read_env_var "LLM_MODEL" "$template_file")
    LLM_MODEL="${LLM_MODEL:-gemma2:2b}"
    log_debug "[read_template_vars] LLM_MODEL=$LLM_MODEL"

    EMBED_MODEL=$(read_env_var "EMBED_MODEL" "$template_file")
    EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"
    log_debug "[read_template_vars] EMBED_MODEL=$EMBED_MODEL"

    log_debug "[read_template_vars] === Environnement de deploiement ==="
    # Environnement de deploiement
    DEPLOY_ENV=$(read_env_var "DEPLOY_ENV" "$template_file")
    DEPLOY_ENV="${DEPLOY_ENV:-dev}"
    log_debug "[read_template_vars] DEPLOY_ENV=$DEPLOY_ENV"

    UVICORN_WORKERS=$(read_env_var "UVICORN_WORKERS" "$template_file")
    UVICORN_WORKERS="${UVICORN_WORKERS:-2}"
    log_debug "[read_template_vars] UVICORN_WORKERS=$UVICORN_WORKERS"

    # Ollama host (depuis .env.example, pas hardcode)
    OLLAMA_HOST=$(read_env_var "OLLAMA_HOST" "$template_file")
    OLLAMA_HOST="${OLLAMA_HOST:-ollama}"
    log_debug "[read_template_vars] OLLAMA_HOST=$OLLAMA_HOST"

    log_debug "[read_template_vars] === Debug ==="
    # Debug
    DEBUG=$(read_env_var "DEBUG" "$template_file")
    log_debug "[read_template_vars] DEBUG=$DEBUG"

    log_debug "[read_template_vars] === Utilisateurs de test ==="
    # Utilisateurs de test
    TEST_ADMIN_EMAIL=$(read_env_var "TEST_ADMIN_EMAIL" "$template_file")
    TEST_ADMIN_PASSWORD=$(read_env_var "TEST_ADMIN_PASSWORD" "$template_file")
    TEST_ADMIN_FIRST_NAME=$(read_env_var "TEST_ADMIN_FIRST_NAME" "$template_file")
    TEST_ADMIN_LAST_NAME=$(read_env_var "TEST_ADMIN_LAST_NAME" "$template_file")
    TEST_ADMIN_PHONE=$(read_env_var "TEST_ADMIN_PHONE" "$template_file")
    TEST_ADMIN_ADDRESS=$(read_env_var "TEST_ADMIN_ADDRESS" "$template_file")
    log_debug "[read_template_vars] TEST_ADMIN_EMAIL=$TEST_ADMIN_EMAIL"

    TEST_USER_EMAIL=$(read_env_var "TEST_USER_EMAIL" "$template_file")
    TEST_USER_PASSWORD=$(read_env_var "TEST_USER_PASSWORD" "$template_file")
    TEST_USER_FIRST_NAME=$(read_env_var "TEST_USER_FIRST_NAME" "$template_file")
    TEST_USER_LAST_NAME=$(read_env_var "TEST_USER_LAST_NAME" "$template_file")
    TEST_USER_PHONE=$(read_env_var "TEST_USER_PHONE" "$template_file")
    TEST_USER_ADDRESS=$(read_env_var "TEST_USER_ADDRESS" "$template_file")
    log_debug "[read_template_vars] TEST_USER_EMAIL=$TEST_USER_EMAIL"

    TEST_CONTRIBUTOR_EMAIL=$(read_env_var "TEST_CONTRIBUTOR_EMAIL" "$template_file")
    TEST_CONTRIBUTOR_PASSWORD=$(read_env_var "TEST_CONTRIBUTOR_PASSWORD" "$template_file")
    TEST_CONTRIBUTOR_FIRST_NAME=$(read_env_var "TEST_CONTRIBUTOR_FIRST_NAME" "$template_file")
    TEST_CONTRIBUTOR_LAST_NAME=$(read_env_var "TEST_CONTRIBUTOR_LAST_NAME" "$template_file")
    TEST_CONTRIBUTOR_PHONE=$(read_env_var "TEST_CONTRIBUTOR_PHONE" "$template_file")
    TEST_CONTRIBUTOR_ADDRESS=$(read_env_var "TEST_CONTRIBUTOR_ADDRESS" "$template_file")
    log_debug "[read_template_vars] TEST_CONTRIBUTOR_EMAIL=$TEST_CONTRIBUTOR_EMAIL"

    TEST_VALIDATOR_EMAIL=$(read_env_var "TEST_VALIDATOR_EMAIL" "$template_file")
    TEST_VALIDATOR_PASSWORD=$(read_env_var "TEST_VALIDATOR_PASSWORD" "$template_file")
    TEST_VALIDATOR_FIRST_NAME=$(read_env_var "TEST_VALIDATOR_FIRST_NAME" "$template_file")
    TEST_VALIDATOR_LAST_NAME=$(read_env_var "TEST_VALIDATOR_LAST_NAME" "$template_file")
    TEST_VALIDATOR_PHONE=$(read_env_var "TEST_VALIDATOR_PHONE" "$template_file")
    TEST_VALIDATOR_ADDRESS=$(read_env_var "TEST_VALIDATOR_ADDRESS" "$template_file")
    log_debug "[read_template_vars] TEST_VALIDATOR_EMAIL=$TEST_VALIDATOR_EMAIL"

    TEST_USERS_CITY_ID=$(read_env_var "TEST_USERS_CITY_ID" "$template_file")
    log_debug "[read_template_vars] TEST_USERS_CITY_ID=$TEST_USERS_CITY_ID"

    log_debug "[read_template_vars] === CORS ==="
    # CORS (correction format JSON array)
    CORS_ORIGINS=$(read_env_var "CORS_ORIGINS" "$template_file")
    log_debug "[read_template_vars] CORS_ORIGINS (brut)=$CORS_ORIGINS"
    CORS_ORIGINS=$(fix_json_array "$CORS_ORIGINS")
    log_debug "[read_template_vars] CORS_ORIGINS (corrige)=$CORS_ORIGINS"

    log_debug "[read_template_vars] === Validation inscriptions ==="
    # Validation inscriptions
    REGISTRATION_VALIDATION_MODE=$(read_env_var "REGISTRATION_VALIDATION_MODE" "$template_file")
    log_debug "[read_template_vars] REGISTRATION_VALIDATION_MODE=$REGISTRATION_VALIDATION_MODE"
    OAUTH_AUTO_APPROVE=$(read_env_var "OAUTH_AUTO_APPROVE" "$template_file")
    log_debug "[read_template_vars] OAUTH_AUTO_APPROVE=$OAUTH_AUTO_APPROVE"
    VALIDATION_ALLOWED_ROLES=$(read_env_var "VALIDATION_ALLOWED_ROLES" "$template_file")
    NOTIFY_ADMIN_ON_REGISTRATION=$(read_env_var "NOTIFY_ADMIN_ON_REGISTRATION" "$template_file")

    log_debug "[read_template_vars] === Email ==="
    # Email (credentials dans .external_secrets)
    EMAIL_BACKEND=$(read_env_var "EMAIL_BACKEND" "$template_file")
    log_debug "[read_template_vars] EMAIL_BACKEND=$EMAIL_BACKEND"
    EMAIL_FROM=$(read_env_var "EMAIL_FROM" "$template_file")
    log_debug "[read_template_vars] EMAIL_FROM=$EMAIL_FROM"
    EMAIL_FROM_NAME=$(read_env_var "EMAIL_FROM_NAME" "$template_file")

    log_debug "[read_template_vars] === SMS ==="
    # SMS (credentials dans .external_secrets)
    SMS_BACKEND=$(read_env_var "SMS_BACKEND" "$template_file")
    log_debug "[read_template_vars] SMS_BACKEND=$SMS_BACKEND"
    SMS_VERIFICATION_ENABLED=$(read_env_var "SMS_VERIFICATION_ENABLED" "$template_file")
    SMS_OTP_EXPIRY_SECONDS=$(read_env_var "SMS_OTP_EXPIRY_SECONDS" "$template_file")
    SMS_OTP_MAX_ATTEMPTS=$(read_env_var "SMS_OTP_MAX_ATTEMPTS" "$template_file")

    log_debug "[read_template_vars] === Adresse publique ==="
    # Adresse publique du serveur
    PUBLIC_HOST=$(read_env_var "PUBLIC_HOST" "$template_file")
    PUBLIC_HOST="${PUBLIC_HOST:-localhost}"
    log_debug "[read_template_vars] PUBLIC_HOST=$PUBLIC_HOST"

    PUBLIC_PROTOCOL=$(read_env_var "PUBLIC_PROTOCOL" "$template_file")
    PUBLIC_PROTOCOL="${PUBLIC_PROTOCOL:-http}"
    log_debug "[read_template_vars] PUBLIC_PROTOCOL=$PUBLIC_PROTOCOL"

    log_debug "[read_template_vars] === OAuth ==="
    # OAuth (credentials dans .external_secrets)
    # Note: API_BASE_URL est maintenant généré depuis PUBLIC_HOST

    log_debug "[read_template_vars] === pgAdmin ==="
    # pgAdmin
    PGADMIN_PORT=$(read_env_var "PGADMIN_PORT" "$template_file")
    PGADMIN_PORT="${PGADMIN_PORT:-5050}"
    log_debug "[read_template_vars] PGADMIN_PORT=$PGADMIN_PORT"
    PGADMIN_EMAIL=$(read_env_var "PGADMIN_EMAIL" "$template_file")
    PGADMIN_EMAIL="${PGADMIN_EMAIL:-admin@local.dev}"
    log_debug "[read_template_vars] PGADMIN_EMAIL=$PGADMIN_EMAIL"
    PGADMIN_PASSWORD=$(read_env_var "PGADMIN_PASSWORD" "$template_file")
    PGADMIN_PASSWORD="${PGADMIN_PASSWORD:-admin123}"

    log_debug "[read_template_vars] === RAG ==="
    # RAG
    TOP_K=$(read_env_var "TOP_K" "$template_file")
    log_debug "[read_template_vars] TOP_K=$TOP_K"
    CHUNK_SIZE=$(read_env_var "CHUNK_SIZE" "$template_file")
    log_debug "[read_template_vars] CHUNK_SIZE=$CHUNK_SIZE"
    CHUNK_OVERLAP=$(read_env_var "CHUNK_OVERLAP" "$template_file")
    log_debug "[read_template_vars] CHUNK_OVERLAP=$CHUNK_OVERLAP"
    CHUNKING_STRATEGY=$(read_env_var "CHUNKING_STRATEGY" "$template_file")
    log_debug "[read_template_vars] CHUNKING_STRATEGY=$CHUNKING_STRATEGY"

    log_debug "[read_template_vars] === Static data ==="
    # Static data (Geo)
    STATIC_DATA_DIR=$(read_env_var "STATIC_DATA_DIR" "$template_file")
    STATIC_DATA_DIR="${STATIC_DATA_DIR:-/code/static-datas}"
    log_debug "[read_template_vars] STATIC_DATA_DIR=$STATIC_DATA_DIR"

    log_debug "[read_template_vars] === Rate limiting ==="
    # Rate limiting
    RATE_LIMIT_CHAT=$(read_env_var "RATE_LIMIT_CHAT" "$template_file")
    log_debug "[read_template_vars] RATE_LIMIT_CHAT=$RATE_LIMIT_CHAT"
    RATE_LIMIT_UPLOAD=$(read_env_var "RATE_LIMIT_UPLOAD" "$template_file")
    log_debug "[read_template_vars] RATE_LIMIT_UPLOAD=$RATE_LIMIT_UPLOAD"
    RATE_LIMIT_STREAM=$(read_env_var "RATE_LIMIT_STREAM" "$template_file")
    log_debug "[read_template_vars] RATE_LIMIT_STREAM=$RATE_LIMIT_STREAM"

    log_debug "[read_template_vars] === Timeouts ==="
    # Timeouts
    OLLAMA_TIMEOUT=$(read_env_var "OLLAMA_TIMEOUT" "$template_file")
    log_debug "[read_template_vars] OLLAMA_TIMEOUT=$OLLAMA_TIMEOUT"
    HTTP_TIMEOUT=$(read_env_var "HTTP_TIMEOUT" "$template_file")
    log_debug "[read_template_vars] HTTP_TIMEOUT=$HTTP_TIMEOUT"
    HEALTH_CHECK_TIMEOUT=$(read_env_var "HEALTH_CHECK_TIMEOUT" "$template_file")
    log_debug "[read_template_vars] HEALTH_CHECK_TIMEOUT=$HEALTH_CHECK_TIMEOUT"

    log_debug "[read_template_vars] === Donnees geographiques ==="
    # Donnees geographiques
    GEO_DEFAULT_COUNTRY=$(read_env_var "GEO_DEFAULT_COUNTRY" "$template_file")
    log_debug "[read_template_vars] GEO_DEFAULT_COUNTRY=$GEO_DEFAULT_COUNTRY"
    GEO_AUTO_IMPORT=$(read_env_var "GEO_AUTO_IMPORT" "$template_file")
    log_debug "[read_template_vars] GEO_AUTO_IMPORT=$GEO_AUTO_IMPORT"
    GEO_CITIES_SOURCE=$(read_env_var "GEO_CITIES_SOURCE" "$template_file")
    log_debug "[read_template_vars] GEO_CITIES_SOURCE=$GEO_CITIES_SOURCE"

    log_debug "[read_template_vars] === N8N Workflow Automation ==="
    # N8N
    N8N_PORT=$(read_env_var "N8N_PORT" "$template_file")
    N8N_PORT="${N8N_PORT:-5678}"
    log_debug "[read_template_vars] N8N_PORT=$N8N_PORT"
    N8N_HOST=$(read_env_var "N8N_HOST" "$template_file")
    N8N_HOST="${N8N_HOST:-localhost}"
    log_debug "[read_template_vars] N8N_HOST=$N8N_HOST"
    N8N_PROTOCOL=$(read_env_var "N8N_PROTOCOL" "$template_file")
    N8N_PROTOCOL="${N8N_PROTOCOL:-http}"
    log_debug "[read_template_vars] N8N_PROTOCOL=$N8N_PROTOCOL"
    N8N_DB_USER=$(read_env_var "N8N_DB_USER" "$template_file")
    N8N_DB_USER="${N8N_DB_USER:-n8n_user}"
    log_debug "[read_template_vars] N8N_DB_USER=$N8N_DB_USER"
    N8N_DB_PASSWORD=$(read_env_var "N8N_DB_PASSWORD" "$template_file")
    N8N_DB_PASSWORD="${N8N_DB_PASSWORD:-change-me-n8n-password}"
    log_debug "[read_template_vars] N8N_DB_PASSWORD=[MASQUE]"
    N8N_DB_NAME=$(read_env_var "N8N_DB_NAME" "$template_file")
    N8N_DB_NAME="${N8N_DB_NAME:-n8n_db}"
    log_debug "[read_template_vars] N8N_DB_NAME=$N8N_DB_NAME"
    N8N_ADMIN_USER=$(read_env_var "N8N_ADMIN_USER" "$template_file")
    N8N_ADMIN_USER="${N8N_ADMIN_USER:-admin}"
    log_debug "[read_template_vars] N8N_ADMIN_USER=$N8N_ADMIN_USER"
    N8N_ADMIN_PASSWORD=$(read_env_var "N8N_ADMIN_PASSWORD" "$template_file")
    N8N_ADMIN_PASSWORD="${N8N_ADMIN_PASSWORD:-change-me-n8n-admin}"
    log_debug "[read_template_vars] N8N_ADMIN_PASSWORD=[MASQUE]"
    N8N_MCP_DOCS_PORT=$(read_env_var "N8N_MCP_DOCS_PORT" "$template_file")
    N8N_MCP_DOCS_PORT="${N8N_MCP_DOCS_PORT:-3100}"
    log_debug "[read_template_vars] N8N_MCP_DOCS_PORT=$N8N_MCP_DOCS_PORT"

    log_debug "[read_template_vars] Lecture du template terminee"
}

# =============================================================================
# CHARGEMENT DES SECRETS EXTERNES
# =============================================================================
# Charge les secrets depuis le fichier .external_secrets s'il existe.
# Les valeurs non vides ecrasent les valeurs actuelles des variables.
#
# Usage:
#   load_external_secrets "/path/to/project"
#
# Parametres:
#   $1 : Chemin du repertoire projet (contenant .external_secrets)
#
# Retour:
#   0 si fichier charge ou absent, 1 si erreur de lecture
# =============================================================================

load_external_secrets() {
    local project_dir="$1"
    local secrets_file="${project_dir}/.external_secrets"

    log_debug "[load_external_secrets] Recherche du fichier: $secrets_file"

    if [[ ! -f "$secrets_file" ]]; then
        log_debug "[load_external_secrets] Fichier non trouve (optionnel)"
        log_info "Fichier .external_secrets non trouve (optionnel)"
        echo "       Creez-le depuis external_secrets.template pour vos credentials SMTP/OAuth"
        return 0
    fi

    log_debug "[load_external_secrets] Fichier trouve, chargement..."

    # Liste des variables de secrets supportees
    local secret_vars=(
        # SMTP
        "SMTP_HOST"
        "SMTP_PORT"
        "SMTP_USERNAME"
        "SMTP_PASSWORD"
        "SMTP_USE_TLS"
        "EMAIL_FROM"
        "EMAIL_FROM_NAME"
        # SendGrid
        "SENDGRID_API_KEY"
        # OAuth Google
        "GOOGLE_CLIENT_ID"
        "GOOGLE_CLIENT_SECRET"
        # OAuth GitHub
        "GITHUB_CLIENT_ID"
        "GITHUB_CLIENT_SECRET"
        # SMS Twilio
        "TWILIO_ACCOUNT_SID"
        "TWILIO_AUTH_TOKEN"
        "TWILIO_PHONE_NUMBER"
        # SMS OVH
        "OVH_SMS_ACCOUNT"
        "OVH_SMS_LOGIN"
        "OVH_SMS_PASSWORD"
        "OVH_SMS_SENDER"
        # SMS Vonage
        "VONAGE_API_KEY"
        "VONAGE_API_SECRET"
        "VONAGE_FROM"
        # SMS AWS SNS
        "AWS_ACCESS_KEY_ID"
        "AWS_SECRET_ACCESS_KEY"
        "AWS_REGION"
        # SMS MessageBird
        "MESSAGEBIRD_API_KEY"
        "MESSAGEBIRD_ORIGINATOR"
    )

    local loaded_count=0
    local loaded_vars=""

    # Lire chaque variable du fichier secrets
    for var_name in "${secret_vars[@]}"; do
        local value
        value=$(read_env_var "$var_name" "$secrets_file")

        # Si la valeur existe et n'est pas vide, l'utiliser
        if [[ -n "$value" ]]; then
            eval "$var_name=\"\$value\""
            log_debug "[load_external_secrets] $var_name charge"
            loaded_vars="${loaded_vars}${var_name}, "
            ((loaded_count++))
        fi
    done

    if [[ $loaded_count -gt 0 ]]; then
        # Retirer la virgule finale
        loaded_vars="${loaded_vars%, }"
        log_success "Secrets charges depuis .external_secrets ($loaded_count variables)"
        log_debug "[load_external_secrets] Variables chargees: $loaded_vars"
    else
        log_info "Fichier .external_secrets present mais vide"
    fi

    return 0
}

# =============================================================================
# AFFICHAGE DU RESUME
# =============================================================================
# Affiche un resume des variables generees.
#
# Usage:
#   show_env_summary
# =============================================================================

show_env_summary() {
    log_debug "[show_env_summary] Affichage du resume"

    local prefix_sanitized
    prefix_sanitized=$(sanitize "$APP_NAME_PREFIX" false)
    local base_url="${PUBLIC_PROTOCOL:-http}://${PUBLIC_HOST:-localhost}"

    echo ""
    echo "============================================================================="
    log_success "Fichier .env genere avec succes"
    echo "============================================================================="
    echo ""
    echo "  APP_NAME_PREFIX:    ${APP_NAME_PREFIX}"
    echo "  Prefixe sanitize:   ${prefix_sanitized}"
    echo ""
    echo "  PUBLIC_HOST:        ${PUBLIC_HOST:-localhost}"
    echo "  PUBLIC_PROTOCOL:    ${PUBLIC_PROTOCOL:-http}"
    echo ""
    echo "  URLs generees:"
    echo "    - API:            ${base_url}:${APP_PORT:-8080}"
    echo "    - Frontend:       ${base_url}:${FRONTEND_PORT:-3000}"
    echo "    - Admin:          ${base_url}:${ADMIN_PORT:-8081}"
    echo "    - pgAdmin:        ${base_url}:${PGADMIN_PORT:-5050}"
    echo ""
    echo "  Services internes:"
    echo "    - PostgreSQL:     localhost:${POSTGRES_PORT:-5432}"
    echo "    - ChromaDB:       localhost:${CHROMA_PORT:-8000}"
    echo "    - Ollama:         localhost:${OLLAMA_PORT:-11434}"
    echo "    - N8N:            localhost:${N8N_PORT:-5678}"
    echo "    - N8N MCP Docs:   localhost:${N8N_MCP_DOCS_PORT:-3100}"
    echo ""
    echo "  POSTGRES_USER:      ${POSTGRES_USER}"
    echo "  APP_DB_USER:        ${APP_DB_USER}"
    echo "  APP_DB_NAME:        ${APP_DB_NAME}"
    echo ""
    echo "  Cles generees:      JWT_SECRET_KEY"
    echo "                      ENCRYPTION_KEY"
    echo "                      SECRET_KEY"
    echo "                      API_KEY"
    echo "                      N8N_ENCRYPTION_KEY"
    echo ""
    echo "============================================================================="
    echo ""

    log_debug "[show_env_summary] Resume affiche"
}

# =============================================================================
# VALIDATION DU FICHIER .ENV
# =============================================================================
# Verifie que toutes les variables requises sont presentes et non vides.
#
# Usage:
#   validate_env_file "/path/to/.env"
#
# Retour:
#   0 si valide, 1 si invalide
#   Affiche les variables manquantes sur stderr
# =============================================================================

validate_env_file() {
    local env_file="$1"
    local missing=()
    local empty=()

    log_debug "[validate_env_file] Validation du fichier: $env_file"

    # Variables obligatoires (doivent etre presentes et non vides)
    local required_vars=(
        "APP_NAME_PREFIX"
        "POSTGRES_USER"
        "POSTGRES_PASSWORD"
        "APP_DB_USER"
        "APP_DB_PASSWORD"
        "APP_DB_NAME"
        "DATABASE_URL"
        "JWT_SECRET_KEY"
        "SECRET_KEY"
        "ENCRYPTION_KEY"
        "API_KEY"
        "FRONTEND_PORT"
        "ADMIN_PORT"
        "APP_PORT"
        "POSTGRES_PORT"
        "CHROMA_PORT"
        "OLLAMA_PORT"
        "LLM_MODEL"
        "EMBED_MODEL"
    )

    log_debug "[validate_env_file] ${#required_vars[@]} variables obligatoires a verifier"

    if [[ ! -f "$env_file" ]]; then
        log_debug "[validate_env_file] Fichier introuvable!"
        echo "Fichier $env_file introuvable" >&2
        return 1
    fi

    # Charger le fichier .env
    # Desactiver temporairement set -e car source peut echouer sur certaines lignes
    log_debug "[validate_env_file] Chargement du fichier..."
    set +e
    set -a
    source "$env_file" 2>/dev/null
    set +a
    set -e

    # Verifier chaque variable requise
    for var in "${required_vars[@]}"; do
        local value="${!var}"
        if [[ -z "$value" ]]; then
            empty+=("$var")
            log_debug "[validate_env_file] Variable vide: $var"
        else
            log_debug "[validate_env_file] Variable OK: $var"
        fi
    done

    if [[ ${#empty[@]} -gt 0 ]]; then
        log_debug "[validate_env_file] ECHEC: ${#empty[@]} variables vides"
        echo "" >&2
        log_warn "Variables manquantes ou vides dans $env_file:" >&2
        for var in "${empty[@]}"; do
            echo "  - $var" >&2
        done
        echo "" >&2
        return 1
    fi

    log_debug "[validate_env_file] Validation reussie"
    return 0
}

# =============================================================================
# EDITION INTERACTIVE DES VARIABLES
# =============================================================================
# Permet a l'utilisateur de modifier les variables de configuration
# de maniere interactive, organisees par categorie.
#
# Usage:
#   edit_config_interactive
#
# Retour:
#   Les variables globales sont mises a jour avec les nouvelles valeurs
# =============================================================================

# Fonction utilitaire pour editer une variable
# Usage: prompt_var "NOM_VARIABLE" "Description" ["secret"]
prompt_var() {
    local var_name="$1"
    local description="$2"
    local is_secret="${3:-false}"
    local current_value="${!var_name}"
    local display_value

    if [[ "$is_secret" == "true" && -n "$current_value" ]]; then
        display_value="********"
    else
        display_value="$current_value"
    fi

    echo -n "  $description [$display_value]: "
    read -r new_value < /dev/tty

    if [[ -n "$new_value" ]]; then
        eval "$var_name=\"\$new_value\""
    fi
}

# Categorie: Configuration obligatoire
edit_category_required() {
    echo ""
    echo "=== CONFIGURATION OBLIGATOIRE ==="
    echo ""
    prompt_var "APP_NAME_PREFIX" "Prefixe application"
    prompt_var "POSTGRES_PASSWORD" "Mot de passe PostgreSQL admin" "true"
    prompt_var "APP_DB_PASSWORD" "Mot de passe PostgreSQL app" "true"
}

# Categorie: Adresse publique
edit_category_public_host() {
    echo ""
    echo "=== ADRESSE PUBLIQUE DU SERVEUR ==="
    echo "(IP ou nom de domaine accessible depuis l'exterieur)"
    echo ""
    echo "Exemples:"
    echo "  - localhost           (dev local)"
    echo "  - 51.210.245.202      (IP serveur)"
    echo "  - myia.mondomaine.com (domaine)"
    echo ""
    prompt_var "PUBLIC_HOST" "Adresse publique"
    prompt_var "PUBLIC_PROTOCOL" "Protocole (http/https)"
}

# Categorie: Ports reseau
edit_category_ports() {
    echo ""
    echo "=== PORTS RESEAU ==="
    echo ""
    prompt_var "FRONTEND_PORT" "Port Frontend"
    prompt_var "ADMIN_PORT" "Port Admin"
    prompt_var "APP_PORT" "Port API"
    prompt_var "POSTGRES_PORT" "Port PostgreSQL"
    prompt_var "CHROMA_PORT" "Port ChromaDB"
    prompt_var "OLLAMA_PORT" "Port Ollama"
}

# Categorie: Modeles Ollama
edit_category_ollama() {
    echo ""
    echo "=== MODELES OLLAMA ==="
    echo "(gemma2:2b, mistral, llama3.2, llama3.2:1b)"
    echo ""
    prompt_var "LLM_MODEL" "Modele LLM"
    prompt_var "EMBED_MODEL" "Modele Embeddings"
}

# Categorie: Mode Debug
edit_category_debug() {
    echo ""
    echo "=== MODE DEBUG ==="
    echo ""
    prompt_var "DEBUG" "Mode debug (true/false)"
}

# Categorie: Utilisateurs de test
edit_category_test_users() {
    echo ""
    echo "=== UTILISATEURS DE TEST ==="
    echo "(utilises uniquement si DEBUG=true)"
    echo ""
    prompt_var "TEST_ADMIN_EMAIL" "Email admin test"
    prompt_var "TEST_ADMIN_PASSWORD" "Password admin test" "true"
    prompt_var "TEST_USER_EMAIL" "Email user test"
    prompt_var "TEST_USER_PASSWORD" "Password user test" "true"
    prompt_var "TEST_CONTRIBUTOR_EMAIL" "Email contributor test"
    prompt_var "TEST_CONTRIBUTOR_PASSWORD" "Password contributor test" "true"
    prompt_var "TEST_VALIDATOR_EMAIL" "Email validator test"
    prompt_var "TEST_VALIDATOR_PASSWORD" "Password validator test" "true"
}

# Categorie: CORS
edit_category_cors() {
    echo ""
    echo "=== CORS (Cross-Origin Resource Sharing) ==="
    echo "Format JSON: [\"*\"] ou [\"http://localhost:3000\",\"http://localhost:8081\"]"
    echo ""
    prompt_var "CORS_ORIGINS" "Origines autorisees (JSON)"
    # Corriger automatiquement le format JSON
    CORS_ORIGINS=$(fix_json_array "$CORS_ORIGINS")
}

# Categorie: Validation inscriptions
edit_category_registration() {
    echo ""
    echo "=== VALIDATION DES INSCRIPTIONS ==="
    echo "(none, email, admin, email+admin)"
    echo ""
    prompt_var "REGISTRATION_VALIDATION_MODE" "Mode de validation"
    prompt_var "OAUTH_AUTO_APPROVE" "Auto-approuver OAuth (true/false)"
    prompt_var "VALIDATION_ALLOWED_ROLES" "Roles autorises a valider"
    prompt_var "NOTIFY_ADMIN_ON_REGISTRATION" "Notifier admin (true/false)"
}

# Categorie: Email
edit_category_email() {
    echo ""
    echo "=== SERVICE EMAIL ==="
    echo "(console, sendgrid, smtp)"
    echo "Note: Les credentials SMTP/SendGrid sont dans la categorie 16 (Secrets externes)"
    echo ""
    prompt_var "EMAIL_BACKEND" "Backend email"
    prompt_var "EMAIL_FROM" "Adresse expediteur"
    prompt_var "EMAIL_FROM_NAME" "Nom expediteur"
}

# Categorie: SMS
edit_category_sms() {
    echo ""
    echo "=== SERVICE SMS ==="
    echo "(console, twilio, ovh, vonage, aws_sns, messagebird)"
    echo "Note: Les credentials SMS sont dans la categorie 16 (Secrets externes)"
    echo ""
    prompt_var "SMS_BACKEND" "Backend SMS"
    prompt_var "SMS_VERIFICATION_ENABLED" "Verification SMS activee (true/false)"
    prompt_var "SMS_OTP_EXPIRY_SECONDS" "Duree OTP en secondes"
    prompt_var "SMS_OTP_MAX_ATTEMPTS" "Nombre max de tentatives OTP"
}

# Categorie: OAuth2
edit_category_oauth() {
    echo ""
    echo "=== OAUTH2 ==="
    echo "Note: Les credentials OAuth sont dans la categorie 16 (Secrets externes)"
    echo ""
    prompt_var "API_BASE_URL" "URL de base API (pour callbacks OAuth)"
}

# Categorie: pgAdmin
edit_category_pgadmin() {
    echo ""
    echo "=== PGADMIN (Interface PostgreSQL) ==="
    echo ""
    prompt_var "PGADMIN_PORT" "Port pgAdmin"
    prompt_var "PGADMIN_EMAIL" "Email connexion pgAdmin"
    prompt_var "PGADMIN_PASSWORD" "Mot de passe pgAdmin" "true"
}

# Categorie: RAG
edit_category_rag() {
    echo ""
    echo "=== CONFIGURATION RAG ==="
    echo ""
    prompt_var "TOP_K" "Nombre de chunks (TOP_K)"
    prompt_var "CHUNK_SIZE" "Taille chunk (caracteres)"
    prompt_var "CHUNK_OVERLAP" "Chevauchement chunks"
    prompt_var "CHUNKING_STRATEGY" "Strategie (semantic/fixed)"
}

# Categorie: Rate Limiting
edit_category_rate_limit() {
    echo ""
    echo "=== RATE LIMITING ==="
    echo "(format: nombre/periode - ex: 30/minute)"
    echo ""
    prompt_var "RATE_LIMIT_CHAT" "Limite chat"
    prompt_var "RATE_LIMIT_UPLOAD" "Limite upload"
    prompt_var "RATE_LIMIT_STREAM" "Limite stream"
}

# Categorie: Timeouts
edit_category_timeouts() {
    echo ""
    echo "=== TIMEOUTS ==="
    echo "(en secondes)"
    echo ""
    prompt_var "OLLAMA_TIMEOUT" "Timeout Ollama"
    prompt_var "HTTP_TIMEOUT" "Timeout HTTP"
    prompt_var "HEALTH_CHECK_TIMEOUT" "Timeout Health Check"
}

# Categorie: Donnees geographiques
edit_category_geo() {
    echo ""
    echo "=== DONNEES GEOGRAPHIQUES ==="
    echo "Configuration pour l'import des pays et villes"
    echo ""
    prompt_var "GEO_DEFAULT_COUNTRY" "Code pays par defaut (FR, BE, CH...)"
    prompt_var "GEO_AUTO_IMPORT" "Import auto au demarrage (true/false)"
    prompt_var "GEO_CITIES_SOURCE" "Source villes (file/api)"
}

# Categorie: Secrets externes
edit_category_external_secrets() {
    echo ""
    echo "=== SECRETS EXTERNES ==="
    echo "Credentials sensibles (SMTP, OAuth, SMS)"
    echo "Ces valeurs peuvent etre sauvegardees dans .external_secrets"
    echo ""

    echo "--- SMTP ---"
    prompt_var "SMTP_HOST" "Serveur SMTP"
    prompt_var "SMTP_PORT" "Port SMTP"
    prompt_var "SMTP_USERNAME" "Username SMTP"
    prompt_var "SMTP_PASSWORD" "Password SMTP" "true"
    prompt_var "SMTP_USE_TLS" "Utiliser TLS (true/false)"
    prompt_var "EMAIL_FROM" "Adresse expediteur"
    prompt_var "EMAIL_FROM_NAME" "Nom expediteur"

    echo ""
    echo "--- SendGrid ---"
    prompt_var "SENDGRID_API_KEY" "SendGrid API Key" "true"

    echo ""
    echo "--- OAuth Google ---"
    prompt_var "GOOGLE_CLIENT_ID" "Google Client ID"
    prompt_var "GOOGLE_CLIENT_SECRET" "Google Client Secret" "true"

    echo ""
    echo "--- OAuth GitHub ---"
    prompt_var "GITHUB_CLIENT_ID" "GitHub Client ID"
    prompt_var "GITHUB_CLIENT_SECRET" "GitHub Client Secret" "true"

    echo ""
    echo "--- SMS Twilio ---"
    prompt_var "TWILIO_ACCOUNT_SID" "Twilio Account SID"
    prompt_var "TWILIO_AUTH_TOKEN" "Twilio Auth Token" "true"
    prompt_var "TWILIO_PHONE_NUMBER" "Twilio Phone Number"

    echo ""
    echo "--- SMS OVH ---"
    prompt_var "OVH_SMS_ACCOUNT" "OVH Account"
    prompt_var "OVH_SMS_LOGIN" "OVH Login"
    prompt_var "OVH_SMS_PASSWORD" "OVH Password" "true"
    prompt_var "OVH_SMS_SENDER" "OVH Sender"

    echo ""
    echo "--- SMS Vonage ---"
    prompt_var "VONAGE_API_KEY" "Vonage API Key"
    prompt_var "VONAGE_API_SECRET" "Vonage API Secret" "true"
    prompt_var "VONAGE_FROM" "Vonage From"

    echo ""
    echo "--- SMS AWS SNS ---"
    prompt_var "AWS_ACCESS_KEY_ID" "AWS Access Key ID"
    prompt_var "AWS_SECRET_ACCESS_KEY" "AWS Secret Access Key" "true"
    prompt_var "AWS_REGION" "AWS Region"

    echo ""
    echo "--- SMS MessageBird ---"
    prompt_var "MESSAGEBIRD_API_KEY" "MessageBird API Key" "true"
    prompt_var "MESSAGEBIRD_ORIGINATOR" "MessageBird Originator"

    echo ""
    # Proposer de sauvegarder dans .external_secrets
    if confirm "Sauvegarder ces secrets dans .external_secrets ?"; then
        save_external_secrets
    fi
}

# =============================================================================
# SAUVEGARDE DES SECRETS EXTERNES
# =============================================================================
# Sauvegarde les credentials dans le fichier .external_secrets
# =============================================================================

save_external_secrets() {
    local secrets_file="${PROJECT_ROOT:-.}/.external_secrets"
    log_debug "[save_external_secrets] Sauvegarde dans: $secrets_file"

    cat > "$secrets_file" << EOF
# =============================================================================
# MY-IA - Secrets Externes
# =============================================================================
# Genere le $(date '+%Y-%m-%d %H:%M:%S')
# Ce fichier est ignore par git (.gitignore)
#
# Apres modification manuelle, regenerez le .env:
#   ./scripts/generate-env.sh --force
# =============================================================================

# =============================================================================
# EMAIL - SMTP
# =============================================================================
SMTP_HOST=${SMTP_HOST:-}
SMTP_PORT=${SMTP_PORT:-587}
SMTP_USERNAME=${SMTP_USERNAME:-}
SMTP_PASSWORD=${SMTP_PASSWORD:-}
SMTP_USE_TLS=${SMTP_USE_TLS:-true}
EMAIL_FROM=${EMAIL_FROM:-}
EMAIL_FROM_NAME=${EMAIL_FROM_NAME:-}

# =============================================================================
# EMAIL - SendGrid
# =============================================================================
SENDGRID_API_KEY=${SENDGRID_API_KEY:-}

# =============================================================================
# OAUTH - Google
# =============================================================================
GOOGLE_CLIENT_ID=${GOOGLE_CLIENT_ID:-}
GOOGLE_CLIENT_SECRET=${GOOGLE_CLIENT_SECRET:-}

# =============================================================================
# OAUTH - GitHub
# =============================================================================
GITHUB_CLIENT_ID=${GITHUB_CLIENT_ID:-}
GITHUB_CLIENT_SECRET=${GITHUB_CLIENT_SECRET:-}

# =============================================================================
# SMS - Twilio
# =============================================================================
TWILIO_ACCOUNT_SID=${TWILIO_ACCOUNT_SID:-}
TWILIO_AUTH_TOKEN=${TWILIO_AUTH_TOKEN:-}
TWILIO_PHONE_NUMBER=${TWILIO_PHONE_NUMBER:-}

# =============================================================================
# SMS - OVH
# =============================================================================
OVH_SMS_ACCOUNT=${OVH_SMS_ACCOUNT:-}
OVH_SMS_LOGIN=${OVH_SMS_LOGIN:-}
OVH_SMS_PASSWORD=${OVH_SMS_PASSWORD:-}
OVH_SMS_SENDER=${OVH_SMS_SENDER:-}

# =============================================================================
# SMS - Vonage
# =============================================================================
VONAGE_API_KEY=${VONAGE_API_KEY:-}
VONAGE_API_SECRET=${VONAGE_API_SECRET:-}
VONAGE_FROM=${VONAGE_FROM:-}

# =============================================================================
# SMS - AWS SNS
# =============================================================================
AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-}
AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY:-}
AWS_REGION=${AWS_REGION:-}

# =============================================================================
# SMS - MessageBird
# =============================================================================
MESSAGEBIRD_API_KEY=${MESSAGEBIRD_API_KEY:-}
MESSAGEBIRD_ORIGINATOR=${MESSAGEBIRD_ORIGINATOR:-}
EOF

    log_success "Secrets sauvegardes dans .external_secrets"
}

# =============================================================================
# SELECTION DE L'ENVIRONNEMENT DE DEPLOIEMENT
# =============================================================================
# Demande a l'utilisateur s'il deploie en local ou sur un serveur.
# Configure PUBLIC_HOST en consequence.
#
# Usage:
#   select_deployment_environment
# =============================================================================

select_deployment_environment() {
    echo ""
    echo "============================================================================="
    echo "                    ENVIRONNEMENT DE DEPLOIEMENT"
    echo "============================================================================="
    echo ""
    echo "  1. Local (developpement sur votre machine)"
    echo "  2. Serveur distant (production)"
    echo ""
    echo -n "Choix [1]: "
    read -r env_choice < /dev/tty

    case "$env_choice" in
        2)
            echo ""
            echo "Entrez l'adresse du serveur (IP ou nom de domaine):"
            echo "  Exemples: 51.210.245.202, myia.mondomaine.com"
            echo ""
            echo -n "Adresse: "
            read -r server_address < /dev/tty

            if [[ -n "$server_address" ]]; then
                PUBLIC_HOST="$server_address"
                log_success "Mode SERVEUR: PUBLIC_HOST=$PUBLIC_HOST"
            else
                log_warn "Adresse vide, utilisation de localhost"
                PUBLIC_HOST="localhost"
            fi

            echo ""
            echo "Protocole (http pour test, https si SSL configure):"
            echo -n "Protocole [http]: "
            read -r protocol_choice < /dev/tty
            PUBLIC_PROTOCOL="${protocol_choice:-http}"
            ;;
        *)
            PUBLIC_HOST="localhost"
            PUBLIC_PROTOCOL="http"
            log_success "Mode LOCAL: PUBLIC_HOST=localhost"
            ;;
    esac

    echo ""
}

# Fonction principale d'edition interactive
edit_config_interactive() {
    log_debug "[edit_config_interactive] Debut de l'edition interactive"

    # Demander l'environnement de deploiement en premier
    select_deployment_environment

    echo ""
    echo "============================================================================="
    echo "                    EDITION DE LA CONFIGURATION"
    echo "============================================================================="
    echo ""
    echo "Pour chaque variable, appuyez sur Entree pour garder la valeur par defaut."
    echo "Les mots de passe sont masques mais seront conserves si vous appuyez Entree."
    echo ""

    # Liste des categories avec leur fonction
    local categories=(
        "1:Configuration obligatoire:edit_category_required"
        "2:Adresse publique (serveur):edit_category_public_host"
        "3:Ports reseau:edit_category_ports"
        "4:Modeles Ollama:edit_category_ollama"
        "5:Mode Debug:edit_category_debug"
        "6:CORS (Cross-Origin Resource Sharing):edit_category_cors"
        "7:Validation inscriptions:edit_category_registration"
        "8:Service Email:edit_category_email"
        "9:Service SMS:edit_category_sms"
        "10:OAuth2:edit_category_oauth"
        "11:pgAdmin:edit_category_pgadmin"
        "12:Configuration RAG:edit_category_rag"
        "13:Rate Limiting:edit_category_rate_limit"
        "14:Timeouts:edit_category_timeouts"
        "15:Donnees geographiques:edit_category_geo"
        "16:Utilisateurs de test:edit_category_test_users"
        "17:Secrets externes (SMTP/OAuth/SMS):edit_category_external_secrets"
    )

    log_debug "[edit_config_interactive] ${#categories[@]} categories disponibles"

    echo "Categories disponibles:"
    for cat in "${categories[@]}"; do
        local num="${cat%%:*}"
        local rest="${cat#*:}"
        local name="${rest%%:*}"
        echo "  $num. $name"
    done
    echo "  0. Toutes les categories"
    echo "  q. Quitter sans editer"
    echo ""

    read -p "Quelles categories editer ? (ex: 1,2,3 ou 0 pour toutes): " choice

    log_debug "[edit_config_interactive] Choix utilisateur: '$choice'"

    if [[ "$choice" == "q" || "$choice" == "Q" ]]; then
        log_debug "[edit_config_interactive] Edition annulee par l'utilisateur"
        echo ""
        log_info "Edition annulee"
        return 0
    fi

    if [[ "$choice" == "0" ]]; then
        log_debug "[edit_config_interactive] Edition de TOUTES les categories"
        # Editer toutes les categories
        for cat in "${categories[@]}"; do
            local func="${cat##*:}"
            log_debug "[edit_config_interactive] Execution de $func"
            $func
        done
    else
        # Editer les categories selectionnees
        log_debug "[edit_config_interactive] Edition des categories selectionnees: $choice"
        IFS=',' read -ra selected <<< "$choice"
        for num in "${selected[@]}"; do
            num=$(echo "$num" | tr -d ' ')
            for cat in "${categories[@]}"; do
                local cat_num="${cat%%:*}"
                if [[ "$cat_num" == "$num" ]]; then
                    local func="${cat##*:}"
                    log_debug "[edit_config_interactive] Execution de $func (categorie $num)"
                    $func
                    break
                fi
            done
        done
    fi

    echo ""
    log_success "Configuration mise a jour"
    log_debug "[edit_config_interactive] Edition terminee"
    echo ""
}

# =============================================================================
# SAUVEGARDE DES CREDENTIALS
# =============================================================================
# Sauvegarde les credentials dans un fichier horodate non versionne.
#
# Usage:
#   save_credentials_file "/path/to/project"
#
# Retourne:
#   Le chemin du fichier cree
# =============================================================================

save_credentials_file() {
    local output_dir="$1"
    local timestamp=$(date '+%Y-%m-%d_%H-%M-%S')
    local filename=".credentials.${timestamp}"
    local filepath="${output_dir}/${filename}"

    log_debug "[save_credentials_file] Sauvegarde vers: $filepath"
    log_debug "[save_credentials_file] Timestamp: $timestamp"

    local base_url="${PUBLIC_PROTOCOL:-http}://${PUBLIC_HOST:-localhost}"

    cat > "$filepath" << EOF
# ============================================
# MY-IA - Credentials
# ============================================
# Genere le: $(date '+%Y-%m-%d %H:%M:%S')
# Prefixe: ${APP_NAME_PREFIX}
# Adresse: ${PUBLIC_HOST:-localhost}
# ============================================

## INTERFACES WEB
- Frontend:     ${base_url}:${FRONTEND_PORT:-3000}
- Admin:        ${base_url}:${ADMIN_PORT:-8081}
- API:          ${base_url}:${APP_PORT:-8080}
- API Docs:     ${base_url}:${APP_PORT:-8080}/docs
- pgAdmin:      ${base_url}:${PGADMIN_PORT:-5050}

## SERVICES
- PostgreSQL:   localhost:${POSTGRES_PORT:-5432}
- ChromaDB:     localhost:${CHROMA_PORT:-8000}
- Ollama:       localhost:${OLLAMA_PORT:-11434}
- N8N:          localhost:${N8N_PORT:-5678}
- N8N MCP Docs: localhost:${N8N_MCP_DOCS_PORT:-3100}

## POSTGRESQL Superuser
- Host:         localhost:${POSTGRES_PORT:-5432}
- User:         ${POSTGRES_USER}
- Password:     ${POSTGRES_PASSWORD}

## POSTGRESQL Application
- Database:     ${APP_DB_NAME}
- User:         ${APP_DB_USER}
- Password:     ${APP_DB_PASSWORD}

## PGADMIN
- URL:          http://localhost:${PGADMIN_PORT:-5050}
- Email:        ${PGADMIN_EMAIL:-admin@local.dev}
- Password:     ${PGADMIN_PASSWORD:-admin123}

## PGADMIN - Configuration serveur PostgreSQL
- Name:         ${APP_NAME_PREFIX} PostgreSQL
- Host:         postgres (ou host.docker.internal si natif)
- Port:         5432
- Database:     postgres
- Username:     ${POSTGRES_USER}
- Password:     ${POSTGRES_PASSWORD}

## API
- URL:          ${base_url}:${APP_PORT:-8080}
- API Key:      ${API_KEY}

## N8N (Workflow Automation)
- URL:          http://localhost:${N8N_PORT:-5678}
- User:         ${N8N_ADMIN_USER:-admin}
- Password:     ${N8N_ADMIN_PASSWORD}
- Database:     ${N8N_DB_NAME:-n8n_db}
- DB User:      ${N8N_DB_USER:-n8n_user}
- DB Password:  ${N8N_DB_PASSWORD}
EOF

    # Ajouter les utilisateurs de test si DEBUG=true
    if [[ "${DEBUG:-false}" == "true" ]]; then
        cat >> "$filepath" << EOF

## UTILISATEURS DE TEST (DEBUG=true)
- Admin:        ${TEST_ADMIN_EMAIL:-admin@test.example} / ${TEST_ADMIN_PASSWORD:-0vpFCb^8BYbM@%w^Q#75p6.1}
- User:         ${TEST_USER_EMAIL:-user@test.example} / ${TEST_USER_PASSWORD:-5#d%o3x3^7%uOwrZw_UIRS60}
- Contributor:  ${TEST_CONTRIBUTOR_EMAIL:-contributor@test.local} / ${TEST_CONTRIBUTOR_PASSWORD:-Contrib123!}
- Validator:    ${TEST_VALIDATOR_EMAIL:-validator@test.local} / ${TEST_VALIDATOR_PASSWORD:-Valid123!}
EOF
    fi

    # Permissions restrictives (lecture/ecriture proprietaire uniquement)
    chmod 600 "$filepath"
    log_debug "[save_credentials_file] Permissions 600 appliquees"

    log_debug "[save_credentials_file] Fichier cree avec succes"
    echo "$filepath"
}
