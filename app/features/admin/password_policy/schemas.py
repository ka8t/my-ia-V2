"""
Schemas pour la gestion des politiques de mot de passe.

Pydantic DTOs pour les endpoints admin.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator


class PasswordPolicyBase(BaseModel):
    """Champs communs pour une politique de mot de passe."""
    name: str = Field(..., min_length=1, max_length=50, description="Nom unique de la politique")
    min_length: int = Field(default=8, ge=4, le=128, description="Longueur minimale")
    max_length: int = Field(default=128, ge=8, le=256, description="Longueur maximale")
    require_uppercase: bool = Field(default=True, description="Exiger au moins une majuscule")
    require_lowercase: bool = Field(default=True, description="Exiger au moins une minuscule")
    require_digit: bool = Field(default=True, description="Exiger au moins un chiffre")
    require_special: bool = Field(default=True, description="Exiger au moins un caractere special")
    special_characters: str = Field(
        default="!@#$%^&*()_+-=[]{}|;:,.<>?",
        max_length=50,
        description="Liste des caracteres speciaux autorises"
    )
    expire_days: int = Field(default=0, ge=0, le=365, description="Jours avant expiration (0=jamais)")
    history_count: int = Field(default=0, ge=0, le=24, description="Nombre anciens mdp interdits")
    max_failed_attempts: int = Field(default=5, ge=1, le=20, description="Tentatives avant blocage")
    lockout_duration_minutes: int = Field(default=30, ge=1, le=1440, description="Duree blocage en minutes")

    @field_validator('max_length')
    @classmethod
    def max_length_greater_than_min(cls, v, info):
        """Valide que max_length >= min_length."""
        min_len = info.data.get('min_length', 8)
        if v < min_len:
            raise ValueError(f"max_length ({v}) doit etre >= min_length ({min_len})")
        return v


class PasswordPolicyCreate(PasswordPolicyBase):
    """Schema pour creer une politique de mot de passe."""
    is_active: bool = Field(default=True, description="Politique active")


class PasswordPolicyUpdate(BaseModel):
    """Schema pour mettre a jour une politique (tous champs optionnels)."""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    min_length: Optional[int] = Field(None, ge=4, le=128)
    max_length: Optional[int] = Field(None, ge=8, le=256)
    require_uppercase: Optional[bool] = None
    require_lowercase: Optional[bool] = None
    require_digit: Optional[bool] = None
    require_special: Optional[bool] = None
    special_characters: Optional[str] = Field(None, max_length=50)
    expire_days: Optional[int] = Field(None, ge=0, le=365)
    history_count: Optional[int] = Field(None, ge=0, le=24)
    max_failed_attempts: Optional[int] = Field(None, ge=1, le=20)
    lockout_duration_minutes: Optional[int] = Field(None, ge=1, le=1440)
    is_active: Optional[bool] = None


class PasswordPolicyRead(PasswordPolicyBase):
    """Schema pour lire une politique de mot de passe."""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PasswordPolicyListItem(BaseModel):
    """Schema simplifie pour la liste des politiques."""
    id: int
    name: str
    min_length: int
    require_uppercase: bool
    require_lowercase: bool
    require_digit: bool
    require_special: bool
    expire_days: int
    is_active: bool

    class Config:
        from_attributes = True


# --- Schemas pour la validation de mot de passe ---

class PasswordValidationRequest(BaseModel):
    """Requete pour valider un mot de passe."""
    password: str = Field(..., min_length=1, description="Mot de passe a valider")
    policy_name: str = Field(default="default", description="Nom de la politique a utiliser")


class PasswordValidationResult(BaseModel):
    """Resultat de la validation d'un mot de passe."""
    is_valid: bool = Field(..., description="Mot de passe valide ou non")
    errors: List[str] = Field(default_factory=list, description="Liste des erreurs")
    strength_score: int = Field(..., ge=0, le=100, description="Score de robustesse (0-100)")
    suggestions: List[str] = Field(default_factory=list, description="Suggestions d'amelioration")


class PasswordRequirements(BaseModel):
    """Exigences de la politique de mot de passe (pour le frontend)."""
    min_length: int
    max_length: int
    require_uppercase: bool
    require_lowercase: bool
    require_digit: bool
    require_special: bool
    special_characters: str
    expire_days: int
    history_count: int

    class Config:
        from_attributes = True
