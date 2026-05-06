#!/bin/sh
# =============================================================================
# MY-IA - Entrypoint pgAdmin
# =============================================================================
# Configure automatiquement le serveur PostgreSQL MY-IA dans pgAdmin
# avec mot de passe sauvegarde dans la configuration
# =============================================================================

SERVERS_JSON="/tmp/servers.json"
MARKER_FILE="/var/lib/pgadmin/.my_ia_server_imported"

echo "[PGADMIN] Verification de la configuration du serveur MY-IA..."

# Generer servers.json avec mot de passe integre
# Note: Le mot de passe sera stocke de maniere securisee dans la DB interne pgAdmin
cat > "$SERVERS_JSON" << EOF
{
  "Servers": {
    "1": {
      "Name": "${APP_NAME_PREFIX:-my_ia_v2} PostgreSQL",
      "Group": "MY-IA",
      "Host": "postgres",
      "Port": 5432,
      "MaintenanceDB": "postgres",
      "Username": "${POSTGRES_USER:-my_ia_postgres_admin}",
      "SSLMode": "prefer",
      "Comment": "Serveur PostgreSQL MY-IA (auto-configure)"
    }
  }
}
EOF

# Verifier si le serveur a deja ete importe
if [ ! -f "$MARKER_FILE" ]; then
    echo "[PGADMIN] Premiere execution - import du serveur MY-IA..."
    echo "[PGADMIN] Serveur:"
    echo "  - Name: ${APP_NAME_PREFIX:-my_ia_v2} PostgreSQL"
    echo "  - Host: postgres"
    echo "  - Port: 5432"
    echo "  - Username: ${POSTGRES_USER:-my_ia_postgres_admin}"

    # Exporter la variable pour que pgAdmin charge le fichier au demarrage
    export PGADMIN_SERVER_JSON_FILE="$SERVERS_JSON"

    # Creer le fichier pgpass dans le home directory de pgadmin
    # Ce fichier sera lu automatiquement par libpq lors des connexions
    PGPASS_DIR="/var/lib/pgadmin"
    PGPASS_FILE="${PGPASS_DIR}/.pgpass"

    echo "[PGADMIN] Configuration du fichier pgpass..."
    cat > "$PGPASS_FILE" << EOF
postgres:5432:*:${POSTGRES_USER:-my_ia_postgres_admin}:${POSTGRES_PASSWORD:-change-me-postgres-password}
EOF
    chmod 600 "$PGPASS_FILE"
    chown pgadmin:root "$PGPASS_FILE" 2>/dev/null || true

    # Creer le marqueur apres le premier demarrage (via un script en arriere-plan)
    (sleep 30 && touch "$MARKER_FILE" 2>/dev/null) &
else
    echo "[PGADMIN] Serveur MY-IA deja configure"

    # Mettre a jour le fichier pgpass a chaque demarrage (au cas ou le mot de passe change)
    PGPASS_FILE="/var/lib/pgadmin/.pgpass"
    cat > "$PGPASS_FILE" << EOF
postgres:5432:*:${POSTGRES_USER:-my_ia_postgres_admin}:${POSTGRES_PASSWORD:-change-me-postgres-password}
EOF
    chmod 600 "$PGPASS_FILE"
    chown pgadmin:root "$PGPASS_FILE" 2>/dev/null || true
fi

echo "[PGADMIN] Demarrage de pgAdmin..."

# Lancer le entrypoint original de pgAdmin
exec /entrypoint.sh "$@"
