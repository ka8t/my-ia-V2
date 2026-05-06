#!/bin/bash
# =============================================================================
# MY-IA - Fonctions de configuration
# =============================================================================
# Ce fichier contient les fonctions pour charger et valider la configuration.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/env.sh"
#   source "$SCRIPT_DIR/lib/config.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier
#   - env.sh doit etre source avant ce fichier
#
# =============================================================================

# =============================================================================
# CHARGEMENT DE LA CONFIGURATION
# =============================================================================
# Charge la configuration depuis .env ou .env.example selon le mode.
#
# Usage:
#   load_config "/path/to/project"
#
# Parametres:
#   $1 - Chemin du projet
#
# Resultat:
#   Definit les variables globales de configuration
#   Retourne 0 si succes, 1 si erreur
# =============================================================================

load_config() {
    local project_root="$1"
    local env_file="${project_root}/.env"
    local template_file="${project_root}/.env.example"

    if [[ -f "$env_file" ]]; then
        log_info "Chargement de la configuration depuis .env"
        source "$env_file"
        return 0
    elif [[ -f "$template_file" ]]; then
        log_info "Chargement de la configuration depuis .env.example"
        read_template_vars "$template_file"
        return 0
    else
        log_error "Aucun fichier de configuration trouve"
        log_error "Fichiers attendus: .env ou .env.example"
        return 1
    fi
}

# =============================================================================
# DETECTION DU MODE DE FONCTIONNEMENT
# =============================================================================
# Detecte si on est en mode INSTALLATION ou MISE A JOUR.
#
# Usage:
#   mode=$(detect_config_mode "/path/to/project")
#
# Parametres:
#   $1 - Chemin du projet
#
# Retour:
#   "install" si .env n'existe pas (nouvelle installation)
#   "update" si .env existe (mise a jour)
# =============================================================================

detect_config_mode() {
    local project_root="$1"
    local env_file="${project_root}/.env"

    if [[ -f "$env_file" ]]; then
        echo "update"
    else
        echo "install"
    fi
}

# =============================================================================
# GESTION DE LA CONFIGURATION
# =============================================================================
# Gere la configuration selon le mode detecte.
#
# Usage:
#   handle_config "/path/to/project" "/path/to/scripts"
#
# Parametres:
#   $1 - Chemin du projet
#   $2 - Chemin du dossier scripts
#
# Retour:
#   0 si succes
#   1 si erreur ou annulation
#
# Actions:
#   - Mode install: lance generate-env.sh
#   - Mode update: propose d'editer ou conserver la config
# =============================================================================

handle_config() {
    local project_root="$1"
    local script_dir="$2"
    local env_file="${project_root}/.env"

    local mode
    mode=$(detect_config_mode "$project_root")

    if [[ "$mode" == "install" ]]; then
        # Mode INSTALLATION
        log_info "Mode: INSTALLATION (nouveau deploiement)"
        log_info "Lancement de la configuration interactive..."
        "$script_dir/generate-env.sh"
        return $?
    else
        # Mode MISE A JOUR
        log_info "Mode: MISE A JOUR (configuration existante)"

        # Backup automatique
        backup_env_file "$env_file"

        # Charger les anciennes valeurs pour comparaison
        load_env_vars_prefixed "$env_file" "OLD"

        # Valider le fichier existant
        if validate_env_file "$env_file"; then
            log_success "Fichier .env valide"

            # Proposer edition ou conservation
            echo ""
            if [[ "${FORCE_EDIT_CONFIG:-false}" == "true" ]] || \
               confirm "Voulez-vous editer la configuration actuelle ?" "n"; then
                "$script_dir/generate-env.sh" --force
                return $?
            else
                log_info "Configuration actuelle conservee"
                return 0
            fi
        else
            # .env invalide
            log_warn "Fichier .env incomplet ou invalide"
            log_info "Lancement de la configuration interactive..."
            "$script_dir/generate-env.sh" --force
            return $?
        fi
    fi
}

# =============================================================================
# AFFICHAGE DU RESUME DE CONFIGURATION
# =============================================================================
# Affiche un resume de la configuration chargee.
#
# Usage:
#   show_config_summary
#
# Prerequis:
#   Les variables de configuration doivent etre definies
# =============================================================================

