"""
Router pour les endpoints utilisateurs

Expose les endpoints de gestion des utilisateurs (/users/me, /users/{id}).
"""
from fastapi import APIRouter
from app.features.auth.service import fastapi_users
from app.features.user.schemas import UserRead, UserUpdate


# Router pour les utilisateurs (/users/me, /users/{id})
router = APIRouter(
    prefix="/users",
    tags=["users"]
)

# Ajouter les routes générées par fastapi_users
users_router = fastapi_users.get_users_router(UserRead, UserUpdate)

# Inclure toutes les routes dans le router principal
for route in users_router.routes:
    router.routes.append(route)

# Inclure le router profile
from app.features.user.profile.router import router as profile_router
router.include_router(profile_router, tags=["users - profile"])
