#!/bin/bash
# =============================================================================
# MY-IA - Detection d'environnement et verification des prerequis
# =============================================================================
# Ce fichier contient les fonctions pour detecter l'OS, l'architecture
# et verifier/installer les prerequis systeme.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/prereqs.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier (log_*, confirm())
#
# =============================================================================

# =============================================================================
# VARIABLES EXPORTEES
# =============================================================================

OS_TYPE=""        # macos, ubuntu, debian, rhel, centos, fedora, alpine
OS_FAMILY=""      # darwin, debian, rhel, alpine, unknown
OS_VERSION=""     # ex: "22.04", "12", "15.2"
PKG_MANAGER=""    # brew, apt, dnf, yum, apk
PKG_INSTALL=""    # "brew install", "sudo apt install -y", etc.
ARCH=""           # x86_64, arm64

# =============================================================================
# DETECTION DE L'OS
# =============================================================================
# Detecte le systeme d'exploitation et configure les variables associees.
#
# Usage:
#   detect_os
#
# Resultat:
#   Definit OS_TYPE, OS_FAMILY, OS_VERSION, PKG_MANAGER, PKG_INSTALL
# =============================================================================

detect_os() {
    log_debug "[detect_os] Detection du systeme d'exploitation..."

    case "$OSTYPE" in
        darwin*)
            OS_TYPE="macos"
            OS_FAMILY="darwin"
            OS_VERSION=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
            PKG_MANAGER="brew"
            PKG_INSTALL="brew install"
            ;;
        linux*)
            if [[ -f /etc/os-release ]]; then
                # shellcheck source=/dev/null
                source /etc/os-release
                local id_lower
                id_lower=$(echo "${ID:-unknown}" | tr '[:upper:]' '[:lower:]')

                case "$id_lower" in
                    ubuntu)
                        OS_TYPE="ubuntu"
                        OS_FAMILY="debian"
                        OS_VERSION="${VERSION_ID:-unknown}"
                        PKG_MANAGER="apt"
                        PKG_INSTALL="sudo apt install -y"
                        ;;
                    debian)
                        OS_TYPE="debian"
                        OS_FAMILY="debian"
                        OS_VERSION="${VERSION_ID:-unknown}"
                        PKG_MANAGER="apt"
                        PKG_INSTALL="sudo apt install -y"
                        ;;
                    rhel|rocky|almalinux)
                        OS_TYPE="${id_lower}"
                        OS_FAMILY="rhel"
                        OS_VERSION="${VERSION_ID:-unknown}"
                        PKG_MANAGER="dnf"
                        PKG_INSTALL="sudo dnf install -y"
                        ;;
                    centos)
                        OS_TYPE="centos"
                        OS_FAMILY="rhel"
                        OS_VERSION="${VERSION_ID:-unknown}"
                        if command -v dnf &> /dev/null; then
                            PKG_MANAGER="dnf"
                            PKG_INSTALL="sudo dnf install -y"
                        else
                            PKG_MANAGER="yum"
                            PKG_INSTALL="sudo yum install -y"
                        fi
                        ;;
                    fedora)
                        OS_TYPE="fedora"
                        OS_FAMILY="rhel"
                        OS_VERSION="${VERSION_ID:-unknown}"
                        PKG_MANAGER="dnf"
                        PKG_INSTALL="sudo dnf install -y"
                        ;;
                    alpine)
                        OS_TYPE="alpine"
                        OS_FAMILY="alpine"
                        OS_VERSION="${VERSION_ID:-unknown}"
                        PKG_MANAGER="apk"
                        PKG_INSTALL="sudo apk add"
                        ;;
                    *)
                        OS_TYPE="${id_lower}"
                        OS_FAMILY="unknown"
                        OS_VERSION="${VERSION_ID:-unknown}"
                        ;;
                esac
            else
                OS_TYPE="linux"
                OS_FAMILY="unknown"
                OS_VERSION="unknown"
            fi
            ;;
        *)
            OS_TYPE="unknown"
            OS_FAMILY="unknown"
            OS_VERSION="unknown"
            ;;
    esac

    export OS_TYPE OS_FAMILY OS_VERSION PKG_MANAGER PKG_INSTALL
    log_debug "[detect_os] OS_TYPE=$OS_TYPE OS_FAMILY=$OS_FAMILY OS_VERSION=$OS_VERSION"
    log_debug "[detect_os] PKG_MANAGER=$PKG_MANAGER"
}

