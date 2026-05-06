#!/bin/bash
# =============================================================================
# MY-IA - Fonctions de configuration via base de donnees
# =============================================================================
# Ce fichier contient les fonctions pour lire et ecrire la configuration
# depuis/vers la base de donnees PostgreSQL.
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/db-config.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier
#   - Variables de connexion PostgreSQL definies:
#     POSTGRES_HOST, POSTGRES_PORT, APP_DB_USER, APP_DB_PASSWORD, APP_DB_NAME
#
# =============================================================================

# =============================================================================
# VERIFICATION DES PREREQUIS
# =============================================================================

_check_db_config_prereqs() {
    local missing=()

    [[ -z "${APP_DB_USER:-}" ]] && missing+=("APP_DB_USER")
    [[ -z "${APP_DB_NAME:-}" ]] && missing+=("APP_DB_NAME")

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Variables manquantes: ${missing[*]}"
        log_error "Assurez-vous que le fichier .env minimal est charge"
        return 1
    fi

    # Verifier que Docker est disponible
    if ! command -v docker &> /dev/null; then
        log_error "docker non trouve"
        return 1
    fi

    return 0
}

# Determine le nom du container PostgreSQL
_get_postgres_container() {
    local prefix="${SANITIZED_PREFIX:-my_ia_v2}"
    echo "${prefix}_postgres"
}

# =============================================================================
# CONNEXION A LA BASE DE DONNEES
# =============================================================================
# Execute une requete SQL sur la base de donnees.
#
# Usage:
#   result=$(db_query "SELECT value FROM system_configs WHERE key = 'app.name'")
#
# Parametres:
#   $1 - Requete SQL
#   $2 - Format de sortie (optionnel: "raw", "json", defaut: "raw")
#
# Variables d'environnement requises:
#   POSTGRES_HOST, POSTGRES_PORT, APP_DB_USER, APP_DB_PASSWORD, APP_DB_NAME
# =============================================================================

db_query() {
    local query="$1"
    local format="${2:-raw}"

    _check_db_config_prereqs || return 1

    local container
    container=$(_get_postgres_container)
    local user="${APP_DB_USER}"
    local password="${APP_DB_PASSWORD}"
    local dbname="${APP_DB_NAME}"

    # Verifier que le container PostgreSQL est running
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        log_error "Container PostgreSQL ($container) non demarre"
        return 1
    fi

    # Executer via docker exec
    local result
    result=$(docker exec -e PGPASSWORD="$password" "$container" \
        psql -U "$user" -d "$dbname" -t -A -c "$query" 2>/dev/null)

    echo "$result"
}

# =============================================================================
# LECTURE D'UNE CONFIGURATION
# =============================================================================
# Lit une valeur de configuration depuis la base de donnees.
#
# Usage:
#   value=$(db_config_get "app.name")
#   value=$(db_config_get "llm.model" "gemma2:2b")  # Avec valeur par defaut
#
# Parametres:
#   $1 - Cle de configuration (ex: "app.name", "llm.model")
#   $2 - Valeur par defaut (optionnel)
#
# Retour:
#   La valeur de la configuration ou la valeur par defaut
# =============================================================================

db_config_get() {
    local key="$1"
    local default="${2:-}"

    local query="SELECT value FROM system_configs WHERE key = '$key'"
    local value
    value=$(db_query "$query")

    if [[ -n "$value" ]]; then
        echo "$value"
    else
        echo "$default"
    fi
}

# =============================================================================
# ECRITURE D'UNE CONFIGURATION
# =============================================================================
# Ecrit une valeur de configuration dans la base de donnees.
#
# Usage:
#   db_config_set "app.name" "MY-IA"
#   db_config_set "llm.model" "mistral" "string" "llm" "Modele LLM"
#
# Parametres:
#   $1 - Cle de configuration
#   $2 - Valeur
#   $3 - Type (optionnel: "string", "int", "float", "bool", "json")
#   $4 - Categorie (optionnel)
#   $5 - Description (optionnel)
#
# Retour:
#   0 si succes, 1 si erreur
# =============================================================================

