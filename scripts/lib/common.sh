#!/bin/bash
# =============================================================================
# MY-IA - Fonctions partagees
# =============================================================================
# Ce fichier contient les fonctions utilitaires partagees entre tous les
# scripts de l'application.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#
# =============================================================================

# =============================================================================
# COULEURS ET FORMATAGE
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Code de la touche Escape
ESC_KEY=$'\033'

# =============================================================================
# GESTION DES SORTIES PROPRES
# =============================================================================
# Permet de quitter proprement le script avec Escape ou Ctrl+C.
#
# Usage:
#   setup_exit_handler  # A appeler au debut du script principal
# =============================================================================

# Variable globale pour savoir si on a demande une sortie
EXIT_REQUESTED=false

# Fonction de nettoyage a la sortie
cleanup_on_exit() {
    local exit_code="${1:-0}"

    # Restaurer le terminal
    stty echo 2>/dev/null || true

    echo ""
    if [[ "$EXIT_REQUESTED" == "true" ]]; then
        echo -e "${YELLOW}[EXIT]${NC} Sortie demandee par l'utilisateur"
    fi
    echo -e "${BLUE}[INFO]${NC} Nettoyage en cours..."

    # Ajouter ici d'autres actions de nettoyage si necessaire

    echo -e "${GREEN}[OK]${NC} Script termine proprement"
    exit "$exit_code"
}

# Gestionnaire de signal pour Ctrl+C (SIGINT)
handle_sigint() {
    EXIT_REQUESTED=true
    cleanup_on_exit 130
}

# Configuration des gestionnaires de sortie
setup_exit_handler() {
    # Capturer Ctrl+C
    trap handle_sigint SIGINT

    # Capturer SIGTERM
    trap 'EXIT_REQUESTED=true; cleanup_on_exit 143' SIGTERM
}

# Fonction pour demander une sortie propre (appelee lors de la detection de Escape)
request_exit() {
    EXIT_REQUESTED=true
    cleanup_on_exit 0
}

# =============================================================================
# MODE DEBUG GLOBAL
# =============================================================================
# Variable globale pour activer le mode debug detaille.
# Peut etre definie via l'option -d ou --debug du script.
#
# Usage:
#   DEBUG_MODE=true ./scripts/generate-env.sh
#   ./scripts/generate-env.sh --debug
# =============================================================================

DEBUG_MODE=${DEBUG_MODE:-false}

# =============================================================================
# MODE DRY-RUN
# =============================================================================
# Permet de simuler les operations destructives sans les executer.
#
# Usage:
#   DRY_RUN=true ./scripts/stop.sh
#   DRY_RUN=true ./scripts/restore.sh backups/file.sql.gz --yes
#
# Les fonctions qui utilisent execute() afficheront les commandes
# sans les executer en mode dry-run.
# =============================================================================

DRY_RUN=${DRY_RUN:-false}

# Wrapper pour commandes destructives
# En mode dry-run, affiche la commande au lieu de l'executer.
#
# Usage:
#   execute docker stop "$container"
#   execute docker volume rm "$vol"
#   execute $COMPOSE_CMD down --volumes
execute() {
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] $*"
        return 0
    else
        "$@"
    fi
}

# LOG_PREFIX automatique : nom du script appelant en majuscules
# Les scripts peuvent le redefinir apres le source de common.sh
# Ex: start.sh → "START", backup.sh → "BACKUP"
_calling_script="${BASH_SOURCE[${#BASH_SOURCE[@]}-1]}"
LOG_PREFIX="${LOG_PREFIX:-$(basename "$_calling_script" .sh | tr '[:lower:]' '[:upper:]')}"
unset _calling_script

# =============================================================================
# FONCTIONS DE LOG
# =============================================================================

log_info() {
    local prefix="${LOG_PREFIX:-INFO}"
    echo -e "${BLUE}[${prefix}]${NC} $1"
}

# Log debug - affiche uniquement si DEBUG_MODE=true
# Utilise une couleur attenuee pour distinguer des logs normaux
log_debug() {
    if [[ "$DEBUG_MODE" == "true" ]]; then
        echo -e "${DIM}[DEBUG]${NC} $1"
    fi
}

log_success() {
    local prefix="${LOG_PREFIX:-OK}"
    echo -e "${GREEN}[${prefix}]${NC} $1"
}

log_warn() {
    local prefix="${LOG_PREFIX:-WARN}"
    echo -e "${YELLOW}[${prefix}]${NC} $1"
}

log_error() {
    local prefix="${LOG_PREFIX:-ERROR}"
    echo -e "${RED}[${prefix}]${NC} $1"
}

log_step() {
    echo -e "${CYAN}==>${NC} ${BOLD}$1${NC}"
}

# =============================================================================
# HELPERS D'ERREUR
# =============================================================================
# die()  - Log erreur + exit (pour les erreurs fatales)
# fail() - Log erreur + return 1 (pour les erreurs dans les fonctions)
#
# Usage:
#   die "Configuration invalide"       # exit 1
#   die "Port occupe" 2                # exit 2
#   fail "Fichier non trouve"          # return 1
# =============================================================================

die() {
    log_error "$1"
    exit "${2:-1}"
}

fail() {
    log_error "$1"
    return "${2:-1}"
}

# =============================================================================
# WRAPPER DOCKER EXEC
# =============================================================================
# Execute une commande dans un container Docker avec gestion d'erreur.
#
# Usage:
#   docker_exec "container_name" python -c "print('ok')"
#   result=$(docker_exec "container_name" cat /etc/hostname)
#
# Parametres:
#   $1 - Nom du container
#   $@ - Commande a executer
#
# Retour:
#   stdout de la commande, ou return 1 si erreur
# =============================================================================

docker_exec() {
    local container="$1"
    shift

    if ! docker exec "$container" "$@" 2>/dev/null; then
        log_debug "docker exec $container $1 echoue"
        return 1
    fi
}

# =============================================================================
# WRAPPERS HTTP
# =============================================================================
# Fonctions utilitaires pour les appels HTTP via curl.
#
# Usage:
#   response=$(http_get "http://localhost:8080/health")
#   response=$(http_get "http://localhost:8080/api" 5)
#   response=$(http_post_json "http://url" '{"key":"val"}' "$token")
# =============================================================================

http_get() {
    local url="$1"
    local timeout="${2:-10}"
    curl -sf --max-time "$timeout" "$url"
}

http_post_json() {
    local url="$1"
    local data="$2"
    local token="${3:-}"

    local -a headers=(-H "Content-Type: application/json")
    if [[ -n "$token" ]]; then
        headers+=(-H "Authorization: Bearer $token")
    fi

    curl -sf "${headers[@]}" -d "$data" "$url"
}

# =============================================================================
# ATTENTE DE SERVICE
# =============================================================================
# Attend qu'un service HTTP soit pret (polling avec timeout).
#
# Usage:
#   wait_for_service "PostgreSQL" "http://localhost:5432" 30
#   wait_for_service "API" "http://localhost:8080/health"
#
# Parametres:
#   $1 - Nom du service (pour les logs)
#   $2 - URL de health check
#   $3 - Timeout en secondes (defaut: 30)
#
# Retour:
#   0 si pret, 1 si timeout
# =============================================================================

wait_for_service() {
    local name="$1"
    local url="$2"
    local timeout="${3:-30}"
    local elapsed=0

    log_info "Attente de ${name}..."

    while ! curl -sf "$url" > /dev/null 2>&1; do
        sleep 2
        elapsed=$((elapsed + 2))
        if [[ $elapsed -ge $timeout ]]; then
            log_warn "${name} non disponible apres ${timeout}s"
            return 1
        fi
    done

    log_success "${name} pret"
    return 0
}

