"""
Service de gestion des utilisateurs

Contient le UserManager avec les hooks pour l'audit des actions utilisateurs
et la creation automatique des collections ChromaDB.
"""
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import Request, Response, HTTPException
from fastapi_users import BaseUserManager, UUIDIDMixin
from sqlalchemy import select, func

from app.models import User, Collection, ApprovalStatus
from app.features.auth.config import SECRET
from app.features.audit.service import AuditService
from app.features.collections.chroma import create_user_collection, delete_user_collection
from app.common.email import get_email_service
from app.common.crypto.search import update_user_search_indexes
from app.common.i18n import t
from app.common.utils.security_logger import (
    log_login_success as sec_log_login_success,
    log_login_failed as sec_log_login_failed,
    log_logout as sec_log_logout,
    log_registration as sec_log_registration,
)

logger = logging.getLogger(__name__)


def get_validation_mode() -> str:
    """
    Retourne le mode de validation des inscriptions.

    Modes possibles:
    - "none": Pas de validation, auto-approuve
    - "email": Verification email uniquement, auto-approuve apres verification
    - "admin": Validation admin uniquement, pas de verification email
    - "email+admin": Double validation (email + admin)
    """
    return os.getenv("REGISTRATION_VALIDATION_MODE", "email+admin").lower()


def is_oauth_auto_approve() -> bool:
    """Verifie si les inscriptions OAuth sont auto-approuvees."""
    return os.getenv("OAUTH_AUTO_APPROVE", "false").lower() == "true"


