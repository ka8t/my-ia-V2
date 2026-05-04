#!/bin/bash
# =============================================================================
# MY-IA - Fonctions de requetes base de donnees
# =============================================================================
# Ce fichier contient les fonctions pour interroger la base PostgreSQL
# depuis les scripts shell via Docker exec + Python asyncpg.
#
# Fonctions disponibles:
#   _db_query_count()      - Requete COUNT(*) generique
#   _db_query_value()      - Requete retournant une valeur string
#   db_read_config()       - Lire une cle system_configs
#   db_config_available()  - Verifier si la table system_configs existe
#   db_sync_db_to_env()    - Lire la BDD et exporter en variables d'env
#   get_cities_count()     - Compter les villes
#   get_countries_count()  - Compter les pays
#   check_test_users_exist() - Verifier les utilisateurs de test
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/db.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier
#
# =============================================================================

# =============================================================================
# FONCTION GENERIQUE DE REQUETE DB
# =============================================================================
# Execute une requete SQL COUNT(*) dans le container app via asyncpg.
#
# Usage:
#   count=$(_db_query_count "container_name" "SELECT COUNT(*) FROM cities")
#
# Parametres:
#   $1 - Nom du container app
#   $2 - Requete SQL (doit retourner un entier)
#
# Retour:
#   Nombre (entier), ou "0" si erreur
# =============================================================================

