#!/bin/bash
# =============================================================================
# MY-IA - Utilitaire psql
# =============================================================================
# Execute des commandes psql dans le container PostgreSQL avec les bonnes
# credentials depuis le fichier .env
#
# Usage:
#   ./scripts/psql.sh                      # Shell interactif
#   ./scripts/psql.sh -c "SELECT 1"        # Commande unique
#   ./scripts/psql.sh -f script.sql        # Fichier SQL
#
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Charger les variables d'environnement
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    # Exporter les variables necessaires
    export $(grep -E "^(POSTGRES_USER|APP_DB_NAME)=" "$PROJECT_ROOT/.env" | xargs)
else
    echo "Erreur: Fichier .env non trouve"
    exit 1
fi

# Utiliser le superuser PostgreSQL
DB_USER="${POSTGRES_USER:-my_ia_postgres_admin}"
DB_NAME="${APP_DB_NAME:-my_ia_db}"

# Executer psql dans le container
if [[ $# -eq 0 ]]; then
    # Mode interactif
    docker-compose exec postgres psql -U "$DB_USER" -d "$DB_NAME"
else
    # Mode commande
    docker-compose exec postgres psql -U "$DB_USER" -d "$DB_NAME" "$@"
fi