db_config_set() {
    local key="$1"
    local value="$2"
    local value_type="${3:-string}"
    local category="${4:-$(echo "$key" | cut -d'.' -f1)}"
    local description="${5:-Configuration $key}"

    # Echapper les apostrophes dans la valeur
    value="${value//\'/\'\'}"
    description="${description//\'/\'\'}"

    local query="INSERT INTO system_configs (key, value, value_type, category, description)
VALUES ('$key', '$value', '$value_type', '$category', '$description')
ON CONFLICT (key) DO UPDATE SET
    value = EXCLUDED.value,
    value_type = EXCLUDED.value_type,
    updated_at = NOW()"

    db_query "$query" > /dev/null
    return $?
}

# =============================================================================
# SUPPRESSION D'UNE CONFIGURATION
# =============================================================================
# Supprime une configuration de la base de donnees.
#
# Usage:
#   db_config_delete "app.old_setting"
#
# Parametres:
#   $1 - Cle de configuration
# =============================================================================

db_config_delete() {
    local key="$1"
    local query="DELETE FROM system_configs WHERE key = '$key'"
    db_query "$query" > /dev/null
}

# =============================================================================
# LISTE DES CONFIGURATIONS
# =============================================================================
# Liste toutes les configurations d'une categorie.
#
# Usage:
#   db_config_list            # Toutes les configs
#   db_config_list "llm"      # Configs de la categorie "llm"
#
# Parametres:
#   $1 - Categorie (optionnel)
#
# Retour:
#   Liste au format "key=value" (une par ligne)
# =============================================================================

db_config_list() {
    local category="${1:-}"

    local query
    if [[ -n "$category" ]]; then
        query="SELECT key || '=' || value FROM system_configs WHERE category = '$category' ORDER BY key"
    else
        query="SELECT key || '=' || value FROM system_configs ORDER BY key"
    fi

    db_query "$query"
}

# =============================================================================
# EXPORT VERS VARIABLES D'ENVIRONNEMENT
# =============================================================================
# Exporte toutes les configurations vers des variables d'environnement.
#
# Usage:
#   eval "$(db_config_export)"
#   # Ou pour une categorie specifique:
#   eval "$(db_config_export "llm")"
#
# Parametres:
#   $1 - Categorie (optionnel)
#
# Retour:
#   Commandes export shell
# =============================================================================

db_config_export() {
    local category="${1:-}"

    # Mapping des cles vers les variables d'environnement
    declare -A KEY_TO_ENV=(
        ["app.id"]="APP_ID"
        ["app.name_prefix"]="APP_NAME_PREFIX"
        ["app.title"]="APP_TITLE"
        ["app.version"]="APP_VERSION"
        ["app.host"]="APP_HOST"
        ["app.port"]="APP_PORT"
        ["app.environment"]="ENVIRONMENT"
        ["app.debug"]="DEBUG"
        ["ports.frontend"]="FRONTEND_PORT"
        ["ports.admin"]="ADMIN_PORT"
        ["ports.api"]="APP_PORT"
        ["public.host"]="PUBLIC_HOST"
        ["public.protocol"]="PUBLIC_PROTOCOL"
        ["llm.provider"]="LLM_PROVIDER"
        ["llm.model"]="LLM_MODEL"
        ["llm.embed_model"]="EMBED_MODEL"
        ["ollama.host"]="OLLAMA_HOST"
        ["ollama.port"]="OLLAMA_PORT"
        ["ollama.timeout"]="OLLAMA_TIMEOUT"
        ["chroma.host"]="CHROMA_HOST"
        ["chroma.port"]="CHROMA_PORT"
        ["chroma.collection_name"]="COLLECTION_NAME"
        ["rag.top_k"]="TOP_K"
        ["rag.chunk_size"]="CHUNK_SIZE"
        ["rag.chunk_overlap"]="CHUNK_OVERLAP"
        ["logging.level"]="LOG_LEVEL"
        ["security.jwt_secret"]="JWT_SECRET_KEY"
        ["security.secret_key"]="SECRET_KEY"
        ["security.encryption_key"]="ENCRYPTION_KEY"
        ["security.api_key"]="API_KEY"
        ["cors.origins"]="CORS_ORIGINS"
        ["rate_limit.chat"]="RATE_LIMIT_CHAT"
        ["rate_limit.upload"]="RATE_LIMIT_UPLOAD"
        ["rate_limit.stream"]="RATE_LIMIT_STREAM"
        ["email.backend"]="EMAIL_BACKEND"
        ["email.from"]="EMAIL_FROM"
        ["sms.backend"]="SMS_BACKEND"
    )

    local query
    if [[ -n "$category" ]]; then
        query="SELECT key, value FROM system_configs WHERE category = '$category'"
    else
        query="SELECT key, value FROM system_configs"
    fi

    # Executer la requete et generer les exports
    while IFS='|' read -r key value; do
        [[ -z "$key" ]] && continue

        local env_var="${KEY_TO_ENV[$key]:-}"

        if [[ -n "$env_var" ]]; then
            # Echapper les caracteres speciaux pour le shell
            value="${value//\\/\\\\}"
            value="${value//\"/\\\"}"
            echo "export $env_var=\"$value\""
        fi
    done < <(db_query "$query" | tr '\t' '|')
}

