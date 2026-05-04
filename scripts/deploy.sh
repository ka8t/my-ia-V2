#!/bin/bash
# =============================================================================
# MY-IA - Script de deploiement universel (Docker + bare-metal + mixte)
# =============================================================================
# Script orchestrateur en 8 phases pour deployer MY-IA.
#
# Phases:
#   1. Detection de l'environnement
#   2. Choix du mode de deploiement (docker/native/mixed)
#   3. Verification des prerequis
#   4. Configuration (.env)
#   5. Installation et demarrage
#   6. Verification de sante
#   7. Post-deploiement (donnees, config BDD)
#   8. Recapitulatif final (securite, URLs)
#
# Usage:
#   ./scripts/deploy.sh                         # Mode interactif
#   ./scripts/deploy.sh docker local             # Docker + dev local
#   ./scripts/deploy.sh docker prod <IP>         # Docker + production
#   ./scripts/deploy.sh native local             # Bare-metal + dev local
#   ./scripts/deploy.sh native prod <IP>         # Bare-metal + production
#   ./scripts/deploy.sh --auto docker local      # Non-interactif
#
# Touches speciales:
#   Escape/q    Quitte proprement
#   Ctrl+C      Quitte proprement
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEMPLATE_FILE="$PROJECT_ROOT/.env.example"
ENV_FILE="$PROJECT_ROOT/.env"

# =============================================================================
# CHARGEMENT DES MODULES
# =============================================================================

source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/env.sh"
source "$SCRIPT_DIR/lib/prereqs.sh"
source "$SCRIPT_DIR/lib/config.sh"
source "$SCRIPT_DIR/lib/instance.sh"
source "$SCRIPT_DIR/lib/db.sh"
source "$SCRIPT_DIR/lib/auth.sh"
source "$SCRIPT_DIR/lib/data.sh"
source "$SCRIPT_DIR/lib/ollama.sh"
source "$SCRIPT_DIR/lib/schema.sh"

# Configuration du gestionnaire de sortie (Escape, Ctrl+C)
setup_exit_handler

# =============================================================================
# VARIABLES GLOBALES
# =============================================================================

DEPLOY_MODE=""       # "docker", "native" ou "mixed"
DEPLOY_ENV=""        # "dev" ou "prod"
PUBLIC_HOST="localhost"
PUBLIC_PROTOCOL="http"
AUTO_MODE=false
FIRST_INSTALL=false

# Mode par service (utilise en mode mixed)
POSTGRES_MODE="docker"
CHROMA_MODE="docker"
OLLAMA_MODE="docker"
APP_MODE="docker"
UI_MODE="docker"

# =============================================================================
# AIDE
# =============================================================================

show_help() {
    cat << 'EOF'
MY-IA - Script de deploiement universel
========================================

USAGE:
    ./scripts/deploy.sh [OPTIONS] [MODE] [ENV] [ADRESSE]

MODES:
    docker          Deploiement avec Docker Compose (defaut si Docker disponible)
    native          Deploiement bare-metal (sans Docker)
    mixed           Mode mixte (certains services natifs, reste en Docker)
    remote          Deploiement sur serveur distant via SSH (config en BDD)

ENVIRONNEMENTS:
    local           Developpement local (localhost, DEBUG=true)
    staging         Staging (pre-production, DEBUG=false)
    prod            Production (IP/domaine, DEBUG=false, multi-workers)

OPTIONS:
    -h, --help      Affiche cette aide
    --auto, -y      Mode non-interactif (installe sans demander)
    --debug         Active les logs de debug

EXEMPLES:
    ./scripts/deploy.sh                             # Interactif complet
    ./scripts/deploy.sh docker local                # Docker + dev local
    ./scripts/deploy.sh docker prod 51.210.245.202  # Docker + production
    ./scripts/deploy.sh docker staging 51.210.245.202  # Docker + staging
    ./scripts/deploy.sh native local                # Bare-metal + dev local
    ./scripts/deploy.sh native prod myia.example.com  # Bare-metal + prod
    ./scripts/deploy.sh mixed local                  # Mixte + dev local
    ./scripts/deploy.sh --auto docker local         # Non-interactif
    ./scripts/deploy.sh --auto mixed local          # Mixte non-interactif (preset macOS)
    ./scripts/deploy.sh remote                       # Deploie sur serveur distant (config BDD)

PREMIERE INSTALLATION:
    Le script detecte automatiquement une premiere installation et:
    - Demande le nom de votre application
    - Demande l'environnement (dev/staging/prod)
    - Genere ou demande les mots de passe
    - Installe les prerequis manquants
    - Configure et demarre tous les services

EOF
    exit 0
}

# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

# Detecte si c'est une adresse IP ou un domaine
is_ip_or_domain() {
    local addr="$1"
    # Exclure les mots-cles
    case "$addr" in
        local|server|prod|production|help|docker|native) return 1 ;;
    esac
    # IP v4
    if [[ "$addr" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        return 0
    fi
    # Domaine
    if [[ "$addr" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*\.)+[a-zA-Z]{2,}$ ]]; then
        return 0
    fi
    return 1
}

# Configure une variable dans .env.example
set_template_var() {
    local var_name="$1"
    local var_value="$2"

    if grep -q "^${var_name}=" "$TEMPLATE_FILE"; then
        sed -i.bak "s|^${var_name}=.*|${var_name}=${var_value}|" "$TEMPLATE_FILE"
        rm -f "$TEMPLATE_FILE.bak"
    fi
}

# Genere un mot de passe aleatoire securise
generate_password() {
    local length="${1:-16}"
    LC_ALL=C tr -dc 'A-Za-z0-9!@#$%&*' < /dev/urandom | head -c "$length"
}

# Banniere de deploiement
show_deploy_banner() {
    echo ""
    echo "============================================================================="
    echo "  MY-IA - DEPLOIEMENT UNIVERSEL"
    echo "============================================================================="
    echo ""
    echo "  Systeme:        ${OS_TYPE} ${OS_VERSION} (${ARCH})"
    if [[ -n "$DEPLOY_MODE" ]]; then
        echo "  Mode:           ${DEPLOY_MODE}"
    fi
    if [[ "$DEPLOY_MODE" == "mixed" ]]; then
        local native_services=""
        [[ "$POSTGRES_MODE" == "native" ]] && native_services+="PostgreSQL "
        [[ "$CHROMA_MODE" == "native" ]] && native_services+="ChromaDB "
        [[ "$OLLAMA_MODE" == "native" ]] && native_services+="Ollama "
        [[ "$APP_MODE" == "native" ]] && native_services+="App "
        [[ "$UI_MODE" == "native" ]] && native_services+="UI "
        if [[ -n "$native_services" ]]; then
            echo "  Services natifs: ${native_services}"
        fi
    fi
    if [[ -n "$DEPLOY_ENV" ]]; then
        echo "  Environnement:  ${DEPLOY_ENV}"
    fi
    echo ""
    echo "============================================================================="
    echo ""
}