class UserNotApprovedException(Exception):
    """Exception levee quand un utilisateur non approuve tente de se connecter."""

    def __init__(self, status: ApprovalStatus, lang: str = "fr"):
        self.status = status
        if status == ApprovalStatus.PENDING:
            self.message = t("error_user_pending", lang)
        elif status == ApprovalStatus.REJECTED:
            self.message = t("error_user_rejected", lang)
        else:
            self.message = t("error_user_unauthorized", lang)
        super().__init__(self.message)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """
    Gestionnaire d'utilisateurs avec hooks d'audit

    Gère l'inscription, la connexion, la réinitialisation de mot de passe
    et enregistre toutes les actions dans l'audit trail.
    """
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def create(self, user_create, safe: bool = False, request: Optional[Request] = None):
        """
        Override de create pour verifier l'unicite du username (insensible a la casse).
        """
        # Verifier si le username existe deja (case-insensitive)
        if hasattr(user_create, 'username') and user_create.username:
            result = await self.user_db.session.execute(
                select(User.id).where(
                    func.lower(User.username) == user_create.username.lower()
                ).limit(1)
            )
            existing_user_id = result.scalar_one_or_none()
            if existing_user_id:
                raise HTTPException(
                    status_code=400,
                    detail=t("error_username_exists")
                )

        return await super().create(user_create, safe=safe, request=request)

    async def authenticate(
        self, credentials
    ) -> Optional[User]:
        """
        Override de authenticate pour verifier le statut d'approbation.

        Bloque les utilisateurs PENDING ou REJECTED.
        """
        user = await super().authenticate(credentials)

        if user is None:
            # Log l'échec de connexion (identifiants invalides)
            sec_log_login_failed(
                email=credentials.username,
                reason="invalid_credentials",
            )
            return None

        # Verifier le statut d'approbation
        if hasattr(user, 'approval_status'):
            if user.approval_status == ApprovalStatus.PENDING:
                logger.warning(f"Login attempt by pending user: user_id={user.id}")
                sec_log_login_failed(email=user.email, reason="user_pending")
                # Log dans l'audit trail
                try:
                    await AuditService.log_login_blocked_pending(
                        db=self.user_db.session,
                        user_id=user.id,
                        email=user.email,
                        request=None  # Pas de request disponible ici
                    )
                except Exception as e:
                    logger.error(f"Error logging blocked login (pending): {e}")
                raise UserNotApprovedException(ApprovalStatus.PENDING)

            elif user.approval_status == ApprovalStatus.REJECTED:
                logger.warning(f"Login attempt by rejected user: user_id={user.id}")
                sec_log_login_failed(email=user.email, reason="user_rejected")
                # Log dans l'audit trail
                try:
                    await AuditService.log_login_blocked_rejected(
                        db=self.user_db.session,
                        user_id=user.id,
                        email=user.email,
                        request=None  # Pas de request disponible ici
                    )
                except Exception as e:
                    logger.error(f"Error logging blocked login (rejected): {e}")
                raise UserNotApprovedException(ApprovalStatus.REJECTED)

        return user

    async def on_after_register(self, user: User, request: Optional[Request] = None):
        """
        Hook appele apres inscription reussie.

        Gere le flux de validation selon REGISTRATION_VALIDATION_MODE:
        - "none": Auto-approuve immediatement
        - "email": Demande verification email, auto-approuve apres
        - "admin": Laisse en pending, notifie les admins
        - "email+admin": Demande verification email, puis validation admin
        """
        logger.info(f"User {user.id} has registered.")

        # Log de sécurité structuré
        ip = request.client.host if request and request.client else None
        sec_log_registration(
            user_id=str(user.id),
            email=user.email,
            ip=ip,
        )

        validation_mode = get_validation_mode()

        # Creer les index de recherche pour les donnees chiffrees (PII)
        try:
            update_user_search_indexes(
                user,
                first_name=user.first_name,
                last_name=user.last_name,
                phone=user.phone
            )
            await self.user_db.session.commit()
        except Exception as e:
            logger.error(f"Error creating search indexes for user {user.id}: {e}")

        # Creer la collection privee de l'utilisateur
        await self._create_user_collection(user)

        # Log l'inscription dans l'audit trail
        try:
            await AuditService.log_user_created(
                db=self.user_db.session,
                admin_user_id=None,  # Auto-registration (pas d'admin)
                new_user_id=user.id,
                new_user_email=user.email,
                role_id=user.role_id,
                request=request
            )
        except Exception as e:
            logger.error(f"Error logging user registration: {e}")

        # Gerer le mode de validation
        if validation_mode == "none":
            # Auto-approuve immediatement
            await self._auto_approve_user(user)
            await self._send_welcome_email(user)

        elif validation_mode == "email":
            # Verification email seulement, approval apres verification
            try:
                await self.request_verify(user, request)
            except Exception as e:
                logger.error(f"Error requesting email verification: {e}")

        elif validation_mode == "admin":
            # Validation admin seulement, pas de verification email
            await self._send_pending_approval_email(user)
            await self._notify_admins_new_registration(user)

        else:  # "email+admin" (default)
            # Double validation: email + admin
            try:
                await self.request_verify(user, request)
            except Exception as e:
                logger.error(f"Error requesting email verification: {e}")
            # L'email pending sera envoye apres verification (on_after_verify)

    async def _create_user_collection(self, user: User):
        """Cree la collection privee ChromaDB pour un nouvel utilisateur."""
        collection_name = f"user_{user.id}"

        try:
            # Creer dans ChromaDB
            create_user_collection(str(user.id))

            # Creer en DB
            collection = Collection(
                name=collection_name,
                display_name="Ma bibliothèque",
                type="private",
                owner_id=user.id,
                space="cosine",
            )
            self.user_db.session.add(collection)
            await self.user_db.session.commit()

            logger.info(f"Collection privee creee pour user_id={user.id}: {collection_name}")

        except Exception as e:
            logger.error(f"Erreur creation collection pour user_id={user.id}: {e}")
            # Ne pas faire echouer l'inscription si la collection echoue
            await self.user_db.session.rollback()

    async def _ensure_user_collection(self, user: User):
        """Vérifie et recrée la collection privée si manquante."""
        # Vérifier si la collection existe
        result = await self.user_db.session.execute(
            select(Collection).where(
                Collection.owner_id == user.id,
                Collection.type == "private"
            )
        )
        existing = result.scalar_one_or_none()

        if not existing:
            logger.info(f"Collection privée manquante pour user_id={user.id}, recréation...")
            await self._create_user_collection(user)

    async def on_after_login(
        self, user: User, request: Optional[Request] = None, response: Optional[Response] = None
    ):
        """Hook appele apres connexion reussie"""
        logger.info(f"User {user.id} has logged in.")

        # Vérifier/recréer la collection privée si manquante
        await self._ensure_user_collection(user)

        # Log de sécurité structuré
        ip = request.client.host if request and request.client else None
        user_agent = request.headers.get("User-Agent") if request else None
        sec_log_login_success(
            user_id=str(user.id),
            ip=ip,
            user_agent=user_agent,
        )

        # Log la connexion dans l'audit trail
        try:
            await AuditService.log_login_success(
                db=self.user_db.session,
                user_id=user.id,
                request=request
            )
        except Exception as e:
            logger.error(f"Error logging login: {e}")

    async def on_after_logout(
        self, user: User, request: Optional[Request] = None, token: Optional[str] = None
    ):
        """Hook appelé après déconnexion réussie."""
        logger.info(f"User {user.id} has logged out.")

        # Log de sécurité structuré
        ip = request.client.host if request and request.client else None
        sec_log_logout(
            user_id=str(user.id),
            ip=ip,
        )

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        """Hook appele apres demande de reinitialisation de mot de passe - envoie l'email"""
        logger.info(f"User {user.id} has forgot their password. Sending reset email.")

        # Envoyer l'email de reinitialisation
        try:
            email_service = get_email_service()
            username = user.email.split("@")[0]
            success = await email_service.send_password_reset_email(
                to_email=user.email,
                username=username,
                token=token
            )
            if success:
                logger.info(f"Password reset email sent to user_id={user.id}")
            else:
                logger.error(f"Failed to send password reset email to user_id={user.id}")
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")

        # Log la demande de reset dans l'audit trail
        try:
            await AuditService.log_action(
                db=self.user_db.session,
                action_name='password_reset_requested',
                user_id=user.id,
                resource_type_name='user',
                resource_id=user.id,
                details={'email': user.email},
                request=request
            )
        except Exception as e:
            logger.error(f"Error logging password reset request: {e}")

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        """Hook appele apres demande de verification email - envoie l'email"""
        logger.info(f"Verification requested for user {user.id}. Sending verification email.")

        try:
            email_service = get_email_service()
            username = user.email.split("@")[0]  # Extraire le nom d'utilisateur
            success = await email_service.send_verification_email(
                to_email=user.email,
                username=username,
                token=token
            )
            if success:
                logger.info(f"Verification email sent to user_id={user.id}")
            else:
                logger.error(f"Failed to send verification email to user_id={user.id}")
        except Exception as e:
            logger.error(f"Error sending verification email: {e}")

    async def on_after_verify(
        self, user: User, request: Optional[Request] = None
    ):
        """
        Hook appele apres verification email reussie.

        Selon le mode de validation:
        - "email": Auto-approuve et envoie welcome
        - "email+admin": Envoie pending_approval et notifie admins
        """
        logger.info(f"User {user.id} has been verified.")
        validation_mode = get_validation_mode()

        # Log la verification dans l'audit trail
        try:
            await AuditService.log_action(
                db=self.user_db.session,
                action_name='email_verified',
                user_id=user.id,
                resource_type_name='user',
                resource_id=user.id,
                details={'email': user.email},
                request=request
            )
        except Exception as e:
            logger.error(f"Error logging email verification: {e}")

        # Gerer selon le mode
        if validation_mode == "email":
            # Email verification seulement -> auto-approve
            await self._auto_approve_user(user)
            await self._send_welcome_email(user)

        elif validation_mode == "email+admin":
            # Double validation -> maintenant en attente d'admin
            await self._send_pending_approval_email(user)
            await self._notify_admins_new_registration(user)
        # Pour les autres modes, on_after_verify ne fait rien de special

    async def on_before_delete(self, user: User, request: Optional[Request] = None):
        """Hook appele avant suppression d'un utilisateur - supprime la collection ChromaDB."""
        delete_user_collection(str(user.id))

    # --- Methodes helpers pour la validation ---

    async def _auto_approve_user(self, user: User) -> None:
        """Auto-approuve un utilisateur (met le statut a APPROVED)."""
        try:
            user.approval_status = ApprovalStatus.APPROVED
            user.approved_at = datetime.now(timezone.utc)
            await self.user_db.session.commit()
            await self.user_db.session.refresh(user)
            logger.info(f"User user_id={user.id} auto-approved")
        except Exception as e:
            logger.error(f"Error auto-approving user: {e}")
            await self.user_db.session.rollback()

    async def _send_welcome_email(self, user: User) -> None:
        """Envoie l'email de bienvenue."""
        try:
            email_service = get_email_service()
            username = user.username or user.email.split("@")[0]
            success = await email_service.send_welcome_email(
                to_email=user.email,
                username=username
            )
            if success:
                logger.info(f"Welcome email sent to user_id={user.id}")
            else:
                logger.error(f"Failed to send welcome email to user_id={user.id}")
        except Exception as e:
            logger.error(f"Error sending welcome email: {e}")

    async def _send_pending_approval_email(self, user: User) -> None:
        """Envoie l'email indiquant que l'inscription est en attente de validation."""
        try:
            email_service = get_email_service()
            username = user.username or user.email.split("@")[0]
            success = await email_service.send_pending_approval_email(
                to_email=user.email,
                username=username
            )
            if success:
                logger.info(f"Pending approval email sent to user_id={user.id}")
            else:
                logger.error(f"Failed to send pending approval email to user_id={user.id}")
        except Exception as e:
            logger.error(f"Error sending pending approval email: {e}")

    async def _notify_admins_new_registration(self, user: User) -> None:
        """Notifie les admins d'une nouvelle inscription en attente."""
        if os.getenv("NOTIFY_ADMIN_ON_REGISTRATION", "true").lower() != "true":
            return

        try:
            email_service = get_email_service()

            # D'abord essayer la variable d'environnement
            admin_emails = os.getenv("ADMIN_NOTIFICATION_EMAILS", "").split(",")
            admin_emails = [e.strip() for e in admin_emails if e.strip()]

            # Si pas configuré, récupérer les admins depuis la DB
            if not admin_emails:
                from sqlalchemy import select
                result = await self.session.execute(
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
            username = user.username or user.email.split("@")[0]

            # Detecter si OAuth
            oauth_provider = None
            if user.oauth_accounts:
                oauth_provider = user.oauth_accounts[0].oauth_name

            registration_method = oauth_provider or "Email/Password"

            for admin_email in admin_emails:
                await email_service.send_new_registration_notification(
                    to_email=admin_email,
                    user_email=user.email,
                    username=username,
                    registration_date=user.created_at.strftime('%d/%m/%Y %H:%M'),
                    registration_method=registration_method,
                    is_verified=user.is_verified,
                    dashboard_url=f"{dashboard_url}/users/pending"
                )

            logger.info(f"Admin notification sent for new registration: user_id={user.id}")

        except Exception as e:
            logger.error(f"Error notifying admins of new registration: {e}")