# =============================================================================
# IMPORT DEPUIS FICHIER JSON
# =============================================================================
# Importe la configuration depuis un fichier JSON.
#
# Usage:
#   db_config_import "/path/to/config.json"
#
# Format du fichier JSON:
#   {
#     "app.name": "MY-IA",
#     "llm.model": "mistral",
#     ...
#   }
#
# Parametres:
#   $1 - Chemin du fichier JSON
#
# Retour:
#   0 si succes, 1 si erreur
# =============================================================================

db_config_import() {
    local json_file="$1"

    if [[ ! -f "$json_file" ]]; then
        log_error "Fichier non trouve: $json_file"
        return 1
    fi

    if ! command -v jq &> /dev/null; then
        log_error "jq non trouve - installez jq"
        return 1
    fi

    log_info "Import de la configuration depuis $json_file..."

    local count=0
    while IFS='=' read -r key value; do
        [[ -z "$key" ]] && continue

        # Determiner le type
        local value_type="string"
        if [[ "$value" =~ ^[0-9]+$ ]]; then
            value_type="int"
        elif [[ "$value" =~ ^[0-9]+\.[0-9]+$ ]]; then
            value_type="float"
        elif [[ "$value" == "true" || "$value" == "false" ]]; then
            value_type="bool"
        elif [[ "$value" =~ ^\[.*\]$ || "$value" =~ ^\{.*\}$ ]]; then
            value_type="json"
        fi

        db_config_set "$key" "$value" "$value_type"
        ((count++))
    done < <(jq -r 'to_entries | .[] | "\(.key)=\(.value)"' "$json_file")

    log_success "$count configurations importees"
    return 0
}

# =============================================================================
# EXPORT VERS FICHIER JSON
# =============================================================================
# Exporte la configuration vers un fichier JSON.
#
# Usage:
#   db_config_dump "/path/to/config.json"
#   db_config_dump  # Affiche sur stdout
#
# Parametres:
#   $1 - Chemin du fichier de sortie (optionnel)
#
# Retour:
#   JSON de la configuration
# =============================================================================

db_config_dump() {
    local output_file="${1:-}"

    local query="SELECT json_object_agg(key, value) FROM system_configs"
    local json
    json=$(db_query "$query")

    if [[ -n "$output_file" ]]; then
        echo "$json" | jq '.' > "$output_file"
        log_success "Configuration exportee vers $output_file"
    else
        echo "$json" | jq '.'
    fi
}

# =============================================================================
# VERIFICATION DE LA TABLE SYSTEM_CONFIG
# =============================================================================
# Verifie si la table system_configs existe et est accessible.
#
# Usage:
#   if db_config_check; then
#       echo "Table OK"
#   fi
#
# Retour:
#   0 si la table existe et est accessible, 1 sinon
# =============================================================================

db_config_check() {
    local query="SELECT EXISTS (
        SELECT FROM information_schema.tables
        WHERE table_name = 'system_configs'
    )"

    local result
    result=$(db_query "$query")

    if [[ "$result" == "t" ]]; then
        return 0
    else
        return 1
    fi
}

# =============================================================================
# INITIALISATION DE LA CONFIGURATION PAR DEFAUT
# =============================================================================
# Insere les valeurs par defaut si la table est vide.
#
# Usage:
#   db_config_init
#
# Retour:
#   0 si succes ou deja initialisee, 1 si erreur
# =============================================================================

