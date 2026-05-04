"""Schemas Pydantic pour le profil utilisateur."""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, field_validator
import re


# =============================================================================
# PROFILE SCHEMAS
# =============================================================================

class ProfileRead(BaseModel):
    """Schema lecture profil complet."""
    # Identite
    email: EmailStr
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    # Contact
    phone: Optional[str] = None

    # Adresse
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city_id: Optional[int] = None
    city_name: Optional[str] = None  # Jointure
    city_postal_code: Optional[str] = None  # Jointure
    country_code: Optional[str] = None
    country_name: Optional[str] = None  # Jointure
    country_flag: Optional[str] = None  # Jointure

    # Meta
    is_verified: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    """Schema mise a jour du profil."""
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
    address_line1: Optional[str] = Field(None, max_length=255)
    address_line2: Optional[str] = Field(None, max_length=255)
    city_id: Optional[int] = None
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)

    @field_validator('phone')
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        """Valide le format du telephone."""
        if v is None or v == "":
            return None
        # Nettoyer le numero (garder uniquement chiffres et +)
        cleaned = re.sub(r'[^\d+]', '', v)
        if len(cleaned) < 8:
            raise ValueError("Numero de telephone invalide (min 8 chiffres)")
        if len(cleaned) > 20:
            raise ValueError("Numero de telephone invalide (max 20 chiffres)")
        return cleaned

    @field_validator('country_code')
    @classmethod
    def validate_country_code(cls, v: Optional[str]) -> Optional[str]:
        """Valide et normalise le code pays."""
        if v is None:
            return None
        return v.upper()


# =============================================================================
# PASSWORD CHANGE SCHEMAS
# =============================================================================

class PasswordChangeRequest(BaseModel):
    """Schema changement de mot de passe."""
    current_password: str = Field(..., min_length=1, description="Mot de passe actuel")
    new_password: str = Field(..., min_length=8, description="Nouveau mot de passe")
    confirm_password: str = Field(..., min_length=8, description="Confirmation")

    @field_validator('confirm_password')
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        """Verifie que les mots de passe correspondent."""
        if 'new_password' in info.data and v != info.data['new_password']:
            raise ValueError("Les mots de passe ne correspondent pas")
        return v


class PasswordChangeResponse(BaseModel):
    """Reponse changement de mot de passe."""
    success: bool
    message: str


# =============================================================================
# EMAIL CHANGE SCHEMAS
# =============================================================================

class EmailChangeRequest(BaseModel):
    """Schema demande de changement d'email."""
    new_email: EmailStr = Field(..., description="Nouvel email")
    password: str = Field(..., min_length=1, description="Mot de passe pour confirmer")


class EmailChangeVerify(BaseModel):
    """Schema verification changement d'email."""
    token: str = Field(..., min_length=1, description="Token de verification")


class EmailChangeResponse(BaseModel):
    """Reponse changement d'email."""
    success: bool
    message: str
    requires_verification: bool = True
