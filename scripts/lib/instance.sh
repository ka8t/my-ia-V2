#!/bin/bash
# =============================================================================
# MY-IA - Fonctions de gestion d'instance
# =============================================================================
# Ce fichier contient les fonctions pour gerer l'identite de l'application
# et detecter les instances multiples.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/instance.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier
#
# =============================================================================

# =============================================================================
# GENERATION D'UUID V4
# =============================================================================
# Genere un UUID version 4 (aleatoire) compatible avec tous les systemes.
#
# Usage:
#   uuid=$(generate_uuid)
#
# Retour:
#   UUID au format xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
# =============================================================================

generate_uuid() {
    # Methode 1: uuidgen (macOS et Linux avec uuid-runtime)
    if command -v uuidgen &> /dev/null; then
        uuidgen | tr '[:upper:]' '[:lower:]'
        return 0
    fi

    # Methode 2: /proc/sys/kernel/random/uuid (Linux)
    if [[ -f /proc/sys/kernel/random/uuid ]]; then
        cat /proc/sys/kernel/random/uuid
        return 0
    fi

    # Methode 3: Python fallback
    if command -v python3 &> /dev/null; then
        python3 -c "import uuid; print(uuid.uuid4())"
        return 0
    fi

    # Methode 4: Generation manuelle avec openssl
    if command -v openssl &> /dev/null; then
        local hex=$(openssl rand -hex 16)
        # Format UUID: 8-4-4-4-12, avec version 4 et variante
        echo "${hex:0:8}-${hex:8:4}-4${hex:13:3}-$(printf '%x' $((0x8 + RANDOM % 4)))${hex:17:3}-${hex:20:12}"
        return 0
    fi

    # Echec
    log_error "Impossible de generer un UUID"
    return 1
}

# =============================================================================
# CHARGEMENT DE L'INSTANCE ID
# =============================================================================
# Charge l'APP_INSTANCE_ID depuis les sources disponibles dans l'ordre:
#   1. Fichier .env (source principale)
#   2. Fichier .instance (backup persistant)
#   3. Labels Docker des containers existants
#   4. Generation d'un nouveau UUID
#
# Usage:
#   load_instance_id "/path/to/project"
#
# Parametres:
#   $1 - Chemin du projet
#
# Resultat:
#   Definit la variable globale APP_INSTANCE_ID
#   Retourne 0 si trouve/genere, 1 si erreur
# =============================================================================

