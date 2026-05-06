#!/bin/bash
# =============================================================================
# MY-IA - Script de réinitialisation de mot de passe
# =============================================================================
# Réinitialise le mot de passe d'un utilisateur et redémarre le container
# pour invalider le cache SQLAlchemy.
#
# Usage:
#   ./scripts/reset-password.sh <email> <new_password>
#   ./scripts/reset-password.sh admin@test.example Admin123!
#
# Note: Ce script utilise PasswordHelper de FastAPI Users (pwdlib/argon2)
#       pour garantir la compatibilité avec le système d'authentification.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Vérification des arguments
if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <email> <new_password>"
    echo ""
    echo "Exemples:"
    echo "  $0 admin@test.example Admin123!"
    echo "  $0 user@test.example User123!"
    exit 1
fi

EMAIL="$1"
PASSWORD="$2"

# Charger le préfixe depuis .env si disponible (seulement SANITIZED_PREFIX)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
    SANITIZED_PREFIX=$(grep "^SANITIZED_PREFIX=" "$PROJECT_ROOT/.env" | cut -d'=' -f2 | tr -d '"' | tr -d "'")
fi
CONTAINER_NAME="${SANITIZED_PREFIX:-my_ia_v2}_app"

# Vérifier que le container existe
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_error "Container $CONTAINER_NAME non trouvé ou non démarré"
    exit 1
fi

log_info "Réinitialisation du mot de passe pour: $EMAIL"

# Exécuter le script Python dans le container
docker exec "$CONTAINER_NAME" python3 -c "
import asyncio
import os
from sqlalchemy import update, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from fastapi_users.password import PasswordHelper

async def reset_password():
    engine = create_async_engine(os.environ['DATABASE_URL'])
    session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    helper = PasswordHelper()

    # Générer le nouveau hash
    new_hash = helper.hash('$PASSWORD')

    async with session_maker() as session:
        # Vérifier que l'utilisateur existe
        result = await session.execute(
            text(\"SELECT id, email FROM users WHERE email = :email\"),
            {'email': '$EMAIL'}
        )
        row = result.fetchone()

        if not row:
            print('USER_NOT_FOUND')
            await engine.dispose()
            return

        # Mettre à jour le mot de passe
        await session.execute(
            text(\"UPDATE users SET hashed_password = :hash WHERE email = :email\"),
            {'hash': new_hash, 'email': '$EMAIL'}
        )
        await session.commit()
        print('PASSWORD_UPDATED')

    await engine.dispose()

asyncio.run(reset_password())
"

RESULT=$?
if [[ $RESULT -ne 0 ]]; then
    log_error "Échec de la mise à jour du mot de passe"
    exit 1
fi

log_info "Mot de passe mis à jour dans la base de données"

# Redémarrer le container pour invalider le cache SQLAlchemy
log_info "Redémarrage du container $CONTAINER_NAME..."
docker restart "$CONTAINER_NAME" > /dev/null

# Attendre que le container soit healthy
log_info "Attente du démarrage..."
ATTEMPTS=0
MAX_ATTEMPTS=30
while [[ $ATTEMPTS -lt $MAX_ATTEMPTS ]]; do
    if curl -sf "http://localhost:8080/health" > /dev/null 2>&1; then
        break
    fi
    sleep 1
    ATTEMPTS=$((ATTEMPTS + 1))
done

if [[ $ATTEMPTS -ge $MAX_ATTEMPTS ]]; then
    log_warn "Le container n'a pas répondu dans les temps, vérifiez les logs"
else
    log_info "Container redémarré et healthy"
fi

# Tester le login
log_info "Test du login..."
LOGIN_RESULT=$(curl -s "http://localhost:8080/auth/jwt/login" \
    -X POST \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=$EMAIL&password=$PASSWORD")

if echo "$LOGIN_RESULT" | grep -q "access_token"; then
    log_info "✅ Login réussi pour $EMAIL"
else
    log_error "❌ Login échoué: $LOGIN_RESULT"
    exit 1
fi

echo ""
log_info "Mot de passe réinitialisé avec succès!"
