"""
Service Admin Permissions - Definition des actions par role.
"""

import logging
from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Role
from app.features.admin.permissions.schemas import (
    ActionInfo,
    CategoryActions,
    RolePermissions,
    PermissionsListResponse,
)

logger = logging.getLogger(__name__)


# =============================================================================
# DEFINITION DES ACTIONS PAR CATEGORIE
# =============================================================================

# Actions disponibles pour le role USER (id=3)
USER_ACTIONS = {
    "chat": {
        "display_name": "Conversations",
        "actions": [
            ActionInfo(
                name="chat_send",
                display_name="Envoyer un message",
                description="Envoyer un message dans une conversation",
                endpoint="/api/chat",
                method="POST",
            ),
            ActionInfo(
                name="chat_list",
                display_name="Lister les conversations",
                description="Voir ses propres conversations",
                endpoint="/api/conversations",
                method="GET",
            ),
            ActionInfo(
                name="chat_delete",
                display_name="Supprimer une conversation",
                description="Supprimer une de ses conversations",
                endpoint="/api/conversations/{id}",
                method="DELETE",
            ),
        ],
    },
    "documents": {
        "display_name": "Documents",
        "actions": [
            ActionInfo(
                name="doc_upload",
                display_name="Uploader un document",
                description="Ajouter un document a sa collection privee",
                endpoint="/api/documents/upload",
                method="POST",
            ),
            ActionInfo(
                name="doc_list",
                display_name="Lister ses documents",
                description="Voir ses propres documents",
                endpoint="/api/documents",
                method="GET",
            ),
            ActionInfo(
                name="doc_download",
                display_name="Telecharger un document",
                description="Telecharger un de ses documents",
                endpoint="/api/documents/{id}/download",
                method="GET",
            ),
            ActionInfo(
                name="doc_delete",
                display_name="Supprimer un document",
                description="Supprimer un de ses documents",
                endpoint="/api/documents/{id}",
                method="DELETE",
            ),
        ],
    },
    "profile": {
        "display_name": "Profil",
        "actions": [
            ActionInfo(
                name="profile_view",
                display_name="Voir son profil",
                description="Consulter ses informations personnelles",
                endpoint="/api/users/me",
                method="GET",
            ),
            ActionInfo(
                name="profile_update",
                display_name="Modifier son profil",
                description="Modifier ses informations personnelles",
                endpoint="/api/users/me",
                method="PATCH",
            ),
            ActionInfo(
                name="preferences_update",
                display_name="Modifier ses preferences",
                description="Configurer theme, langue, parametres RAG",
                endpoint="/api/users/me/preferences",
                method="PATCH",
            ),
        ],
    },
}

# Actions supplementaires pour le role CONTRIBUTOR (id=2)
CONTRIBUTOR_ACTIONS = {
    "documents": {
        "display_name": "Documents",
        "actions": [
            ActionInfo(
                name="doc_public_upload",
                display_name="Uploader dans collection publique",
                description="Ajouter un document dans une collection publique",
                endpoint="/api/documents/upload",
                method="POST",
            ),
            ActionInfo(
                name="doc_visibility",
                display_name="Modifier la visibilite",
                description="Changer la visibilite d'un document (public/prive)",
                endpoint="/api/documents/{id}/visibility",
                method="PATCH",
            ),
        ],
    },
}