# =============================================================================
# FONCTIONS UX : EN-TETE DE PHASE + RECAP + GESTION D'ERREUR
# =============================================================================

TOTAL_PHASES=8

# Affiche un en-tete numerote pour chaque phase du deploiement.
#
# Usage:
#   show_phase_header 2 "Choix du mode de deploiement"
#
# Parametres:
#   $1 - Numero de la phase (1..TOTAL_PHASES)
#   $2 - Titre de la phase
show_phase_header() {
    local phase_num="$1"
    local phase_title="$2"

    echo ""
    echo "============================================================================="
    echo "  Phase ${phase_num}/${TOTAL_PHASES} — ${phase_title}"
    echo "============================================================================="
    echo ""
}

# Affiche un mini-recapitulatif en fin de phase.
#
# Usage:
#   show_phase_recap 2 "Mode: docker | Environnement: dev"
#
# Parametres:
#   $1 - Numero de la phase
#   $2 - Message recapitulatif (une ligne)
show_phase_recap() {
    local phase_num="$1"
    local recap_msg="$2"

    echo ""
    echo "  ─── Phase ${phase_num}/${TOTAL_PHASES} terminee ───"
    echo "  ${recap_msg}"
    echo ""
}

# Gestion d'erreur de phase avec options utilisateur.
# Propose Reessayer / Ignorer / Quitter.
#
# Usage:
#   handle_phase_error 5 "Erreur Docker" "Verifiez que Docker Desktop est demarre"
#
# Parametres:
#   $1 - Numero de la phase
#   $2 - Message d'erreur
#   $3 - Suggestion de correction (optionnel)
#
# Retour:
#   0 si l'utilisateur choisit "Ignorer"
#   1 si l'utilisateur choisit "Reessayer" (l'appelant doit boucler)
#   exit si "Quitter"
handle_phase_error() {
    local phase_num="$1"
    local error_msg="$2"
    local suggestion="${3:-}"

    echo ""
    log_error "Phase ${phase_num}: ${error_msg}"
    if [[ -n "$suggestion" ]]; then
        echo "  Suggestion: ${suggestion}"
    fi
    echo ""

    # En mode auto, quitter directement
    if [[ "$AUTO_MODE" == "true" ]]; then
        log_error "Mode auto: arret suite a une erreur en phase ${phase_num}"
        exit 1
    fi

    echo "  Options:"
    echo "    [r] Reessayer cette phase"
    echo "    [i] Ignorer et continuer"
    echo "    [q] Quitter"
    echo ""
    printf "  Votre choix [r/i/q]: "
    local choice
    read -r choice < /dev/tty

    case "$choice" in
        r|R)
            log_info "Relance de la phase ${phase_num}..."
            return 1
            ;;
        i|I)
            log_warn "Phase ${phase_num} ignoree"
            return 0
            ;;
        q|Q|*)
            log_info "Deploiement interrompu par l'utilisateur"
            exit 0
            ;;
    esac
}

# =============================================================================
# CONFIGURATION MODE MIXTE
# =============================================================================
# Permet de choisir quels services sont en Docker et lesquels en natif.
# Sur macOS, propose un preset optimise (Ollama natif pour GPU Metal).
# =============================================================================

configure_mixed_mode() {
    # En mode auto, utiliser le preset macOS (Ollama natif + reste Docker)
    if [[ "$AUTO_MODE" == "true" ]]; then
        OLLAMA_MODE="native"
        log_info "Mode mixte auto: Ollama natif, reste en Docker"
        return 0
    fi

    echo ""
    echo "  Configuration du mode mixte"
    echo "  ----------------------------"
    echo ""

    # Proposer le preset macOS si applicable
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        echo "  Profil recommande pour macOS :"
        echo "    - Ollama en natif (acces GPU Metal pour les modeles IA)"
        echo "    - PostgreSQL, ChromaDB, App, UI en Docker (isoles)"
        echo ""
        if confirm "  Utiliser ce profil optimise macOS ?" "y"; then
            OLLAMA_MODE="native"
            log_success "Profil macOS: Ollama natif + reste Docker"
            return 0
        fi
    fi

    # Configuration manuelle par service
    echo ""
    echo "  Pour chaque service, choisissez Docker (d) ou Natif (n) :"
    echo ""

    local choice
    printf "  PostgreSQL  [D/n]: "
    read -r choice < /dev/tty
    [[ "$choice" == "n" || "$choice" == "N" ]] && POSTGRES_MODE="native"

    printf "  ChromaDB    [D/n]: "
    read -r choice < /dev/tty
    [[ "$choice" == "n" || "$choice" == "N" ]] && CHROMA_MODE="native"

    printf "  Ollama      [d/N]: "
    read -r choice < /dev/tty
    [[ "$choice" != "d" && "$choice" != "D" ]] && OLLAMA_MODE="native"

    printf "  App (API)   [D/n]: "
    read -r choice < /dev/tty
    [[ "$choice" == "n" || "$choice" == "N" ]] && APP_MODE="native"

    printf "  UI (Front/Back) [D/n]: "
    read -r choice < /dev/tty
    [[ "$choice" == "n" || "$choice" == "N" ]] && UI_MODE="native"

    echo ""
    log_info "Configuration mixte:"
    echo "  PostgreSQL: $POSTGRES_MODE | ChromaDB: $CHROMA_MODE | Ollama: $OLLAMA_MODE"
    echo "  App: $APP_MODE | UI: $UI_MODE"
}