db_config_init() {
    log_info "Verification de la configuration en base..."

    # Verifier si la table existe
    if ! db_config_check; then
        log_warn "Table system_configs non trouvee - sera creee au demarrage de l'app"
        return 0
    fi

    # Verifier si des configs existent
    local count
    count=$(db_query "SELECT COUNT(*) FROM system_configs")

    if [[ "$count" -gt 0 ]]; then
        log_success "Configuration existante: $count parametres"
        return 0
    fi

    log_info "Table vide - initialisation avec les valeurs par defaut..."

    # Utiliser le script Python pour l'initialisation complete
    if [[ -f "${PROJECT_ROOT:-$(pwd)}/app/core/bootstrap.py" ]]; then
        cd "${PROJECT_ROOT:-$(pwd)}"
        python -c "
from app.core.bootstrap import bootstrap_sync
config = bootstrap_sync()
print(f'Initialisation terminee: {len(config)} parametres')
"
        return $?
    else
        log_warn "Script bootstrap.py non trouve - initialisation manuelle requise"
        return 1
    fi
}

# =============================================================================
# SYNCHRONISATION ENV -> BDD
# =============================================================================
# Synchronise les variables d'environnement vers la base de donnees.
# Utile pour migrer depuis un ancien .env complet vers la config BDD.
#
# Usage:
#   db_config_sync_from_env
#
# Retour:
#   0 si succes, 1 si erreur
# =============================================================================

db_config_sync_from_env() {
    log_info "Synchronisation des variables d'environnement vers la BDD..."

    local count=0

    # Mapping inverse: ENV -> DB key
    declare -A ENV_TO_KEY=(
        ["APP_NAME_PREFIX"]="app.name_prefix"
        ["APP_TITLE"]="app.title"
        ["APP_VERSION"]="app.version"
        ["DEBUG"]="app.debug"
        ["ENVIRONMENT"]="app.environment"
        ["FRONTEND_PORT"]="ports.frontend"
        ["ADMIN_PORT"]="ports.admin"
        ["APP_PORT"]="ports.api"
        ["PUBLIC_HOST"]="public.host"
        ["PUBLIC_PROTOCOL"]="public.protocol"
        ["LLM_PROVIDER"]="llm.provider"
        ["LLM_MODEL"]="llm.model"
        ["EMBED_MODEL"]="llm.embed_model"
        ["OLLAMA_HOST"]="ollama.host"
        ["OLLAMA_PORT"]="ollama.port"
        ["CHROMA_HOST"]="chroma.host"
        ["CHROMA_PORT"]="chroma.port"
        ["TOP_K"]="rag.top_k"
        ["CHUNK_SIZE"]="rag.chunk_size"
        ["LOG_LEVEL"]="logging.level"
        ["JWT_SECRET_KEY"]="security.jwt_secret"
        ["SECRET_KEY"]="security.secret_key"
        ["ENCRYPTION_KEY"]="security.encryption_key"
        ["API_KEY"]="security.api_key"
        ["EMAIL_BACKEND"]="email.backend"
        ["EMAIL_FROM"]="email.from"
        ["SMS_BACKEND"]="sms.backend"
    )

    for env_var in "${!ENV_TO_KEY[@]}"; do
        local value="${!env_var:-}"
        if [[ -n "$value" ]]; then
            local db_key="${ENV_TO_KEY[$env_var]}"
            db_config_set "$db_key" "$value"
            ((count++))
            log_debug "Sync: $env_var -> $db_key = $value"
        fi
    done

    log_success "$count variables synchronisees vers la BDD"
    return 0
}

# =============================================================================
# AFFICHAGE DU STATUS
# =============================================================================
# Affiche le status de la configuration en base.
#
# Usage:
#   db_config_status
# =============================================================================

db_config_status() {
    echo ""
    echo "============================================="
    echo "        STATUS CONFIGURATION BDD"
    echo "============================================="
    echo ""

    # Verifier la connexion
    if ! _check_db_config_prereqs 2>/dev/null; then
        echo "  Status: ERREUR - Prerequis manquants"
        return 1
    fi

    # Verifier la table
    if ! db_config_check; then
        echo "  Status: TABLE NON TROUVEE"
        echo "  La table system_configs n'existe pas encore."
        echo "  Elle sera creee au premier demarrage de l'application."
        return 0
    fi

    # Compter les configurations
    local total
    total=$(db_query "SELECT COUNT(*) FROM system_configs")

    local categories
    categories=$(db_query "SELECT DISTINCT category FROM system_configs ORDER BY category")

    echo "  Status: OK"
    echo "  Total configs: $total"
    echo ""
    echo "  Categories:"
    echo "$categories" | while read -r cat; do
        local cat_count
        cat_count=$(db_query "SELECT COUNT(*) FROM system_configs WHERE category = '$cat'")
        echo "    - $cat: $cat_count parametres"
    done
    echo ""
    echo "============================================="
}
