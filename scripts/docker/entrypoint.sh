#!/bin/bash
# =============================================================================
# Script d'entrypoint Docker - MY-IA API
# =============================================================================
# Ce script s'execute au demarrage du container app et effectue :
# 1. Attente de PostgreSQL
# 2. Execution des migrations Alembic
# 3. Seeding des donnees (tables de reference + utilisateurs de test)
# 4. Lancement de l'application
# =============================================================================

set -e

# Couleurs pour les logs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[ENTRYPOINT]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[ENTRYPOINT]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[ENTRYPOINT]${NC} $1"
}

log_error() {
    echo -e "${RED}[ENTRYPOINT]${NC} $1"
}

# =============================================================================
# 1. ATTENTE DE POSTGRESQL
# =============================================================================
wait_for_postgres() {
    log_info "Attente de PostgreSQL..."

    # Extraire les infos de connexion de DATABASE_URL
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    local db_host=$(echo "$DATABASE_URL" | sed -n 's/.*@\([^:]*\):.*/\1/p')
    local db_port=$(echo "$DATABASE_URL" | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')

    # Valeurs par defaut
    db_host=${db_host:-postgres}
    db_port=${db_port:-5432}

    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if nc -z "$db_host" "$db_port" 2>/dev/null; then
            log_success "PostgreSQL est pret ($db_host:$db_port)"
            return 0
        fi

        log_info "Tentative $attempt/$max_attempts - PostgreSQL pas encore disponible..."
        sleep 2
        ((attempt++))
    done

    log_error "PostgreSQL n'est pas accessible apres $max_attempts tentatives"
    exit 1
}

# =============================================================================
# 2. MIGRATIONS ALEMBIC
# =============================================================================
run_migrations() {
    log_info "Execution des migrations Alembic..."

    cd /code

    # Verifier la version actuelle
    local current_version=$(alembic current 2>/dev/null | grep -oE '[a-f0-9]+' | head -1 || echo "none")
    log_info "Version actuelle: ${current_version:-aucune}"

    # Executer les migrations
    if alembic upgrade head; then
        local new_version=$(alembic current 2>/dev/null | grep -oE '[a-f0-9]+' | head -1 || echo "unknown")
        log_success "Migrations terminees (version: $new_version)"
    else
        log_error "Echec des migrations Alembic"
        exit 1
    fi

    cd /code
}

# =============================================================================
# 3. SEEDING DES DONNEES
# =============================================================================
run_seeding() {
    log_info "Verification et seeding des donnees..."

    # IMPORTANT: Les donnees geographiques doivent etre importees EN PREMIER
    # car les utilisateurs de test ont une contrainte FK sur city_id
    log_info "Seeding des donnees geographiques (pays, villes)..."
    if python /code/scripts/docker/seed_geo.py; then
        log_success "Seeding geographique termine"
    else
        log_warning "Le seeding geo a rencontre des erreurs (non bloquant)"
    fi

    # Executer le script de seeding Python (tables de reference + utilisateurs)
    # Les utilisateurs de test utilisent city_id qui doit exister
    if python /code/scripts/docker/seed.py; then
        log_success "Seeding des donnees de reference termine"
    else
        log_warning "Le seeding a rencontre des erreurs (non bloquant)"
    fi
}

# =============================================================================
# 4. LANCEMENT DE L'APPLICATION
# =============================================================================
start_application() {
    log_info "Demarrage de l'application..."

    local host=${APP_HOST:-0.0.0.0}
    local port=${APP_PORT:-8080}
    local env=${DEPLOY_ENV:-dev}
    local workers=${UVICORN_WORKERS:-1}

    case "$env" in
        dev)
            log_info "Mode DEV : hot-reload actif (--reload)"
            log_success "Lancement uvicorn sur $host:$port"
            exec uvicorn app.main:app --host "$host" --port "$port" --reload \
                --proxy-headers --forwarded-allow-ips='*'
            ;;
        staging)
            log_info "Mode STAGING : $workers worker(s), pas de reload"
            log_success "Lancement uvicorn sur $host:$port"
            exec uvicorn app.main:app --host "$host" --port "$port" --workers "$workers" \
                --proxy-headers --forwarded-allow-ips='*'
            ;;
        prod)
            log_info "Mode PROD : $workers worker(s), log-level warning"
            log_success "Lancement uvicorn sur $host:$port"
            exec uvicorn app.main:app --host "$host" --port "$port" \
                --workers "$workers" --log-level warning \
                --proxy-headers --forwarded-allow-ips='*'
            ;;
        *)
            log_warning "DEPLOY_ENV=$env inconnu, fallback sur mode dev"
            log_success "Lancement uvicorn sur $host:$port"
            exec uvicorn app.main:app --host "$host" --port "$port" --reload \
                --proxy-headers --forwarded-allow-ips='*'
            ;;
    esac
}

# =============================================================================
# MAIN
# =============================================================================
main() {
    echo ""
    echo "============================================================================="
    echo "                    MY-IA API - Demarrage du container"
    echo "============================================================================="
    echo ""

    # Afficher les variables d'environnement importantes
    log_info "Configuration:"
    echo "  - DATABASE_URL: ${DATABASE_URL:0:50}..."
    echo "  - DEPLOY_ENV: ${DEPLOY_ENV:-dev}"
    echo "  - ENVIRONMENT: ${ENVIRONMENT:-development}"
    echo "  - Debug: pilote par la BDD (panneau admin)"
    echo ""

    # Etapes de demarrage
    wait_for_postgres
    run_migrations
    run_seeding

    echo ""
    echo "============================================================================="
    log_success "Initialisation terminee - Demarrage de l'API"
    echo "============================================================================="
    echo ""

    start_application
}

# Executer le main
main "$@"