# =============================================================================
# DETECTION DOCKER COMPOSE
# =============================================================================
# Detecte la commande Docker Compose disponible (v2 plugin ou standalone).
# Definit la variable globale COMPOSE_CMD.
#
# Usage:
#   detect_compose_cmd || die "Docker Compose non installe"
#   $COMPOSE_CMD up -d
# =============================================================================

detect_compose_cmd() {
    # Si deja detecte, ne pas refaire
    if [[ -n "${COMPOSE_CMD:-}" ]]; then
        return 0
    fi

    if docker compose version &> /dev/null; then
        COMPOSE_CMD="docker compose"
    elif command -v docker-compose &> /dev/null; then
        COMPOSE_CMD="docker-compose"
    else
        return 1
    fi

    export COMPOSE_CMD
}

# =============================================================================
# FICHIERS DOCKER COMPOSE PAR ENVIRONNEMENT
# =============================================================================
# Retourne les flags -f pour docker compose selon DEPLOY_ENV.
# Charge le fichier de base + l'override correspondant a l'environnement.
#
# Usage:
#   $COMPOSE_CMD $(get_compose_files) up -d
#   $COMPOSE_CMD $(get_compose_files) down
#
# Fichiers charges:
#   - docker-compose.yml              (toujours)
#   - docker-compose.{DEPLOY_ENV}.yml (si existe)
#   - docker-compose.override.yml     (si existe, pour surcharges locales)
# =============================================================================

get_compose_files() {
    local env="${DEPLOY_ENV:-dev}"
    local files="-f docker-compose.yml"

    # Override par environnement (dev, staging, prod)
    local override="docker-compose.${env}.yml"
    if [[ -f "$PROJECT_ROOT/$override" ]]; then
        files="$files -f $override"
        log_debug "Compose override: $override"
    fi

    # Override local (non versionne, pour surcharges personnelles)
    if [[ -f "$PROJECT_ROOT/docker-compose.override.yml" ]]; then
        files="$files -f docker-compose.override.yml"
        log_debug "Compose override local: docker-compose.override.yml"
    fi

    echo "$files"
}

# =============================================================================
# FONCTION DE SANITIZATION
# =============================================================================
# Sanitize une chaine selon les regles PostgreSQL ou la retourne inchangee.
#
# Usage:
#   sanitize "Ma Chaine" false   # Identifiants PostgreSQL → "ma_chaine"
#   sanitize "P@ss-word!" true   # Mots de passe → "P@ss-word!" (inchange)
#
# Parametres:
#   $1 : Chaine a sanitizer
#   $2 : Autoriser caracteres speciaux (true/false, defaut: false)
#
# Regles appliquees si $2=false (identifiants PostgreSQL):
#   1. Tirets (-) → Underscores (_)
#   2. Espaces → Underscores (_)
#   3. Majuscules → Minuscules
#   4. Supprime tout sauf : a-z, 0-9, _
#   5. Verifie que le resultat ne commence pas par un chiffre
#
# Regles si $2=true (mots de passe, valeurs):
#   - Retourne la chaine inchangee
#
# Voir CLAUDE.md section "Regles de Nommage PostgreSQL" pour plus de details.
# =============================================================================

sanitize() {
    local input="$1"
    local allow_special="${2:-false}"

    if [[ "$allow_special" == "true" ]]; then
        # Mots de passe / valeurs : retourner tel quel
        echo "$input"
    else
        # Identifiants PostgreSQL : appliquer les regles de nommage
        local result
        result=$(echo "$input" \
            | tr '-' '_' \
            | tr ' ' '_' \
            | tr '[:upper:]' '[:lower:]' \
            | tr -cd '[:alnum:]_')

        # Verifier que le resultat ne commence pas par un chiffre
        if [[ "$result" =~ ^[0-9] ]]; then
            # Prefixer avec underscore si commence par un chiffre
            result="_${result}"
        fi

        # Verifier que le resultat n'est pas vide
        if [[ -z "$result" ]]; then
            result="default"
        fi

        echo "$result"
    fi
}

# =============================================================================
# FONCTION DE GENERATION DE CLE
# =============================================================================
# Genere une cle hexadecimale aleatoire.
#
# Usage:
#   generate_key 32   # Genere 64 caracteres hex (256 bits)
#   generate_key 16   # Genere 32 caracteres hex (128 bits)
#
# Parametre:
#   $1 : Nombre d'octets (sera double en hex)
# =============================================================================

generate_key() {
    local bytes="${1:-32}"
    openssl rand -hex "$bytes"
}

# =============================================================================
# FONCTION DE LECTURE VARIABLE DEPUIS FICHIER
# =============================================================================
# Lit la valeur d'une variable depuis un fichier .env ou template.
#
# Usage:
#   value=$(read_env_var "APP_NAME_PREFIX" "..env.example")
#
# Parametres:
#   $1 : Nom de la variable
#   $2 : Chemin du fichier (defaut: ..env.example)
# =============================================================================

read_env_var() {
    local var_name="$1"
    local file="${2:-..env.example}"

    if [[ ! -f "$file" ]]; then
        echo ""
        return 1
    fi

    grep "^${var_name}=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'"
}

# =============================================================================
# FONCTION DE CORRECTION JSON ARRAY
# =============================================================================
# Corrige le format d'un JSON array (ex: [*] -> ["*"])
# Utilise pour CORS_ORIGINS et autres valeurs JSON.
#
# Usage:
#   value=$(fix_json_array "[*]")  # Retourne ["*"]
#   value=$(fix_json_array '["http://localhost"]')  # Inchange
#
# Parametres:
#   $1 : Valeur a corriger
# =============================================================================

fix_json_array() {
    local value="$1"

    # Si vide, retourner valeur par defaut
    if [[ -z "$value" ]]; then
        echo '["*"]'
        return
    fi

    # Nettoyer les backslashes echappes (\" -> ")
    value=$(echo "$value" | sed 's/\\"/"/g')

    # Si c'est deja un JSON array valide avec guillemets ["..."], retourner tel quel
    # Pattern: commence par [" et finit par "]
    if echo "$value" | grep -qE '^\[".*"\]$'; then
        echo "$value"
        return
    fi

    # Si c'est [*] sans guillemets, corriger en ["*"]
    if [[ "$value" == "[*]" ]]; then
        echo '["*"]'
        return
    fi

    # Si c'est une liste entre crochets sans guillemets [a,b,c]
    # Utiliser sed pour ajouter les guillemets (compatible POSIX)
    if echo "$value" | grep -qE '^\[.+\]$'; then
        # Extraire contenu, ajouter guillemets autour de chaque element
        local content
        content=$(echo "$value" | sed 's/^\[//; s/\]$//')
        # Remplacer les virgules par ","," et wrapper
        local result
        result=$(echo "$content" | sed 's/,/","/g')
        echo "[\"$result\"]"
        return
    fi

    # Sinon, wrapper dans un array
    echo "[\"$value\"]"
}

# =============================================================================
# FONCTION DE VERIFICATION PREREQUIS
# =============================================================================
# Verifie que les outils requis sont installes.
#
# Usage:
#   check_prerequisites docker openssl
# =============================================================================

check_prerequisites() {
    local missing=()

    for cmd in "$@"; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Outils manquants: ${missing[*]}"
        return 1
    fi

    return 0
}

