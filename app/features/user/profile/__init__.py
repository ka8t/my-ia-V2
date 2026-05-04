"""Module profil utilisateur - Gestion du profil et changement de mot de passe."""
from app.features.user.profile.router import router
from app.features.user.profile.service import ProfileService

__all__ = ["router", "ProfileService"]