# =============================================================================
# PARSING DES ARGUMENTS
# =============================================================================

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help|help)
                show_help
                ;;
            --auto|-y)
                AUTO_MODE=true
                shift
                ;;
            --debug|-d)
                DEBUG_MODE=true
                shift
                ;;
            docker)
                DEPLOY_MODE="docker"
                shift
                ;;
            native|baremetal|bare-metal)
                DEPLOY_MODE="native"
                shift
                ;;
            mixed|mixte)
                DEPLOY_MODE="mixed"
                shift
                ;;
            remote|distant)
                DEPLOY_MODE="remote"
                shift
                ;;
            local)
                DEPLOY_ENV="dev"
                PUBLIC_HOST="localhost"
                PUBLIC_PROTOCOL="http"
                shift
                ;;
            staging)
                DEPLOY_ENV="staging"
                shift
                # Verifier si l'argument suivant est une adresse
                if [[ -n "${1:-}" ]] && is_ip_or_domain "$1"; then
                    PUBLIC_HOST="$1"
                    shift
                fi
                ;;
            prod|production)
                DEPLOY_ENV="prod"
                shift
                # Verifier si l'argument suivant est une adresse
                if [[ -n "${1:-}" ]] && is_ip_or_domain "$1"; then
                    PUBLIC_HOST="$1"
                    shift
                fi
                ;;
            *)
                # Tenter de traiter comme adresse
                if is_ip_or_domain "$1"; then
                    PUBLIC_HOST="$1"
                    if [[ -z "$DEPLOY_ENV" ]]; then
                        DEPLOY_ENV="prod"
                    fi
                    shift
                else
                    log_error "Argument invalide: $1"
                    echo "Utilisez --help pour voir les options"
                    exit 1
                fi
                ;;
        esac
    done
}

# =============================================================================
# ASSISTANT PREMIERE INSTALLATION (WIZARD)
# =============================================================================

first_install_wizard() {
    echo ""
    echo "============================================================================="
    echo "            BIENVENUE - PREMIERE INSTALLATION DETECTEE"
    echo "============================================================================="
    echo ""
    echo "Ce guide va vous aider a configurer votre instance."
    echo ""

    # 1. Nom de l'application
    echo "----------------------------------------------"
    echo "1/4 - NOM DE L'APPLICATION"
    echo "----------------------------------------------"
    echo ""
    local app_name
    app_name=$(read_with_escape "Nom de votre application" "MY-IA")
    set_template_var "APP_TITLE" "$app_name"
    set_template_var "APP_NAME_PREFIX" "$app_name"
    log_success "Application: $app_name"
    echo ""

    # 2. Environnement (dev/staging/prod)
    echo "----------------------------------------------"
    echo "2/4 - ENVIRONNEMENT DE DEPLOIEMENT"
    echo "----------------------------------------------"
    echo ""
    echo "  1. Developpement (hot-reload, debug, utilisateurs test)"
    echo "  2. Staging (pre-production, sans debug, sans hot-reload)"
    echo "  3. Production (optimise, securise, multi-workers)"
    echo ""
    local env_choice
    env_choice=$(read_with_escape "Choix" "1")

    case "$env_choice" in
        2)
            DEPLOY_ENV="staging"
            set_template_var "DEBUG" "false"
            set_template_var "DEPLOY_ENV" "staging"
            log_success "Mode: STAGING"
            ;;
        3)
            DEPLOY_ENV="prod"
            set_template_var "DEBUG" "false"
            set_template_var "DEPLOY_ENV" "prod"
            log_success "Mode: PRODUCTION"
            ;;
        *)
            DEPLOY_ENV="dev"
            set_template_var "DEBUG" "true"
            set_template_var "DEPLOY_ENV" "dev"
            log_success "Mode: DEVELOPPEMENT"
            ;;
    esac
    echo ""

    # 3. Mots de passe
    echo "----------------------------------------------"
    echo "3/4 - MOTS DE PASSE BASE DE DONNEES"
    echo "----------------------------------------------"
    echo ""
    echo "  1. Generer automatiquement (recommande)"
    echo "  2. Saisir manuellement"
    echo ""
    local pwd_choice
    pwd_choice=$(read_with_escape "Choix" "1")

    local pg_password app_password
    case "$pwd_choice" in
        2)
            echo ""
            echo -n "Mot de passe PostgreSQL admin: "
            read -rs pg_password
            echo ""
            echo -n "Mot de passe PostgreSQL app: "
            read -rs app_password
            echo ""
            ;;
        *)
            pg_password=$(generate_password 20)
            app_password=$(generate_password 20)
            log_info "Mots de passe generes automatiquement"
            ;;
    esac
    set_template_var "POSTGRES_PASSWORD" "$pg_password"
    set_template_var "APP_DB_PASSWORD" "$app_password"
    log_success "Mots de passe configures"
    echo ""

    # 4. Adresse du serveur
    echo "----------------------------------------------"
    echo "4/4 - ADRESSE DU SERVEUR"
    echo "----------------------------------------------"
    echo ""
    echo "  1. Localhost (developpement local)"
    echo "  2. Serveur distant (IP ou domaine)"
    echo ""
    local addr_choice
    addr_choice=$(read_with_escape "Choix" "1")

    case "$addr_choice" in
        2)
            echo ""
            PUBLIC_HOST=$(read_with_escape "Adresse (IP ou domaine)" "localhost")
            if [[ "$PUBLIC_HOST" != "localhost" ]]; then
                PUBLIC_PROTOCOL=$(read_with_escape "Protocole (http/https)" "http")
            fi
            ;;
        *)
            PUBLIC_HOST="localhost"
            PUBLIC_PROTOCOL="http"
            ;;
    esac
    set_template_var "PUBLIC_HOST" "$PUBLIC_HOST"
    set_template_var "PUBLIC_PROTOCOL" "$PUBLIC_PROTOCOL"
    log_success "Adresse: ${PUBLIC_PROTOCOL}://${PUBLIC_HOST}"
    echo ""
    log_success "Configuration terminee !"
}

# =============================================================================
# GESTION D'UNE INSTALLATION EXISTANTE
# =============================================================================
# Propose un menu clair pour une installation existante :
#   1. Mettre a jour (conserver donnees et configuration)
#   2. Reconfigurer (editer le .env)
#   3. Reinstaller (PERTE DE DONNEES - double confirmation)
# =============================================================================

