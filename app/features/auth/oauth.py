"""
Configuration OAuth2 - Google et GitHub

Configure les clients OAuth pour l'authentification sociale.
Les credentials sont definis via les variables d'environnement:
- GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
- GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET
"""
import os
import logging
from typing import Optional, List

from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.clients.github import GitHubOAuth2

logger = logging.getLogger(__name__)


def get_google_oauth_client() -> Optional[GoogleOAuth2]:
    """
    Retourne le client OAuth Google si configure.

    Returns:
        GoogleOAuth2 ou None si non configure
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.info("Google OAuth non configure (GOOGLE_CLIENT_ID/SECRET manquants)")
        return None

    logger.info("Google OAuth configure")
    return GoogleOAuth2(client_id, client_secret)


def get_github_oauth_client() -> Optional[GitHubOAuth2]:
    """
    Retourne le client OAuth GitHub si configure.

    Returns:
        GitHubOAuth2 ou None si non configure
    """
    client_id = os.getenv("GITHUB_CLIENT_ID")
    client_secret = os.getenv("GITHUB_CLIENT_SECRET")

    if not client_id or not client_secret:
        logger.info("GitHub OAuth non configure (GITHUB_CLIENT_ID/SECRET manquants)")
        return None

    logger.info("GitHub OAuth configure")
    return GitHubOAuth2(client_id, client_secret)


def get_oauth_redirect_url(provider: str) -> str:
    """
    Retourne l'URL de callback OAuth.

    Args:
        provider: Nom du provider (google, github)

    Returns:
        URL complete de callback
    """
    base_url = os.getenv("API_BASE_URL", "http://localhost:8080")
    return f"{base_url}/auth/oauth/{provider}/callback"


# Clients OAuth (initialises au chargement du module)
google_oauth_client = get_google_oauth_client()
github_oauth_client = get_github_oauth_client()


def get_available_oauth_providers() -> List[str]:
    """
    Retourne la liste des providers OAuth disponibles.

    Returns:
        Liste des noms de providers configures
    """
    providers = []
    if google_oauth_client:
        providers.append("google")
    if github_oauth_client:
        providers.append("github")
    return providers
