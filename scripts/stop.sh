#!/bin/bash
# =============================================================================
# MY-IA - Arret de l'application
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Charger les fonctions partagees
source "$SCRIPT_DIR/lib/common.sh"

# =============================================================================
# AIDE
# =============================================================================

show_help() {
    cat << 'EOF'
MY-IA - Arret de l'application
==============================

DESCRIPTION:
    Ce script arrete l'application MY-IA et ses containers Docker.

    Il effectue les operations suivantes:
      1. Arrete tous les containers de l'application
      2. Demande si vous voulez supprimer les volumes (defaut: Non)
      3. Optionnellement, supprime les images (--rmi)

USAGE:
    ./scripts/stop.sh [OPTIONS]

OPTIONS:
    -h, --help      Affiche cette aide
    --rmi           Supprime aussi les images Docker
    -y, --yes       Repond oui a toutes les questions (non-interactif)

EXEMPLES:
    # Arret simple (demande pour les volumes)
    ./scripts/stop.sh

    # Arret avec suppression des images
    ./scripts/stop.sh --rmi

    # Arret non-interactif (conserve les volumes)
    ./scripts/stop.sh -y

ATTENTION:
    La suppression des volumes efface definitivement :
      - La base de donnees PostgreSQL
      - Les index ChromaDB
      - Les modeles Ollama telecharges

VOIR AUSSI:
    ./scripts/start.sh           Demarre l'application
    ./scripts/generate-env.sh    Regenere le fichier .env

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
RMI=false
YES=false

for arg in "$@"; do
    case $arg in
        --rmi)
            RMI=true
            ;;
        -y|--yes)
            YES=true
            ;;
        -*)
            log_error "Option inconnue: $arg"
            echo "Utilisez --help pour voir les options disponibles"
            exit 1
            ;;
    esac
done

# =============================================================================
# VERIFICATION DOCKER
# =============================================================================

# Detecter Docker Compose (v2 plugin ou standalone)
detect_compose_cmd || die "Docker Compose n'est pas installe"

# =============================================================================
# ARRET DES CONTAINERS
# =============================================================================

log_step "Arret des containers Docker..."

cd "$PROJECT_ROOT"

# Charger les variables depuis .env si disponible
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    DEPLOY_ENV=$(grep "^DEPLOY_ENV=" "$PROJECT_ROOT/.env" 2>/dev/null | cut -d'=' -f2 || echo "")
    LLM_PROVIDER=$(grep "^LLM_PROVIDER=" "$PROJECT_ROOT/.env" 2>/dev/null | cut -d'=' -f2 || echo "ollama")
    if [[ -z "$DEPLOY_ENV" ]]; then
        # Ancien .env sans DEPLOY_ENV: deduire depuis DEBUG
        DEBUG_VAL=$(grep "^DEBUG=" "$PROJECT_ROOT/.env" 2>/dev/null | cut -d'=' -f2 || echo "true")
        if [[ "$DEBUG_VAL" == "true" ]]; then
            DEPLOY_ENV="dev"
        else
            DEPLOY_ENV="prod"
        fi
    fi
fi
DEPLOY_ENV="${DEPLOY_ENV:-dev}"
LLM_PROVIDER="${LLM_PROVIDER:-ollama}"

# Construire la liste des fichiers compose selon DEPLOY_ENV
COMPOSE_FILES=$(get_compose_files)

# Arreter les containers (sans volumes pour l'instant)
execute $COMPOSE_CMD $COMPOSE_FILES down

log_success "Containers arretes"

# =============================================================================
# QUESTION INTERACTIVE: SUPPRESSION DES VOLUMES
# =============================================================================

VOLUMES=false

if [[ "$YES" != "true" ]]; then
    echo ""
    log_warn "Voulez-vous aussi supprimer les volumes Docker ?"
    echo "  Cela effacera definitivement :"
    echo "    - Base de donnees PostgreSQL"
    echo "    - Index ChromaDB"
    echo "    - Modeles Ollama telecharges"
    echo ""

    if confirm "Supprimer les volumes ?" "n"; then
        VOLUMES=true
    fi
fi

# =============================================================================
# SUPPRESSION DES VOLUMES (si demande)
# =============================================================================

if [[ "$VOLUMES" == "true" ]]; then
    log_step "Suppression des volumes..."
    execute $COMPOSE_CMD $COMPOSE_FILES down --volumes
    log_success "Volumes supprimes"
fi

# =============================================================================
# SUPPRESSION DES IMAGES (si demande)
# =============================================================================

if [[ "$RMI" == "true" ]]; then
    log_step "Suppression des images..."
    execute $COMPOSE_CMD $COMPOSE_FILES down --rmi all
    log_success "Images supprimees"
fi

# =============================================================================
# ARRET DE LLAMA-SERVER (si LLM_PROVIDER=llamacpp)
# =============================================================================

if [[ "${LLM_PROVIDER:-ollama}" == "llamacpp" ]]; then
    if [[ -f "$SCRIPT_DIR/llamacpp.sh" ]]; then
        log_step "Arret de llama-server..."
        "$SCRIPT_DIR/llamacpp.sh" stop 2>/dev/null || true
    fi
fi

# =============================================================================
# RESUME
# =============================================================================

echo ""
echo "============================================================================="
log_success "Application MY-IA arretee"
echo "============================================================================="

if [[ "$VOLUMES" == "true" ]]; then
    echo ""
    log_warn "Les volumes ont ete supprimes."
    log_warn "Au prochain demarrage, la base de donnees sera recreee."
fi

if [[ "$RMI" == "true" ]]; then
    echo ""
    log_info "Les images ont ete supprimees."
    log_info "Au prochain demarrage, elles seront reconstruites."
fi

echo ""
echo "  Pour redemarrer: ./scripts/start.sh"
echo ""
echo "============================================================================="
echo ""
