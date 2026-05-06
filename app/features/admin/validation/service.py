"""
Service de validation des inscriptions utilisateurs.

Gere l'approbation et le refus des inscriptions par les admins/validateurs.
"""
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import User, ApprovalStatus, OAuthAccount
from app.common.email import get_email_service

logger = logging.getLogger(__name__)


class ValidationService:
    """Service pour la validation des inscriptions."""

    @staticmethod
    async def get_pending_users(
        db: AsyncSession,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[User], int]:
        """
        Recupere les utilisateurs en attente de validation.

        Args:
            db: Session de base de donnees
            limit: Nombre max de resultats
            offset: Offset pour pagination

        Returns:
            Tuple (liste users, total count)
        """
        # Compter le total
        count_query = select(func.count()).where(
            User.approval_status == ApprovalStatus.PENDING
        ).select_from(User)
        total = await db.scalar(count_query) or 0

        # Recuperer les users avec leurs comptes OAuth et role
        query = (
            select(User)
            .options(selectinload(User.oauth_accounts), selectinload(User.role))
            .where(User.approval_status == ApprovalStatus.PENDING)
            .order_by(User.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(query)
        users = list(result.scalars().all())

        return users, total

    @staticmethod
    async def approve_user(
        db: AsyncSession,
        user_id: UUID,
        approver_id: UUID
    ) -> Optional[User]:
        """
        Approuve un utilisateur.

        Args:
            db: Session de base de donnees
            user_id: ID de l'utilisateur a approuver
            approver_id: ID de l'admin/validateur

        Returns:
            User approuve ou None si non trouve
        """
        # Recuperer l'utilisateur
        query = select(User).where(User.id == user_id)
        result = await db.execute(query)
        user = result.unique().scalar_one_or_none()

        if not user:
            return None

        if user.approval_status != ApprovalStatus.PENDING:
            logger.warning(f"User {user_id} n'est pas en attente (status: {user.approval_status})")
            return None

        # Mettre a jour le statut
        user.approval_status = ApprovalStatus.APPROVED
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = approver_id
        user.rejection_reason = None

        await db.commit()
        await db.refresh(user)

        logger.info(f"User user_id={user.id} approuve par {approver_id}")

        # Envoyer l'email de bienvenue
        await ValidationService._send_approved_email(user)

        return user

    @staticmethod
    async def reject_user(
        db: AsyncSession,
        user_id: UUID,
        approver_id: UUID,
        reason: str
    ) -> Optional[User]:
        """
        Refuse un utilisateur.

        Args:
            db: Session de base de donnees
            user_id: ID de l'utilisateur a refuser
            approver_id: ID de l'admin/validateur
            reason: Raison du refus

        Returns:
            User refuse ou None si non trouve
        """
        # Recuperer l'utilisateur
        query = select(User).where(User.id == user_id)
        result = await db.execute(query)
        user = result.unique().scalar_one_or_none()

        if not user:
            return None

        if user.approval_status != ApprovalStatus.PENDING:
            logger.warning(f"User {user_id} n'est pas en attente (status: {user.approval_status})")
            return None

        # Mettre a jour le statut
        user.approval_status = ApprovalStatus.REJECTED
        user.approved_at = datetime.now(timezone.utc)
        user.approved_by = approver_id
        user.rejection_reason = reason

        await db.commit()
        await db.refresh(user)

        logger.info(f"User user_id={user.id} refuse par {approver_id}: {reason}")

        # Envoyer l'email de refus
        await ValidationService._send_rejected_email(user, reason)

        return user

    @staticmethod
    async def get_validation_stats(db: AsyncSession) -> dict:
        """
        Recupere les statistiques de validation.

        Returns:
            Dict avec pending_count, approved_today, rejected_today
        """
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Pending count
        pending_count = await db.scalar(
            select(func.count()).where(User.approval_status == ApprovalStatus.PENDING).select_from(User)
        ) or 0

        # Approved today
        approved_today = await db.scalar(
            select(func.count()).where(
                and_(
                    User.approval_status == ApprovalStatus.APPROVED,
                    User.approved_at >= today_start
                )
            ).select_from(User)
        ) or 0

        # Rejected today
        rejected_today = await db.scalar(
            select(func.count()).where(
                and_(
                    User.approval_status == ApprovalStatus.REJECTED,
                    User.approved_at >= today_start
                )
            ).select_from(User)
        ) or 0

        return {
            "pending_count": pending_count,
            "approved_today": approved_today,
            "rejected_today": rejected_today
        }

    @staticmethod
    async def notify_admins_new_registration(
        db: AsyncSession,
        user: User
    ) -> None:
        """
        Notifie les admins d'une nouvelle inscription.

        Args:
            db: Session de base de données
            user: Nouvel utilisateur inscrit
        """
        if not os.getenv("NOTIFY_ADMIN_ON_REGISTRATION", "true").lower() == "true":
            return

        try:
            email_service = get_email_service()

            # D'abord essayer la variable d'environnement
            admin_emails = os.getenv("ADMIN_NOTIFICATION_EMAILS", "").split(",")
            admin_emails = [e.strip() for e in admin_emails if e.strip()]

            # Si pas configuré, récupérer les admins depuis la DB
            if not admin_emails:
                result = await db.execute(
                    select(User.email).where(
                        User.role_id == 1,  # Admin
                        User.is_active == True,
                        User.is_verified == True
                    )
                )
                admin_emails = [row[0] for row in result.fetchall()]

            if not admin_emails:
                logger.info("Pas d'emails admin disponibles pour notification")
                return

            dashboard_url = os.getenv("ADMIN_DASHBOARD_URL", "http://localhost:8081")

            for admin_email in admin_emails:
                await email_service.backend.send(
                    to_email=admin_email,
                    subject=f"Nouvelle inscription en attente - {user.email}",
                    html_content=f"""
                    <h2>Nouvelle inscription</h2>
                    <p>Un nouvel utilisateur s'est inscrit et attend votre validation :</p>
                    <ul>
                        <li><strong>Email:</strong> {user.email}</li>
                        <li><strong>Username:</strong> {user.username}</li>
                        <li><strong>Date:</strong> {user.created_at.strftime('%d/%m/%Y %H:%M')}</li>
                    </ul>
                    <p><a href="{dashboard_url}/users/pending">Voir les inscriptions en attente</a></p>
                    """,
                    text_content=f"Nouvelle inscription: {user.email} ({user.username})"
                )

            logger.info(f"Notification envoyee aux admins pour user_id={user.id}")

        except Exception as e:
            logger.error(f"Erreur notification admin: {e}")

    @staticmethod
    async def _send_approved_email(user: User) -> None:
        """Envoie l'email d'approbation."""
        try:
            email_service = get_email_service()
            username = user.username or user.email.split("@")[0]

            # Utiliser le template welcome existant
            await email_service.send_welcome_email(
                to_email=user.email,
                username=username
            )
        except Exception as e:
            logger.error(f"Erreur envoi email approbation: {e}")

    @staticmethod
    async def _send_rejected_email(user: User, reason: str) -> None:
        """Envoie l'email de refus."""
        try:
            email_service = get_email_service()
            username = user.username or user.email.split("@")[0]

            html_content = email_service._load_template(
                "rejected",
                {
                    "username": username,
                    "reason": reason,
                    "title": "Inscription refusee",
                    "message": f"Bonjour {username}, votre demande d'inscription a ete refusee."
                }
            )

            await email_service.backend.send(
                to_email=user.email,
                subject="Inscription refusee - MY-IA",
                html_content=html_content,
                text_content=f"Bonjour {username}, votre inscription a ete refusee. Raison: {reason}"
            )
        except Exception as e:
            logger.error(f"Erreur envoi email refus: {e}")

    @staticmethod
    async def bulk_approve_users(
        db: AsyncSession,
        user_ids: List[UUID],
        approver_id: UUID
    ) -> dict:
        """
        Approuve plusieurs utilisateurs en masse.

        Charge tous les utilisateurs en une seule requête pour éviter le N+1.

        Args:
            db: Session de base de données
            user_ids: Liste des IDs à approuver
            approver_id: ID de l'admin

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []
        approved_users = []

        logger.info(f"Bulk approve: {len(user_ids)} utilisateurs par {approver_id}")

        # Charger tous les utilisateurs en une seule requête
        query = select(User).where(User.id.in_(user_ids))
        result = await db.execute(query)
        users_by_id = {user.id: user for user in result.unique().scalars().all()}

        now = datetime.now(timezone.utc)

        for user_id in user_ids:
            user = users_by_id.get(user_id)

            if not user:
                failed_ids.append(user_id)
                logger.warning(f"Bulk approve: utilisateur {user_id} non trouvé")
                continue

            # Vérifier si c'est un admin (protection)
            if user.role_id == 1:
                logger.warning(f"Bulk approve: admin {user_id} ignoré (protection)")
                failed_ids.append(user_id)
                continue

            if user.approval_status != ApprovalStatus.PENDING:
                logger.warning(f"Bulk approve: {user_id} n'est pas en attente (status: {user.approval_status})")
                failed_ids.append(user_id)
                continue

            # Mettre à jour le statut
            user.approval_status = ApprovalStatus.APPROVED
            user.approved_at = now
            user.approved_by = approver_id
            user.rejection_reason = None
            success_count += 1
            approved_users.append(user)

        # Un seul commit pour toutes les modifications
        if approved_users:
            await db.commit()
            for user in approved_users:
                await db.refresh(user)

        logger.info(f"Bulk approve terminé: {success_count} succès, {len(failed_ids)} échecs")

        # Envoyer les emails après le commit (hors transaction)
        for user in approved_users:
            logger.info(f"User user_id={user.id} approuvé par {approver_id}")
            await ValidationService._send_approved_email(user)

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }

    @staticmethod
    async def bulk_reject_users(
        db: AsyncSession,
        user_ids: List[UUID],
        approver_id: UUID,
        reason: str
    ) -> dict:
        """
        Rejette plusieurs utilisateurs en masse.

        Charge tous les utilisateurs en une seule requête pour éviter le N+1.

        Args:
            db: Session de base de données
            user_ids: Liste des IDs à rejeter
            approver_id: ID de l'admin
            reason: Raison commune du rejet

        Returns:
            Dict avec success_count, failed_count, failed_ids
        """
        success_count = 0
        failed_ids = []
        rejected_users = []

        logger.info(f"Bulk reject: {len(user_ids)} utilisateurs par {approver_id}, raison: {reason}")

        # Charger tous les utilisateurs en une seule requête
        query = select(User).where(User.id.in_(user_ids))
        result = await db.execute(query)
        users_by_id = {user.id: user for user in result.unique().scalars().all()}

        now = datetime.now(timezone.utc)

        for user_id in user_ids:
            user = users_by_id.get(user_id)

            if not user:
                failed_ids.append(user_id)
                logger.warning(f"Bulk reject: utilisateur {user_id} non trouvé")
                continue

            # Vérifier si c'est un admin (protection)
            if user.role_id == 1:
                logger.warning(f"Bulk reject: admin {user_id} ignoré (protection)")
                failed_ids.append(user_id)
                continue

            if user.approval_status != ApprovalStatus.PENDING:
                logger.warning(f"Bulk reject: {user_id} n'est pas en attente (status: {user.approval_status})")
                failed_ids.append(user_id)
                continue

            # Mettre à jour le statut
            user.approval_status = ApprovalStatus.REJECTED
            user.approved_at = now
            user.approved_by = approver_id
            user.rejection_reason = reason
            success_count += 1
            rejected_users.append(user)

        # Un seul commit pour toutes les modifications
        if rejected_users:
            await db.commit()
            for user in rejected_users:
                await db.refresh(user)

        logger.info(f"Bulk reject terminé: {success_count} succès, {len(failed_ids)} échecs")

        # Envoyer les emails après le commit (hors transaction)
        for user in rejected_users:
            logger.info(f"User user_id={user.id} refusé par {approver_id}: {reason}")
            await ValidationService._send_rejected_email(user, reason)

        return {
            "success_count": success_count,
            "failed_count": len(failed_ids),
            "failed_ids": failed_ids
        }