handle_existing_installation() {
    echo ""
    echo "============================================================================="
    echo "  INSTALLATION EXISTANTE DETECTEE"
    echo "============================================================================="
    echo ""
    echo "  Options disponibles:"
    echo ""
    echo "  1. Mettre a jour (conserver donnees et configuration)"
    echo "  2. Reconfigurer (editer la configuration .env)"
    echo "  3. Reinstaller completement (PERTE DE DONNEES)"
    echo ""

    local choice
    choice=$(read_with_escape "Choix" "1")

    case "$choice" in
        1)
            log_info "Mise a jour en conservant les donnees..."

            # --- Git pull si dans un depot git ---
            if [[ -d "$PROJECT_ROOT/.git" ]]; then
                log_step "Recuperation des dernieres modifications..."
                cd "$PROJECT_ROOT"

                local old_hash
                old_hash=$(git rev-parse HEAD 2>/dev/null || echo "")
                local current_branch
                current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")

                if git pull origin "$current_branch" 2>/dev/null; then
                    local new_hash
                    new_hash=$(git rev-parse HEAD 2>/dev/null || echo "")

                    if [[ "$old_hash" != "$new_hash" && -n "$old_hash" ]]; then
                        local commit_count
                        commit_count=$(git rev-list --count "${old_hash}..${new_hash}" 2>/dev/null || echo "0")
                        log_success "Code mis a jour ($commit_count nouveau(x) commit(s))"

                        # Detecter si un rebuild Docker est necessaire
                        if git diff --name-only "${old_hash}..${new_hash}" | grep -qE "(requirements\.txt|Dockerfile|docker-compose\.yml)"; then
                            log_warn "Fichiers d'infrastructure modifies (requirements.txt, Dockerfile ou docker-compose.yml)"
                            log_warn "Les images Docker seront reconstruites"
                            FIRST_INSTALL=true
                        fi
                    else
                        log_info "Code deja a jour"
                    fi
                else
                    log_warn "Git pull echoue (non bloquant, le code local sera utilise)"
                fi
            fi

            # --- Backup du .env ---
            if [[ -f "$ENV_FILE" ]]; then
                local backup_name=".env.backup.$(date +%Y%m%d-%H%M%S)"
                cp "$ENV_FILE" "$PROJECT_ROOT/$backup_name"
                log_success "Backup .env: $backup_name"
            fi

            # Regenerer le .env (preserve les valeurs existantes)
            "$SCRIPT_DIR/generate-env.sh" --force
            ;;
        2)
            log_info "Reconfiguration..."
            # Backup du .env
            if [[ -f "$ENV_FILE" ]]; then
                local backup_name=".env.backup.$(date +%Y%m%d-%H%M%S)"
                cp "$ENV_FILE" "$PROJECT_ROOT/$backup_name"
                log_success "Backup: $backup_name"
            fi
            if ! handle_config "$PROJECT_ROOT" "$SCRIPT_DIR"; then
                log_error "Echec de la configuration"
                exit 1
            fi
            ;;
        3)
            echo ""
            log_warn "ATTENTION: Cette action va supprimer TOUTES les donnees!"
            log_warn "  - Containers Docker et volumes"
            log_warn "  - Base de donnees (conversations, utilisateurs, documents)"
            log_warn "  - Configuration (.env)"
            echo ""
            if confirm "Etes-vous CERTAIN de vouloir tout reinstaller ?" "n"; then
                echo ""
                if confirm "DERNIERE CONFIRMATION: perte de donnees irreversible ?" "n"; then
                    local sanitized
                    sanitized=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)
                    cleanup_project "$sanitized"
                    FIRST_INSTALL=true
                    # Relancer le wizard
                    first_install_wizard
                    "$SCRIPT_DIR/generate-env.sh" --force
                else
                    log_info "Reinstallation annulee"
                    exit 0
                fi
            else
                log_info "Reinstallation annulee"
                exit 0
            fi
            ;;
        *)
            log_error "Choix invalide"
            exit 1
            ;;
    esac
}

# =============================================================================
# PHASE 5A - INSTALLATION DOCKER
# =============================================================================

docker_install() {
    log_step "Installation Docker..."

    # Charger la config
    set +e
    source "$ENV_FILE"
    set -e

    SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)
    export SANITIZED_PREFIX

    # Gerer les containers existants
    check_project_containers "$SANITIZED_PREFIX"

    # Verifier les ports
    check_all_ports

    # Options docker compose
    local compose_opts="-d"
    if [[ "$FIRST_INSTALL" == true ]]; then
        compose_opts="-d --build"
    fi

    log_step "Demarrage des containers..."
    cd "$PROJECT_ROOT"
    local compose_files
    compose_files=$(get_compose_files)
    log_info "Environnement: ${DEPLOY_ENV:-dev} ($compose_files)"
    $COMPOSE_CMD $compose_files up $compose_opts

    log_step "Attente des services..."
    sleep 5

    # Gestion des modeles Ollama (detection automatique Docker/natif)
    if [[ "$AUTO_MODE" != "true" ]]; then
        manage_all_models
    else
        auto_download_models
    fi
}

# =============================================================================
# PHASE 5B - INSTALLATION NATIVE (BARE-METAL)
# =============================================================================

native_install() {
    log_step "Installation bare-metal..."

    source "$SCRIPT_DIR/lib/baremetal.sh"
    baremetal_install "$PROJECT_ROOT" "$SCRIPT_DIR"
}

# =============================================================================
# PHASE 5C - INSTALLATION MIXTE
# =============================================================================
# Installe les services natifs choisis, puis lance Docker pour le reste.
# Genere un docker-compose.override.yml excluant les services natifs.
# =============================================================================

mixed_install() {
    log_step "Installation mixte..."

    source "$SCRIPT_DIR/lib/baremetal.sh"

    # Charger la config
    set +e
    source "$ENV_FILE"
    set -e

    SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)
    export SANITIZED_PREFIX

    # --- Installation des services natifs choisis ---

    if [[ "$POSTGRES_MODE" == "native" ]]; then
        log_step "Installation PostgreSQL natif..."
        install_postgresql
    fi

    if [[ "$OLLAMA_MODE" == "native" ]]; then
        log_step "Installation Ollama natif..."
        install_ollama_native
    fi

    if [[ "$CHROMA_MODE" == "native" ]]; then
        log_step "Installation ChromaDB natif..."
        install_chromadb_native
    fi

    if [[ "$APP_MODE" == "native" ]]; then
        log_step "Installation App (API) native..."
        setup_python_venv "$PROJECT_ROOT"
    fi

    # --- Generer docker-compose.override.yml pour exclure les services natifs ---

    generate_mixed_override

    # --- Adapter le .env pour les services natifs (hostname Docker -> localhost) ---

    if [[ "$POSTGRES_MODE" == "native" ]]; then
        sed -i.bak "s|POSTGRES_HOST=.*|POSTGRES_HOST=localhost|" "$ENV_FILE"
    fi
    if [[ "$OLLAMA_MODE" == "native" ]]; then
        sed -i.bak "s|OLLAMA_HOST=.*|OLLAMA_HOST=http://host.docker.internal:11434|" "$ENV_FILE"
    fi
    if [[ "$CHROMA_MODE" == "native" ]]; then
        sed -i.bak "s|CHROMA_HOST=.*|CHROMA_HOST=localhost|" "$ENV_FILE"
    fi
    rm -f "${ENV_FILE}.bak"

    # --- Demarrer les containers Docker restants ---

    local compose_opts="-d"
    if [[ "$FIRST_INSTALL" == true ]]; then
        compose_opts="-d --build"
    fi

    # Gerer les containers existants
    check_project_containers "$SANITIZED_PREFIX"
    check_all_ports

    log_step "Demarrage des containers Docker (services non-natifs)..."
    cd "$PROJECT_ROOT"
    local compose_files
    compose_files=$(get_compose_files)
    log_info "Environnement: ${DEPLOY_ENV:-dev} ($compose_files)"
    $COMPOSE_CMD $compose_files up $compose_opts

    log_step "Attente des services..."
    sleep 5

    # Gestion des modeles Ollama (detection automatique Docker/natif)
    if [[ "$AUTO_MODE" != "true" ]]; then
        manage_all_models
    else
        auto_download_models
    fi
}

