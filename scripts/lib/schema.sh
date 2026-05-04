#!/bin/bash
# =============================================================================
# MY-IA - Fonctions de verification et synchronisation du schema BDD
# =============================================================================
# Compare les structures de tables entre local et remote.
# Ajoute automatiquement les colonnes manquantes sur le serveur distant.
# =============================================================================

# -----------------------------------------------------------------------------
# get_schema_columns
# Retourne la liste des colonnes au format: table_name|column_name|data_type
# Usage: get_schema_columns "local" ou get_schema_columns "remote"
# -----------------------------------------------------------------------------
get_schema_columns() {
    local target="$1"
    local query="SELECT table_name || '|' || column_name || '|' || data_type || '|' || is_nullable
                 FROM information_schema.columns
                 WHERE table_schema = 'public'
                 AND table_name NOT LIKE 'alembic%'
                 ORDER BY table_name, ordinal_position;"

    if [[ "$target" == "local" ]]; then
        ./scripts/psql.sh -t -c "$query" 2>/dev/null | grep -v "^$" | sed 's/^ *//'
    else
        ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" \
            "cd ${DEPLOY_REMOTE_PATH} && docker compose exec -T postgres psql -U \${APP_DB_USER:-my_ia_db_user} -d \${APP_DB_NAME:-my_ia_db} -t -c \"$query\"" 2>/dev/null \
            | grep -v "^$" | sed 's/^ *//'
    fi
}

# -----------------------------------------------------------------------------
# compare_schemas
# Compare les schemas local et remote, retourne les colonnes manquantes
# Output: table_name|column_name|data_type par ligne
# -----------------------------------------------------------------------------
compare_schemas() {
    local local_schema remote_schema

    log_info "Recuperation du schema local..."
    local_schema=$(get_schema_columns "local")

    log_info "Recuperation du schema distant..."
    remote_schema=$(get_schema_columns "remote")

    # Extraire juste table|column pour la comparaison
    local local_cols remote_cols
    local_cols=$(echo "$local_schema" | cut -d'|' -f1,2 | sort -u)
    remote_cols=$(echo "$remote_schema" | cut -d'|' -f1,2 | sort -u)

    # Trouver les colonnes manquantes sur remote
    local missing
    missing=$(comm -23 <(echo "$local_cols") <(echo "$remote_cols"))

    if [[ -z "$missing" ]]; then
        return 0
    fi

    # Pour chaque colonne manquante, retrouver le type
    while IFS='|' read -r table column; do
        [[ -z "$table" ]] && continue
        local type_info
        type_info=$(echo "$local_schema" | grep "^${table}|${column}|" | head -1)
        echo "$type_info"
    done <<< "$missing"
}

# -----------------------------------------------------------------------------
# map_pg_type
# Convertit un type PostgreSQL information_schema vers un type SQL valide
# -----------------------------------------------------------------------------
map_pg_type() {
    local type="$1"
    local nullable="$2"

    case "$type" in
        "character varying")
            echo "VARCHAR(255)"
            ;;
        "integer")
            echo "INTEGER"
            ;;
        "bigint")
            echo "BIGINT"
            ;;
        "boolean")
            echo "BOOLEAN"
            ;;
        "text")
            echo "TEXT"
            ;;
        "timestamp with time zone"|"timestamp without time zone")
            echo "TIMESTAMP"
            ;;
        "uuid")
            echo "UUID"
            ;;
        "jsonb")
            echo "JSONB"
            ;;
        "json")
            echo "JSON"
            ;;
        "double precision")
            echo "DOUBLE PRECISION"
            ;;
        "real")
            echo "REAL"
            ;;
        "numeric")
            echo "NUMERIC"
            ;;
        "bytea")
            echo "BYTEA"
            ;;
        *)
            echo "$type"
            ;;
    esac
}

# -----------------------------------------------------------------------------
# sync_missing_columns
# Ajoute les colonnes manquantes sur le serveur distant
# -----------------------------------------------------------------------------
sync_missing_columns() {
    local missing_columns
    missing_columns=$(compare_schemas)

    if [[ -z "$missing_columns" ]]; then
        log_success "Schema synchronise (aucune colonne manquante)"
        return 0
    fi

    log_warn "Colonnes manquantes sur le serveur distant:"
    echo "$missing_columns" | while IFS='|' read -r table column type nullable; do
        echo "  - $table.$column ($type)"
    done
    echo ""

    # Appliquer les modifications
    local count=0
    while IFS='|' read -r table column type nullable; do
        [[ -z "$table" ]] && continue

        local pg_type
        pg_type=$(map_pg_type "$type" "$nullable")

        log_info "Ajout de $table.$column ($pg_type)..."

        ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" \
            "cd ${DEPLOY_REMOTE_PATH} && docker compose exec -T postgres psql -U \${APP_DB_USER:-my_ia_db_user} -d \${APP_DB_NAME:-my_ia_db} -c \"ALTER TABLE $table ADD COLUMN IF NOT EXISTS $column $pg_type;\"" 2>/dev/null

        ((count++))
    done <<< "$missing_columns"

    if [[ $count -gt 0 ]]; then
        log_success "$count colonne(s) ajoutee(s)"

        # Redemarrer l'app pour prendre en compte les changements
        log_info "Redemarrage de l'application..."
        ssh "${DEPLOY_REMOTE_USER}@${DEPLOY_REMOTE_HOST}" \
            "cd ${DEPLOY_REMOTE_PATH} && docker compose restart app" 2>/dev/null
        sleep 5
    fi

    return 0
}

# -----------------------------------------------------------------------------
# remote_check_schema
# Point d'entree pour la verification de schema dans remote_deploy
# -----------------------------------------------------------------------------
remote_check_schema() {
    log_info "Verification du schema de base de donnees..."

    if ! sync_missing_columns; then
        log_warn "Erreur lors de la synchronisation du schema"
        return 1
    fi

    return 0
}
