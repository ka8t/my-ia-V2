#!/bin/bash
# =============================================================================
# MY-IA - Script de backup (PostgreSQL + ChromaDB)
# =============================================================================
# Sauvegarde la base de donnees PostgreSQL (pg_dump) et le volume ChromaDB.
#
# Usage:
#   ./scripts/backup.sh                    # Backup interactif
#   ./scripts/backup.sh --auto             # Backup silencieux (cron)
#   ./scripts/backup.sh --db-only          # PostgreSQL uniquement
#   ./scripts/backup.sh --chroma-only      # ChromaDB uniquement
#   ./scripts/backup.sh --keep 7           # Garder les 7 derniers backups
#
# Cron (backup quotidien a 3h du matin):
#   0 3 * * * /chemin/vers/scripts/backup.sh --auto >> /var/log/myia-backup.log 2>&1
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

# Chargement des modules
source "$SCRIPT_DIR/lib/common.sh"

# =============================================================================
# OPTIONS
# =============================================================================

AUTO_MODE=false
DB_ONLY=false
CHROMA_ONLY=false
KEEP_LAST=10
BACKUP_DIR="$PROJECT_ROOT/backups"

for arg in "$@"; do
    case "$arg" in
        --auto|-y)
            AUTO_MODE=true
            ;;
        --db-only)
            DB_ONLY=true
            ;;
        --chroma-only)
            CHROMA_ONLY=true
            ;;
        --keep)
            shift
            KEEP_LAST="${1:-10}"
            ;;
        --keep=*)
            KEEP_LAST="${arg#*=}"
            ;;
        -h|--help)
            cat << 'EOF'
MY-IA - Script de backup
=========================

USAGE:
    ./scripts/backup.sh [OPTIONS]

OPTIONS:
    --auto, -y       Mode silencieux (pour cron)
    --db-only        Sauvegarder uniquement PostgreSQL
    --chroma-only    Sauvegarder uniquement ChromaDB
    --keep N         Nombre de backups a conserver (defaut: 10)
    -h, --help       Affiche cette aide

EXEMPLES:
    ./scripts/backup.sh                    # Backup complet interactif
    ./scripts/backup.sh --auto             # Backup complet silencieux
    ./scripts/backup.sh --auto --keep 7    # Backup + garder 7 derniers
    ./scripts/backup.sh --db-only          # PostgreSQL uniquement

RESTAURATION:
    ./scripts/restore.sh backups/myia_db_20260204_030000.sql.gz
    ./scripts/restore.sh backups/myia_chroma_20260204_030000.tar.gz

CRON (backup quotidien a 3h):
    0 3 * * * /chemin/scripts/backup.sh --auto >> /var/log/myia-backup.log 2>&1

EOF
            exit 0
            ;;
    esac
done

# =============================================================================
# VERIFICATION PREREQUIS
# =============================================================================

if [[ ! -f "$ENV_FILE" ]]; then
    die "Fichier .env non trouve. Lancez d'abord ./scripts/start.sh"
fi

# Charger les variables
set +e
source "$ENV_FILE"
set -e

SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Creer le dossier de backups
mkdir -p "$BACKUP_DIR"

# =============================================================================
# BACKUP POSTGRESQL
# =============================================================================

backup_postgres() {
    local container="${SANITIZED_PREFIX}_postgres"
    local db_name="${APP_DB_NAME}"
    local db_user="${POSTGRES_USER}"
    local backup_file="${BACKUP_DIR}/${SANITIZED_PREFIX}_db_${TIMESTAMP}.sql.gz"

    log_step "Backup PostgreSQL ($db_name)..."

    # Verifier que le container tourne
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        fail "Container $container non trouve" || return 1
    fi

    # pg_dump compresse avec gzip
    if docker exec "$container" pg_dump -U "$db_user" -d "$db_name" \
        --no-owner --no-privileges --clean --if-exists \
        | gzip > "$backup_file" 2>/dev/null; then

        local size
        size=$(du -sh "$backup_file" | cut -f1)
        log_success "PostgreSQL sauvegarde: ${backup_file##*/} ($size)"

        # Backup N8N si la base existe
        local n8n_db="${N8N_DB_NAME:-}"
        if [[ -n "$n8n_db" ]]; then
            local n8n_backup="${BACKUP_DIR}/${SANITIZED_PREFIX}_n8n_${TIMESTAMP}.sql.gz"
            if docker exec "$container" pg_dump -U "$db_user" -d "$n8n_db" \
                --no-owner --no-privileges --clean --if-exists \
                2>/dev/null | gzip > "$n8n_backup" 2>/dev/null; then
                local n8n_size
                n8n_size=$(du -sh "$n8n_backup" | cut -f1)
                log_success "N8N sauvegarde: ${n8n_backup##*/} ($n8n_size)"
            else
                rm -f "$n8n_backup"
                log_warn "Backup N8N ignore (base $n8n_db non accessible)"
            fi
        fi
    else
        rm -f "$backup_file"
        log_error "Echec du backup PostgreSQL"
        return 1
    fi
}