# =============================================================================
# GENERATION DU DOCKER-COMPOSE OVERRIDE (MODE MIXTE)
# =============================================================================
# Genere un fichier docker-compose.override.yml qui desactive les services
# deployes en natif via le mecanisme de profiles Docker.
# =============================================================================

generate_mixed_override() {
    local override_file="$PROJECT_ROOT/docker-compose.override.yml"
    local services_to_disable=()

    [[ "$POSTGRES_MODE" == "native" ]] && services_to_disable+=("postgres")
    [[ "$CHROMA_MODE" == "native" ]] && services_to_disable+=("chroma")
    [[ "$OLLAMA_MODE" == "native" ]] && services_to_disable+=("ollama")
    [[ "$APP_MODE" == "native" ]] && services_to_disable+=("app")
    [[ "$UI_MODE" == "native" ]] && services_to_disable+=("ui-front" "ui-back")

    if [[ ${#services_to_disable[@]} -eq 0 ]]; then
        log_info "Aucun service natif, pas d'override necessaire"
        rm -f "$override_file"
        return 0
    fi

    log_info "Generation de docker-compose.override.yml..."
    log_info "Services desactives (natifs): ${services_to_disable[*]}"

    cat > "$override_file" << 'HEADER'
# =============================================================================
# FICHIER GENERE AUTOMATIQUEMENT par deploy.sh (mode mixte)
# Ne pas editer manuellement - sera regenere au prochain deploiement
# =============================================================================

services:
HEADER

    for service in "${services_to_disable[@]}"; do
        cat >> "$override_file" << EOF
  ${service}:
    profiles:
      - disabled

EOF
    done

    log_success "docker-compose.override.yml genere (${#services_to_disable[@]} services desactives)"
}

# =============================================================================
# MIGRATIONS BASE DE DONNEES
# =============================================================================
# Execute alembic upgrade head pour appliquer les migrations en attente.
# Supporte les modes Docker, natif et mixte.
# =============================================================================

run_migrations() {
    log_step "Application des migrations de base de donnees..."

    if [[ "$DEPLOY_MODE" == "docker" || "$DEPLOY_MODE" == "mixed" ]]; then
        local app_container="${SANITIZED_PREFIX}_app"

        # Verifier que le container app est running
        if ! docker ps --format '{{.Names}}' | grep -q "^${app_container}$"; then
            log_warn "Container $app_container non trouve, migrations ignorees"
            return 0
        fi

        # Attendre que le container soit pret (max 30s)
        local attempts=0
        while [[ $attempts -lt 15 ]]; do
            if docker exec "$app_container" python -c "print('ok')" > /dev/null 2>&1; then
                break
            fi
            sleep 2
            attempts=$((attempts + 1))
        done

        local migration_output
        migration_output=$(docker exec "$app_container" python -m alembic upgrade head 2>&1)
        local exit_code=$?

        if [[ $exit_code -eq 0 ]]; then
            if echo "$migration_output" | grep -q "Running upgrade"; then
                log_success "Migrations appliquees:"
                echo "$migration_output" | grep "Running upgrade" | while read -r line; do
                    echo "    $line"
                done
            else
                log_success "Base de donnees a jour (aucune migration en attente)"
            fi
        else
            log_warn "Echec des migrations (non bloquant)"
            echo "  $migration_output" | head -5
        fi

    elif [[ "$DEPLOY_MODE" == "native" ]]; then
        local venv_python="${PROJECT_ROOT}/venv/bin/python"
        if [[ -f "$venv_python" ]]; then
            cd "$PROJECT_ROOT"
            local migration_output
            migration_output=$("$venv_python" -m alembic upgrade head 2>&1)
            local exit_code=$?

            if [[ $exit_code -eq 0 ]]; then
                if echo "$migration_output" | grep -q "Running upgrade"; then
                    log_success "Migrations appliquees"
                else
                    log_success "Base de donnees a jour"
                fi
            else
                log_warn "Echec des migrations: $migration_output"
            fi
        else
            log_warn "Python venv non trouve, migrations ignorees"
        fi
    fi
}

# =============================================================================
# PHASE 6 - HEALTH CHECKS
# =============================================================================

run_health_checks() {
    log_step "Verification de la sante des services..."

    local app_port="${APP_PORT:-8080}"
    local max_attempts=30
    local attempt=1

    echo "  Attente de l'API (port $app_port)..."
    while [[ $attempt -le $max_attempts ]]; do
        if curl -sf "http://localhost:$app_port/health" > /dev/null 2>&1; then
            break
        fi
        sleep 2
        attempt=$((attempt + 1))
    done

    if [[ $attempt -gt $max_attempts ]]; then
        log_warn "L'API n'a pas repondu"
        if [[ "$DEPLOY_MODE" == "docker" ]]; then
            echo "  Verifiez les logs: $COMPOSE_CMD logs app"
        else
            echo "  Verifiez les logs: journalctl -u myia-api -f"
        fi
        return 1
    fi

    local health_status
    health_status=$(curl -s "http://localhost:$app_port/health" 2>/dev/null)

    if echo "$health_status" | grep -q '"status":"healthy"'; then
        log_success "API: healthy"
    else
        log_warn "API: degraded ou unhealthy"
        echo "  Details: $health_status"
    fi

    # Afficher les services selon le mode
    if [[ "$DEPLOY_MODE" == "docker" ]]; then
        echo ""
        echo "  Status des containers:"
        $COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}" 2>/dev/null \
            || $COMPOSE_CMD ps
    fi

    return 0
}

# =============================================================================
# PHASE 7 - DONNEES
# =============================================================================

handle_data() {
    log_step "Gestion des donnees..."

    set +e
    source "$ENV_FILE"
    set -e

    SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)

    if [[ "$AUTO_MODE" == "true" ]]; then
        log_info "Mode auto: import des donnees ignore"
        return 0
    fi

    if [[ "$DEPLOY_MODE" == "docker" ]]; then
        handle_data_imports "$PROJECT_ROOT"
    else
        # En bare-metal, les appels API se font directement via curl
        local app_port="${APP_PORT:-8080}"
        local admin_token

        if [[ -n "${INSTALL_DIR:-}" ]]; then
            source "$SCRIPT_DIR/lib/baremetal.sh"
            admin_token=$(generate_admin_token_native "$PROJECT_ROOT")
        else
            # Fallback: generer un token via Docker si disponible
            local app_container="${SANITIZED_PREFIX}_app"
            admin_token=$(generate_admin_token "$app_container")
        fi

        if [[ -z "$admin_token" ]]; then
            log_warn "Impossible de generer le token admin"
            log_warn "Les imports devront etre faits via l'interface admin"
            return 0
        fi

        # Import pays
        show_countries_menu "${SANITIZED_PREFIX}_app" "$app_port" "$admin_token" "$PROJECT_ROOT"
        # Import villes
        show_cities_menu "${SANITIZED_PREFIX}_app" "$app_port" "$admin_token" "$PROJECT_ROOT"
        # Users de test
        show_test_users_menu "${SANITIZED_PREFIX}_app"
    fi
}

# =============================================================================
# PHASE 8 - PUSH CONFIG BDD
# =============================================================================

push_config_to_db() {
    log_step "Push de la configuration en BDD..."

    set +e
    source "$ENV_FILE"
    set -e

    local api_url="http://localhost:${APP_PORT:-8080}"
    local token=""

    SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)

    # Generer un token admin JWT (5 min)
    if [[ "$DEPLOY_MODE" == "docker" ]]; then
        token=$(generate_admin_token "${SANITIZED_PREFIX}_app")
    else
        if [[ -n "${INSTALL_DIR:-}" ]]; then
            source "$SCRIPT_DIR/lib/baremetal.sh"
            init_baremetal_vars "$PROJECT_ROOT"
            token=$(generate_admin_token_native "$PROJECT_ROOT")
        fi
    fi

    if [[ -z "$token" ]]; then
        log_warn "Token admin non genere - push config ignore (non bloquant)"
        return 0
    fi

    # PATCH /api/admin/config/rag — configuration RAG depuis .env
    if curl -sf -X PATCH "$api_url/api/admin/config/rag" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "{\"top_k\": ${TOP_K:-4}, \"chunk_size\": ${CHUNK_SIZE:-1000}, \"chunk_overlap\": ${CHUNK_OVERLAP:-200}, \"chunking_strategy\": \"${CHUNKING_STRATEGY:-semantic}\"}" \
        > /dev/null 2>&1; then
        log_success "Config RAG poussee en BDD"
    else
        log_warn "Config RAG : echec (non bloquant)"
    fi

    # PATCH /api/admin/config/timeouts — timeouts depuis .env
    if curl -sf -X PATCH "$api_url/api/admin/config/timeouts" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "{\"ollama_timeout\": ${OLLAMA_TIMEOUT:-600.0}, \"http_timeout\": ${HTTP_TIMEOUT:-30.0}, \"health_check_timeout\": ${HEALTH_CHECK_TIMEOUT:-5.0}}" \
        > /dev/null 2>&1; then
        log_success "Config timeouts poussee en BDD"
    else
        log_warn "Config timeouts : echec (non bloquant)"
    fi

    # PATCH /api/admin/config/rate-limits — rate limits depuis .env
    if curl -sf -X PATCH "$api_url/api/admin/config/rate-limits" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d "{\"chat\": \"${RATE_LIMIT_CHAT:-30/minute}\", \"upload\": \"${RATE_LIMIT_UPLOAD:-10/minute}\", \"stream\": \"${RATE_LIMIT_STREAM:-20/minute}\"}" \
        > /dev/null 2>&1; then
        log_success "Config rate limits poussee en BDD"
    else
        log_warn "Config rate limits : echec (non bloquant)"
    fi

    # PATCH /api/admin/config/logging (niveaux prod/staging)
    if [[ "$DEPLOY_ENV" == "prod" || "$DEPLOY_ENV" == "staging" ]]; then
        if curl -sf -X PATCH "$api_url/api/admin/config/logging" \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d '{"log_level_technical":"INFO","log_level_access":"INFO","log_level_audit":"WARN","log_level_security":"WARN","log_level_infra":"INFO","log_db_enabled":true}' \
            > /dev/null 2>&1; then
            log_success "Config logging poussee en BDD"
        else
            log_warn "Config logging : echec (non bloquant)"
        fi
    fi

    # PATCH /api/admin/config/dynamic — cles generales (DEPLOY_ENV, DEBUG, API_URL, PUBLIC_HOST)
    local dynamic_keys=(
        "app.deploy_env|${DEPLOY_ENV:-dev}"
        "app.debug|${DEBUG:-true}"
        "app.api_url|${API_URL:-http://localhost:${APP_PORT:-8080}}"
        "app.public_host|${PUBLIC_HOST:-localhost}"
        "app.version|${APP_VERSION:-1.0.0}"
    )

    local sync_ok=true
    for entry in "${dynamic_keys[@]}"; do
        local key="${entry%%|*}"
        local value="${entry#*|}"
        if ! curl -sf -X PATCH "$api_url/api/admin/config/dynamic/$key" \
            -H "Authorization: Bearer $token" \
            -H "Content-Type: application/json" \
            -d "{\"value\": \"$value\"}" \
            > /dev/null 2>&1; then
            sync_ok=false
        fi
    done

    if [[ "$sync_ok" == "true" ]]; then
        log_success "Config generale synchronisee en BDD"
    else
        log_warn "Config generale : sync partielle (non bloquant)"
    fi

    # PATCH /api/admin/config/smtp — initialisation config SMTP (desactive par defaut)
    if curl -sf -X PATCH "$api_url/api/admin/config/smtp" \
        -H "Authorization: Bearer $token" \
        -H "Content-Type: application/json" \
        -d '{"provider":"smtp","enabled":false,"port":587,"use_tls":true,"use_ssl":false}' \
        > /dev/null 2>&1; then
        log_success "Config SMTP initialisee en BDD"
    else
        log_warn "Config SMTP : echec initialisation (non bloquant)"
    fi
}

