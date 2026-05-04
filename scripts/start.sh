#!/bin/bash
# =============================================================================
# MY-IA - Demarrage de l'application
# =============================================================================
# Script orchestrateur pour le demarrage de l'application MY-IA.
#
# Ce script coordonne les differentes phases:
#   1. PREREQUIS    - Docker, fichiers de configuration
#   2. IDENTITE     - Banniere, detection instances multiples
#   3. CONFIGURATION - Mode install/update, .env, comparaison
#   4. CONTAINERS   - Ports, rebuild si necessaire, docker compose up
#   5. SERVICES     - Healthcheck, modeles Ollama
#   6. DONNEES      - Import pays/villes, users test
#   7. FINALISATION - Credentials, recapitulatif
#
# Usage:
#   ./scripts/start.sh [OPTIONS]
#
# Options ligne de commande:
#   -h, --help      Affiche l'aide
#   -f, --force     Force la regeneration du fichier .env
#   -b, --build     Reconstruit les images Docker
#   --no-cache      Reconstruit sans cache Docker
#   --auto          Mode non-interactif (pour CI/CD)
#
# Touches speciales:
#   Escape          Quitte le script proprement
#   Ctrl+C          Quitte le script proprement
#
# =============================================================================

# =============================================================================
# OPTIONS PAR DEFAUT
# =============================================================================
# Ces valeurs peuvent etre modifiees dans .env.example avant le premier
# demarrage, ou dans .env apres la generation.
#
# DEBUG (defaut: true)
# --------------------
# Active le mode developpement avec:
#   - Hot-reload du code Python (uvicorn --reload)
#   - Logs verbeux (niveau DEBUG au lieu de INFO)
#   - Creation des 4 utilisateurs de test (admin, user, contributor, validator)
#   - Endpoints de debug accessibles (/auth/register/debug)
#   - Options de debug visibles dans l'interface
#   - Section utilisateurs de test dans le fichier credentials
#
# En production, mettre DEBUG=false dans .env.example AVANT le premier
# demarrage, ou regenerer .env avec: ./scripts/generate-env.sh --force
#
# GEO_AUTO_IMPORT (defaut: false)
# -------------------------------
# Si true, importe automatiquement les donnees geographiques (pays, villes)
# au demarrage sans demander confirmation. Utile pour CI/CD.
# Si false, un menu interactif propose les options d'import.
#
# LLM_MODEL (defaut: gemma2:2b)
# -----------------------------
# Modele Ollama pour la generation de reponses.
# Options legeres: gemma2:2b, llama3.2:1b
# Options standard: mistral, llama3.2, gemma2
#
# EMBED_MODEL (defaut: nomic-embed-text)
# --------------------------------------
# Modele Ollama pour les embeddings (recherche semantique RAG).
# Recommande: nomic-embed-text (performant et leger)
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# =============================================================================
# CHARGEMENT DES MODULES
# =============================================================================

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/compare.sh"
source "$SCRIPT_DIR/lib/env.sh"
source "$SCRIPT_DIR/lib/instance.sh"
source "$SCRIPT_DIR/lib/config.sh"
source "$SCRIPT_DIR/lib/ollama.sh"
source "$SCRIPT_DIR/lib/db.sh"
source "$SCRIPT_DIR/lib/db-config.sh"
source "$SCRIPT_DIR/lib/auth.sh"
source "$SCRIPT_DIR/lib/data.sh"

# Configuration du gestionnaire de sortie (Escape, Ctrl+C)
setup_exit_handler

# =============================================================================
# AIDE
# =============================================================================

show_help() {
    cat << 'EOF'
MY-IA - Demarrage de l'application
==================================

DESCRIPTION:
    Ce script demarre l'application MY-IA avec Docker Compose.

    Phases d'execution:
      1. Verification des prerequis (Docker, docker-compose)
      2. Chargement de l'identite et detection d'instances
      3. Generation/validation du fichier .env
      4. Verification des ports
      5. Demarrage des containers Docker
      6. Telechargement des modeles Ollama
      7. Import des donnees geographiques
      8. Recapitulatif final

USAGE:
    ./scripts/start.sh [OPTIONS]

OPTIONS:
    -h, --help      Affiche cette aide
    -f, --force     Force la regeneration du fichier .env
    -b, --build     Reconstruit les images Docker avant le demarrage
    --no-cache      Reconstruit les images sans utiliser le cache
    --auto          Mode non-interactif (pour CI/CD)

TOUCHES SPECIALES:
    Escape          Quitte le script proprement a tout moment
    Ctrl+C          Quitte le script proprement

EXEMPLES:
    # Demarrage standard
    ./scripts/start.sh

    # Forcer la regeneration de .env
    ./scripts/start.sh --force

    # Reconstruire les images
    ./scripts/start.sh --build

    # Mode CI/CD (non-interactif)
    ./scripts/start.sh --auto

FICHIERS:
    .env.example    Configuration source (a editer)
    .env            Configuration generee (utilise par Docker)
    .instance       Identifiant d'instance (genere automatiquement)

VOIR AUSSI:
    ./scripts/generate-env.sh    Genere le fichier .env
    ./scripts/stop.sh            Arrete l'application

EOF
    exit 0
}