show_config_summary() {
    local sanitized_prefix
    sanitized_prefix=$(sanitize "${APP_NAME_PREFIX:-my_ia_v2}" false)

    echo ""
    echo "============================================================================="
    echo "  RESUME DE LA CONFIGURATION"
    echo "============================================================================="
    echo ""
    echo "  Identite:"
    echo "    - APP_ID:           ${APP_ID:-my-ia}"
    echo "    - APP_NAME_PREFIX:  ${APP_NAME_PREFIX:-MY-IA}"
    echo "    - APP_TITLE:        ${APP_TITLE:-MY-IA Assistant}"
    echo "    - APP_VERSION:      ${APP_VERSION:-1.0.0}"
    echo "    - Instance ID:      ${APP_INSTANCE_ID:0:8}..."
    echo ""
    echo "  Ports:"
    echo "    - Frontend:   ${FRONTEND_PORT:-3000}"
    echo "    - Admin:      ${ADMIN_PORT:-8081}"
    echo "    - API:        ${APP_PORT:-8080}"
    echo "    - PostgreSQL: ${POSTGRES_PORT:-5432}"
    echo "    - ChromaDB:   ${CHROMA_PORT:-8000}"
    echo "    - Ollama:     ${OLLAMA_PORT:-11434}"
    echo ""
    echo "  Modeles:"
    echo "    - LLM:        ${LLM_MODEL:-gemma2:2b}"
    echo "    - Embeddings: ${EMBED_MODEL:-nomic-embed-text}"
    echo ""
    echo "  Mode:"
    if [[ "${DEBUG:-false}" == "true" ]]; then
        echo -e "    - Debug:      ${YELLOW}ACTIVE${NC} (developpement)"
    else
        echo -e "    - Debug:      ${GREEN}DESACTIVE${NC} (production)"
    fi
    echo ""
    echo "============================================================================="
    echo ""
}

# =============================================================================
# VERIFICATION DES PREREQUIS SYSTEME
# =============================================================================
# Verifie que tous les prerequis systeme sont satisfaits.
#
# Usage:
#   check_system_prerequisites
#
# Retour:
#   0 si tous les prerequis sont satisfaits
#   1 si un prerequis manque
# =============================================================================

check_system_prerequisites() {
    log_step "Verification des prerequis systeme..."

    # Docker
    if ! check_prerequisites docker; then
        log_error "Docker n'est pas installe ou n'est pas dans le PATH"
        return 1
    fi

    # Docker demarre
    if ! docker info &> /dev/null; then
        log_error "Docker n'est pas demarre. Lancez Docker Desktop."
        return 1
    fi
    log_success "Docker OK"

    # Docker Compose (detection centralisee dans common.sh)
    if detect_compose_cmd; then
        log_success "Docker Compose OK ($COMPOSE_CMD)"
    else
        log_error "Docker Compose n'est pas installe"
        return 1
    fi

    return 0
}

# =============================================================================
# VERIFICATION DE TOUS LES PORTS
# =============================================================================
# Verifie que tous les ports requis sont disponibles.
#
# Usage:
#   check_all_ports
#
# Retour:
#   0 si tous les ports sont disponibles
#   1 si au moins un port est occupe
# =============================================================================

check_all_ports() {
    log_step "Verification des ports..."

    local all_ok=true

    # Liste des ports a verifier
    local ports=(
        "$FRONTEND_PORT:Frontend"
        "$ADMIN_PORT:Admin UI"
        "$APP_PORT:API FastAPI"
        "$POSTGRES_PORT:PostgreSQL"
        "$CHROMA_PORT:ChromaDB"
        "$OLLAMA_PORT:Ollama"
    )

    for port_info in "${ports[@]}"; do
        local port="${port_info%%:*}"
        local service="${port_info#*:}"

        if [[ -z "$port" ]]; then
            continue
        fi

        # En mode mixte : un port occupe par un service natif attendu n'est pas un conflit
        if [[ "${DEPLOY_MODE:-}" == "mixed" ]]; then
            case "$service" in
                PostgreSQL) [[ "${POSTGRES_MODE:-docker}" == "native" ]] && { log_success "$service: port $port (service natif attendu)"; continue; } ;;
                ChromaDB)   [[ "${CHROMA_MODE:-docker}" == "native" ]]   && { log_success "$service: port $port (service natif attendu)"; continue; } ;;
                Ollama)     [[ "${OLLAMA_MODE:-docker}" == "native" ]]   && { log_success "$service: port $port (service natif attendu)"; continue; } ;;
            esac
        fi

        if check_port "$port"; then
            log_success "$service: port $port disponible"
        else
            all_ok=false
            local process=$(get_port_process "$port")
            local container=$(get_docker_container_on_port "$port")

            if [[ -n "$container" ]]; then
                log_warn "Port $port ($service) occupe par container: $container"

                if confirm "  Arreter le container '$container' ?" "y"; then
                    docker stop "$container" > /dev/null 2>&1
                    log_success "Container $container arrete"

                    if confirm "  Supprimer le container '$container' ?" "n"; then
                        docker rm "$container" > /dev/null 2>&1
                        log_success "Container $container supprime"
                    fi

                    sleep 1
                    if check_port "$port"; then
                        all_ok=true
                    fi
                fi
            else
                log_error "Port $port ($service) occupe par: $process"
                echo "  Pour utiliser un autre port, executez:"
                echo "    ./scripts/generate-env.sh --force"
            fi
        fi
    done

    if [[ "$all_ok" != "true" ]]; then
        echo ""
        log_error "Certains ports sont occupes. Impossible de demarrer."
        echo ""
        echo "Options:"
        echo "  1. Arreter les processus utilisant ces ports"
        echo "  2. Regenerer .env avec: ./scripts/generate-env.sh --force"
        return 1
    fi

    return 0
}