# =============================================================================
# PHASE 9 - SECURITE
# =============================================================================

show_security_checklist() {
    echo ""
    echo "============================================================================="
    echo "                        CHECKLIST SECURITE"
    echo "============================================================================="
    echo ""
    echo "  [AUTO]  Cles de securite generees (JWT, API, ENCRYPTION)"
    echo "  [AUTO]  Identifiants PostgreSQL configures"

    if [[ "$DEPLOY_ENV" == "prod" ]]; then
        echo "  [AUTO]  Mode production active (DEBUG=false, multi-workers)"
    elif [[ "$DEPLOY_ENV" == "staging" ]]; then
        echo "  [AUTO]  Mode staging active (DEBUG=false, pre-production)"
    else
        echo "  [INFO]  Mode developpement (utilisateurs de test crees)"
    fi

    echo ""

    # Permissions securisees sur les fichiers sensibles
    chmod 600 "$ENV_FILE" 2>/dev/null || true
    chmod 600 "$PROJECT_ROOT/.external_secrets" 2>/dev/null || true

    if [[ "$PUBLIC_HOST" != "localhost" ]]; then
        echo "  [TODO]  Ouvrir les ports firewall:"
        echo "            ufw allow ${FRONTEND_PORT:-3000}/tcp  # Frontend"
        echo "            ufw allow ${APP_PORT:-8080}/tcp  # API"
        echo "            ufw allow ${ADMIN_PORT:-8081}/tcp  # Admin"
        echo ""

        if [[ "$DEPLOY_MODE" == "native" ]]; then
            echo "  [TODO]  HTTPS recommande en production"
            echo "            Utiliser certbot --nginx si domaine configure"
        else
            echo "  [TODO]  HTTPS recommande (reverse proxy nginx/traefik)"
        fi
    fi

    echo ""
    echo "  [IMPORTANT]  Sauvegardez le fichier .env"
    echo "               La cle ENCRYPTION_KEY est critique (perte = donnees perdues)"
    echo ""
    echo "============================================================================="
}

