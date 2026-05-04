"""
Configuration de l'authentification JWT

Contient la configuration des secrets et de la stratégie JWT.
Les valeurs sont chargées depuis les settings (qui peuvent provenir de la BDD).
"""
from fastapi_users.authentication import JWTStrategy


def _get_settings():
    """Import tardif des settings pour éviter les dépendances circulaires."""
    from app.core.config import settings
    return settings


def get_jwt_strategy() -> JWTStrategy:
    """
    Retourne la stratégie JWT configurée.

    Utilise les settings pour obtenir le secret JWT (chargé depuis la BDD
    si BOOTSTRAP_FROM_DB=true, sinon depuis les variables d'environnement).

    Returns:
        JWTStrategy: Stratégie JWT avec secret et durée de vie configurable
    """
    settings = _get_settings()
    lifetime_seconds = settings.access_token_expire_minutes * 60
    return JWTStrategy(secret=settings.jwt_secret_key, lifetime_seconds=lifetime_seconds)


def get_secret() -> str:
    """Retourne le secret JWT depuis les settings."""
    return _get_settings().jwt_secret_key


def get_token_lifetime_seconds() -> int:
    """Retourne la durée de vie du token en secondes."""
    return _get_settings().access_token_expire_minutes * 60


# SECRET et TOKEN_LIFETIME_SECONDS sont calculés à l'import depuis settings.
# Le bootstrap doit avoir été exécuté avant que ce module soit importé
# pour que les valeurs soient correctes.
# Note: settings est importé via _get_settings() qui fait un import tardif,
# donc le bootstrap aura été exécuté lorsque ces valeurs sont lues.
SECRET: str = _get_settings().jwt_secret_key
TOKEN_LIFETIME_SECONDS: int = _get_settings().access_token_expire_minutes * 60