# =============================================================================
# DETECTION DE L'ARCHITECTURE CPU
# =============================================================================
# Detecte l'architecture processeur.
#
# Usage:
#   detect_arch
#
# Resultat:
#   Definit la variable ARCH (x86_64 ou arm64)
# =============================================================================

detect_arch() {
    local raw_arch
    raw_arch=$(uname -m)

    case "$raw_arch" in
        x86_64|amd64)
            ARCH="x86_64"
            ;;
        arm64|aarch64)
            ARCH="arm64"
            ;;
        *)
            ARCH="$raw_arch"
            ;;
    esac

    export ARCH
    log_debug "[detect_arch] Architecture: $ARCH (raw: $raw_arch)"
}

# =============================================================================
# EXTRACTION DE VERSION D'UNE COMMANDE
# =============================================================================
# Extrait le numero de version d'une commande.
#
# Usage:
#   version=$(get_version "python3")
#   version=$(get_version "docker")
#
# Parametres:
#   $1 - Nom de la commande
#
# Retour:
#   Numero de version (ex: "3.10.12", "24.0.7") ou vide si echec
# =============================================================================

get_version() {
    local cmd="$1"

    if ! command -v "$cmd" &> /dev/null; then
        echo ""
        return 1
    fi

    local version_output
    version_output=$("$cmd" --version 2>&1 || true)

    # Extraire le premier pattern semver trouve
    echo "$version_output" | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1
}

# =============================================================================
# COMPARAISON DE VERSIONS SEMVER
# =============================================================================
# Compare deux versions semver. Retourne 0 si v1 >= v2.
#
# Usage:
#   if version_gte "3.10.4" "3.10.0"; then
#       echo "Version suffisante"
#   fi
#
# Parametres:
#   $1 - Version a tester
#   $2 - Version minimale requise
#
# Retour:
#   0 si v1 >= v2, 1 sinon
# =============================================================================