# =============================================================================
# PARSING DES ARGUMENTS
# =============================================================================

# --help prioritaire
for arg in "$@"; do
    case $arg in
        -h|--help)
            show_help
            ;;
    esac
done

# Autres arguments
FORCE=false
BUILD=false
NO_CACHE=false
AUTO_MODE=false

for arg in "$@"; do
    case $arg in
        -f|--force)
            FORCE=true
            ;;
        -b|--build)
            BUILD=true
            ;;
        --no-cache)
            NO_CACHE=true
            BUILD=true  # --no-cache implique --build
            ;;
        --auto)
            AUTO_MODE=true
            ;;
        -*)
            log_error "Option inconnue: $arg"
            echo "Utilisez --help pour voir les options disponibles"
            exit 1
            ;;
    esac
done

# =============================================================================
# PHASE 1: PREREQUIS
# =============================================================================

if ! check_system_prerequisites; then
    exit 1
fi

# Verifier que .env.example existe
if [[ ! -f "$PROJECT_ROOT/.env.example" ]]; then
    log_error "Fichier .env.example non trouve"
    log_error "Ce fichier est necessaire pour configurer l'application"
    exit 1
fi

# =============================================================================
# PHASE 2: IDENTITE
# =============================================================================

# Charger les variables d'identite depuis .env ou .env.example
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    load_identity_vars "$PROJECT_ROOT/.env"
else
    load_identity_vars "$PROJECT_ROOT/.env.example"
fi

# Charger ou generer l'instance ID
load_instance_id "$PROJECT_ROOT"

# Afficher la banniere
show_app_banner

# Detecter les autres instances
check_other_instances "${APP_NAME_PREFIX:-MY-IA}"

# Verifier l'instance courante (containers existants)
SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)
if ! check_current_instance "$APP_NAME_PREFIX" "$APP_INSTANCE_ID"; then
    exit 1
fi

# =============================================================================
# PHASE 3: CONFIGURATION
# =============================================================================

log_step "Verification du fichier .env..."

# Variable pour savoir si on doit comparer les configs
ENV_EXISTED_BEFORE=false

if [[ "$FORCE" == "true" ]]; then
    log_info "Mode force: regeneration de .env"
    "$SCRIPT_DIR/generate-env.sh" --force
elif ! handle_config "$PROJECT_ROOT" "$SCRIPT_DIR"; then
    log_error "Echec de la configuration"
    exit 1
fi

# Charger les variables d'environnement
# Desactiver temporairement set -e car source peut echouer sur certaines lignes
set +e
source "$PROJECT_ROOT/.env"
set -e

# S'assurer que SANITIZED_PREFIX est defini (fallback pour anciens .env)
if [[ -z "$SANITIZED_PREFIX" ]]; then
    SANITIZED_PREFIX=$(sanitize "$APP_NAME_PREFIX" false)
    export SANITIZED_PREFIX
fi

# S'assurer que DEPLOY_ENV est defini (fallback pour anciens .env sans DEPLOY_ENV)
# Deduire depuis DEBUG si absent : DEBUG=true → dev, sinon → prod
if [[ -z "${DEPLOY_ENV:-}" ]]; then
    if [[ "${DEBUG:-false}" == "true" ]]; then
        DEPLOY_ENV="dev"
    elif [[ "${PUBLIC_HOST:-localhost}" == "localhost" ]]; then
        DEPLOY_ENV="dev"
    else
        DEPLOY_ENV="prod"
    fi
    export DEPLOY_ENV
    log_info "DEPLOY_ENV deduit automatiquement: $DEPLOY_ENV"
fi

