"""
Schemas Pydantic pour les utilisateurs

Définit les modèles de données pour la création, lecture et mise à jour des utilisateurs.
"""
import uuid
from typing import Optional
from pydantic import Field
from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Schéma pour la lecture d'un utilisateur"""
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city_id: Optional[int] = None
    country_code: Optional[str] = None
    role_id: int

    class Config:
        from_attributes = True


class UserCreate(schemas.BaseUserCreate):
    """
    Schéma pour la création d'un utilisateur (inscription)

    Champs obligatoires:
    - email, password (hérités de BaseUserCreate)
    - username, first_name, last_name, phone
    - address_line1, country_code

    Champs optionnels:
    - address_line2, city_id
    """
    username: str = Field(..., min_length=3, max_length=100)
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    phone: str = Field(..., min_length=5, max_length=20)
    address_line1: str = Field(..., min_length=1, max_length=255)
    address_line2: Optional[str] = Field(None, max_length=255)
    country_code: str = Field(default="FR", min_length=2, max_length=2)
    city_id: Optional[int] = None


class UserUpdate(schemas.BaseUserUpdate):
    """
    Schéma pour la mise à jour d'un utilisateur (profil)

    Tous les champs sont optionnels pour permettre des mises à jour partielles.
    """
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, min_length=5, max_length=20)
    address_line1: Optional[str] = Field(None, min_length=1, max_length=255)
    address_line2: Optional[str] = Field(None, min_length=1, max_length=255)
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    city_id: Optional[int] = None


class PasswordChange(schemas.BaseModel):
    """Schéma pour le changement de mot de passe"""
    current_password: str = Field(..., min_length=8)
    new_password: str = Field(..., min_length=8)
    confirm_password: str = Field(..., min_length=8)
