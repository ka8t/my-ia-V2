#!/bin/bash
# =============================================================================
# MY-IA - Fonctions d'authentification
# =============================================================================
# Ce fichier contient les fonctions de generation de tokens JWT
# pour les appels API internes (import donnees, etc.)
#
# Usage:
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   source "$SCRIPT_DIR/lib/common.sh"
#   source "$SCRIPT_DIR/lib/auth.sh"
#
# Prerequis:
#   - common.sh doit etre source avant ce fichier
#
# =============================================================================

# =============================================================================
# CODE PYTHON PARTAGE POUR LA GENERATION DE TOKEN
# =============================================================================
# Retourne le code Python JWT commun (utilise par Docker et native).
# =============================================================================

_token_python_code() {
    cat << 'PYEOF'
import asyncio
import jwt
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.features.auth.config import SECRET

async def get_token():
    db_url = os.getenv('DATABASE_URL', '')
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.role_id == 1, User.is_active == True).limit(1)
        )
        admin = result.unique().scalar_one_or_none()

        if admin:
            token = jwt.encode({
                'sub': str(admin.id),
                'aud': ['fastapi-users:auth'],
                'exp': datetime.now(timezone.utc) + timedelta(minutes=5)
            }, SECRET, algorithm='HS256')
            print(token)

    await engine.dispose()

asyncio.run(get_token())
PYEOF
}

# =============================================================================
# GENERATION DE TOKEN ADMIN (DOCKER)
# =============================================================================
# Genere un token JWT temporaire pour un admin existant via Docker.
#
# Usage:
#   token=$(generate_admin_token "container_name")
#
# Parametres:
#   $1 - Nom du container app
#
# Retour:
#   Token JWT valide 5 minutes, ou vide si erreur
# =============================================================================

generate_admin_token() {
    local container_name="$1"

    local token
    token=$(docker exec "$container_name" python -c "$(_token_python_code)" 2>/dev/null) || token=""

    echo "$token"
}

# =============================================================================
# GENERATION DE TOKEN ADMIN (NATIVE / BARE-METAL)
# =============================================================================
# Genere un token JWT temporaire pour un admin en mode natif (sans Docker).
#
# Usage:
#   token=$(generate_admin_token_native "/path/to/project")
#
# Parametres:
#   $1 - Chemin du projet (ou INSTALL_DIR)
#
# Retour:
#   Token JWT valide 5 minutes, ou vide si erreur
# =============================================================================

generate_admin_token_native() {
    local work_dir="$1"
    local venv_dir="${INSTALL_DIR:-$work_dir}/venv"

    if [[ "${OS_FAMILY:-}" != "darwin" && -d "${INSTALL_DIR:-$work_dir}/app" ]]; then
        work_dir="${INSTALL_DIR:-$work_dir}/app"
    fi

    local token
    token=$(cd "$work_dir" && "$venv_dir/bin/python" -c "$(_token_python_code)" 2>/dev/null) || token=""

    echo "$token"
}