# Sauvegarder le fichier .instance si nouveau
if [[ ! -f "$PROJECT_ROOT/.instance" ]]; then
    save_instance_file "$PROJECT_ROOT"
fi

# Comparaison des configurations si necessaire
if [[ -f "$PROJECT_ROOT/.env.backup" ]]; then
    log_step "Comparaison des configurations..."
    load_env_vars_prefixed "$PROJECT_ROOT/.env.backup" "OLD"
    load_env_vars_prefixed "$PROJECT_ROOT/.env" "NEW"
    run_config_comparison "$SANITIZED_PREFIX"
fi

# =============================================================================
# PHASE 4: CONTAINERS
# =============================================================================

# Verification des ports
if ! check_all_ports; then
    exit 1
fi

# Demarrage des containers
log_step "Demarrage des containers Docker..."

cd "$PROJECT_ROOT"

# Construire les options docker compose
COMPOSE_OPTS=""
if [[ "$BUILD" == "true" ]]; then
    if [[ "$NO_CACHE" == "true" ]]; then
        log_info "Reconstruction des images (sans cache)..."
        COMPOSE_OPTS="--build --no-cache"
    else
        log_info "Reconstruction des images..."
        COMPOSE_OPTS="--build"
    fi
fi

# Construire la liste des fichiers compose selon DEPLOY_ENV
COMPOSE_FILES=$(get_compose_files)
log_info "Environnement: ${DEPLOY_ENV:-dev} ($COMPOSE_FILES)"

# Demarrer les containers
$COMPOSE_CMD $COMPOSE_FILES up -d $COMPOSE_OPTS

# =============================================================================
# PHASE 5: SERVICES
# =============================================================================

log_step "Verification des services..."

# Attendre que les services soient prets
sleep 5

# Afficher les containers demarres
CONTAINERS=$($COMPOSE_CMD $COMPOSE_FILES ps --format "{{.Name}}" 2>/dev/null || $COMPOSE_CMD $COMPOSE_FILES ps | tail -n +2 | awk '{print $1}')

echo ""
log_info "Containers demarres:"
for container in $CONTAINERS; do
    echo "  - $container"
done

# Migrations de base de donnees (alembic upgrade head)
log_step "Application des migrations de base de donnees..."
APP_CONTAINER="${SANITIZED_PREFIX}_app"
if docker ps --format '{{.Names}}' | grep -q "^${APP_CONTAINER}$"; then
    MIGRATION_OUTPUT=$(docker exec "$APP_CONTAINER" python -m alembic upgrade head 2>&1)
    MIGRATION_EXIT=$?

    if [[ $MIGRATION_EXIT -eq 0 ]]; then
        if echo "$MIGRATION_OUTPUT" | grep -q "Running upgrade"; then
            log_success "Migrations appliquees:"
            echo "$MIGRATION_OUTPUT" | grep "Running upgrade" | while read -r line; do
                echo "    $line"
            done
        else
            log_success "Base de donnees a jour (aucune migration en attente)"
        fi
    else
        log_warn "Migrations: echec (non bloquant)"
        echo "$MIGRATION_OUTPUT" | head -5
    fi
else
    log_warn "Container $APP_CONTAINER non trouve, migrations ignorees"
fi

