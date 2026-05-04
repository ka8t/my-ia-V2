"""
Service Admin Bulk

Logique métier pour les opérations en masse.
"""
import uuid
import shutil
import logging
from pathlib import Path
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi import HTTPException

from app.models import User, Conversation, Document, Session
from app.features.admin.bulk.schemas import (
    BulkOperationResult, BulkUserFilters, BulkPreflightResponse, AdminUserInfo
)
from app.core.deps import get_chroma_client
from app.core.config import settings
from app.features.collections.chroma import delete_user_collection

logger = logging.getLogger(__name__)


class BulkService:
    """Service pour les opérations bulk"""

    # ========================================================================
    # UTILISATEURS
    # ========================================================================

    @staticmethod
    async def activate_users(
        db: AsyncSession,
        user_ids: List[uuid.UUID],
        admin_user_id: uuid.UUID
    ) -> BulkOperationResult:
        """
        Active plusieurs utilisateurs.

        Args:
            db: Session de base de données
            user_ids: Liste des IDs utilisateurs
            admin_user_id: ID de l'admin effectuant l'action

        Returns:
            BulkOperationResult
        """
        success_count = 0
        failed_ids = []
        errors = {}

        for user_id in user_ids:
            try:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.unique().scalar_one_or_none()

                if not user:
                    failed_ids.append(user_id)
                    errors[str(user_id)] = "User not found"
                    continue

                user.is_active = True
                success_count += 1

            except Exception as e:
                failed_ids.append(user_id)
                errors[str(user_id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    @staticmethod
    async def deactivate_users(
        db: AsyncSession,
        user_ids: List[uuid.UUID],
        admin_user_id: uuid.UUID
    ) -> BulkOperationResult:
        """
        Désactive plusieurs utilisateurs.

        Args:
            db: Session de base de données
            user_ids: Liste des IDs utilisateurs
            admin_user_id: ID de l'admin effectuant l'action

        Returns:
            BulkOperationResult
        """
        success_count = 0
        failed_ids = []
        errors = {}

        for user_id in user_ids:
            try:
                # Empêcher la désactivation de soi-même
                if user_id == admin_user_id:
                    failed_ids.append(user_id)
                    errors[str(user_id)] = "Cannot deactivate your own account"
                    continue

                result = await db.execute(select(User).where(User.id == user_id))
                user = result.unique().scalar_one_or_none()

                if not user:
                    failed_ids.append(user_id)
                    errors[str(user_id)] = "User not found"
                    continue

                user.is_active = False
                success_count += 1

            except Exception as e:
                failed_ids.append(user_id)
                errors[str(user_id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    @staticmethod
    async def change_users_role(
        db: AsyncSession,
        user_ids: List[uuid.UUID],
        new_role_id: int,
        admin_user_id: uuid.UUID
    ) -> BulkOperationResult:
        """
        Change le rôle de plusieurs utilisateurs.

        Args:
            db: Session de base de données
            user_ids: Liste des IDs utilisateurs
            new_role_id: Nouveau rôle ID
            admin_user_id: ID de l'admin effectuant l'action

        Returns:
            BulkOperationResult
        """
        success_count = 0
        failed_ids = []
        errors = {}

        for user_id in user_ids:
            try:
                # Empêcher la modification de son propre rôle
                if user_id == admin_user_id and new_role_id != 1:
                    failed_ids.append(user_id)
                    errors[str(user_id)] = "Cannot demote yourself"
                    continue

                result = await db.execute(select(User).where(User.id == user_id))
                user = result.unique().scalar_one_or_none()

                if not user:
                    failed_ids.append(user_id)
                    errors[str(user_id)] = "User not found"
                    continue

                user.role_id = new_role_id
                user.is_superuser = (new_role_id == 1)
                success_count += 1

            except Exception as e:
                failed_ids.append(user_id)
                errors[str(user_id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    @staticmethod
    async def delete_users(
        db: AsyncSession,
        user_ids: List[uuid.UUID],
        admin_user_id: uuid.UUID,
        confirm: bool
    ) -> BulkOperationResult:
        """
        Supprime plusieurs utilisateurs.

        Args:
            db: Session de base de données
            user_ids: Liste des IDs utilisateurs
            admin_user_id: ID de l'admin effectuant l'action
            confirm: Confirmation obligatoire

        Returns:
            BulkOperationResult

        Raises:
            HTTPException 400 si confirm n'est pas True
        """
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Bulk delete requires confirm=true"
            )

        success_count = 0
        failed_ids = []
        errors = {}

        for user_id in user_ids:
            try:
                # Empêcher la suppression de soi-même
                if user_id == admin_user_id:
                    failed_ids.append(user_id)
                    errors[str(user_id)] = "Cannot delete your own account"
                    continue

                result = await db.execute(select(User).where(User.id == user_id))
                user = result.unique().scalar_one_or_none()

                if not user:
                    failed_ids.append(user_id)
                    errors[str(user_id)] = "User not found"
                    continue

                user_id_str = str(user_id)

                # 1. Nettoyage ChromaDB EN PREMIER — si échec, user marqué failed
                delete_user_collection(user_id_str)

                # 2. Nettoyage fichiers disque
                user_storage_path = Path(settings.storage_local_path) / user_id_str
                if user_storage_path.exists():
                    try:
                        shutil.rmtree(user_storage_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete storage folder for user {user_id_str}: {e}")

                # 3. Supprimer de la DB
                await db.delete(user)
                success_count += 1

            except Exception as e:
                failed_ids.append(user_id)
                errors[str(user_id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    # ========================================================================
    # CONVERSATIONS
    # ========================================================================

    @staticmethod
    async def delete_conversations(
        db: AsyncSession,
        conversation_ids: List[uuid.UUID],
        confirm: bool
    ) -> BulkOperationResult:
        """
        Supprime plusieurs conversations.

        Args:
            db: Session de base de données
            conversation_ids: Liste des IDs conversations
            confirm: Confirmation obligatoire

        Returns:
            BulkOperationResult
        """
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Bulk delete requires confirm=true"
            )

        success_count = 0
        failed_ids = []
        errors = {}

        for conv_id in conversation_ids:
            try:
                result = await db.execute(
                    select(Conversation).where(Conversation.id == conv_id)
                )
                conversation = result.scalar_one_or_none()

                if not conversation:
                    failed_ids.append(conv_id)
                    errors[str(conv_id)] = "Conversation not found"
                    continue

                await db.delete(conversation)
                success_count += 1

            except Exception as e:
                failed_ids.append(conv_id)
                errors[str(conv_id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    # ========================================================================
    # DOCUMENTS
    # ========================================================================

    @staticmethod
    async def delete_documents(
        db: AsyncSession,
        document_ids: List[uuid.UUID],
        confirm: bool
    ) -> BulkOperationResult:
        """
        Supprime plusieurs documents (DB + ChromaDB).

        Args:
            db: Session de base de données
            document_ids: Liste des IDs documents
            confirm: Confirmation obligatoire

        Returns:
            BulkOperationResult
        """
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Bulk delete requires confirm=true"
            )

        success_count = 0
        failed_ids = []
        errors = {}

        # Récupérer le client ChromaDB une fois
        chroma_client = None
        try:
            chroma_client = get_chroma_client()
        except Exception as e:
            logger.warning(f"ChromaDB unavailable: {e}")

        for doc_id in document_ids:
            try:
                result = await db.execute(select(Document).where(Document.id == doc_id))
                document = result.scalar_one_or_none()

                if not document:
                    failed_ids.append(doc_id)
                    errors[str(doc_id)] = "Document not found"
                    continue

                # Supprimer de ChromaDB
                if chroma_client:
                    try:
                        collection = chroma_client.get_collection(name=settings.collection_name)
                        collection.delete(where={"file_hash": document.file_hash})
                    except Exception as e:
                        logger.warning(f"Could not delete from ChromaDB: {e}")

                # Supprimer de la DB
                await db.delete(document)
                success_count += 1

            except Exception as e:
                failed_ids.append(doc_id)
                errors[str(doc_id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    # ========================================================================
    # SESSIONS
    # ========================================================================

    @staticmethod
    async def revoke_sessions(
        db: AsyncSession,
        session_ids: List[uuid.UUID],
        confirm: bool
    ) -> BulkOperationResult:
        """
        Révoque plusieurs sessions.

        Args:
            db: Session de base de données
            session_ids: Liste des IDs sessions
            confirm: Confirmation obligatoire

        Returns:
            BulkOperationResult
        """
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Bulk delete requires confirm=true"
            )

        success_count = 0
        failed_ids = []
        errors = {}

        for session_id in session_ids:
            try:
                result = await db.execute(
                    select(Session).where(Session.id == session_id)
                )
                session = result.scalar_one_or_none()

                if not session:
                    failed_ids.append(session_id)
                    errors[str(session_id)] = "Session not found"
                    continue

                await db.delete(session)
                success_count += 1

            except Exception as e:
                failed_ids.append(session_id)
                errors[str(session_id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    # ========================================================================
    # OPÉRATIONS FILTRÉES (UTILISATEURS)
    # ========================================================================

    @staticmethod
    def _build_user_query(filters: BulkUserFilters):
        """
        Construit une query SQLAlchemy avec les filtres.

        Args:
            filters: Filtres à appliquer

        Returns:
            Query SQLAlchemy
        """
        query = select(User)

        if filters.role_id is not None:
            query = query.where(User.role_id == filters.role_id)

        if filters.is_active is not None:
            query = query.where(User.is_active == filters.is_active)

        if filters.is_verified is not None:
            query = query.where(User.is_verified == filters.is_verified)

        if filters.search:
            search_term = f"%{filters.search}%"
            query = query.where(
                (User.email.ilike(search_term)) |
                (User.username.ilike(search_term))
            )

        return query

    @staticmethod
    async def preflight_filtered_users(
        db: AsyncSession,
        filters: BulkUserFilters,
        check_admins: bool = True,
        admin_user_id: uuid.UUID = None
    ) -> BulkPreflightResponse:
        """
        Vérifie les utilisateurs qui seront impactés avant une opération bulk.

        Args:
            db: Session de base de données
            filters: Filtres à appliquer
            check_admins: Si True, vérifie la présence d'admins
            admin_user_id: ID de l'admin effectuant l'action (exclu du comptage)

        Returns:
            BulkPreflightResponse avec le nombre d'utilisateurs et les admins détectés
        """
        query = BulkService._build_user_query(filters)
        result = await db.execute(query)
        users = result.unique().scalars().all()

        # Exclure l'admin courant de la liste
        if admin_user_id:
            users = [u for u in users if u.id != admin_user_id]

        total_count = len(users)
        admins = []
        admin_count = 0

        if check_admins:
            for user in users:
                if user.role_id == 1:  # Admin role
                    admin_count += 1
                    admins.append(AdminUserInfo(
                        id=user.id,
                        email=user.email,
                        username=user.username
                    ))

        can_proceed = admin_count == 0 if check_admins else True
        warning_message = None

        if not can_proceed:
            warning_message = f"{admin_count} administrateur(s) détecté(s). Veuillez les traiter manuellement."

        return BulkPreflightResponse(
            total_count=total_count,
            admin_count=admin_count,
            admins=admins,
            can_proceed=can_proceed,
            warning_message=warning_message
        )

    @staticmethod
    async def activate_users_filtered(
        db: AsyncSession,
        filters: BulkUserFilters,
        admin_user_id: uuid.UUID
    ) -> BulkOperationResult:
        """
        Active tous les utilisateurs correspondant aux filtres.
        Note: Cette action n'a pas besoin de vérifier les admins.

        Args:
            db: Session de base de données
            filters: Filtres à appliquer
            admin_user_id: ID de l'admin effectuant l'action

        Returns:
            BulkOperationResult
        """
        query = BulkService._build_user_query(filters)
        result = await db.execute(query)
        users = result.unique().scalars().all()

        success_count = 0
        failed_ids = []
        errors = {}

        for user in users:
            try:
                user.is_active = True
                success_count += 1
            except Exception as e:
                failed_ids.append(user.id)
                errors[str(user.id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    @staticmethod
    async def deactivate_users_filtered(
        db: AsyncSession,
        filters: BulkUserFilters,
        admin_user_id: uuid.UUID
    ) -> BulkOperationResult:
        """
        Désactive tous les utilisateurs correspondant aux filtres.
        IMPORTANT: Vérifie qu'il n'y a pas d'admins avant d'exécuter.

        Args:
            db: Session de base de données
            filters: Filtres à appliquer
            admin_user_id: ID de l'admin effectuant l'action

        Returns:
            BulkOperationResult

        Raises:
            HTTPException 400 si des admins sont présents
        """
        # Preflight check
        preflight = await BulkService.preflight_filtered_users(
            db, filters, check_admins=True, admin_user_id=admin_user_id
        )

        if not preflight.can_proceed:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": preflight.warning_message,
                    "admin_count": preflight.admin_count,
                    "admins": [{"id": str(a.id), "email": a.email} for a in preflight.admins]
                }
            )

        query = BulkService._build_user_query(filters)
        result = await db.execute(query)
        users = result.unique().scalars().all()

        success_count = 0
        failed_ids = []
        errors = {}

        for user in users:
            try:
                # Skip l'admin courant
                if user.id == admin_user_id:
                    continue

                user.is_active = False
                success_count += 1
            except Exception as e:
                failed_ids.append(user.id)
                errors[str(user.id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    @staticmethod
    async def change_users_role_filtered(
        db: AsyncSession,
        filters: BulkUserFilters,
        new_role_id: int,
        admin_user_id: uuid.UUID
    ) -> BulkOperationResult:
        """
        Change le rôle de tous les utilisateurs correspondant aux filtres.
        IMPORTANT: Vérifie qu'il n'y a pas d'admins avant d'exécuter.

        Args:
            db: Session de base de données
            filters: Filtres à appliquer
            new_role_id: Nouveau rôle ID
            admin_user_id: ID de l'admin effectuant l'action

        Returns:
            BulkOperationResult

        Raises:
            HTTPException 400 si des admins sont présents
        """
        # Preflight check
        preflight = await BulkService.preflight_filtered_users(
            db, filters, check_admins=True, admin_user_id=admin_user_id
        )

        if not preflight.can_proceed:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": preflight.warning_message,
                    "admin_count": preflight.admin_count,
                    "admins": [{"id": str(a.id), "email": a.email} for a in preflight.admins]
                }
            )

        query = BulkService._build_user_query(filters)
        result = await db.execute(query)
        users = result.unique().scalars().all()

        success_count = 0
        failed_ids = []
        errors = {}

        for user in users:
            try:
                # Skip l'admin courant
                if user.id == admin_user_id:
                    continue

                user.role_id = new_role_id
                user.is_superuser = (new_role_id == 1)
                success_count += 1
            except Exception as e:
                failed_ids.append(user.id)
                errors[str(user.id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )

    @staticmethod
    async def delete_users_filtered(
        db: AsyncSession,
        filters: BulkUserFilters,
        admin_user_id: uuid.UUID,
        confirm: bool
    ) -> BulkOperationResult:
        """
        Supprime tous les utilisateurs correspondant aux filtres.
        IMPORTANT: Vérifie qu'il n'y a pas d'admins avant d'exécuter.

        Args:
            db: Session de base de données
            filters: Filtres à appliquer
            admin_user_id: ID de l'admin effectuant l'action
            confirm: Confirmation obligatoire

        Returns:
            BulkOperationResult

        Raises:
            HTTPException 400 si confirm=False ou si des admins sont présents
        """
        if not confirm:
            raise HTTPException(
                status_code=400,
                detail="Bulk delete requires confirm=true"
            )

        # Preflight check
        preflight = await BulkService.preflight_filtered_users(
            db, filters, check_admins=True, admin_user_id=admin_user_id
        )

        if not preflight.can_proceed:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": preflight.warning_message,
                    "admin_count": preflight.admin_count,
                    "admins": [{"id": str(a.id), "email": a.email} for a in preflight.admins]
                }
            )

        query = BulkService._build_user_query(filters)
        result = await db.execute(query)
        users = result.unique().scalars().all()

        success_count = 0
        failed_ids = []
        errors = {}

        for user in users:
            try:
                # Skip l'admin courant
                if user.id == admin_user_id:
                    continue

                user_id_str = str(user.id)

                # 1. Nettoyage ChromaDB EN PREMIER — si échec, user marqué failed
                delete_user_collection(user_id_str)

                # 2. Nettoyage fichiers disque
                user_storage_path = Path(settings.storage_local_path) / user_id_str
                if user_storage_path.exists():
                    try:
                        shutil.rmtree(user_storage_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete storage folder for user {user_id_str}: {e}")

                # 3. Supprimer de la DB
                await db.delete(user)
                success_count += 1
            except Exception as e:
                failed_ids.append(user.id)
                errors[str(user.id)] = str(e)

        await db.commit()

        return BulkOperationResult(
            success_count=success_count,
            failed_count=len(failed_ids),
            failed_ids=failed_ids,
            errors=errors
        )