# =============================================================================
# BACKUP CHROMADB
# =============================================================================

backup_chroma() {
    local container="${SANITIZED_PREFIX}_chroma"
    local backup_file="${BACKUP_DIR}/${SANITIZED_PREFIX}_chroma_${TIMESTAMP}.tar.gz"

    log_step "Backup ChromaDB..."

    # Verifier que le container tourne
    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        fail "Container $container non trouve" || return 1
    fi

    # Tar du repertoire /data dans le container
    if docker exec "$container" tar czf - /data 2>/dev/null > "$backup_file"; then
        local size
        size=$(du -sh "$backup_file" | cut -f1)
        log_success "ChromaDB sauvegarde: ${backup_file##*/} ($size)"
    else
        rm -f "$backup_file"
        log_error "Echec du backup ChromaDB"
        return 1
    fi
}

# =============================================================================
# ROTATION DES BACKUPS
# =============================================================================

rotate_backups() {
    log_step "Rotation des backups (conserver les $KEEP_LAST derniers)..."

    local types=("db" "n8n" "chroma")
    local total_deleted=0

    for type in "${types[@]}"; do
        local pattern="${SANITIZED_PREFIX}_${type}_*.gz"
        local count
        count=$(find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -type f 2>/dev/null | wc -l | tr -d ' ')

        if [[ "$count" -gt "$KEEP_LAST" ]]; then
            local to_delete=$((count - KEEP_LAST))
            find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -type f -print0 \
                | sort -z \
                | head -z -n "$to_delete" \
                | xargs -0 rm -f
            total_deleted=$((total_deleted + to_delete))
        fi
    done

    if [[ "$total_deleted" -gt 0 ]]; then
        log_info "$total_deleted ancien(s) backup(s) supprime(s)"
    else
        log_info "Aucun backup a supprimer"
    fi
}

# =============================================================================
# MAIN
# =============================================================================

echo ""
echo "============================================================================="
echo "  MY-IA - BACKUP"
echo "============================================================================="
echo ""
echo "  Instance:   ${APP_NAME_PREFIX:-MY-IA}"
echo "  Destination: $BACKUP_DIR"
echo "  Date:       $(date '+%Y-%m-%d %H:%M:%S')"
echo ""
echo "============================================================================="
echo ""

errors=0

if [[ "$CHROMA_ONLY" != "true" ]]; then
    if ! backup_postgres; then
        errors=$((errors + 1))
    fi
fi

if [[ "$DB_ONLY" != "true" ]]; then
    if ! backup_chroma; then
        errors=$((errors + 1))
    fi
fi

# Rotation
rotate_backups

# Resume
echo ""
echo "============================================================================="
if [[ "$errors" -eq 0 ]]; then
    log_success "BACKUP TERMINE"
else
    log_warn "BACKUP TERMINE AVEC $errors ERREUR(S)"
fi

# Lister les fichiers crees
echo ""
echo "  Fichiers crees:"
find "$BACKUP_DIR" -maxdepth 1 -name "*_${TIMESTAMP}*" -type f | sort | while read -r f; do
    local size
    size=$(du -sh "$f" | cut -f1)
    echo "    - ${f##*/} ($size)"
done
echo ""
echo "============================================================================="
echo ""

exit "$errors"