# =============================================================================
# FONCTION DE CONFIRMATION
# =============================================================================
# Demande confirmation a l'utilisateur.
# Supporte la touche Escape pour quitter proprement.
#
# Usage:
#   if confirm "Voulez-vous continuer?"; then
#       echo "Oui"
#   fi
#
# Touches speciales:
#   - Escape/q/Q : Quitte le script proprement
#   - Ctrl+C     : Quitte le script proprement
#   - y/Y        : Retourne vrai
#   - n/N        : Retourne faux
#   - Entree     : Utilise la valeur par defaut
# =============================================================================

confirm() {
    local message="$1"
    local default="${2:-n}"

    local prompt
    if [[ "$default" == "y" ]]; then
        prompt="[Y/n/q]"
    else
        prompt="[y/N/q]"
    fi

    local response

    # Methode simple et robuste avec read -p
    # Utiliser /dev/tty si disponible, sinon stdin standard
    if [[ -e /dev/tty ]]; then
        read -p "$message $prompt " response < /dev/tty || response="$default"
    else
        read -p "$message $prompt " response || response="$default"
    fi

    # Verifier si c'est une demande de sortie (q, Q, ou vide avec Escape)
    if [[ "$response" == "q" ]] || [[ "$response" == "Q" ]] || [[ "$response" == $'\033' ]]; then
        request_exit
        return 1
    fi

    # Valeur par defaut si vide
    if [[ -z "$response" ]]; then
        response="$default"
    fi

    [[ "$response" =~ ^[Yy]$ ]]
}

# =============================================================================
# FONCTION DE LECTURE AVEC SUPPORT QUIT
# =============================================================================
# Lit une entree utilisateur avec support de la sortie (q/Q).
#
# Usage:
#   value=$(read_with_escape "Entrez une valeur" "default")
#
# Parametres:
#   $1 - Message/prompt
#   $2 - Valeur par defaut (optionnel)
#
# Retour:
#   La valeur entree ou la valeur par defaut
#   Quitte le script si q/Q est entre
# =============================================================================

read_with_escape() {
    local message="$1"
    local default="$2"
    local display_default=""

    if [[ -n "$default" ]]; then
        display_default=" [$default]"
    fi

    local result
    # Utiliser /dev/tty si disponible, sinon stdin standard
    if [[ -e /dev/tty ]]; then
        read -p "${message}${display_default}: " result < /dev/tty || result=""
    else
        read -p "${message}${display_default}: " result || result=""
    fi

    # Verifier si c'est une demande de sortie
    if [[ "$result" == "q" ]] || [[ "$result" == "Q" ]]; then
        request_exit
        return 1
    fi

    # Retourner la valeur ou le defaut
    if [[ -z "$result" ]]; then
        echo "$default"
    else
        echo "$result"
    fi
}

# =============================================================================
# FONCTION DE VERIFICATION DE PORT
# =============================================================================
# Verifie si un port TCP est disponible.
#
# Usage:
#   if check_port 8080; then
#       echo "Port disponible"
#   else
#       echo "Port occupe"
#   fi
#
# Retour:
#   0 si disponible, 1 si occupe
# =============================================================================

check_port() {
    local port="$1"

    # Methode 1: lsof (plus fiable)
    if lsof -i TCP:"$port" -sTCP:LISTEN > /dev/null 2>&1; then
        return 1
    fi

    # Methode 2: netcat (fallback)
    if nc -z localhost "$port" 2>/dev/null; then
        return 1
    fi

    return 0
}

# =============================================================================
# FONCTION D'IDENTIFICATION DE PROCESSUS SUR UN PORT
# =============================================================================
# Retourne les informations sur le processus utilisant un port.
#
# Usage:
#   get_port_process 8080
#   # Affiche: "docker (PID: 1234)"
# =============================================================================

get_port_process() {
    local port="$1"
    local process_info
    process_info=$(lsof -i TCP:"$port" -sTCP:LISTEN 2>/dev/null | tail -1)

    if [[ -n "$process_info" ]]; then
        local process_name=$(echo "$process_info" | awk '{print $1}')
        local process_pid=$(echo "$process_info" | awk '{print $2}')
        echo "$process_name (PID: $process_pid)"
    else
        echo "inconnu"
    fi
}

# =============================================================================
# FONCTION DE VERIFICATION DE TOUS LES PORTS
# =============================================================================
# Verifie une liste de ports et retourne ceux qui sont occupes.
#
# Usage:
#   check_ports 8080 3000 8081 11434
#   # Retourne les ports occupes (un par ligne)
# =============================================================================

