"""
Schemas Admin Permissions - DTOs pour les permissions et actions.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class ActionInfo(BaseModel):
    """Information sur une action."""
    name: str = Field(..., description="Nom technique de l'action")
    display_name: str = Field(..., description="Nom affiche")
    description: str = Field(..., description="Description de l'action")
    endpoint: Optional[str] = Field(None, description="Endpoint API associe")
    method: Optional[str] = Field(None, description="Methode HTTP (GET, POST, etc.)")


class CategoryActions(BaseModel):
    """Actions regroupees par categorie."""
    category: str = Field(..., description="Nom de la categorie")
    display_name: str = Field(..., description="Nom affiche de la categorie")
    actions: List[ActionInfo] = Field(default_factory=list)


class RolePermissions(BaseModel):
    """Permissions d'un role."""
    role_id: int
    role_name: str
    role_display_name: str
    categories: List[CategoryActions] = Field(default_factory=list)


class PermissionsListResponse(BaseModel):
    """Liste des permissions par role."""
    roles: List[RolePermissions]
    total_actions: int
