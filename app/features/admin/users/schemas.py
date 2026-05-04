"""
Schemas Admin Users

Schémas Pydantic pour la gestion des utilisateurs par les administrateurs.
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, EmailStr


# =============================================================================
# CRÉATION
# =============================================================================

class AdminUserCreate(BaseModel):
    """Création d'un utilisateur par un admin"""
    email: EmailStr = Field(..., description="Adresse email de l'utilisateur")
    username: str = Field(..., min_length=3, max_length=100, description="Nom d'utilisateur")
    password: str = Field(..., min_length=8, description="Mot de passe (min 8 caractères)")
    first_name: Optional[str] = Field(None, max_length=100, description="Prénom")
    last_name: Optional[str] = Field(None, max_length=100, description="Nom de famille")
    phone: Optional[str] = Field(None, max_length=20, description="Numéro de téléphone")
    address_line1: Optional[str] = Field(None, max_length=255, description="Adresse ligne 1")
    address_line2: Optional[str] = Field(None, max_length=255, description="Adresse ligne 2")
    city_id: Optional[int] = Field(None, description="ID de la ville")
    country_code: Optional[str] = Field(None, min_length=2, max_length=2, description="Code pays ISO")
    role_id: int = Field(default=2, ge=1, description="ID du rôle (1=admin, 2=user par défaut)")
    is_active: bool = Field(default=True, description="Compte actif")
    is_verified: bool = Field(default=False, description="Email vérifié")
    voice_to_text_enabled: bool = Field(default=False, description="Transcription vocale activée")


# =============================================================================
# MISE À JOUR
# =============================================================================

class AdminUserUpdate(BaseModel):
    """Mise à jour d'un utilisateur par un admin"""
    email: Optional[EmailStr] = Field(None, description="Nouvelle adresse email")
    username: Optional[str] = Field(None, min_length=3, max_length=100, description="Nouveau nom d'utilisateur")
    first_name: Optional[str] = Field(None, max_length=100, description="Nouveau prénom")
    last_name: Optional[str] = Field(None, max_length=100, description="Nouveau nom de famille")
    phone: Optional[str] = Field(None, max_length=20, description="Numéro de téléphone")
    address_line1: Optional[str] = Field(None, max_length=255, description="Adresse ligne 1")
    address_line2: Optional[str] = Field(None, max_length=255, description="Adresse ligne 2")
    city_id: Optional[int] = Field(None, description="ID de la ville")
    country_code: Optional[str] = Field(None, min_length=2, max_length=2, description="Code pays ISO")
    is_verified: Optional[bool] = Field(None, description="Statut de vérification email")
    approval_status: Optional[str] = Field(None, pattern="^(pending|approved|rejected)$", description="Statut d'approbation")


class RoleChangeRequest(BaseModel):
    """Changement de rôle d'un utilisateur"""
    role_id: int = Field(..., ge=1, description="Nouveau rôle ID")
    reason: Optional[str] = Field(None, max_length=500, description="Raison du changement")


class StatusChangeRequest(BaseModel):
    """Activation/Désactivation d'un utilisateur"""
    is_active: bool = Field(..., description="Nouveau statut actif/inactif")
    reason: Optional[str] = Field(None, max_length=500, description="Raison du changement")


class PasswordResetRequest(BaseModel):
    """Demande de reset de mot de passe par admin"""
    new_password: str = Field(..., min_length=8, description="Nouveau mot de passe")
    notify_user: bool = Field(default=False, description="Notifier l'utilisateur par email")


class VoiceToTextToggleRequest(BaseModel):
    """Activation/Désactivation de la transcription vocale"""
    enabled: bool = Field(..., description="Activer/désactiver la transcription vocale")


# =============================================================================
# LECTURE
# =============================================================================

class AdminUserRead(BaseModel):
    """Lecture d'un utilisateur (vue admin enrichie)"""
    id: uuid.UUID
    email: str
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city_id: Optional[int] = None
    city_name: Optional[str] = None
    city_postal_code: Optional[str] = None
    country_code: Optional[str] = None
    country_name: Optional[str] = None
    role_id: int
    role_name: str = Field(..., description="Nom du rôle")
    is_active: bool
    is_verified: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    last_login: Optional[datetime] = None
    conversations_count: int = Field(default=0, description="Nombre de conversations")
    documents_count: int = Field(default=0, description="Nombre de documents")
    voice_to_text_enabled: bool = Field(default=False, description="Transcription vocale activée")
    approval_status: Optional[str] = Field(None, description="Statut d'approbation (pending/approved/rejected)")

    class Config:
        from_attributes = True


class AdminUserListItem(BaseModel):
    """Élément de liste d'utilisateurs (version allégée)"""
    id: uuid.UUID
    email: str
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role_id: int
    role_name: str
    is_active: bool
    is_verified: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    voice_to_text_enabled: bool = Field(default=False, description="Transcription vocale activée")
    approval_status: Optional[str] = Field(None, description="Statut d'approbation (pending/approved/rejected)")
    has_collection: bool = Field(default=False, description="L'utilisateur a une collection privée")

    class Config:
        from_attributes = True


# =============================================================================
# FILTRES
# =============================================================================

class UserFilter(BaseModel):
    """Filtres pour la liste des utilisateurs"""
    role_id: Optional[int] = Field(None, description="Filtrer par rôle")
    is_active: Optional[bool] = Field(None, description="Filtrer par statut actif")
    is_verified: Optional[bool] = Field(None, description="Filtrer par vérification email")
    search: Optional[str] = Field(None, max_length=100, description="Recherche email/username")
    created_after: Optional[datetime] = Field(None, description="Créé après cette date")
    created_before: Optional[datetime] = Field(None, description="Créé avant cette date")