check_ports() {
    local occupied=()

    for port in "$@"; do
        if ! check_port "$port"; then
            occupied+=("$port")
        fi
    done

    if [[ ${#occupied[@]} -gt 0 ]]; then
        printf '%s\n' "${occupied[@]}"
        return 1
    fi

    return 0
}

# =============================================================================
# FONCTION DE RECHERCHE DE PORT DISPONIBLE
# =============================================================================
# Trouve un port disponible a partir d'un port de depart.
#
# Usage:
#   new_port=$(find_available_port 8080)
#   # Retourne 8080 si disponible, sinon 8081, 8082, etc.
#
# Parametre:
#   $1 - Port de depart
#   $2 - Nombre max de tentatives (defaut: 10)
# =============================================================================

find_available_port() {
    local start_port="$1"
    local max_attempts="${2:-10}"
    local port="$start_port"

    for ((i=0; i<max_attempts; i++)); do
        if check_port "$port"; then
            echo "$port"
            return 0
        fi
        ((port++))
    done

    # Aucun port trouve
    return 1
}

# =============================================================================
# FONCTION DE VERIFICATION DE NOM DE CONTAINER DOCKER
# =============================================================================
# Verifie si un container avec ce nom existe (running ou stopped).
#
# Usage:
#   if check_docker_container_exists "my_container"; then
#       echo "Container existe"
#   fi
#
# Retour:
#   0 si existe, 1 sinon
# =============================================================================

check_docker_container_exists() {
    local name="$1"

    if ! command -v docker &> /dev/null; then
        return 1
    fi

    # Chercher dans tous les containers (running + stopped)
    docker ps -a --filter "name=^${name}$" --format "{{.Names}}" 2>/dev/null | grep -q "^${name}$"
}

# =============================================================================
# FONCTION DE RECUPERATION D'INFO CONTAINER DOCKER
# =============================================================================
# Retourne les infos d'un container existant (status, ports).
#
# Usage:
#   info=$(get_docker_container_info "my_container")
# =============================================================================

get_docker_container_info() {
    local name="$1"

    if ! command -v docker &> /dev/null; then
        echo ""
        return 1
    fi

    local info
    info=$(docker ps -a --filter "name=^${name}$" --format "{{.Status}} | Ports: {{.Ports}}" 2>/dev/null | head -1)

    echo "$info"
}

# =============================================================================
# FONCTION DE GESTION DE CONTAINER EXISTANT
# =============================================================================
# Propose d'arreter et/ou supprimer un container existant.
#
# Usage:
#   handle_existing_container "my_container"
#
# Retour:
#   0 si le container a ete supprime ou n'existe plus, 1 sinon
# =============================================================================

handle_existing_container() {
    local name="$1"

    if ! check_docker_container_exists "$name"; then
        return 0
    fi

    local info
    info=$(get_docker_container_info "$name")

    echo "" >&2
    log_warn "Container existant detecte: $name" >&2
    echo "  Status: $info" >&2

    # Verifier si le container est running
    local is_running
    is_running=$(docker ps --filter "name=^${name}$" --format "{{.Names}}" 2>/dev/null | grep -q "^${name}$" && echo "yes" || echo "no")

    if [[ "$is_running" == "yes" ]]; then
        if confirm "  Arreter le container '$name' ?" "y"; then
            log_info "Arret du container $name..." >&2
            if ! docker stop "$name" > /dev/null 2>&1; then
                log_error "Impossible d'arreter le container" >&2
                return 1
            fi
            log_success "Container $name arrete" >&2
        else
            return 1
        fi
    fi

    if confirm "  Supprimer le container '$name' ?" "n"; then
        if docker rm "$name" > /dev/null 2>&1; then
            log_success "Container $name supprime" >&2
            return 0
        else
            log_error "Impossible de supprimer le container" >&2
            return 1
        fi
    fi

    return 1
}

# =============================================================================
# FONCTION DE VERIFICATION DES CONTAINERS D'UN PROJET
# =============================================================================
# Verifie tous les containers d'un projet et propose de les gerer.
#
# Usage:
#   check_project_containers "my_ia_v2"
#
# Parametres:
#   $1 - Prefixe du projet (APP_NAME_PREFIX)
#
# Retour:
#   0 si tous les containers ont ete geres, 1 sinon
# =============================================================================

check_project_containers() {
    local prefix="$1"

    if ! command -v docker &> /dev/null; then
        return 0
    fi

    # Liste des services Docker du projet
    local services=("postgres" "chroma" "ollama" "app" "ui_front" "ui_back" "pgadmin")
    local existing_containers=()

    # Chercher les containers existants
    for service in "${services[@]}"; do
        local container_name="${prefix}_${service}"
        if check_docker_container_exists "$container_name"; then
            existing_containers+=("$container_name")
        fi
    done

    if [[ ${#existing_containers[@]} -eq 0 ]]; then
        return 0
    fi

    echo "" >&2
    log_warn "Containers existants detectes pour le projet '$prefix':" >&2
    for container in "${existing_containers[@]}"; do
        local info=$(get_docker_container_info "$container")
        echo "  - $container ($info)" >&2
    done

    echo "" >&2
    if confirm "Arreter et supprimer TOUS ces containers ?" "n"; then
        for container in "${existing_containers[@]}"; do
            # Arreter si running
            if docker ps --filter "name=^${container}$" --format "{{.Names}}" 2>/dev/null | grep -q "^${container}$"; then
                log_info "Arret de $container..." >&2
                docker stop "$container" > /dev/null 2>&1
            fi
            # Supprimer
            log_info "Suppression de $container..." >&2
            docker rm "$container" > /dev/null 2>&1
        done
        log_success "Tous les containers ont ete supprimes" >&2
        return 0
    else
        echo "" >&2
        echo "Gestion individuelle des containers:" >&2
        local all_handled=true
        for container in "${existing_containers[@]}"; do
            if ! handle_existing_container "$container"; then
                all_handled=false
            fi
        done

        if [[ "$all_handled" == "true" ]]; then
            return 0
        else
            log_warn "Certains containers n'ont pas ete supprimes" >&2
            log_warn "Cela peut causer des conflits de noms au demarrage" >&2
            return 1
        fi
    fi
}

# =============================================================================
# FONCTION DE LISTE DES VOLUMES D'UN PROJET
# =============================================================================
# Retourne la liste des volumes Docker d'un projet.
#
# Usage:
#   volumes=$(get_project_volumes "my_ia_v2")
#
# Parametres:
#   $1 - Prefixe du projet (APP_NAME_PREFIX)
# =============================================================================

get_project_volumes() {
    local prefix="$1"

    if ! command -v docker &> /dev/null; then
        return 1
    fi

    # Liste des volumes du projet
    docker volume ls --filter "name=${prefix}_" --format "{{.Name}}" 2>/dev/null
}

# =============================================================================
# FONCTION DE SUPPRESSION DES VOLUMES D'UN PROJET
# =============================================================================
# Supprime les volumes Docker d'un projet (tous ou individuellement).
#
# Usage:
#   delete_project_volumes "my_ia_v2"
#
# Parametres:
#   $1 - Prefixe du projet (APP_NAME_PREFIX)
#
# Retour:
#   0 si tous les volumes ont ete supprimes, 1 sinon
# =============================================================================

delete_project_volumes() {
    local prefix="$1"

    if ! command -v docker &> /dev/null; then
        return 0
    fi

    # Recuperer la liste des volumes
    local volumes
    volumes=$(get_project_volumes "$prefix")

    if [[ -z "$volumes" ]]; then
        log_info "Aucun volume trouve pour le projet '$prefix'" >&2
        return 0
    fi

    # Convertir en tableau
    local volume_list=()
    while IFS= read -r vol; do
        [[ -n "$vol" ]] && volume_list+=("$vol")
    done <<< "$volumes"

    echo "" >&2
    log_warn "Volumes detectes pour le projet '$prefix':" >&2
    for vol in "${volume_list[@]}"; do
        echo "  - $vol" >&2
    done

    echo "" >&2
    echo "  /!\\ ATTENTION: La suppression des volumes entraine une PERTE DE DONNEES" >&2
    echo "" >&2

    if confirm "Supprimer TOUS ces volumes ?" "n"; then
        for vol in "${volume_list[@]}"; do
            log_info "Suppression du volume $vol..." >&2
            if execute docker volume rm "$vol" > /dev/null 2>&1; then
                log_success "Volume $vol supprime" >&2
            else
                log_error "Impossible de supprimer le volume $vol" >&2
            fi
        done
        return 0
    else
        echo "" >&2
        echo "Gestion individuelle des volumes:" >&2
        local all_deleted=true
        for vol in "${volume_list[@]}"; do
            echo "" >&2
            if confirm "  Supprimer le volume '$vol' ?" "n"; then
                if execute docker volume rm "$vol" > /dev/null 2>&1; then
                    log_success "Volume $vol supprime" >&2
                else
                    log_error "Impossible de supprimer le volume $vol" >&2
                    all_deleted=false
                fi
            else
                all_deleted=false
            fi
        done

        if [[ "$all_deleted" == "true" ]]; then
            return 0
        else
            log_info "Certains volumes ont ete conserves" >&2
            return 1
        fi
    fi
}

# =============================================================================
# FONCTION DE NETTOYAGE COMPLET D'UN PROJET
# =============================================================================
# Supprime containers et volumes d'un projet.
#
# Usage:
#   cleanup_project "my_ia_v2"
#
# Retour:
#   0 si nettoyage reussi (ou partiel accepte), 1 si abandonne
# =============================================================================

cleanup_project() {
    local prefix="$1"

    if ! command -v docker &> /dev/null; then
        return 0
    fi

    # Verifier si des containers existent
    local services=("postgres" "chroma" "ollama" "app" "ui_front" "ui_back" "pgadmin")
    local existing_containers=()

    for service in "${services[@]}"; do
        local container_name="${prefix}_${service}"
        if check_docker_container_exists "$container_name"; then
            existing_containers+=("$container_name")
        fi
    done

    if [[ ${#existing_containers[@]} -eq 0 ]]; then
        log_info "Aucun container existant pour le projet '$prefix'" >&2
        return 0
    fi

    echo "" >&2
    log_warn "Pour reconfigurer, les containers existants doivent etre supprimes." >&2
    echo "" >&2
    echo "Containers detectes:" >&2
    for container in "${existing_containers[@]}"; do
        local info=$(get_docker_container_info "$container")
        echo "  - $container ($info)" >&2
    done

    echo "" >&2
    if ! confirm "Continuer et supprimer les containers ?" "y"; then
        log_error "Configuration annulee" >&2
        return 1
    fi

    # Supprimer tous les containers ou individuellement
    echo "" >&2
    if confirm "Supprimer TOUS les containers ?" "y"; then
        for container in "${existing_containers[@]}"; do
            # Arreter si running
            if docker ps --filter "name=^${container}$" --format "{{.Names}}" 2>/dev/null | grep -q "^${container}$"; then
                log_info "Arret de $container..." >&2
                execute docker stop "$container" > /dev/null 2>&1
            fi
            # Supprimer
            log_info "Suppression de $container..." >&2
            execute docker rm "$container" > /dev/null 2>&1
        done
        log_success "Tous les containers ont ete supprimes" >&2
    else
        echo "" >&2
        echo "Gestion individuelle des containers:" >&2
        for container in "${existing_containers[@]}"; do
            if ! handle_existing_container "$container"; then
                log_warn "Container $container conserve" >&2
            fi
        done
    fi

    # Proposer suppression des volumes
    echo "" >&2
    if confirm "Supprimer aussi les volumes ? (PERTE DE DONNEES)" "n"; then
        delete_project_volumes "$prefix"
    else
        log_info "Volumes conserves (donnees preservees)" >&2
    fi

    return 0
}

# =============================================================================
# FONCTION DE DETECTION DE CONTAINER DOCKER SUR UN PORT
# =============================================================================
# Retourne le nom du container Docker utilisant un port, ou vide si aucun.
#
# Usage:
#   container=$(get_docker_container_on_port 8080)
# =============================================================================

get_docker_container_on_port() {
    local port="$1"

    # Verifier si Docker est disponible
    if ! command -v docker &> /dev/null; then
        echo ""
        return 1
    fi

    # Chercher un container exposant ce port
    local container
    container=$(docker ps --filter "publish=$port" --format "{{.Names}}" 2>/dev/null | head -1)

    if [[ -n "$container" ]]; then
        echo "$container"
        return 0
    fi

    echo ""
    return 1
}

# =============================================================================
# FONCTION D'ARRET ET SUPPRESSION DE CONTAINER DOCKER
# =============================================================================
# Propose d'arreter et/ou supprimer un container Docker.
#
# Usage:
#   handle_docker_container "my_container" 8080
#
# Retour:
#   0 si le container a ete arrete/supprime, 1 sinon
# =============================================================================

handle_docker_container() {
    local container="$1"
    local port="$2"

    echo "" >&2
    echo "  Container Docker detecte: $container" >&2

    if confirm "  Arreter le container '$container' ?" "y"; then
        log_info "Arret du container $container..." >&2
        if docker stop "$container" > /dev/null 2>&1; then
            log_success "Container $container arrete" >&2

            if confirm "  Supprimer le container '$container' ?" "n"; then
                if docker rm "$container" > /dev/null 2>&1; then
                    log_success "Container $container supprime" >&2
                else
                    log_warn "Impossible de supprimer le container" >&2
                fi
            fi

            # Verifier que le port est maintenant libre
            sleep 1
            if check_port "$port"; then
                return 0
            else
                log_warn "Port $port toujours occupe apres arret du container" >&2
                return 1
            fi
        else
            log_error "Impossible d'arreter le container" >&2
            return 1
        fi
    fi

    return 1
}

# =============================================================================
# FONCTION DE VERIFICATION INTERACTIVE DE PORT
# =============================================================================
# Verifie un port et propose une alternative si occupe.
# Si le port est utilise par Docker, propose d'arreter/supprimer le container.
#
# Usage:
#   FRONTEND_PORT=$(check_port_interactive "$FRONTEND_PORT" "Frontend")
#
# Parametres:
#   $1 - Port a verifier
#   $2 - Nom du service (pour l'affichage)
#
# Retour:
#   Affiche le port disponible (original ou alternatif)
# =============================================================================

check_port_interactive() {
    local port="$1"
    local service="$2"

    if check_port "$port"; then
        echo "$port"
        return 0
    fi

    # Port occupe - tous les messages vers stderr pour ne pas polluer stdout
    local process=$(get_port_process "$port")
    log_warn "Port $port ($service) occupe par: $process" >&2

    # Verifier si c'est un container Docker
    local container
    container=$(get_docker_container_on_port "$port")

    if [[ -n "$container" ]]; then
        # Proposer d'arreter le container Docker
        if handle_docker_container "$container" "$port"; then
            # Port libere, on peut l'utiliser
            echo "$port"
            return 0
        fi
    fi

    # Chercher un port alternatif
    local alt_port
    alt_port=$(find_available_port $((port + 1)))

    if [[ -n "$alt_port" ]]; then
        echo "" >&2
        echo "  Port $port toujours occupe. Alternative disponible: $alt_port" >&2
        if confirm "  Utiliser le port $alt_port pour $service ?" "y"; then
            echo "$alt_port"
            return 0
        fi
    fi

    # Demander manuellement
    echo "" >&2
    read -p "  Entrez un port pour $service: " manual_port

    if [[ -n "$manual_port" ]] && check_port "$manual_port"; then
        echo "$manual_port"
        return 0
    elif [[ -n "$manual_port" ]]; then
        log_error "Port $manual_port egalement occupe" >&2
        exit 1
    else
        log_error "Port requis pour $service" >&2
        exit 1
    fi
}

# =============================================================================
# DETECTION DES SERVICES NATIFS
# =============================================================================
# Detecte les services installes et actifs nativement (hors Docker).
# Exporte des variables NATIVE_*_RUNNING pour chaque service.
#
# Usage:
#   detect_native_services
#
# Variables exportees:
#   NATIVE_POSTGRES_RUNNING  - "true" si PostgreSQL natif actif
#   NATIVE_OLLAMA_RUNNING    - "true" si Ollama natif actif
#   NATIVE_CHROMADB_RUNNING  - "true" si ChromaDB natif actif
#   NATIVE_NGINX_RUNNING     - "true" si nginx natif actif
# =============================================================================

detect_native_services() {
    NATIVE_POSTGRES_RUNNING="false"
    NATIVE_OLLAMA_RUNNING="false"
    NATIVE_CHROMADB_RUNNING="false"
    NATIVE_NGINX_RUNNING="false"

    # --- PostgreSQL ---
    if command -v pg_isready &> /dev/null && pg_isready -q 2>/dev/null; then
        NATIVE_POSTGRES_RUNNING="true"
    elif [[ "$(uname -s)" == "Darwin" ]]; then
        if brew services list 2>/dev/null | grep -q "postgresql.*started"; then
            NATIVE_POSTGRES_RUNNING="true"
        fi
    else
        if systemctl is-active --quiet postgresql 2>/dev/null; then
            NATIVE_POSTGRES_RUNNING="true"
        fi
    fi

    # --- Ollama ---
    if pgrep -x "ollama" > /dev/null 2>&1; then
        NATIVE_OLLAMA_RUNNING="true"
    elif curl -sf "http://localhost:${OLLAMA_PORT:-11434}/api/tags" > /dev/null 2>&1; then
        NATIVE_OLLAMA_RUNNING="true"
    fi

    # --- ChromaDB ---
    if curl -sf "http://localhost:${CHROMA_PORT:-8000}/api/v1/heartbeat" > /dev/null 2>&1; then
        NATIVE_CHROMADB_RUNNING="true"
    fi

    # --- nginx ---
    if pgrep -x "nginx" > /dev/null 2>&1; then
        NATIVE_NGINX_RUNNING="true"
    fi

    export NATIVE_POSTGRES_RUNNING NATIVE_OLLAMA_RUNNING NATIVE_CHROMADB_RUNNING NATIVE_NGINX_RUNNING
}

# =============================================================================
# NOTE: Les fonctions suivantes ont ete deplacees pour une meilleure
# organisation modulaire:
#
#   get_cities_count()          -> scripts/lib/db.sh
#   get_countries_count()       -> scripts/lib/db.sh
#   check_test_users_exist()    -> scripts/lib/db.sh
#   generate_admin_token()      -> scripts/lib/auth.sh
#   generate_admin_token_native() -> scripts/lib/auth.sh
#   show_progress_bar()         -> scripts/lib/data.sh
#   import_cities_stream()      -> scripts/lib/data.sh
#   import_countries_from_file() -> scripts/lib/data.sh
#   create_test_users()         -> scripts/lib/data.sh
#
# =============================================================================

# =============================================================================
# DEPLOIEMENT DISTANT (SSH)
# =============================================================================
# Fonctions pour deployer sur un serveur distant via SSH.
# La configuration est lue depuis la base de donnees (system_configs).
#
# Usage:
#   load_deploy_config           # Charge la config depuis la BDD
#   remote_deploy                # Execute le deploiement complet
# =============================================================================

# Variables globales pour le deploiement distant
DEPLOY_REMOTE_HOST=""
DEPLOY_REMOTE_USER=""
DEPLOY_REMOTE_PATH=""
DEPLOY_REMOTE_PORT=""
DEPLOY_GIT_BRANCH=""
DEPLOY_AUTO_RESTART=""
DEPLOY_HEALTH_CHECK_URL=""
DEPLOY_CONFIG_FILES_TO_RESET=""

# -----------------------------------------------------------------------------
# get_db_config()
# -----------------------------------------------------------------------------
# Recupere une valeur de configuration depuis la base de donnees.
# Utilise psql via Docker pour lire la table system_configs.
#
# Arguments:
#   $1 - Cle de configuration (ex: "deploy.remote_host")
#   $2 - Valeur par defaut si la cle n'existe pas
#
# Retour:
#   stdout - Valeur de la configuration
# -----------------------------------------------------------------------------
get_db_config() {
    local key="$1"
    local default="${2:-}"
    local project_root="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"

    # Detecter la commande docker compose
    local compose_cmd="docker compose"
    if ! docker compose version &>/dev/null; then
        compose_cmd="docker-compose"
    fi

    # Lire depuis la BDD via Docker
    local value
    value=$(cd "$project_root" && $compose_cmd exec -T postgres psql -U my_ia_db_user -d my_ia_db -t -A -c \
        "SELECT value FROM system_configs WHERE key = '$key' LIMIT 1;" 2>/dev/null | tr -d '\r\n')

    if [[ -n "$value" && "$value" != "" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

# -----------------------------------------------------------------------------
# load_deploy_config()
# -----------------------------------------------------------------------------
# Charge la configuration de deploiement depuis la base de donnees.
# Definit les variables globales DEPLOY_*.
# -----------------------------------------------------------------------------
load_deploy_config() {
    log_info "Chargement de la configuration de deploiement depuis la BDD..."

    DEPLOY_REMOTE_HOST=$(get_db_config "deploy.remote_host" "")
    DEPLOY_REMOTE_USER=$(get_db_config "deploy.remote_user" "debian")
    DEPLOY_REMOTE_PATH=$(get_db_config "deploy.remote_path" "/home/debian/my-ia")
    DEPLOY_REMOTE_PORT=$(get_db_config "deploy.remote_port" "22")
    DEPLOY_GIT_BRANCH=$(get_db_config "deploy.git_branch" "main")
    DEPLOY_AUTO_RESTART=$(get_db_config "deploy.auto_restart" "true")
    DEPLOY_HEALTH_CHECK_URL=$(get_db_config "deploy.health_check_url" "/health")
    DEPLOY_CONFIG_FILES_TO_RESET=$(get_db_config "deploy.config_files_to_reset" "")

    # Validation
    if [[ -z "$DEPLOY_REMOTE_HOST" ]]; then
        log_error "deploy.remote_host non configure dans la BDD"
        return 1
    fi

    log_success "Configuration chargee:"
    log_info "  Host: ${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}:${DEPLOY_REMOTE_PORT}"
    log_info "  Path: ${DEPLOY_REMOTE_PATH}"
    log_info "  Branch: ${DEPLOY_GIT_BRANCH}"

    export DEPLOY_REMOTE_HOST DEPLOY_REMOTE_USER DEPLOY_REMOTE_PATH DEPLOY_REMOTE_PORT
    export DEPLOY_GIT_BRANCH DEPLOY_AUTO_RESTART DEPLOY_HEALTH_CHECK_URL DEPLOY_CONFIG_FILES_TO_RESET
}

# -----------------------------------------------------------------------------
# ssh_exec()
# -----------------------------------------------------------------------------
# Execute une commande sur le serveur distant via SSH.
#
# Arguments:
#   $@ - Commande a executer
#
# Retour:
#   Code de retour de la commande SSH
# -----------------------------------------------------------------------------
ssh_exec() {
    local ssh_opts="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10"

    if [[ -n "$DEPLOY_REMOTE_PORT" && "$DEPLOY_REMOTE_PORT" != "22" ]]; then
        ssh_opts="$ssh_opts -p $DEPLOY_REMOTE_PORT"
    fi

    ssh $ssh_opts "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" "$@"
}

# -----------------------------------------------------------------------------
# remote_git_sync()
# -----------------------------------------------------------------------------
# Synchronise le code sur le serveur distant:
# 1. Push local vers origin
# 2. Pull sur le serveur
# 3. Nettoyage des fichiers inutiles en prod
# -----------------------------------------------------------------------------
remote_git_sync() {
    local branch="${DEPLOY_GIT_BRANCH:-main}"

    # 1. Push local vers origin
    log_info "Push local vers origin ($branch)..."
    if ! git push origin "$branch" 2>/dev/null; then
        log_warn "Push echoue ou rien a pousser"
    fi

    # 2. Correction des permissions (fichiers créés par Docker avec root)
    ssh_exec "cd $DEPLOY_REMOTE_PATH && sudo chown -R \$(whoami):\$(whoami) . 2>/dev/null" || true

    # 3. Reset + pull sur le serveur distant (ecrase les modifs locales)
    log_info "Synchronisation du serveur (reset + pull)..."
    if ! ssh_exec "cd $DEPLOY_REMOTE_PATH && git fetch origin $branch && git reset --hard origin/$branch"; then
        log_error "Echec de la synchronisation sur le serveur"
        return 1
    fi

    # 4. Nettoyage des fichiers inutiles en production
    # Note: ssl et nginx sont conserves (necessaires pour HTTPS sur VPS)
    log_info "Nettoyage des fichiers non necessaires en production..."
    ssh_exec "cd $DEPLOY_REMOTE_PATH && rm -rf \
        docs \
        tests \
        CLAUDE.md \
        CLAUDE2.md \
        .dockerignore \
        pytest.ini \
        requirements-test.txt \
        static-datas \
        docker-compose.dev.yml \
        docker-compose.staging.yml \
        docker-compose.override.yml \
        2>/dev/null" || true

    log_success "Code synchronise sur le serveur"
}

# -----------------------------------------------------------------------------
# remote_restart_containers()
# -----------------------------------------------------------------------------
# Redemarre les containers Docker sur le serveur distant.
# -----------------------------------------------------------------------------
remote_restart_containers() {
    if [[ "$DEPLOY_AUTO_RESTART" != "true" ]]; then
        log_info "Redemarrage automatique desactive"
        return 0
    fi

    log_info "Redemarrage des containers sur le serveur..."

    # Detecter la commande docker compose
    local compose_cmd
    compose_cmd=$(ssh_exec "docker compose version >/dev/null 2>&1 && echo 'docker compose' || echo 'docker-compose'")

    # Rebuild app container (code Python bake dans l'image) + restart UI
    if ! ssh_exec "cd $DEPLOY_REMOTE_PATH && $compose_cmd up -d --build app && $compose_cmd restart ui-front ui-back 2>/dev/null"; then
        log_warn "Redemarrage partiel, tentative restart global..."
        ssh_exec "cd $DEPLOY_REMOTE_PATH && $compose_cmd down && $compose_cmd up -d --build"
    fi

    log_success "Containers redemarres"
}

# -----------------------------------------------------------------------------
# remote_run_migrations()
# -----------------------------------------------------------------------------
# Execute les migrations Alembic sur le serveur distant.
# -----------------------------------------------------------------------------
remote_run_migrations() {
    log_info "Application des migrations Alembic..."

    # Detecter la commande docker compose
    local compose_cmd
    compose_cmd=$(ssh_exec "docker compose version >/dev/null 2>&1 && echo 'docker compose' || echo 'docker-compose'")

    # Executer alembic upgrade head dans le container app
    local migration_output
    migration_output=$(ssh_exec "cd $DEPLOY_REMOTE_PATH && $compose_cmd exec -T app python -m alembic upgrade head 2>&1")
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
        return 0
    else
        log_error "Echec des migrations:"
        echo "$migration_output" | head -10
        return 1
    fi
}

# -----------------------------------------------------------------------------
# remote_health_check()
# -----------------------------------------------------------------------------
# Verifie que l'application repond sur le serveur distant.
# -----------------------------------------------------------------------------
remote_health_check() {
    local health_url="${DEPLOY_HEALTH_CHECK_URL:-/health}"
    local public_host="$DEPLOY_REMOTE_HOST"
    local api_port=$(get_db_config "ports.api" "8080")

    log_info "Verification de sante: http://${public_host}:${api_port}${health_url}"

    local max_attempts=10
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        if curl -sf "http://${public_host}:${api_port}${health_url}" > /dev/null 2>&1; then
            log_success "Application accessible"
            return 0
        fi
        log_info "  Tentative $attempt/$max_attempts..."
        sleep 3
        ((attempt++))
    done

    log_error "Application non accessible apres $max_attempts tentatives"
    return 1
}

# -----------------------------------------------------------------------------
# remote_check_sync()
# -----------------------------------------------------------------------------
# Verifie la synchronisation entre local et VPS:
# - Commits git
# - Migrations Alembic
# - Configurations systeme (system_configs)
# Affiche un recapitulatif des differences.
# -----------------------------------------------------------------------------
remote_check_sync() {
    echo ""
    echo "============================================================================="
    echo "  VERIFICATION DE SYNCHRONISATION"
    echo "============================================================================="
    echo ""

    local has_diff=false

    # --- 1. Verification Git ---
    log_step "Verification Git"

    local local_commit local_branch
    local_commit=$(git rev-parse --short HEAD 2>/dev/null)
    local_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)

    local remote_commit remote_branch
    remote_commit=$(ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" "cd $DEPLOY_REMOTE_PATH && git rev-parse --short HEAD" 2>/dev/null | tr -d '\r\n')
    remote_branch=$(ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" "cd $DEPLOY_REMOTE_PATH && git rev-parse --abbrev-ref HEAD" 2>/dev/null | tr -d '\r\n')

    if [[ "$local_commit" == "$remote_commit" ]]; then
        echo -e "  ${GREEN}✓${NC} Git commit: $local_commit ($local_branch)"
    else
        echo -e "  ${RED}✗${NC} Git commit different:"
        echo "      Local: $local_commit ($local_branch)"
        echo "      VPS:   $remote_commit ($remote_branch)"
        has_diff=true
    fi

    # --- 2. Verification Alembic ---
    log_step "Verification Alembic"

    # Utiliser docker exec directement (plus fiable que docker compose exec)
    local local_alembic remote_alembic
    local_alembic=$(docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c \
        "SELECT version_num FROM alembic_version LIMIT 1;" 2>/dev/null | tr -d '\r\n')
    remote_alembic=$(ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" \
        "docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c 'SELECT version_num FROM alembic_version LIMIT 1;'" 2>/dev/null | tr -d '\r\n')

    if [[ "$local_alembic" == "$remote_alembic" ]]; then
        echo -e "  ${GREEN}✓${NC} Alembic version: $local_alembic"
    else
        echo -e "  ${RED}✗${NC} Alembic version differente:"
        echo "      Local: $local_alembic"
        echo "      VPS:   $remote_alembic"
        has_diff=true
    fi

    # --- 3. Verification system_configs ---
    log_step "Verification Configurations (system_configs)"

    local local_count remote_count
    local_count=$(docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c \
        "SELECT COUNT(*) FROM system_configs;" 2>/dev/null | tr -d '\r\n')
    remote_count=$(ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" \
        "docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c 'SELECT COUNT(*) FROM system_configs;'" 2>/dev/null | tr -d '\r\n')

    if [[ "$local_count" == "$remote_count" ]]; then
        echo -e "  ${GREEN}✓${NC} Nombre de configs: $local_count"
    else
        echo -e "  ${YELLOW}!${NC} Nombre de configs different: Local=$local_count, VPS=$remote_count"
        has_diff=true
    fi

    # Exporter les cles locales et VPS
    docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c \
        "SELECT key FROM system_configs ORDER BY key;" 2>/dev/null > /tmp/local_keys.txt

    ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" \
        "docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c 'SELECT key FROM system_configs ORDER BY key;'" \
        2>/dev/null > /tmp/vps_keys.txt

    # Chercher les cles manquantes sur le VPS
    local missing_keys
    missing_keys=$(comm -23 <(sort /tmp/local_keys.txt 2>/dev/null) <(sort /tmp/vps_keys.txt 2>/dev/null) 2>/dev/null | grep -v "^$" || true)

    if [[ -n "$missing_keys" ]]; then
        local missing_count
        missing_count=$(echo "$missing_keys" | grep -c "." || echo "0")
        echo -e "  ${YELLOW}!${NC} Cles manquantes sur VPS ($missing_count):"
        echo "$missing_keys" | head -10 | while read -r key; do
            [[ -n "$key" ]] && echo "      - $key"
        done
        if [[ $missing_count -gt 10 ]]; then
            echo "      ... et $((missing_count - 10)) autres"
        fi
        has_diff=true
    fi

    # Chercher les cles uniquement sur le VPS
    local extra_keys
    extra_keys=$(comm -13 <(sort /tmp/local_keys.txt 2>/dev/null) <(sort /tmp/vps_keys.txt 2>/dev/null) 2>/dev/null | grep -v "^$" || true)

    if [[ -n "$extra_keys" ]]; then
        local extra_count
        extra_count=$(echo "$extra_keys" | grep -c "." || echo "0")
        echo -e "  ${YELLOW}!${NC} Cles uniquement sur VPS ($extra_count):"
        echo "$extra_keys" | head -5 | while read -r key; do
            [[ -n "$key" ]] && echo "      - $key"
        done
        has_diff=true
    fi

    # Comparer les valeurs differentes (exclure les cles sensibles/environnement)
    log_step "Valeurs differentes (hors securite/environnement)"

    docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c \
        "SELECT key || '|' || value FROM system_configs ORDER BY key;" 2>/dev/null > /tmp/local_cfg.txt

    ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" \
        "docker exec my_ia_postgres psql -U my_ia_db_user -d my_ia_db -t -A -c 'SELECT key || chr(124) || value FROM system_configs ORDER BY key;'" \
        2>/dev/null > /tmp/vps_cfg.txt

    local exclude_pattern="security\.|app.api_url|ollama.host|llm\..*\.host|deploy\."
    local diff_values
    diff_values=$(diff /tmp/local_cfg.txt /tmp/vps_cfg.txt 2>/dev/null | grep -E "^[<>]" | grep -vE "$exclude_pattern" || true)

    if [[ -n "$diff_values" ]]; then
        local diff_count
        diff_count=$(echo "$diff_values" | grep -c "." || echo "0")
        echo -e "  ${YELLOW}!${NC} Valeurs differentes ($((diff_count / 2)) cles):"
        echo "$diff_values" | head -20 | while read -r line; do
            if [[ "$line" == "<"* ]]; then
                local key_val="${line:2}"
                local key="${key_val%%|*}"
                local val="${key_val#*|}"
                # Tronquer les valeurs longues
                [[ ${#val} -gt 50 ]] && val="${val:0:47}..."
                echo -e "      ${BLUE}Local${NC}  $key = $val"
            elif [[ "$line" == ">"* ]]; then
                local key_val="${line:2}"
                local key="${key_val%%|*}"
                local val="${key_val#*|}"
                [[ ${#val} -gt 50 ]] && val="${val:0:47}..."
                echo -e "      ${CYAN}VPS${NC}    $key = $val"
            fi
        done
        has_diff=true
    else
        echo -e "  ${GREEN}✓${NC} Toutes les valeurs sont identiques"
    fi

    # Nettoyage
    rm -f /tmp/local_keys.txt /tmp/vps_keys.txt /tmp/local_cfg.txt /tmp/vps_cfg.txt 2>/dev/null

    # --- Resume ---
    echo ""
    echo "-----------------------------------------------------------------------------"
    if [[ "$has_diff" == "true" ]]; then
        echo -e "  ${YELLOW}Resume: Des differences ont ete detectees${NC}"
        echo "  Les differences de valeurs peuvent etre normales (environnement different)"
        echo "  Les cles manquantes peuvent etre ajoutees via l'admin UI ou SQL"
    else
        echo -e "  ${GREEN}Resume: Local et VPS sont synchronises${NC}"
    fi
    echo "-----------------------------------------------------------------------------"
    echo ""
}

# -----------------------------------------------------------------------------
# remote_deploy()
# -----------------------------------------------------------------------------
# Execute le deploiement complet sur le serveur distant:
# 1. Charge la config depuis la BDD
# 2. Verifie la branche (doit etre sur main)
# 3. Verifie l'etat git (pas de modifs non commitees)
# 4. Synchronise le code via rsync
# 5. Redemarre les containers
# 6. Applique les migrations Alembic
# 7. Health check
# 8. Verification de synchronisation
# -----------------------------------------------------------------------------
remote_deploy() {
    echo ""
    echo "============================================================================="
    echo "  DEPLOIEMENT DISTANT"
    echo "============================================================================="
    echo ""

    # 1. Charger la config
    if ! load_deploy_config; then
        log_error "Impossible de charger la configuration de deploiement"
        log_info "Configurez deploy.remote_host dans la base de donnees"
        return 1
    fi

    # 2. Verifier qu'on est sur la bonne branche
    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    local target_branch="${DEPLOY_GIT_BRANCH:-main}"

    if [[ "$current_branch" != "$target_branch" ]]; then
        echo ""
        echo -e "${YELLOW}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
        echo -e "${YELLOW}║  ⚠️  ATTENTION: Mauvaise branche pour le deploiement                         ║${NC}"
        echo -e "${YELLOW}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
        echo ""
        echo -e "  Branche actuelle : ${RED}$current_branch${NC}"
        echo -e "  Branche attendue : ${GREEN}$target_branch${NC}"
        echo ""
        echo -e "${CYAN}Instructions pour basculer sur $target_branch :${NC}"
        echo ""
        echo "  1. Commiter vos modifications locales (si necessaire) :"
        echo -e "     ${WHITE}git add -A && git commit -m \"votre message\"${NC}"
        echo ""
        echo "  2. Basculer sur $target_branch :"
        echo -e "     ${WHITE}git checkout $target_branch${NC}"
        echo ""
        echo "  3. Merger $current_branch dans $target_branch (si necessaire) :"
        echo -e "     ${WHITE}git merge $current_branch${NC}"
        echo ""
        echo "  4. Relancer le deploiement :"
        echo -e "     ${WHITE}./scripts/deploy.sh remote${NC}"
        echo ""

        # Proposer la bascule automatique en mode interactif
        if [[ -t 0 ]]; then
            echo -e "${CYAN}Options :${NC}"
            echo "  [1] Basculer automatiquement sur $target_branch et merger $current_branch"
            echo "  [2] Basculer automatiquement sur $target_branch (sans merger)"
            echo "  [3] Annuler le deploiement"
            echo ""
            read -p "Votre choix [1/2/3] : " choice

            case "$choice" in
                1)
                    log_info "Bascule vers $target_branch avec merge de $current_branch..."
                    if git checkout "$target_branch" && git merge "$current_branch" --no-edit; then
                        log_success "Merge reussi"
                        current_branch="$target_branch"
                    else
                        log_error "Echec du merge. Resolvez les conflits manuellement."
                        return 1
                    fi
                    ;;
                2)
                    log_info "Bascule vers $target_branch..."
                    if git checkout "$target_branch"; then
                        log_success "Bascule reussie"
                        current_branch="$target_branch"
                    else
                        log_error "Echec de la bascule"
                        return 1
                    fi
                    ;;
                *)
                    log_info "Deploiement annule"
                    return 1
                    ;;
            esac
        else
            log_error "Mode non-interactif: basculez manuellement sur $target_branch"
            return 1
        fi
    fi
    log_success "Branche: $current_branch"

    # 3. Verifier l'etat git local (pas de modifications non commitees)
    # Note: ignore les fichiers untracked (??) - seuls les modifies/staged bloquent
    log_info "Verification de l'etat git local..."
    local modified_files
    modified_files=$(git status --porcelain 2>/dev/null | grep -v '^??' || true)
    if [[ -n "$modified_files" ]]; then
        log_warn "Modifications non commitees detectees"
        echo "$modified_files"
        echo ""
        # En mode non-interactif, arreter
        if [[ -t 0 ]]; then
            if ! confirm "Continuer quand meme ?" "n"; then
                return 1
            fi
        else
            log_error "Mode non-interactif: arret (modifications non commitees)"
            return 1
        fi
    fi

    # 4. Synchroniser le code
    if ! remote_git_sync; then
        log_error "Echec de la synchronisation du code"
        return 1
    fi

    # 5. Redemarrer les containers
    if ! remote_restart_containers; then
        log_error "Echec du redemarrage des containers"
        return 1
    fi

    # 6. Appliquer les migrations Alembic
    sleep 5  # Laisser le temps aux containers de demarrer
    if ! remote_run_migrations; then
        log_warn "Migrations echouees"
    fi

    # 7. Health check
    if ! remote_health_check; then
        log_warn "Health check echoue, verifiez les logs sur le serveur"
    fi

    # 8. Verification de synchronisation
    remote_check_sync

    echo ""
    echo "============================================================================="
    log_success "Deploiement termine"
    echo "============================================================================="
    echo ""
    echo "  Serveur: ${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}"
    echo "  Chemin:  ${DEPLOY_REMOTE_PATH}"
    echo "  Branch:  ${DEPLOY_GIT_BRANCH}"
    echo ""
}
