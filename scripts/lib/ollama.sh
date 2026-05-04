#!/bin/bash
# =============================================================================
# MY-IA - Fonctions de gestion Ollama (unifiees Docker/natif)
# =============================================================================
# Ce fichier contient les fonctions pour gerer les modeles Ollama.
# Les fonctions sont unifiees : elles detectent automatiquement si Ollama
# tourne dans Docker ou nativement, et adaptent les commandes en consequence.
#
# Detection du backend (priorite) :
#   1. Variable OLLAMA_MODE="native" (mode mixed, set par deploy.sh)
#   2. Container Docker running (nom: ${SANITIZED_PREFIX}_ollama)
#   3. CLI ollama natif disponible
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/ollama.sh"
#
#   detect_ollama_backend                    # Detecte et exporte OLLAMA_BACKEND
#   ollama_list                              # Liste les modeles
#   ollama_has_model "gemma2:2b"             # Verifie si un modele est installe
#   ollama_pull "gemma2:2b"                  # Telecharge un modele
#   ollama_manage_model "gemma2:2b" "LLM"   # Gestion interactive
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier
#
# =============================================================================

# Backend detecte : "docker" ou "native"
OLLAMA_BACKEND=""
# Nom du container (defini par detect_ollama_backend si Docker)
OLLAMA_CONTAINER=""

# =============================================================================
# DETECTION DU BACKEND OLLAMA
# =============================================================================
# Detecte automatiquement si Ollama est disponible via Docker ou en natif.
# Exporte OLLAMA_BACKEND ("docker"/"native") et OLLAMA_CONTAINER.
#
# Usage:
#   if detect_ollama_backend; then
#       echo "Ollama disponible via $OLLAMA_BACKEND"
#   fi
#
# Retour:
#   0 si un backend est trouve, 1 sinon
# =============================================================================

detect_ollama_backend() {
    OLLAMA_BACKEND=""
    OLLAMA_CONTAINER=""

    # 1. Si OLLAMA_MODE est explicitement "native" (mode mixed)
    if [[ "${OLLAMA_MODE:-}" == "native" ]]; then
        if command -v ollama &> /dev/null; then
            OLLAMA_BACKEND="native"
            export OLLAMA_BACKEND OLLAMA_CONTAINER
            log_debug "[detect_ollama_backend] Mode natif (OLLAMA_MODE=native)"
            return 0
        fi
    fi

    # 2. Container Docker running ?
    local container="${SANITIZED_PREFIX:-}_ollama"
    if docker ps --format "{{.Names}}" 2>/dev/null | grep -q "^${container}$"; then
        OLLAMA_BACKEND="docker"
        OLLAMA_CONTAINER="$container"
        export OLLAMA_BACKEND OLLAMA_CONTAINER
        log_debug "[detect_ollama_backend] Backend Docker: $container"
        return 0
    fi

    # 3. CLI ollama natif disponible ?
    if command -v ollama &> /dev/null && ollama list &> /dev/null; then
        OLLAMA_BACKEND="native"
        export OLLAMA_BACKEND
        log_debug "[detect_ollama_backend] Fallback natif (CLI ollama)"
        return 0
    fi

    # Aucun backend trouve
    export OLLAMA_BACKEND OLLAMA_CONTAINER
    log_warn "Ollama non disponible (ni Docker, ni natif)"
    return 1
}

# =============================================================================
# ATTENTE DU DEMARRAGE D'OLLAMA
# =============================================================================
# Attend que Ollama soit pret (Docker ou natif).
#
# Usage:
#   wait_for_ollama_ready 30
#
# Parametres:
#   $1 - Timeout en secondes (defaut: 30)
#
# Retour:
#   0 si pret, 1 si timeout
# =============================================================================

wait_for_ollama_ready() {
    local timeout="${1:-30}"
    local elapsed=0

    log_info "Attente du demarrage d'Ollama..."

    while [[ $elapsed -lt $timeout ]]; do
        if [[ "$OLLAMA_BACKEND" == "docker" && -n "$OLLAMA_CONTAINER" ]]; then
            if docker exec "$OLLAMA_CONTAINER" ollama list &> /dev/null; then
                log_success "Ollama pret (Docker: $OLLAMA_CONTAINER)"
                return 0
            fi
        elif [[ "$OLLAMA_BACKEND" == "native" ]]; then
            if ollama list &> /dev/null; then
                log_success "Ollama pret (natif)"
                return 0
            fi
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done

    log_warn "Timeout: Ollama n'est pas pret apres ${timeout}s"
    return 1
}