# Synchronisation bidirectionnelle configuration ↔ BDD
if docker ps --format '{{.Names}}' | grep -q "^${APP_CONTAINER}$"; then
    log_step "Synchronisation configuration ↔ base de donnees..."

    # Verifier si la table system_config existe
    if db_config_check 2>/dev/null; then
        # 1. Initialiser la config par defaut si table vide
        db_config_init

        # 2. Charger la config depuis la BDD et exporter vers env
        log_info "Chargement de la configuration depuis la BDD..."
        eval "$(db_config_export 2>/dev/null)" || true

        # 3. Synchroniser les valeurs du .env vers la BDD
        if [[ "${DB_CONFIG_SYNC_FROM_ENV:-false}" == "true" ]]; then
            log_info "Synchronisation .env → BDD..."
            db_config_sync_from_env
        fi

        # 4. Mettre a jour les valeurs runtime dans la BDD
        SYNC_API_URL="http://localhost:${APP_PORT:-8080}"
        SYNC_TOKEN=$(generate_admin_token "$APP_CONTAINER" 2>/dev/null)

        if [[ -n "$SYNC_TOKEN" ]]; then
            SYNC_KEYS=(
                "app.deploy_env|${DEPLOY_ENV:-dev}"
                "app.debug|${DEBUG:-true}"
                "app.api_url|${API_URL:-http://localhost:${APP_PORT:-8080}}"
                "app.public_host|${PUBLIC_HOST:-localhost}"
                "app.version|${APP_VERSION:-1.0.0}"
            )

            SYNC_OK=true
            for entry in "${SYNC_KEYS[@]}"; do
                key="${entry%%|*}"
                value="${entry#*|}"
                if ! curl -sf -X PATCH "$SYNC_API_URL/api/admin/config/dynamic/$key" \
                    -H "Authorization: Bearer $SYNC_TOKEN" \
                    -H "Content-Type: application/json" \
                    -d "{\"value\": \"$value\"}" \
                    > /dev/null 2>&1; then
                    SYNC_OK=false
                fi
            done

            if [[ "$SYNC_OK" == "true" ]]; then
                log_success "Configuration synchronisee (runtime → BDD)"
            else
                log_warn "Synchronisation partielle (non bloquant)"
            fi
        else
            log_debug "Token admin non genere - ecriture API ignoree"
        fi

        log_success "Configuration chargee depuis la BDD"
    else
        log_info "Table system_config non disponible - sera creee au prochain demarrage"
        # Fallback: utiliser la synchronisation via container
        if db_config_available "$APP_CONTAINER" 2>/dev/null; then
            if db_sync_db_to_env "$APP_CONTAINER" 2>/dev/null; then
                log_success "Configuration lue depuis la BDD (via container)"
            fi
        fi
    fi
fi

# Gestion des modeles LLM selon le provider configure
if [[ "$AUTO_MODE" != "true" ]]; then
    if [[ "${LLM_PROVIDER:-ollama}" == "llamacpp" ]]; then
        # llama.cpp : verifier/demarrer llama-server
        log_step "Verification de llama-server..."
        if "$SCRIPT_DIR/llamacpp.sh" status > /dev/null 2>&1; then
            log_success "llama-server deja en cours d'execution"
        else
            log_info "LLM_PROVIDER=llamacpp - demarrage de llama-server..."
            # Utiliser --from-db pour charger la config depuis system_configs
            if "$SCRIPT_DIR/llamacpp.sh" start --from-db 2>/dev/null; then
                log_success "llama-server demarre avec la configuration BDD"
            else
                log_warn "Echec du demarrage avec --from-db"
                log_warn "Demarrez manuellement: ./scripts/llamacpp.sh start --model <chemin.gguf>"
            fi
        fi
    else
        # Ollama : gestion des modeles
        manage_all_models
    fi
fi

# =============================================================================
# PHASE 6: DONNEES
# =============================================================================

if [[ "$AUTO_MODE" != "true" ]]; then
    handle_data_imports "$PROJECT_ROOT"
else
    log_info "Mode auto: import des donnees ignore"
    RECAP_COUNTRIES_STATUS="Mode auto"
    RECAP_CITIES_STATUS="Mode auto"
    RECAP_TEST_USERS_STATUS="Mode auto"
fi

# =============================================================================
# PHASE 7: FINALISATION
# =============================================================================

# Sauvegarde des credentials
CREDENTIALS_FILE=$(save_credentials_file "$PROJECT_ROOT")
log_success "Credentials sauvegardes dans: $CREDENTIALS_FILE"

# Recapitulatif final
echo ""
echo "============================================================================="
log_success "Application MY-IA demarree avec succes"
echo "============================================================================="
echo ""
echo "  INTERFACES:"
echo "    - Frontend:  http://localhost:${FRONTEND_PORT:-3000}"
echo "    - Admin:     http://localhost:${ADMIN_PORT:-8081}"
echo "    - API:       http://localhost:${APP_PORT:-8080}"
echo "    - API Docs:  http://localhost:${APP_PORT:-8080}/docs"
echo "    - pgAdmin:   http://localhost:${PGADMIN_PORT:-5050}"
echo ""

# Recapitulatif des imports
show_data_recap
echo "    Credentials:      Sauvegardes dans ${CREDENTIALS_FILE##*/}"
echo ""
echo "============================================================================="
echo "  COMMANDES UTILES"
echo "============================================================================="
echo ""
echo "    - Voir les logs:     docker compose logs -f app"
echo "    - Arreter:           ./scripts/stop.sh"
echo "    - Regenerer .env:    ./scripts/generate-env.sh --force"
echo ""
echo "============================================================================="
echo ""