_db_query_count() {
    local container_name="$1"
    local sql_query="$2"

    local count
    count=$(docker exec "$container_name" python -c "
import asyncio
import asyncpg
import os
import re

async def get_count():
    url = os.getenv('DATABASE_URL', '')
    pattern = r'^postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)\$'
    match = re.match(pattern, url)
    if not match:
        return 0
    user, password, host, port, database = match.groups()
    conn = await asyncpg.connect(
        user=user.lower(), password=password,
        host=host, port=int(port), database=database.lower()
    )
    try:
        count = await conn.fetchval(\"\"\"${sql_query}\"\"\")
        return count or 0
    finally:
        await conn.close()

print(asyncio.run(get_count()))
" 2>/dev/null) || count="0"

    if [[ "$count" =~ ^[0-9]+$ ]]; then
        echo "$count"
    else
        echo "0"
    fi
}

# =============================================================================
# COMPTAGE DES VILLES EN BASE
# =============================================================================
# Usage:
#   count=$(get_cities_count "container_name")
# =============================================================================

get_cities_count() {
    _db_query_count "$1" "SELECT COUNT(*) FROM cities"
}

# =============================================================================
# COMPTAGE DES PAYS EN BASE
# =============================================================================
# Usage:
#   count=$(get_countries_count "container_name")
# =============================================================================

get_countries_count() {
    _db_query_count "$1" "SELECT COUNT(*) FROM countries"
}

# =============================================================================
# VERIFICATION DES UTILISATEURS DE TEST
# =============================================================================
# Usage:
#   exists=$(check_test_users_exist "container_name")
#   # Retourne "true" ou "false"
# =============================================================================

check_test_users_exist() {
    local count
    count=$(_db_query_count "$1" "SELECT COUNT(*) FROM users WHERE email LIKE '%@test.local'")

    if [[ "$count" -gt 0 ]]; then
        echo "true"
    else
        echo "false"
    fi
}

# =============================================================================
# FONCTION GENERIQUE DE REQUETE DB (STRING)
# =============================================================================
# Execute une requete SQL retournant une valeur string via asyncpg.
# Meme pattern que _db_query_count mais pour les valeurs textuelles.
#
# Usage:
#   value=$(_db_query_value "container_name" "SELECT value FROM system_configs WHERE key = 'app.debug'")
#
# Parametres:
#   $1 - Nom du container app
#   $2 - Requete SQL (doit retourner une seule valeur)
#
# Retour:
#   Valeur string, ou vide si erreur/absent
# =============================================================================

_db_query_value() {
    local container_name="$1"
    local sql_query="$2"

    local result
    result=$(docker exec "$container_name" python -c "
import asyncio
import asyncpg
import os
import re

async def get_value():
    url = os.getenv('DATABASE_URL', '')
    pattern = r'^postgresql\+asyncpg://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)\$'
    match = re.match(pattern, url)
    if not match:
        return ''
    user, password, host, port, database = match.groups()
    conn = await asyncpg.connect(
        user=user.lower(), password=password,
        host=host, port=int(port), database=database.lower()
    )
    try:
        val = await conn.fetchval(\"\"\"${sql_query}\"\"\")
        return val if val is not None else ''
    finally:
        await conn.close()

result = asyncio.run(get_value())
if result:
    print(result, end='')
" 2>/dev/null) || result=""

    echo "$result"
}

# =============================================================================
# VERIFICATION TABLE SYSTEM_CONFIGS
# =============================================================================
# Verifie que la table system_configs existe en base.
# Utile pour savoir si on peut lire/ecrire la configuration.
#
# Usage:
#   if db_config_available "container_name"; then
#       echo "Table system_configs accessible"
#   fi
#
# Retour:
#   0 si la table existe, 1 sinon
# =============================================================================

db_config_available() {
    local container_name="$1"
    local count
    count=$(_db_query_count "$container_name" "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'system_configs'")

    [[ "$count" -gt 0 ]]
}

# =============================================================================
# LECTURE D'UNE CLE SYSTEM_CONFIGS
# =============================================================================
# Lit une valeur dans la table system_configs par sa cle.
#
# Usage:
#   value=$(db_read_config "container_name" "app.deploy_env" "dev")
#
# Parametres:
#   $1 - Nom du container app
#   $2 - Cle (ex: "app.deploy_env")
#   $3 - Valeur par defaut si absent (optionnel)
#
# Retour:
#   Valeur de la cle, ou valeur par defaut
# =============================================================================

db_read_config() {
    local container_name="$1"
    local config_key="$2"
    local default_value="${3:-}"

    local result
    result=$(_db_query_value "$container_name" "SELECT value FROM system_configs WHERE key = '${config_key}' LIMIT 1")

    if [[ -n "$result" ]]; then
        echo "$result"
    else
        echo "$default_value"
    fi
}

# =============================================================================
# SYNCHRONISATION BDD → VARIABLES D'ENVIRONNEMENT
# =============================================================================
# Lit les cles de configuration pertinentes depuis system_configs
# et les exporte comme variables d'environnement (override du .env).
#
# Usage:
#   db_sync_db_to_env "container_name"
#
# Cles synchronisees:
#   app.deploy_env   → DEPLOY_ENV
#   app.debug        → DEBUG
#   app.api_url      → API_URL
#   app.public_host  → PUBLIC_HOST
#   rag.llm_model    → LLM_MODEL
#   rag.embedding_model → EMBED_MODEL
#
# Retour:
#   0 si succes, 1 si echec
# =============================================================================

db_sync_db_to_env() {
    local container_name="$1"

    # Lire toutes les cles pertinentes en une seule requete (string_agg pour fetchval)
    local configs
    configs=$(_db_query_value "$container_name" "SELECT string_agg(key || '=' || value, E'\n') FROM system_configs WHERE key IN ('app.deploy_env', 'app.debug', 'app.api_url', 'app.public_host', 'rag.llm_model', 'rag.embedding_model')")

    if [[ -z "$configs" ]]; then
        return 1
    fi

    # Mapping cle BDD → variable env
    while IFS='=' read -r db_key db_value; do
        [[ -z "$db_key" || -z "$db_value" ]] && continue
        case "$db_key" in
            app.deploy_env)      export DEPLOY_ENV="$db_value" ;;
            app.debug)           export DEBUG="$db_value" ;;
            app.api_url)         export API_URL="$db_value" ;;
            app.public_host)     export PUBLIC_HOST="$db_value" ;;
            rag.llm_model)       export LLM_MODEL="$db_value" ;;
            rag.embedding_model) export EMBED_MODEL="$db_value" ;;
        esac
    done <<< "$configs"

    return 0
}