# =============================================================================
# LISTE DES MODELES INSTALLES
# =============================================================================
# Retourne la liste des modeles Ollama installes (unifie Docker/natif).
#
# Usage:
#   models=$(ollama_list)
#
# Retour:
#   Liste des modeles (un par ligne) au format: nom taille
# =============================================================================

ollama_list() {
    if [[ "$OLLAMA_BACKEND" == "docker" && -n "$OLLAMA_CONTAINER" ]]; then
        docker exec "$OLLAMA_CONTAINER" ollama list 2>/dev/null | tail -n +2
    elif [[ "$OLLAMA_BACKEND" == "native" ]]; then
        ollama list 2>/dev/null | tail -n +2
    fi
}

# =============================================================================
# VERIFICATION D'UN MODELE
# =============================================================================
# Verifie si un modele est installe (unifie Docker/natif).
#
# Usage:
#   if ollama_has_model "gemma2:2b"; then
#       echo "Modele installe"
#   fi
#
# Parametres:
#   $1 - Nom du modele
#
# Retour:
#   0 si installe, 1 sinon
# =============================================================================

ollama_has_model() {
    local model_name="$1"

    if [[ "$OLLAMA_BACKEND" == "docker" && -n "$OLLAMA_CONTAINER" ]]; then
        docker exec "$OLLAMA_CONTAINER" ollama list 2>/dev/null | grep -q "^${model_name}"
    elif [[ "$OLLAMA_BACKEND" == "native" ]]; then
        ollama list 2>/dev/null | grep -q "^${model_name}"
    else
        return 1
    fi
}

# =============================================================================
# TELECHARGEMENT D'UN MODELE
# =============================================================================
# Telecharge un modele Ollama (unifie Docker/natif).
#
# Usage:
#   ollama_pull "gemma2:2b"
#
# Parametres:
#   $1 - Nom du modele
#
# Retour:
#   0 si succes, 1 si erreur
# =============================================================================

ollama_pull() {
    local model_name="$1"

    log_info "Telechargement de $model_name..."
    if [[ "$OLLAMA_BACKEND" == "docker" && -n "$OLLAMA_CONTAINER" ]]; then
        if docker exec "$OLLAMA_CONTAINER" ollama pull "$model_name"; then
            log_success "Modele $model_name telecharge (Docker)"
            return 0
        fi
    elif [[ "$OLLAMA_BACKEND" == "native" ]]; then
        if ollama pull "$model_name"; then
            log_success "Modele $model_name telecharge (natif)"
            return 0
        fi
    fi

    log_error "Erreur lors du telechargement de $model_name"
    return 1
}

# =============================================================================
# GESTION D'UN MODELE (INTERACTIF)
# =============================================================================
# Gere un modele Ollama de maniere interactive (unifie Docker/natif).
#
# Usage:
#   ollama_manage_model "gemma2:2b" "LLM"
#
# Parametres:
#   $1 - Nom du modele
#   $2 - Type de modele ("LLM" ou "Embeddings")
#
# Actions:
#   - Si modele existe: propose mise a jour
#   - Si modele n'existe pas: propose telechargement
# =============================================================================

ollama_manage_model() {
    local model_name="$1"
    local model_type="$2"

    # Verifier si le modele existe
    local model_info=""
    if [[ "$OLLAMA_BACKEND" == "docker" && -n "$OLLAMA_CONTAINER" ]]; then
        model_info=$(docker exec "$OLLAMA_CONTAINER" ollama list 2>/dev/null | grep "^$model_name" || true)
    elif [[ "$OLLAMA_BACKEND" == "native" ]]; then
        model_info=$(ollama list 2>/dev/null | grep "^$model_name" || true)
    fi

    if [[ -n "$model_info" ]]; then
        # Modele existe - extraire les infos (taille)
        local model_size
        model_size=$(echo "$model_info" | awk '{print $3, $4}')
        log_success "Modele $model_type: $model_name ($model_size) [$OLLAMA_BACKEND]"

        if confirm "  Mettre a jour/re-telecharger ce modele ?" "n"; then
            ollama_pull "$model_name"
        fi
    else
        # Modele n'existe pas
        log_warn "Modele $model_type non trouve: $model_name"

        if confirm "  Telecharger ce modele ? (peut prendre plusieurs minutes)" "y"; then
            ollama_pull "$model_name"
        else
            log_warn "Modele $model_name non telecharge - l'application pourrait ne pas fonctionner"
        fi
    fi
}

# =============================================================================
# GESTION DE TOUS LES MODELES
# =============================================================================
# Gere tous les modeles configures. Detecte automatiquement le backend.
#
# Usage:
#   manage_all_models
#
# Prerequis:
#   Variables globales definies: SANITIZED_PREFIX, LLM_MODEL, EMBED_MODEL
# =============================================================================