# =============================================================================
# PHASE 10 - RECAPITULATIF
# =============================================================================

show_final_summary() {
    set +e
    source "$ENV_FILE"
    set -e

    local base_url="${PUBLIC_PROTOCOL:-http}://${PUBLIC_HOST:-localhost}"

    # Sauvegarde des credentials
    local credentials_file
    credentials_file=$(save_credentials_file "$PROJECT_ROOT")

    echo ""
    echo "============================================================================="
    log_success "DEPLOIEMENT TERMINE"
    echo "============================================================================="
    echo ""
    local env_label
    case "$DEPLOY_ENV" in
        staging) env_label="STAGING" ;;
        prod)    env_label="PRODUCTION" ;;
        *)       env_label="DEVELOPPEMENT" ;;
    esac
    echo "  MODE: $(echo "$DEPLOY_MODE" | tr '[:lower:]' '[:upper:]') | ENVIRONNEMENT: $env_label"
    echo ""
    echo "  INTERFACES:"
    echo "    - Frontend:  ${base_url}:${FRONTEND_PORT:-3000}"
    echo "    - Admin:     ${base_url}:${ADMIN_PORT:-8081}"
    echo "    - API:       ${base_url}:${APP_PORT:-8080}"
    echo "    - API Docs:  ${base_url}:${APP_PORT:-8080}/docs"
    echo ""

    if [[ "$DEPLOY_ENV" != "prod" ]]; then
        echo "  IDENTIFIANTS DE TEST:"
        echo "    - Admin:       ${TEST_ADMIN_EMAIL:-admin@test.example} / ${TEST_ADMIN_PASSWORD:-Admin123!}"
        echo "    - Utilisateur: ${TEST_USER_EMAIL:-user@test.example} / ${TEST_USER_PASSWORD:-User123!}"
        echo ""
    fi

    # Recapitulatif des imports
    show_data_recap
    echo "    Credentials:      Sauvegardes dans ${credentials_file##*/}"
    echo ""

    echo "============================================================================="
    echo "  COMMANDES UTILES"
    echo "============================================================================="
    echo ""
    if [[ "$DEPLOY_MODE" == "docker" || "$DEPLOY_MODE" == "mixed" ]]; then
        echo "    - Voir les logs:     $COMPOSE_CMD logs -f app"
        echo "    - Arreter:           ./scripts/stop.sh"
        echo "    - Regenerer .env:    ./scripts/generate-env.sh --force"
    fi
    if [[ "$DEPLOY_MODE" == "native" || "$DEPLOY_MODE" == "mixed" ]]; then
        [[ "$DEPLOY_MODE" == "mixed" ]] && echo ""
        echo "    - Voir les logs API: journalctl -u myia-api -f"
        echo "    - Redemarrer API:    sudo systemctl restart myia-api"
        echo "    - Status services:   systemctl status myia-api myia-chromadb"
    fi
    echo ""
    echo "============================================================================="
    echo ""
}

# =============================================================================
# MAIN - ORCHESTRATION DES 8 PHASES
# =============================================================================

# Parser les arguments
parse_args "$@"

# ─────────────────────────────────────────────────────────────────────────────
# MODE REMOTE - Deploiement distant via SSH (court-circuite les phases locales)
# ─────────────────────────────────────────────────────────────────────────────

if [[ "$DEPLOY_MODE" == "remote" ]]; then
    # Le mode remote utilise la configuration de la BDD
    # et deploie sur un serveur distant via SSH
    remote_deploy
    exit $?
fi

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 - Detection de l'environnement
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 1 "Detection de l'environnement"

detect_os
detect_arch

# Verifier que .env.example existe
if [[ ! -f "$TEMPLATE_FILE" ]]; then
    log_error "Fichier .env.example non trouve"
    log_error "Ce fichier est necessaire pour configurer l'application"
    exit 1
fi

show_phase_recap 1 "OS: ${OS_TYPE} ${OS_VERSION} (${ARCH})"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 - Choix du mode de deploiement
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 2 "Choix du mode de deploiement"

if [[ -z "$DEPLOY_MODE" ]]; then
    # Detecter Docker automatiquement
    if command -v docker &> /dev/null && docker info &> /dev/null 2>&1; then
        if [[ "$AUTO_MODE" == "true" ]]; then
            DEPLOY_MODE="docker"
        else
            echo "  1. Docker (recommande - isole, portable)"
            echo "  2. Natif / bare-metal (installation directe sur le serveur)"
            echo "  3. Mixte (certains services natifs, reste en Docker)"
            echo ""
            mode_choice=$(read_with_escape "Choix" "1")

            case "$mode_choice" in
                2) DEPLOY_MODE="native" ;;
                3) DEPLOY_MODE="mixed" ;;
                *) DEPLOY_MODE="docker" ;;
            esac
        fi
    else
        DEPLOY_MODE="native"
        log_info "Docker non disponible, mode bare-metal selectionne"
    fi
fi

# Configuration du mode mixte (choix des services natifs)
if [[ "$DEPLOY_MODE" == "mixed" ]]; then
    configure_mixed_mode
fi

# Afficher la banniere
show_deploy_banner

