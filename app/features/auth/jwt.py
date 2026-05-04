"""
JWT Token Generation

Helper pour generer des tokens JWT compatibles avec FastAPI Users.
"""
import jwt
from datetime import datetime, timedelta, timezone

from app.features.auth.config import SECRET, TOKEN_LIFETIME_SECONDS
from app.models import User


def create_access_token(user: User) -> str:
    """
    Genere un token JWT pour un utilisateur.

    Compatible avec FastAPI Users authentication.

    Args:
        user: Utilisateur pour lequel generer le token

    Returns:
        Token JWT signe
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(seconds=TOKEN_LIFETIME_SECONDS)

    payload = {
        "sub": str(user.id),
        "aud": ["fastapi-users:auth"],
        "exp": expire,
        "iat": now
    }

    return jwt.encode(payload, SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """
    Decode un token JWT.

    Args:
        token: Token JWT a decoder

    Returns:
        Payload du token

    Raises:
        jwt.ExpiredSignatureError: Si le token est expire
        jwt.InvalidTokenError: Si le token est invalide
    """
    return jwt.decode(
        token,
        SECRET,
        algorithms=["HS256"],
        audience=["fastapi-users:auth"]
    )