version_gte() {
    local v1="$1"
    local v2="$2"

    # Decouper en composants
    local IFS='.'
    read -ra v1_parts <<< "$v1"
    read -ra v2_parts <<< "$v2"

    # Comparer chaque composant
    local max_len=${#v1_parts[@]}
    if [[ ${#v2_parts[@]} -gt $max_len ]]; then
        max_len=${#v2_parts[@]}
    fi

    for ((i=0; i<max_len; i++)); do
        local p1="${v1_parts[$i]:-0}"
        local p2="${v2_parts[$i]:-0}"

        if [[ "$p1" -gt "$p2" ]]; then
            return 0
        elif [[ "$p1" -lt "$p2" ]]; then
            return 1
        fi
    done

    # Versions egales
    return 0
}

# =============================================================================
# VERIFICATION D'UN PREREQUIS
# =============================================================================
# Verifie qu'un outil est installe avec la version minimale requise.
# Propose l'installation si manquant (mode interactif ou auto).
#
# Usage:
#   check_prereq "docker" "20.0" "docker.io" "https://get.docker.com"
#   check_prereq "python3" "3.10" "python3" ""
#
# Parametres:
#   $1 - Nom de la commande
#   $2 - Version minimale (ex: "20.0", "3.10")
#   $3 - Nom du paquet pour le gestionnaire de paquets
#   $4 - Hint d'installation alternatif (optionnel)
#
# Retour:
#   0 si OK, 1 si manquant et non installe
# =============================================================================

check_prereq() {
    local cmd="$1"
    local min_version="$2"
    local pkg_name="$3"
    local install_hint="$4"

    if command -v "$cmd" &> /dev/null; then
        local current_version
        current_version=$(get_version "$cmd")

        if [[ -n "$current_version" && -n "$min_version" ]]; then
            if version_gte "$current_version" "$min_version"; then
                log_success "$cmd $current_version (>= $min_version)"
                return 0
            else
                log_warn "$cmd $current_version (< $min_version requis)"
            fi
        else
            # Pas de version verifiable, mais la commande existe
            log_success "$cmd installe"
            return 0
        fi
    else
        log_warn "$cmd non trouve"
    fi

    # Proposer l'installation
    if [[ -n "$PKG_INSTALL" && -n "$pkg_name" ]]; then
        if [[ "${AUTO_MODE:-false}" == "true" ]]; then
            log_info "Installation automatique de $pkg_name..."
            if $PKG_INSTALL "$pkg_name"; then
                log_success "$pkg_name installe"
                return 0
            else
                log_error "Echec de l'installation de $pkg_name"
                return 1
            fi
        else
            if confirm "Installer $cmd ($pkg_name) ?" "y"; then
                log_info "Installation de $pkg_name..."
                if $PKG_INSTALL "$pkg_name"; then
                    log_success "$pkg_name installe"
                    return 0
                else
                    log_error "Echec de l'installation de $pkg_name"
                    return 1
                fi
            fi
        fi
    fi

    # Afficher l'hint d'installation si disponible
    if [[ -n "$install_hint" ]]; then
        echo "  Installation: $install_hint"
    fi

    return 1
}

# =============================================================================
# VERIFICATION DES PREREQUIS COMMUNS
# =============================================================================
# Verifie les outils de base requis pour tout mode de deploiement.
#
# Usage:
#   check_common_prereqs
#
# Retour:
#   0 si tous presents, 1 sinon
# =============================================================================

check_common_prereqs() {
    log_step "Verification des prerequis communs..."

    local errors=0

    # Homebrew (requis sur macOS pour installer les dependances)
    if [[ "$OS_FAMILY" == "darwin" ]]; then
        if command -v brew &> /dev/null; then
            log_success "Homebrew $(brew --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')"
        else
            log_warn "Homebrew non trouve (requis sur macOS)"
            local install_brew=false
            if [[ "${AUTO_MODE:-false}" == "true" ]]; then
                install_brew=true
            else
                if confirm "Installer Homebrew (gestionnaire de paquets macOS) ?" "y"; then
                    install_brew=true
                fi
            fi

            if [[ "$install_brew" == "true" ]]; then
                log_info "Installation de Homebrew..."
                if /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; then
                    # Configurer le PATH selon l'architecture
                    if [[ -f /opt/homebrew/bin/brew ]]; then
                        # Apple Silicon (M1/M2/M3)
                        eval "$(/opt/homebrew/bin/brew shellenv)"
                    elif [[ -f /usr/local/bin/brew ]]; then
                        # Intel Mac
                        eval "$(/usr/local/bin/brew shellenv)"
                    fi
                    log_success "Homebrew installe"
                else
                    log_error "Echec de l'installation de Homebrew"
                    errors=$((errors + 1))
                fi
            else
                log_warn "Homebrew non installe — les installations via brew seront indisponibles"
                PKG_INSTALL=""
                PKG_MANAGER=""
                errors=$((errors + 1))
            fi
        fi
    fi

    # Bash 4+ (requis pour les tableaux associatifs)
    local bash_version
    bash_version="${BASH_VERSION%%(*}"
    bash_version="${bash_version%%.*}"
    if [[ "$bash_version" -ge 4 ]]; then
        log_success "Bash ${BASH_VERSION} (>= 4)"
    else
        log_warn "Bash ${BASH_VERSION} (< 4 requis)"
        if [[ "$OS_FAMILY" == "darwin" ]]; then
            echo "  Installation: brew install bash"
        fi
        errors=$((errors + 1))
    fi

    # curl
    if ! check_prereq "curl" "" "curl" ""; then
        errors=$((errors + 1))
    fi

    # openssl
    if ! check_prereq "openssl" "" "openssl" ""; then
        errors=$((errors + 1))
    fi

    # git
    if ! check_prereq "git" "" "git" ""; then
        errors=$((errors + 1))
    fi

    if [[ $errors -gt 0 ]]; then
        return 1
    fi

    return 0
}

# =============================================================================
# VERIFICATION DES PREREQUIS DOCKER
# =============================================================================
# Verifie Docker, Docker Compose et le daemon.
#
# Usage:
#   check_docker_prereqs
#
# Retour:
#   0 si tous presents, 1 sinon
#   Definit COMPOSE_CMD (export)
# =============================================================================

check_docker_prereqs() {
    log_step "Verification des prerequis Docker..."

    local errors=0

    # Docker
    if ! command -v docker &> /dev/null; then
        log_error "Docker n'est pas installe"
        case "$OS_FAMILY" in
            darwin)
                echo "  Installation: brew install --cask docker"
                ;;
            debian)
                echo "  Installation: curl -fsSL https://get.docker.com | sh"
                ;;
            rhel)
                echo "  Installation: sudo dnf install docker-ce"
                ;;
            *)
                echo "  Installation: https://docs.docker.com/engine/install/"
                ;;
        esac
        errors=$((errors + 1))
    else
        local docker_version
        docker_version=$(get_version "docker")
        if [[ -n "$docker_version" ]] && version_gte "$docker_version" "20.0"; then
            log_success "Docker $docker_version (>= 20.0)"
        else
            log_warn "Docker $docker_version (>= 20.0 recommande)"
        fi
    fi

    # Docker Compose
    if docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
        local compose_version
        compose_version=$(docker compose version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
        log_success "Docker Compose v2 ($compose_version)"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
        local compose_version
        compose_version=$(docker-compose --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+' | head -1)
        log_success "Docker Compose standalone ($compose_version)"
    else
        log_error "Docker Compose n'est pas installe"
        case "$OS_FAMILY" in
            debian)
                echo "  Installation: sudo apt install docker-compose-plugin"
                ;;
            *)
                echo "  Installation: https://docs.docker.com/compose/install/"
                ;;
        esac
        errors=$((errors + 1))
    fi

    export COMPOSE_CMD

    # Docker daemon actif
    if command -v docker &> /dev/null; then
        if ! docker info &> /dev/null; then
            log_error "Le daemon Docker n'est pas demarre"
            case "$OS_FAMILY" in
                darwin)
                    echo "  Demarrage: Ouvrez Docker Desktop"
                    ;;
                *)
                    echo "  Demarrage: sudo systemctl start docker"
                    ;;
            esac
            errors=$((errors + 1))
        else
            log_success "Docker daemon actif"
        fi
    fi

    if [[ $errors -gt 0 ]]; then
        return 1
    fi

    return 0
}

