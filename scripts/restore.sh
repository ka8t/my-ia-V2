#!/bin/bash
# =============================================================================
# MY-IA - Script de restauration (PostgreSQL + ChromaDB)
# =============================================================================
# Restaure une sauvegarde creee par backup.sh.
#
# Usage:
#   ./scripts/restore.sh backups/myia_db_20260204.sql.gz       # PostgreSQL
#   ./scripts/restore.sh backups/myia_chroma_20260204.tar.gz    # ChromaDB
#   ./scripts/restore.sh backups/myia_db_20260204.sql.gz --yes  # Sans confirmation
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

# Chargement des modules
source "$SCRIPT_DIR/lib/common.sh"

# =============================================================================
# PARSING ARGUMENTS
# =============================================================================

BACKUP_FILE=""
SKIP_CONFIRM=false

for arg in "$@"; do
    case "$arg" in
        --yes|-y)
            SKIP_CONFIRM=true
            ;;
        -h|--help)
            cat << 'EOF'
MY-IA - Script de restauration
================================

USAGE:
    ./scripts/restore.sh <fichier_backup> [OPTIONS]

ARGUMENTS:
    fichier_backup    Chemin vers le fichier de backup (.sql.gz ou .tar.gz)

OPTIONS:
    --yes, -y         Restaurer sans demander confirmation
    -h, --help        Affiche cette aide

EXEMPLES:
    # Restaurer PostgreSQL
    ./scripts/restore.sh backups/myia_db_20260204_030000.sql.gz

    # Restaurer ChromaDB
    ./scripts/restore.sh backups/myia_chroma_20260204_030000.tar.gz

    # Restaurer N8N
    ./scripts/restore.sh backups/myia_n8n_20260204_030000.sql.gz

    # Sans confirmation
    ./scripts/restore.sh backups/myia_db_20260204_030000.sql.gz --yes

NOTES:
    - La restauration PostgreSQL ecrase les donnees existantes
    - La restauration ChromaDB remplace le contenu du volume
    - Creez un backup avant de restaurer (./scripts/backup.sh)

EOF
            exit 0
            ;;
        -*)
            die "Option inconnue: $arg"
            ;;
        *)
            BACKUP_FILE="$arg"
            ;;
    esac
done

# =============================================================================
# VERIFICATION PREREQUIS
# =============================================================================

if [[ -z "$BACKUP_FILE" ]]; then
    log_error "Aucun fichier de backup specifie"
    echo ""
    echo "Usage: ./scripts/restore.sh <fichier_backup>"
    echo ""

    # Lister les backups disponibles
    if [[ -d "$PROJECT_ROOT/backups" ]]; then
        echo "Backups disponibles:"
        find "$PROJECT_ROOT/backups" -maxdepth 1 -name "*.gz" -type f | sort -r | while read -r f; do
            local size
            size=$(du -sh "$f" | cut -f1)
            echo "  - ${f##*/}  ($size)"
        done
        echo ""
    fi
    exit 1
fi