# Actions supplementaires pour le role ADMIN (id=1)
ADMIN_ACTIONS = {
    "users": {
        "display_name": "Gestion des utilisateurs",
        "actions": [
            ActionInfo(
                name="users_list",
                display_name="Lister les utilisateurs",
                description="Voir tous les utilisateurs du systeme",
                endpoint="/api/admin/users",
                method="GET",
            ),
            ActionInfo(
                name="users_create",
                display_name="Creer un utilisateur",
                description="Ajouter un nouvel utilisateur",
                endpoint="/api/admin/users",
                method="POST",
            ),
            ActionInfo(
                name="users_update",
                display_name="Modifier un utilisateur",
                description="Modifier les informations d'un utilisateur",
                endpoint="/api/admin/users/{id}",
                method="PATCH",
            ),
            ActionInfo(
                name="users_delete",
                display_name="Supprimer un utilisateur",
                description="Supprimer un compte utilisateur",
                endpoint="/api/admin/users/{id}",
                method="DELETE",
            ),
            ActionInfo(
                name="users_role",
                display_name="Changer le role",
                description="Modifier le role d'un utilisateur",
                endpoint="/api/admin/users/{id}/role",
                method="PATCH",
            ),
            ActionInfo(
                name="users_bulk",
                display_name="Operations en masse",
                description="Activer/desactiver/supprimer plusieurs utilisateurs",
                endpoint="/api/admin/bulk/users/*",
                method="POST",
            ),
        ],
    },
    "collections": {
        "display_name": "Collections ChromaDB",
        "actions": [
            ActionInfo(
                name="collections_list",
                display_name="Lister les collections",
                description="Voir toutes les collections (publiques et privees)",
                endpoint="/api/admin/collections",
                method="GET",
            ),
            ActionInfo(
                name="collections_create",
                display_name="Creer une collection publique",
                description="Ajouter une nouvelle collection publique",
                endpoint="/api/admin/collections/public",
                method="POST",
            ),
            ActionInfo(
                name="collections_update",
                display_name="Modifier une collection",
                description="Modifier nom/description d'une collection",
                endpoint="/api/admin/collections/{id}",
                method="PATCH",
            ),
            ActionInfo(
                name="collections_delete",
                display_name="Supprimer une collection",
                description="Supprimer une collection et ses documents",
                endpoint="/api/admin/collections/{id}",
                method="DELETE",
            ),
            ActionInfo(
                name="collections_clear",
                display_name="Vider une collection",
                description="Supprimer tous les documents d'une collection",
                endpoint="/api/admin/collections/{id}/documents",
                method="DELETE",
            ),
            ActionInfo(
                name="collections_sync",
                display_name="Synchroniser les compteurs",
                description="Recalculer les compteurs documents/chunks",
                endpoint="/api/admin/collections/{id}/sync",
                method="POST",
            ),
        ],
    },
    "corpus": {
        "display_name": "Corpus thematiques",
        "actions": [
            ActionInfo(
                name="corpus_list",
                display_name="Lister les corpus",
                description="Voir tous les corpus thematiques",
                endpoint="/api/admin/corpus",
                method="GET",
            ),
            ActionInfo(
                name="corpus_create",
                display_name="Creer un corpus",
                description="Ajouter un nouveau corpus thematique",
                endpoint="/api/admin/corpus",
                method="POST",
            ),
            ActionInfo(
                name="corpus_update",
                display_name="Modifier un corpus",
                description="Modifier nom/description d'un corpus",
                endpoint="/api/admin/corpus/{id}",
                method="PATCH",
            ),
            ActionInfo(
                name="corpus_delete",
                display_name="Supprimer un corpus",
                description="Supprimer un corpus (collections/sources dissociees)",
                endpoint="/api/admin/corpus/{id}",
                method="DELETE",
            ),
            ActionInfo(
                name="corpus_collections",
                display_name="Gerer les collections du corpus",
                description="Ajouter/retirer des collections d'un corpus",
                endpoint="/api/admin/corpus/{id}/collections",
                method="POST/DELETE",
            ),
            ActionInfo(
                name="corpus_sources",
                display_name="Gerer les sources du corpus",
                description="Ajouter/retirer des sources d'un corpus",
                endpoint="/api/admin/corpus/{id}/sources",
                method="POST/DELETE",
            ),
        ],
    },
    "sources": {
        "display_name": "Sources externes",
        "actions": [
            ActionInfo(
                name="sources_list",
                display_name="Lister les sources",
                description="Voir toutes les sources externes",
                endpoint="/api/admin/sources",
                method="GET",
            ),
            ActionInfo(
                name="sources_create",
                display_name="Creer une source",
                description="Ajouter une nouvelle source externe",
                endpoint="/api/admin/sources",
                method="POST",
            ),
            ActionInfo(
                name="sources_update",
                display_name="Modifier une source",
                description="Modifier la configuration d'une source",
                endpoint="/api/admin/sources/{id}",
                method="PATCH",
            ),
            ActionInfo(
                name="sources_delete",
                display_name="Supprimer une source",
                description="Supprimer une source externe",
                endpoint="/api/admin/sources/{id}",
                method="DELETE",
            ),
            ActionInfo(
                name="sources_reindex",
                display_name="Reindexer une source",
                description="Lancer la reindexation d'une source",
                endpoint="/api/admin/sources/{id}/reindex",
                method="POST",
            ),
            ActionInfo(
                name="sources_health",
                display_name="Verifier la sante",
                description="Tester la connectivite d'une source",
                endpoint="/api/admin/sources/{id}/health",
                method="POST",
            ),
        ],
    },
    "documents_admin": {
        "display_name": "Documents (admin)",
        "actions": [
            ActionInfo(
                name="docs_admin_list",
                display_name="Lister tous les documents",
                description="Voir les documents de tous les utilisateurs",
                endpoint="/api/admin/documents",
                method="GET",
            ),
            ActionInfo(
                name="docs_admin_update",
                display_name="Modifier un document",
                description="Modifier visibilite/indexation d'un document",
                endpoint="/api/admin/documents/{id}",
                method="PATCH",
            ),
            ActionInfo(
                name="docs_admin_delete",
                display_name="Supprimer un document",
                description="Supprimer le document d'un utilisateur",
                endpoint="/api/admin/documents/{id}",
                method="DELETE",
            ),
            ActionInfo(
                name="docs_admin_reindex",
                display_name="Reindexer un document",
                description="Forcer la reindexation d'un document",
                endpoint="/api/admin/documents/{id}/reindex",
                method="POST",
            ),
        ],
    },
    "conversations_admin": {
        "display_name": "Conversations (admin)",
        "actions": [
            ActionInfo(
                name="conv_admin_list",
                display_name="Lister les conversations",
                description="Voir les conversations de tous les utilisateurs",
                endpoint="/api/admin/conversations",
                method="GET",
            ),
            ActionInfo(
                name="conv_admin_view",
                display_name="Voir une conversation",
                description="Consulter les messages d'une conversation",
                endpoint="/api/admin/conversations/{id}",
                method="GET",
            ),
            ActionInfo(
                name="conv_admin_delete",
                display_name="Supprimer une conversation",
                description="Supprimer la conversation d'un utilisateur",
                endpoint="/api/admin/conversations/{id}",
                method="DELETE",
            ),
        ],
    },
    "config": {
        "display_name": "Configuration systeme",
        "actions": [
            ActionInfo(
                name="config_rag",
                display_name="Configurer le RAG",
                description="Modifier les parametres RAG (top_k, threshold, etc.)",
                endpoint="/api/admin/config/rag",
                method="PATCH",
            ),
            ActionInfo(
                name="config_llm",
                display_name="Configurer le LLM",
                description="Changer le provider LLM (Ollama, llama.cpp)",
                endpoint="/api/admin/config/llm-provider",
                method="PATCH",
            ),
            ActionInfo(
                name="config_storage",
                display_name="Configurer le stockage",
                description="Modifier les limites de stockage",
                endpoint="/api/admin/config/storage",
                method="PATCH",
            ),
            ActionInfo(
                name="config_models",
                display_name="Gerer les modeles LLM",
                description="Telecharger/supprimer des modeles",
                endpoint="/api/admin/config/models",
                method="POST/DELETE",
            ),
        ],
    },
    "audit": {
        "display_name": "Audit et logs",
        "actions": [
            ActionInfo(
                name="audit_list",
                display_name="Consulter l'audit",
                description="Voir l'historique des actions",
                endpoint="/api/admin/audit",
                method="GET",
            ),
            ActionInfo(
                name="logs_list",
                display_name="Consulter les logs",
                description="Voir les logs applicatifs",
                endpoint="/api/admin/logs",
                method="GET",
            ),
            ActionInfo(
                name="logs_cleanup",
                display_name="Nettoyer les logs",
                description="Supprimer les anciens logs",
                endpoint="/api/admin/logs/cleanup",
                method="DELETE",
            ),
        ],
    },
    "validation": {
        "display_name": "Validation des inscriptions",
        "actions": [
            ActionInfo(
                name="validation_pending",
                display_name="Inscriptions en attente",
                description="Voir les demandes d'inscription",
                endpoint="/api/admin/validation/pending",
                method="GET",
            ),
            ActionInfo(
                name="validation_approve",
                display_name="Approuver une inscription",
                description="Valider un compte utilisateur",
                endpoint="/api/admin/validation/{id}/approve",
                method="POST",
            ),
            ActionInfo(
                name="validation_reject",
                display_name="Refuser une inscription",
                description="Rejeter une demande d'inscription",
                endpoint="/api/admin/validation/{id}/reject",
                method="POST",
            ),
        ],
    },
}