load_instance_id() {
    local project_root="$1"
    local env_file="${project_root}/.env"
    local instance_file="${project_root}/.instance"

    # Source 1: Fichier .env
    if [[ -f "$env_file" ]]; then
        local env_instance_id
        env_instance_id=$(grep "^APP_INSTANCE_ID=" "$env_file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
        if [[ -n "$env_instance_id" ]]; then
            APP_INSTANCE_ID="$env_instance_id"
            export APP_INSTANCE_ID
            return 0
        fi
    fi

    # Source 2: Fichier .instance
    if [[ -f "$instance_file" ]]; then
        local file_instance_id
        file_instance_id=$(grep "^APP_INSTANCE_ID=" "$instance_file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
        if [[ -n "$file_instance_id" ]]; then
            APP_INSTANCE_ID="$file_instance_id"
            export APP_INSTANCE_ID
            log_info "Instance ID charge depuis .instance"
            return 0
        fi
    fi

    # Source 3: Labels Docker
    if command -v docker &> /dev/null && docker info &> /dev/null; then
        local prefix="${APP_NAME_PREFIX:-my_ia_v2}"
        local sanitized_prefix
        sanitized_prefix=$(sanitize "$prefix" false)

        # Chercher un container avec le label ${sanitized_prefix}.instance.id
        local docker_instance_id
        docker_instance_id=$(docker ps -a --filter "name=^${sanitized_prefix}_" \
            --format "{{.Label \"${sanitized_prefix}.instance.id\"}}" 2>/dev/null | head -1)

        if [[ -n "$docker_instance_id" && "$docker_instance_id" != "<no value>" ]]; then
            APP_INSTANCE_ID="$docker_instance_id"
            export APP_INSTANCE_ID
            log_info "Instance ID recupere depuis labels Docker"
            return 0
        fi
    fi

    # Source 4: Generation d'un nouveau UUID
    APP_INSTANCE_ID=$(generate_uuid)
    if [[ -n "$APP_INSTANCE_ID" ]]; then
        export APP_INSTANCE_ID
        log_info "Nouveau Instance ID genere: ${APP_INSTANCE_ID:0:8}-****-****-****-************"
        return 0
    fi

    return 1
}

# =============================================================================
# SAUVEGARDE DU FICHIER .INSTANCE
# =============================================================================
# Sauvegarde les informations d'instance dans un fichier persistant.
# Ce fichier sert de backup si .env est supprime ou recree.
#
# Usage:
#   save_instance_file "/path/to/project"
#
# Parametres:
#   $1 - Chemin du projet
#
# Fichier cree:
#   .instance contenant APP_INSTANCE_ID, date creation, chemin, prefixe
# =============================================================================

save_instance_file() {
    local project_root="$1"
    local instance_file="${project_root}/.instance"
    local timestamp
    timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

    cat > "$instance_file" << EOF
# =============================================================================
# MY-IA - Fichier d'instance
# =============================================================================
# Ce fichier est genere automatiquement et ajoute a .gitignore.
# Il sert de backup pour identifier l'instance si .env est supprime.
# NE PAS MODIFIER MANUELLEMENT sauf si vous savez ce que vous faites.
# =============================================================================

APP_INSTANCE_ID=${APP_INSTANCE_ID}
INSTANCE_CREATED_AT=${timestamp}
INSTANCE_PATH=${project_root}
INSTANCE_PREFIX=${APP_NAME_PREFIX:-MY-IA}
INSTANCE_INITIAL_VERSION=${APP_VERSION:-1.0.0}
EOF

    chmod 600 "$instance_file"
    log_success "Fichier .instance cree"
}

# =============================================================================
# AFFICHAGE DE LA BANNIERE DE DEMARRAGE
# =============================================================================
# Affiche la banniere de l'application avec les informations d'identite.
#
# Usage:
#   show_app_banner
#
# Prerequis:
#   Variables globales definies: APP_TITLE, APP_VERSION, APP_DESCRIPTION,
#   APP_ICON, APP_INSTANCE_ID, APP_NAME_PREFIX, DEBUG
# =============================================================================

show_app_banner() {
    local title="${APP_TITLE:-MY-IA Assistant}"
    local version="${APP_VERSION:-1.0.0}"
    local description="${APP_DESCRIPTION:-Chatbot RAG avec gestion documentaire}"
    local icon="${APP_ICON:-🤖}"
    local instance_id="${APP_INSTANCE_ID:-non defini}"
    local prefix="${APP_NAME_PREFIX:-MY-IA}"
    local debug_mode="${DEBUG:-false}"

    # Masquer partiellement l'instance ID
    local masked_id
    if [[ ${#instance_id} -gt 8 ]]; then
        masked_id="${instance_id:0:8}-****-****-****-************"
    else
        masked_id="$instance_id"
    fi

    # Determiner le mode
    local mode_text
    local mode_color
    if [[ "$debug_mode" == "true" ]]; then
        mode_text="DEVELOPPEMENT (DEBUG=true)"
        mode_color="${YELLOW}"
    else
        mode_text="PRODUCTION (DEBUG=false)"
        mode_color="${GREEN}"
    fi

    echo ""
    echo "============================================================================="
    echo "  ${icon}  ${title} v${version}"
    echo "============================================================================="
    echo ""
    echo "  ${description}"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────────────────"
    echo "  │ Instance ID:  ${masked_id}"
    echo "  │ Prefixe:      ${prefix}"
    echo -e "  │ Mode:         ${mode_color}${mode_text}${NC}"
    echo "  └─────────────────────────────────────────────────────────────────────────"
    echo ""
}

# =============================================================================
# DETECTION DES AUTRES INSTANCES
# =============================================================================
# Detecte les containers Docker d'autres instances MY-IA sur la machine.
#
# Usage:
#   check_other_instances "current_prefix"
#
# Parametres:
#   $1 - Prefixe de l'instance courante (pour l'exclure)
#
# Retour:
#   0 si aucune autre instance trouvee
#   1 si autres instances trouvees (affiche un warning)
# =============================================================================

check_other_instances() {
    local current_prefix="$1"
    local current_sanitized
    current_sanitized=$(sanitize "$current_prefix" false)

    if ! command -v docker &> /dev/null || ! docker info &> /dev/null; then
        return 0
    fi

    # Chercher tous les containers MY-IA (label commun myia.managed=true)
    local other_containers
    other_containers=$(docker ps --filter "label=myia.managed=true" \
        --format "{{.Names}}" 2>/dev/null)

    if [[ -z "$other_containers" ]]; then
        return 0
    fi

    local found_other=false
    local other_prefixes=()

    # Services connus (pour extraire correctement le prefixe)
    local known_services=("postgres" "chroma" "ollama" "app" "ui_front" "ui_back")

    while IFS= read -r container_name; do
        # Extraire le prefixe en testant les suffixes de services connus
        local container_prefix=""
        for service in "${known_services[@]}"; do
            if [[ "$container_name" == *"_${service}" ]]; then
                container_prefix="${container_name%_${service}}"
                break
            fi
        done

        # Si aucun service connu trouve, utiliser la methode simple
        if [[ -z "$container_prefix" ]]; then
            container_prefix="${container_name%_*}"
        fi

        # Ignorer les containers de l'instance courante
        if [[ "$container_prefix" != "$current_sanitized" ]]; then
            found_other=true
            # Ajouter le prefixe a la liste s'il n'y est pas deja
            local already_added=false
            for p in "${other_prefixes[@]}"; do
                if [[ "$p" == "$container_prefix" ]]; then
                    already_added=true
                    break
                fi
            done
            if [[ "$already_added" == "false" && -n "$container_prefix" ]]; then
                other_prefixes+=("$container_prefix")
            fi
        fi
    done <<< "$other_containers"

    if [[ "$found_other" == "true" ]]; then
        echo "" >&2
        log_warn "Autres instances MY-IA detectees sur cette machine:" >&2
        for p in "${other_prefixes[@]}"; do
            echo "  - Prefixe: $p" >&2
        done
        echo "" >&2
        log_warn "Assurez-vous que les ports ne sont pas en conflit." >&2
        echo "" >&2
        return 1
    fi

    return 0
}

# =============================================================================
# VERIFICATION DE L'INSTANCE COURANTE
# =============================================================================
# Verifie si des containers existent pour l'instance courante et propose
# des actions appropriees.
#
# Usage:
#   check_current_instance "prefix" "instance_id"
#
# Parametres:
#   $1 - Prefixe de l'application
#   $2 - Instance ID
#
# Retour:
#   0 si OK pour continuer
#   1 si l'utilisateur a annule
#
# Actions possibles:
#   - Mettre a jour (conserver les donnees)
#   - Reconfigurer (nouveau .env)
#   - Supprimer et reinstaller
# =============================================================================

check_current_instance() {
    local prefix="$1"
    local instance_id="$2"
    local sanitized_prefix
    sanitized_prefix=$(sanitize "$prefix" false)

    if ! command -v docker &> /dev/null || ! docker info &> /dev/null; then
        return 0
    fi

    # Chercher les containers de cette instance
    local containers
    containers=$(docker ps -a --filter "name=^${sanitized_prefix}_" \
        --format "{{.Names}}|{{.Status}}" 2>/dev/null)

    if [[ -z "$containers" ]]; then
        log_info "Aucun container existant pour le prefixe '$sanitized_prefix'"
        return 0
    fi

    # Compter les containers
    local count
    count=$(echo "$containers" | wc -l | tr -d ' ')

    echo "" >&2
    log_info "Containers existants pour '${prefix}' (${count} trouves):" >&2
    while IFS='|' read -r name status; do
        echo "  - $name ($status)" >&2
    done <<< "$containers"
    echo "" >&2

    # Menu d'options
    echo "Options disponibles:" >&2
    echo "  [1] Mettre a jour (conserver donnees et configuration)" >&2
    echo "  [2] Reconfigurer (editer la configuration)" >&2
    echo "  [3] Supprimer et reinstaller (PERTE DE DONNEES)" >&2
    echo "  [4] Annuler" >&2
    echo "" >&2
    printf "Votre choix [1/2/3/4]: " >&2
    read -r choice < /dev/tty

    case "$choice" in
        1)
            log_info "Mise a jour en conservant les donnees..."
            return 0
            ;;
        2)
            log_info "Reconfiguration..."
            # Indiquer qu'il faut editer la config
            FORCE_EDIT_CONFIG=true
            export FORCE_EDIT_CONFIG
            return 0
            ;;
        3)
            log_warn "Suppression des containers et volumes..."
            if confirm "Etes-vous sur ? Cette action est IRREVERSIBLE." "n"; then
                cleanup_project "$sanitized_prefix"
                return 0
            else
                log_error "Operation annulee"
                return 1
            fi
            ;;
        4|*)
            log_error "Operation annulee"
            return 1
            ;;
    esac
}

# =============================================================================
# CHARGEMENT DES VARIABLES D'IDENTITE
# =============================================================================
# Charge toutes les variables d'identite depuis un fichier.
#
# Usage:
#   load_identity_vars "/path/to/file"
#
# Parametres:
#   $1 - Chemin du fichier (.env ou .env.example)
#
# Resultat:
#   Definit les variables globales:
#     APP_ID, APP_NAME_PREFIX, APP_TITLE, APP_DESCRIPTION,
#     APP_ICON, APP_VERSION, APP_INSTANCE_ID
# =============================================================================

load_identity_vars() {
    local file="$1"

    if [[ ! -f "$file" ]]; then
        return 1
    fi

    APP_ID=$(grep "^APP_ID=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
    APP_NAME_PREFIX=$(grep "^APP_NAME_PREFIX=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
    APP_TITLE=$(grep "^APP_TITLE=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
    APP_DESCRIPTION=$(grep "^APP_DESCRIPTION=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
    APP_ICON=$(grep "^APP_ICON=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
    APP_VERSION=$(grep "^APP_VERSION=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
    APP_INSTANCE_ID=$(grep "^APP_INSTANCE_ID=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")
    DEBUG=$(grep "^DEBUG=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"'"'")

    # Valeurs par defaut
    APP_ID="${APP_ID:-my-ia}"
    APP_NAME_PREFIX="${APP_NAME_PREFIX:-MY-IA}"
    APP_TITLE="${APP_TITLE:-MY-IA Assistant}"
    APP_DESCRIPTION="${APP_DESCRIPTION:-Chatbot RAG avec gestion documentaire}"
    APP_ICON="${APP_ICON:-🤖}"
    APP_VERSION="${APP_VERSION:-1.0.0}"
    DEBUG="${DEBUG:-true}"

    export APP_ID APP_NAME_PREFIX APP_TITLE APP_DESCRIPTION APP_ICON APP_VERSION APP_INSTANCE_ID DEBUG
}

# =============================================================================
# DETECTION DE L'ETAT D'INSTALLATION
# =============================================================================
# Detecte si c'est une premiere installation, une mise a jour ou un etat partiel
# en verifiant plusieurs signaux.
#
# Usage:
#   detect_installation_state "/path/to/project" "sanitized_prefix"
#
# Variables exportees:
#   INSTALL_STATE      - "fresh", "existing" ou "partial"
#   SIGNAL_ENV_EXISTS  - true/false
#   SIGNAL_CONTAINERS  - true/false
#   SIGNAL_VOLUMES     - true/false
#   SIGNAL_VENV        - true/false
# =============================================================================

detect_installation_state() {
    local project_root="$1"
    local prefix="${2:-}"
    local signals=0

    # Signal 1 : fichier .env present
    SIGNAL_ENV_EXISTS=false
    if [[ -f "$project_root/.env" ]]; then
        SIGNAL_ENV_EXISTS=true
        signals=$((signals + 1))
    fi

    # Signal 2 : containers Docker du projet
    SIGNAL_CONTAINERS=false
    if [[ -n "$prefix" ]] && command -v docker &> /dev/null && docker info &> /dev/null 2>&1; then
        local container_count
        container_count=$(docker ps -a --filter "name=^${prefix}_" --format "{{.Names}}" 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$container_count" -gt 0 ]]; then
            SIGNAL_CONTAINERS=true
            signals=$((signals + 1))
        fi
    fi

    # Signal 3 : volumes Docker du projet
    SIGNAL_VOLUMES=false
    if [[ -n "$prefix" ]] && command -v docker &> /dev/null && docker info &> /dev/null 2>&1; then
        local volume_count
        volume_count=$(docker volume ls --filter "name=${prefix}_" --format "{{.Name}}" 2>/dev/null | wc -l | tr -d ' ')
        if [[ "$volume_count" -gt 0 ]]; then
            SIGNAL_VOLUMES=true
            signals=$((signals + 1))
        fi
    fi

    # Signal 4 : environnement virtuel Python (bare-metal)
    SIGNAL_VENV=false
    if [[ -d "$project_root/venv" ]]; then
        SIGNAL_VENV=true
        signals=$((signals + 1))
    fi

    # Determiner l'etat
    if [[ $signals -eq 0 ]]; then
        INSTALL_STATE="fresh"
    elif [[ $signals -ge 2 ]]; then
        INSTALL_STATE="existing"
    else
        INSTALL_STATE="partial"
    fi

    export INSTALL_STATE SIGNAL_ENV_EXISTS SIGNAL_CONTAINERS SIGNAL_VOLUMES SIGNAL_VENV
}