# Resoudre le chemin
if [[ ! "$BACKUP_FILE" = /* ]]; then
    BACKUP_FILE="$PROJECT_ROOT/$BACKUP_FILE"
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
    die "Fichier non trouve: $BACKUP_FILE"
fi

if [[ ! -f "$ENV_FILE" ]]; then
    die "Fichier .env non trouve"
fi

# Charger les variables
set +e
source "$ENV_FILE"
set -e

SANITIZED_PREFIX=$(sanitize "${APP_NAME_PREFIX:-MY-IA}" false)

# =============================================================================
# DETECTION DU TYPE DE BACKUP
# =============================================================================

FILENAME=$(basename "$BACKUP_FILE")
BACKUP_TYPE=""

if [[ "$FILENAME" == *"_db_"* && "$FILENAME" == *.sql.gz ]]; then
    BACKUP_TYPE="postgres"
elif [[ "$FILENAME" == *"_n8n_"* && "$FILENAME" == *.sql.gz ]]; then
    BACKUP_TYPE="n8n"
elif [[ "$FILENAME" == *"_chroma_"* && "$FILENAME" == *.tar.gz ]]; then
    BACKUP_TYPE="chroma"
else
    log_error "Type de backup non reconnu: $FILENAME"
    echo "  Formats attendus:"
    echo "    - *_db_*.sql.gz       (PostgreSQL)"
    echo "    - *_n8n_*.sql.gz      (N8N)"
    echo "    - *_chroma_*.tar.gz   (ChromaDB)"
    exit 1
fi

# =============================================================================
# CONFIRMATION
# =============================================================================

echo ""
echo "============================================================================="
echo "  MY-IA - RESTAURATION"
echo "============================================================================="
echo ""
echo "  Fichier: $FILENAME"
echo "  Type:    $BACKUP_TYPE"
echo "  Taille:  $(du -sh "$BACKUP_FILE" | cut -f1)"
echo ""

if [[ "$SKIP_CONFIRM" != "true" ]]; then
    log_warn "ATTENTION: Cette operation va REMPLACER les donnees actuelles!"
    echo ""
    if ! confirm "Confirmer la restauration ?" "n"; then
        log_info "Restauration annulee"
        exit 0
    fi
fi

# =============================================================================
# RESTAURATION POSTGRESQL
# =============================================================================

restore_postgres() {
    local db_name="$1"
    local container="${SANITIZED_PREFIX}_postgres"
    local db_user="${POSTGRES_USER}"

    log_step "Restauration PostgreSQL ($db_name)..."

    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        fail "Container $container non trouve" || return 1
    fi

    # Mode dry-run : afficher sans executer
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] gunzip -c $BACKUP_FILE | docker exec -i $container psql -U $db_user -d $db_name"
        return 0
    fi

    # Decompresser et injecter via psql
    if gunzip -c "$BACKUP_FILE" | docker exec -i "$container" \
        psql -U "$db_user" -d "$db_name" --quiet --no-psqlrc 2>/dev/null; then
        log_success "PostgreSQL restaure ($db_name)"
    else
        log_error "Echec de la restauration PostgreSQL"
        return 1
    fi
}

# =============================================================================
# RESTAURATION CHROMADB
# =============================================================================

restore_chroma() {
    local container="${SANITIZED_PREFIX}_chroma"

    log_step "Restauration ChromaDB..."

    if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        fail "Container $container non trouve" || return 1
    fi

    # Mode dry-run : afficher sans executer
    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "[DRY-RUN] docker exec $container rm -rf /data/*"
        log_info "[DRY-RUN] docker cp $BACKUP_FILE $container:/tmp/chroma_restore.tar.gz"
        log_info "[DRY-RUN] docker exec $container tar xzf /tmp/chroma_restore.tar.gz -C /"
        log_info "[DRY-RUN] docker restart $container"
        return 0
    fi

    # Supprimer les donnees existantes et restaurer
    if docker exec "$container" rm -rf /data/* 2>/dev/null \
        && docker cp "$BACKUP_FILE" "$container:/tmp/chroma_restore.tar.gz" \
        && docker exec "$container" tar xzf /tmp/chroma_restore.tar.gz -C / 2>/dev/null \
        && docker exec "$container" rm -f /tmp/chroma_restore.tar.gz; then
        log_success "ChromaDB restaure"
        log_info "Redemarrage du container ChromaDB..."
        docker restart "$container" > /dev/null 2>&1
        log_success "Container redemarre"
    else
        log_error "Echec de la restauration ChromaDB"
        return 1
    fi
}

# =============================================================================
# EXECUTION
# =============================================================================

case "$BACKUP_TYPE" in
    postgres)
        restore_postgres "${APP_DB_NAME}"
        ;;
    n8n)
        restore_postgres "${N8N_DB_NAME}"
        ;;
    chroma)
        restore_chroma
        ;;
esac

echo ""
echo "============================================================================="
log_success "RESTAURATION TERMINEE"
echo "============================================================================="
echo ""