class PermissionsService:
    """Service de gestion des permissions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_permissions(self) -> PermissionsListResponse:
        """
        Retourne toutes les permissions organisees par role.

        Chaque role herite des permissions des roles inferieurs :
        - Admin (id=1) : toutes les permissions
        - Contributor (id=2) : USER + CONTRIBUTOR actions
        - User (id=3) : USER actions uniquement
        """
        # Charger les roles depuis la DB
        result = await self.session.execute(
            select(Role).order_by(Role.id)
        )
        roles = result.scalars().all()

        roles_permissions = []
        total_actions = 0

        for role in roles:
            categories = []

            # Determiner les actions selon le role
            if role.name == "admin" or role.id == 1:
                # Admin : toutes les actions
                all_actions = {**USER_ACTIONS, **CONTRIBUTOR_ACTIONS, **ADMIN_ACTIONS}
            elif role.name == "contributor" or role.id == 2:
                # Contributor : USER + CONTRIBUTOR
                all_actions = {**USER_ACTIONS, **CONTRIBUTOR_ACTIONS}
            else:
                # User : actions de base
                all_actions = USER_ACTIONS.copy()

            # Construire les categories
            for cat_key, cat_data in all_actions.items():
                cat_actions = cat_data.get("actions", [])
                if cat_actions:
                    categories.append(CategoryActions(
                        category=cat_key,
                        display_name=cat_data.get("display_name", cat_key),
                        actions=cat_actions,
                    ))
                    total_actions += len(cat_actions)

            roles_permissions.append(RolePermissions(
                role_id=role.id,
                role_name=role.name,
                role_display_name=role.display_name,
                categories=categories,
            ))

        return PermissionsListResponse(
            roles=roles_permissions,
            total_actions=total_actions,
        )

    async def get_role_permissions(self, role_id: int) -> RolePermissions:
        """Retourne les permissions d'un role specifique."""
        result = await self.session.execute(
            select(Role).where(Role.id == role_id)
        )
        role = result.scalar_one_or_none()

        if not role:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Role non trouve")

        # Determiner les actions selon le role
        if role.name == "admin" or role.id == 1:
            all_actions = {**USER_ACTIONS, **CONTRIBUTOR_ACTIONS, **ADMIN_ACTIONS}
        elif role.name == "contributor" or role.id == 2:
            all_actions = {**USER_ACTIONS, **CONTRIBUTOR_ACTIONS}
        else:
            all_actions = USER_ACTIONS.copy()

        categories = []
        for cat_key, cat_data in all_actions.items():
            cat_actions = cat_data.get("actions", [])
            if cat_actions:
                categories.append(CategoryActions(
                    category=cat_key,
                    display_name=cat_data.get("display_name", cat_key),
                    actions=cat_actions,
                ))

        return RolePermissions(
            role_id=role.id,
            role_name=role.name,
            role_display_name=role.display_name,
            categories=categories,
        )