# =============================================================================
# VERIFICATION DES PREREQUIS BARE-METAL
# =============================================================================
# Verifie les outils requis pour une installation native.
#
# Usage:
#   check_baremetal_prereqs
#
# Retour:
#   0 si tous presents (ou installables), 1 sinon
# =============================================================================

check_baremetal_prereqs() {
    log_step "Verification des prerequis bare-metal..."

    local errors=0

    # Python 3.10+
    local python_cmd="python3"
    if ! command -v python3 &> /dev/null; then
        log_warn "python3 non trouve"
        echo "  → Backend API FastAPI de l'application"
        case "$OS_FAMILY" in
            darwin) echo "  Installation: brew install python@3.12" ;;
            debian) echo "  Installation: sudo apt install python3 python3-venv python3-pip" ;;
            rhel)   echo "  Installation: sudo dnf install python3.12" ;;
        esac
        errors=$((errors + 1))
    else
        local py_version
        py_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        if version_gte "$py_version" "3.10"; then
            log_success "Python $py_version (>= 3.10)"
            echo "  → Backend API FastAPI de l'application"
        else
            log_warn "Python $py_version (>= 3.10 requis)"
            echo "  → Backend API FastAPI de l'application"
            errors=$((errors + 1))
        fi
    fi

    # pip
    if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
        log_warn "pip3 non trouve"
        echo "  → Gestionnaire de paquets Python (dependances backend)"
        case "$OS_FAMILY" in
            debian) echo "  Installation: sudo apt install python3-pip" ;;
            rhel)   echo "  Installation: sudo dnf install python3-pip" ;;
        esac
        errors=$((errors + 1))
    else
        log_success "pip3 installe"
        echo "  → Gestionnaire de paquets Python (dependances backend)"
    fi

    # PostgreSQL 15+
    if ! command -v psql &> /dev/null; then
        log_warn "PostgreSQL (psql) non trouve"
        echo "  → Base de donnees : utilisateurs, sessions, conversations, audit"
        case "$OS_FAMILY" in
            darwin) echo "  Installation: brew install postgresql@15" ;;
            debian) echo "  Installation: sudo apt install postgresql postgresql-contrib" ;;
            rhel)   echo "  Installation: sudo dnf install postgresql-server" ;;
        esac
        errors=$((errors + 1))
    else
        local pg_version
        pg_version=$(psql --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        if version_gte "$pg_version" "15.0"; then
            log_success "PostgreSQL $pg_version (>= 15.0)"
            echo "  → Base de donnees : utilisateurs, sessions, conversations, audit"
        else
            log_warn "PostgreSQL $pg_version (>= 15.0 recommande)"
            echo "  → Base de donnees : utilisateurs, sessions, conversations, audit"
        fi
    fi

    # Ollama
    if ! command -v ollama &> /dev/null; then
        log_warn "Ollama non trouve"
        echo "  → Moteur IA local : modeles LLM et embeddings pour le RAG"
        echo "  Installation: curl -fsSL https://ollama.com/install.sh | sh"
        errors=$((errors + 1))
    else
        local ollama_version
        ollama_version=$(get_version "ollama")
        log_success "Ollama ${ollama_version:-installe}"
        echo "  → Moteur IA local : modeles LLM et embeddings pour le RAG"
    fi

    # nginx
    if ! command -v nginx &> /dev/null; then
        log_warn "nginx non trouve (optionnel, recommande en production)"
        echo "  → Reverse proxy : routage HTTP/HTTPS vers l'API et les interfaces"
        case "$OS_FAMILY" in
            darwin) echo "  Installation: brew install nginx" ;;
            debian) echo "  Installation: sudo apt install nginx" ;;
            rhel)   echo "  Installation: sudo dnf install nginx" ;;
        esac
        # nginx n'est pas bloquant (optionnel pour dev)
    else
        local nginx_version
        nginx_version=$(get_version "nginx")
        log_success "nginx ${nginx_version:-installe}"
        echo "  → Reverse proxy : routage HTTP/HTTPS vers l'API et les interfaces"
    fi

    if [[ $errors -gt 0 ]]; then
        return 1
    fi

    return 0
}