manage_all_models() {
    log_step "Verification des modeles Ollama..."

    # Detecter le backend si pas deja fait
    if [[ -z "$OLLAMA_BACKEND" ]]; then
        if ! detect_ollama_backend; then
            log_warn "Les modeles devront etre telecharges manuellement"
            return 1
        fi
    fi

    # Attendre qu'Ollama soit pret
    if ! wait_for_ollama_ready 60; then
        log_warn "Ollama n'est pas pret, les modeles devront etre telecharges manuellement"
        return 1
    fi

    # Recuperer les modeles configures
    local llm_model="${LLM_MODEL:-gemma2:2b}"
    local embed_model="${EMBED_MODEL:-nomic-embed-text}"

    echo ""
    log_info "Modeles configures dans .env:"
    echo "  - LLM (generation):    $llm_model"
    echo "  - Embeddings (RAG):    $embed_model"
    echo ""

    # Lister les modeles installes
    log_info "Modeles actuellement installes [$OLLAMA_BACKEND]:"
    local installed_models
    installed_models=$(ollama_list)
    if [[ -n "$installed_models" ]]; then
        echo "$installed_models" | while read -r line; do
            echo "  - $line"
        done
    else
        echo "  (aucun modele installe)"
    fi
    echo ""

    # Gerer les modeles
    ollama_manage_model "$llm_model" "LLM"
    ollama_manage_model "$embed_model" "Embeddings"
}

# =============================================================================
# TELECHARGEMENT AUTOMATIQUE DES MODELES
# =============================================================================
# Telecharge les modeles manquants sans interaction (mode --auto).
# Detecte automatiquement le backend.
#
# Usage:
#   auto_download_models
#
# Prerequis:
#   Variables globales definies: SANITIZED_PREFIX, LLM_MODEL, EMBED_MODEL
# =============================================================================

auto_download_models() {
    # Detecter le backend si pas deja fait
    if [[ -z "$OLLAMA_BACKEND" ]]; then
        if ! detect_ollama_backend; then
            log_warn "Ollama non disponible, modeles non telecharges"
            return 1
        fi
    fi

    # Attendre qu'Ollama soit pret
    if ! wait_for_ollama_ready 60; then
        log_warn "Ollama non pret, modeles non telecharges"
        return 1
    fi

    local llm_model="${LLM_MODEL:-gemma2:2b}"
    local embed_model="${EMBED_MODEL:-nomic-embed-text}"

    if ! ollama_has_model "$llm_model"; then
        ollama_pull "$llm_model"
    else
        log_success "Modele LLM deja present: $llm_model"
    fi

    if ! ollama_has_model "$embed_model"; then
        ollama_pull "$embed_model"
    else
        log_success "Modele Embeddings deja present: $embed_model"
    fi
}

# =============================================================================
# AFFICHAGE DU MENU OLLAMA
# =============================================================================
# Affiche le menu de gestion des modeles Ollama.
#
# Usage:
#   show_ollama_menu
# =============================================================================

show_ollama_menu() {
    echo ""
    echo "============================================================================="
    echo "  MODELES OLLAMA"
    echo "============================================================================="
    echo ""

    # Detecter le backend
    if ! detect_ollama_backend; then
        log_warn "Ollama non disponible (ni Docker, ni natif)"
        return 1
    fi

    log_info "Backend detecte: $OLLAMA_BACKEND"
    echo ""

    # Lister les modeles
    log_info "Modeles installes:"
    local installed_models
    installed_models=$(ollama_list)
    if [[ -n "$installed_models" ]]; then
        echo "$installed_models" | while read -r line; do
            echo "  - $line"
        done
    else
        echo "  (aucun modele installe)"
    fi
    echo ""

    echo "Modeles configures:"
    echo "  - LLM:        ${LLM_MODEL:-gemma2:2b}"
    echo "  - Embeddings: ${EMBED_MODEL:-nomic-embed-text}"
    echo ""

    echo "Options:"
    echo "  [1] Telecharger/Mettre a jour les modeles configures"
    echo "  [2] Telecharger un modele personnalise"
    echo "  [3] Ignorer"
    echo ""
    printf "Votre choix [1/2/3]: "
    read -r choice < /dev/tty

    case "$choice" in
        1)
            manage_all_models
            ;;
        2)
            echo ""
            printf "Nom du modele a telecharger: "
            read -r custom_model < /dev/tty
            if [[ -n "$custom_model" ]]; then
                ollama_pull "$custom_model"
            fi
            ;;
        3|*)
            log_info "Gestion des modeles ignoree"
            ;;
    esac
}