show_phase_recap 2 "Mode: ${DEPLOY_MODE}"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 - Verification des prerequis
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 3 "Verification des prerequis"

if ! check_common_prereqs; then
    log_error "Prerequis communs manquants. Corrigez les erreurs ci-dessus."
    exit 1
fi

if [[ "$DEPLOY_MODE" == "docker" ]]; then
    if ! check_docker_prereqs; then
        handle_phase_error 3 "Prerequis Docker manquants" "Installez Docker Desktop ou Docker Engine" || exit 1
    fi
elif [[ "$DEPLOY_MODE" == "mixed" ]]; then
    if ! check_mixed_prereqs; then
        echo ""
        if ! confirm "Continuer malgre les prerequis manquants ?" "n"; then
            exit 1
        fi
    fi
else
    if ! check_baremetal_prereqs; then
        echo ""
        if ! confirm "Continuer malgre les prerequis manquants ?" "n"; then
            exit 1
        fi
    fi
fi

show_prereqs_summary
show_phase_recap 3 "Prerequis verifies (mode ${DEPLOY_MODE})"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 - Configuration
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 4 "Configuration"

# Detection multi-signaux : premiere installation vs mise a jour
# Utiliser SANITIZED_PREFIX s'il est deja defini (via args ou .env precedent)
local_prefix=""
if [[ -f "$ENV_FILE" ]]; then
    local_prefix=$(grep "^APP_NAME_PREFIX=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'" || true)
    local_prefix=$(sanitize "${local_prefix:-MY-IA}" false)
fi
detect_installation_state "$PROJECT_ROOT" "$local_prefix"

case "$INSTALL_STATE" in
    fresh)
        FIRST_INSTALL=true
        log_success "Nouvelle installation detectee"
        ;;
    existing)
        FIRST_INSTALL=false
        log_info "Installation existante detectee"
        echo "  .env:        $( [[ "$SIGNAL_ENV_EXISTS" == true ]] && echo "present" || echo "absent" )"
        echo "  Containers:  $( [[ "$SIGNAL_CONTAINERS" == true ]] && echo "trouves" || echo "aucun" )"
        echo "  Volumes:     $( [[ "$SIGNAL_VOLUMES" == true ]] && echo "trouves" || echo "aucun" )"
        echo "  Venv:        $( [[ "$SIGNAL_VENV" == true ]] && echo "present" || echo "absent" )"
        echo ""
        ;;
    partial)
        log_warn "Installation partielle detectee"
        echo "  .env:        $( [[ "$SIGNAL_ENV_EXISTS" == true ]] && echo "present" || echo "absent" )"
        echo "  Containers:  $( [[ "$SIGNAL_CONTAINERS" == true ]] && echo "trouves" || echo "aucun" )"
        echo "  Volumes:     $( [[ "$SIGNAL_VOLUMES" == true ]] && echo "trouves" || echo "aucun" )"
        echo "  Venv:        $( [[ "$SIGNAL_VENV" == true ]] && echo "present" || echo "absent" )"
        echo ""
        if confirm "Completer l'installation existante ?" "y"; then
            FIRST_INSTALL=false
        else
            FIRST_INSTALL=true
        fi
        ;;
esac

if [[ "$FIRST_INSTALL" == true ]]; then
    # Wizard premiere installation
    if [[ "$AUTO_MODE" != "true" ]]; then
        first_install_wizard
    else
        # Mode auto: valeurs par defaut
        if [[ -z "$DEPLOY_ENV" ]]; then
            DEPLOY_ENV="dev"
        fi
        set_template_var "PUBLIC_HOST" "$PUBLIC_HOST"
        set_template_var "PUBLIC_PROTOCOL" "$PUBLIC_PROTOCOL"
        if [[ "$DEPLOY_ENV" == "prod" ]]; then
            set_template_var "DEBUG" "false"
        else
            set_template_var "DEBUG" "true"
        fi
    fi

    # Generer le .env
    "$SCRIPT_DIR/generate-env.sh" --force
else
    # Mise a jour / installation existante
    if [[ "$AUTO_MODE" != "true" ]]; then
        handle_existing_installation
    else
        # Mode auto: regenerer le .env
        "$SCRIPT_DIR/generate-env.sh" --force
    fi
fi

# Charger les variables
set +e
source "$ENV_FILE"
set -e

# S'assurer que SANITIZED_PREFIX est defini
if [[ -z "${SANITIZED_PREFIX:-}" ]]; then
    SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)
    export SANITIZED_PREFIX
fi

# Determiner DEPLOY_ENV si non defini
if [[ -z "$DEPLOY_ENV" ]]; then
    if [[ "${DEBUG:-true}" == "false" ]]; then
        DEPLOY_ENV="prod"
    else
        DEPLOY_ENV="dev"
    fi
fi

# Mode native: adapter le .env
if [[ "$DEPLOY_MODE" == "native" ]]; then
    source "$SCRIPT_DIR/lib/baremetal.sh"
    init_baremetal_vars "$PROJECT_ROOT"
    generate_baremetal_env "$ENV_FILE"
    # Recharger apres adaptation
    set +e
    source "$ENV_FILE"
    set -e
fi

show_phase_recap 4 "Env: ${DEPLOY_ENV} | Host: ${PUBLIC_HOST:-localhost} | Install: $( [[ "$FIRST_INSTALL" == true ]] && echo "premiere" || echo "mise a jour" )"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5 - Installation et demarrage
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 5 "Installation et demarrage"

if [[ "$DEPLOY_MODE" == "docker" ]]; then
    docker_install
elif [[ "$DEPLOY_MODE" == "mixed" ]]; then
    mixed_install
else
    native_install
fi

show_phase_recap 5 "Installation ${DEPLOY_MODE} terminee"

# ─────────────────────────────────────────────────────────────────────────────
# MIGRATIONS (entre Phase 5 et Phase 6)
# ─────────────────────────────────────────────────────────────────────────────

run_migrations

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 6 - Verification de sante
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 6 "Verification de sante"

if ! run_health_checks; then
    handle_phase_error 6 "Certains services ne repondent pas" \
        "Verifiez les logs avec: $COMPOSE_CMD logs -f" || true
fi

show_phase_recap 6 "Health checks effectues"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 7 - Post-deploiement (donnees + config BDD)
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 7 "Post-deploiement"

handle_data
push_config_to_db

show_phase_recap 7 "Donnees et configuration en base traitees"

# ─────────────────────────────────────────────────────────────────────────────
# PHASE 8 - Recapitulatif final
# ─────────────────────────────────────────────────────────────────────────────

show_phase_header 8 "Recapitulatif final"

show_security_checklist
show_final_summary