# =============================================================================
# AFFICHAGE DU RESUME D'ENVIRONNEMENT
# =============================================================================
# Affiche un resume formate de l'environnement detecte.
#
# Usage:
#   show_environment_summary
#
# Prerequis:
#   detect_os et detect_arch doivent avoir ete appeles
# =============================================================================

# =============================================================================
# VERIFICATION DES PREREQUIS MODE MIXTE
# =============================================================================
# Combine les prerequis Docker ET les prerequis natifs des services choisis.
# Lit les variables *_MODE pour savoir quels services sont en natif.
#
# Usage:
#   check_mixed_prereqs
#
# Retour:
#   0 si tous presents, 1 sinon
# =============================================================================

check_mixed_prereqs() {
    local errors=0

    # Docker est toujours requis en mode mixte (au moins certains services)
    log_step "Verification des prerequis Docker (mode mixte)..."
    if ! check_docker_prereqs; then
        errors=$((errors + 1))
    fi

    # Verifier les prerequis des services natifs choisis
    local has_native=false
    [[ "${POSTGRES_MODE:-docker}" == "native" ]] && has_native=true
    [[ "${CHROMA_MODE:-docker}" == "native" ]] && has_native=true
    [[ "${OLLAMA_MODE:-docker}" == "native" ]] && has_native=true
    [[ "${APP_MODE:-docker}" == "native" ]] && has_native=true

    if [[ "$has_native" == "true" ]]; then
        echo ""
        log_step "Verification des prerequis natifs (services choisis)..."

        # PostgreSQL natif
        if [[ "${POSTGRES_MODE:-docker}" == "native" ]]; then
            if ! command -v psql &> /dev/null; then
                log_warn "PostgreSQL (psql) non trouve"
                echo "  → Base de donnees : utilisateurs, sessions, conversations, audit"
                case "$OS_FAMILY" in
                    darwin) echo "  Installation: brew install postgresql@15" ;;
                    debian) echo "  Installation: sudo apt install postgresql postgresql-contrib" ;;
                    rhel)   echo "  Installation: sudo dnf install postgresql-server" ;;
                esac
                errors=$((errors + 1))
            else
                local pg_version
                pg_version=$(psql --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
                log_success "PostgreSQL $pg_version"
                echo "  → Base de donnees : utilisateurs, sessions, conversations, audit"
            fi
        fi

        # Ollama natif
        if [[ "${OLLAMA_MODE:-docker}" == "native" ]]; then
            if ! command -v ollama &> /dev/null; then
                log_warn "Ollama non trouve"
                echo "  → Moteur IA local : modeles LLM et embeddings pour le RAG"
                echo "  Installation: curl -fsSL https://ollama.com/install.sh | sh"
                errors=$((errors + 1))
            else
                local ollama_version
                ollama_version=$(get_version "ollama")
                log_success "Ollama ${ollama_version:-installe}"
                echo "  → Moteur IA local : modeles LLM et embeddings pour le RAG"
            fi
        fi

        # ChromaDB natif
        if [[ "${CHROMA_MODE:-docker}" == "native" ]]; then
            if ! command -v pip3 &> /dev/null && ! python3 -m pip --version &> /dev/null; then
                log_warn "pip3 non trouve (requis pour ChromaDB)"
                echo "  → Gestionnaire de paquets Python (dependances backend)"
                errors=$((errors + 1))
            else
                log_success "pip3 installe (pour ChromaDB)"
            fi
        fi

        # App native (Python + venv)
        if [[ "${APP_MODE:-docker}" == "native" ]]; then
            if ! command -v python3 &> /dev/null; then
                log_warn "python3 non trouve"
                echo "  → Backend API FastAPI de l'application"
                errors=$((errors + 1))
            else
                local py_version
                py_version=$(python3 --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
                if version_gte "$py_version" "3.10"; then
                    log_success "Python $py_version (>= 3.10)"
                    echo "  → Backend API FastAPI de l'application"
                else
                    log_warn "Python $py_version (>= 3.10 requis)"
                    echo "  → Backend API FastAPI de l'application"
                    errors=$((errors + 1))
                fi
            fi
        fi
    fi

    if [[ $errors -gt 0 ]]; then
        return 1
    fi
    return 0
}

# =============================================================================
# RECAPITULATIF DES PREREQUIS
# =============================================================================
# Affiche un resume des prerequis verifies.
#
# Usage:
#   show_prereqs_summary
# =============================================================================

show_prereqs_summary() {
    echo ""
    echo "  -------------------------------------------"
    echo "  Verification des prerequis terminee"
    echo "  Mode: ${DEPLOY_MODE:-inconnu}"
    if [[ "${DEPLOY_MODE:-}" == "mixed" ]]; then
        local native_list=""
        [[ "${POSTGRES_MODE:-docker}" == "native" ]] && native_list+="PostgreSQL "
        [[ "${CHROMA_MODE:-docker}" == "native" ]] && native_list+="ChromaDB "
        [[ "${OLLAMA_MODE:-docker}" == "native" ]] && native_list+="Ollama "
        [[ "${APP_MODE:-docker}" == "native" ]] && native_list+="App "
        [[ "${UI_MODE:-docker}" == "native" ]] && native_list+="UI "
        if [[ -n "$native_list" ]]; then
            echo "  Services natifs: $native_list"
        fi
    fi
    echo "  -------------------------------------------"
    echo ""
}

# =============================================================================
# AFFICHAGE DU RESUME D'ENVIRONNEMENT
# =============================================================================

show_environment_summary() {
    echo ""
    echo "============================================================================="
    echo "  ENVIRONNEMENT DETECTE"
    echo "============================================================================="
    echo ""
    echo "  Systeme:        ${OS_TYPE} ${OS_VERSION} (${OS_FAMILY})"
    echo "  Architecture:   ${ARCH}"

    if [[ -n "$PKG_MANAGER" ]]; then
        echo "  Gestionnaire:   ${PKG_MANAGER}"
    fi

    if [[ -n "${DEPLOY_MODE:-}" ]]; then
        echo "  Mode:           ${DEPLOY_MODE}"
    fi

    if [[ -n "${DEPLOY_ENV:-}" ]]; then
        echo "  Environnement:  ${DEPLOY_ENV}"
    fi

    echo ""
    echo "============================================================================="
    echo ""
}
