"""
Service Admin Dashboard

Logique métier pour les statistiques et métriques du dashboard.
"""
import logging
from datetime import datetime, timedelta, date, timezone
from typing import List, Dict

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.models import (
    User, Role, Conversation, ConversationMode, Message,
    Document, Session, AuditLog
)
from app.features.admin.dashboard.schemas import (
    DashboardOverview, UserStats, ConversationStats,
    DocumentStats, SystemStats, UsageDaily, TrendData
)

logger = logging.getLogger(__name__)


class DashboardService:
    """Service pour les statistiques du dashboard"""

    # ========================================================================
    # OVERVIEW
    # ========================================================================

    @staticmethod
    async def get_overview(db: AsyncSession) -> DashboardOverview:
        """
        Récupère la vue d'ensemble complète du dashboard.

        Args:
            db: Session de base de données

        Returns:
            DashboardOverview avec toutes les statistiques
        """
        user_stats = await DashboardService.get_user_stats(db)
        conversation_stats = await DashboardService.get_conversation_stats(db)
        document_stats = await DashboardService.get_document_stats(db)
        system_stats = await DashboardService.get_system_stats(db)

        return DashboardOverview(
            users=user_stats,
            conversations=conversation_stats,
            documents=document_stats,
            system=system_stats
        )

    # ========================================================================
    # STATISTIQUES UTILISATEURS
    # ========================================================================

    @staticmethod
    async def get_user_stats(db: AsyncSession) -> UserStats:
        """Récupère les statistiques des utilisateurs"""
        # Total
        total_result = await db.execute(select(func.count(User.id)))
        total = total_result.scalar() or 0

        # Actifs / Inactifs
        active_result = await db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )
        active = active_result.scalar() or 0
        inactive = total - active

        # Vérifiés
        verified_result = await db.execute(
            select(func.count(User.id)).where(User.is_verified == True)
        )
        verified = verified_result.scalar() or 0

        # Par rôle
        role_query = (
            select(Role.name, func.count(User.id))
            .join(User, User.role_id == Role.id)
            .group_by(Role.name)
        )
        role_result = await db.execute(role_query)
        by_role = {name: count for name, count in role_result.all()}

        # Nouveaux utilisateurs
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        new_7_result = await db.execute(
            select(func.count(User.id)).where(User.created_at >= week_ago)
        )
        new_last_7_days = new_7_result.scalar() or 0

        new_30_result = await db.execute(
            select(func.count(User.id)).where(User.created_at >= month_ago)
        )
        new_last_30_days = new_30_result.scalar() or 0

        return UserStats(
            total=total,
            active=active,
            inactive=inactive,
            verified=verified,
            by_role=by_role,
            new_last_7_days=new_last_7_days,
            new_last_30_days=new_last_30_days
        )

    # ========================================================================
    # STATISTIQUES CONVERSATIONS
    # ========================================================================

    @staticmethod
    async def get_conversation_stats(db: AsyncSession) -> ConversationStats:
        """Récupère les statistiques des conversations"""
        # Total conversations
        total_result = await db.execute(select(func.count(Conversation.id)))
        total = total_result.scalar() or 0

        # Par mode
        mode_query = (
            select(ConversationMode.name, func.count(Conversation.id))
            .join(Conversation, Conversation.mode_id == ConversationMode.id)
            .group_by(ConversationMode.name)
        )
        mode_result = await db.execute(mode_query)
        by_mode = {name: count for name, count in mode_result.all()}

        # Total messages
        messages_result = await db.execute(select(func.count(Message.id)))
        messages_total = messages_result.scalar() or 0

        # Moyenne messages par conversation
        avg_messages = messages_total / total if total > 0 else 0.0

        return ConversationStats(
            total=total,
            by_mode=by_mode,
            messages_total=messages_total,
            avg_messages_per_conversation=round(avg_messages, 2)
        )

    # ========================================================================
    # STATISTIQUES DOCUMENTS
    # ========================================================================

    @staticmethod
    async def get_document_stats(db: AsyncSession) -> DocumentStats:
        """Récupère les statistiques des documents"""
        # Total documents
        total_result = await db.execute(select(func.count(Document.id)))
        total = total_result.scalar() or 0

        # Taille totale
        size_result = await db.execute(select(func.sum(Document.file_size)))
        total_size = size_result.scalar() or 0

        # Par type de fichier
        type_query = (
            select(Document.file_type, func.count(Document.id))
            .group_by(Document.file_type)
        )
        type_result = await db.execute(type_query)
        by_type = {file_type: count for file_type, count in type_result.all()}

        # Total chunks
        chunks_result = await db.execute(select(func.sum(Document.chunk_count)))
        total_chunks = chunks_result.scalar() or 0

        return DocumentStats(
            total=total,
            total_size_bytes=total_size,
            by_type=by_type,
            total_chunks=total_chunks
        )

    # ========================================================================
    # STATISTIQUES SYSTÈME
    # ========================================================================

    @staticmethod
    async def get_system_stats(db: AsyncSession) -> SystemStats:
        """Récupère les statistiques système"""
        # Total sessions
        total_sessions_result = await db.execute(select(func.count(Session.id)))
        total_sessions = total_sessions_result.scalar() or 0

        # Sessions actives
        now = datetime.now(timezone.utc)
        active_sessions_result = await db.execute(
            select(func.count(Session.id)).where(Session.expires_at > now)
        )
        active_sessions = active_sessions_result.scalar() or 0

        # Total audit logs
        audit_logs_result = await db.execute(select(func.count(AuditLog.id)))
        total_audit_logs = audit_logs_result.scalar() or 0

        return SystemStats(
            total_sessions=total_sessions,
            active_sessions=active_sessions,
            total_audit_logs=total_audit_logs
        )

    # ========================================================================
    # USAGE QUOTIDIEN
    # ========================================================================

    @staticmethod
    async def get_usage_daily(
        db: AsyncSession,
        days: int = 30
    ) -> List[UsageDaily]:
        """
        Récupère les statistiques d'usage des N derniers jours.

        Args:
            db: Session de base de données
            days: Nombre de jours à analyser (défaut: 30)

        Returns:
            Liste des statistiques par jour
        """
        result = []
        now = datetime.now(timezone.utc)

        for i in range(days):
            target_date = (now - timedelta(days=i)).date()
            start = datetime.combine(target_date, datetime.min.time())
            end = datetime.combine(target_date, datetime.max.time())

            # Conversations créées
            conv_result = await db.execute(
                select(func.count(Conversation.id)).where(
                    and_(
                        Conversation.created_at >= start,
                        Conversation.created_at <= end
                    )
                )
            )
            conversations_created = conv_result.scalar() or 0

            # Messages envoyés
            msg_result = await db.execute(
                select(func.count(Message.id)).where(
                    and_(
                        Message.created_at >= start,
                        Message.created_at <= end
                    )
                )
            )
            messages_sent = msg_result.scalar() or 0

            # Documents uploadés
            doc_result = await db.execute(
                select(func.count(Document.id)).where(
                    and_(
                        Document.created_at >= start,
                        Document.created_at <= end
                    )
                )
            )
            documents_uploaded = doc_result.scalar() or 0

            # Utilisateurs actifs (ont envoyé un message ou créé une conversation)
            active_users_result = await db.execute(
                select(func.count(func.distinct(Conversation.user_id))).where(
                    and_(
                        Conversation.created_at >= start,
                        Conversation.created_at <= end
                    )
                )
            )
            active_users = active_users_result.scalar() or 0

            result.append(UsageDaily(
                day=target_date,
                conversations_created=conversations_created,
                messages_sent=messages_sent,
                documents_uploaded=documents_uploaded,
                active_users=active_users
            ))

        # Trier par date croissante
        result.reverse()
        return result

    # ========================================================================
    # TENDANCES
    # ========================================================================

    @staticmethod
    async def get_trends(db: AsyncSession) -> TrendData:
        """
        Calcule les tendances de croissance.

        Compare les 7 derniers jours aux 7 jours précédents.

        Args:
            db: Session de base de données

        Returns:
            TrendData avec les pourcentages de croissance
        """
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        two_weeks_ago = now - timedelta(days=14)

        # Période actuelle (7 derniers jours)
        current_users = await db.execute(
            select(func.count(User.id)).where(User.created_at >= week_ago)
        )
        current_users_count = current_users.scalar() or 0

        current_conv = await db.execute(
            select(func.count(Conversation.id)).where(Conversation.created_at >= week_ago)
        )
        current_conv_count = current_conv.scalar() or 0

        current_docs = await db.execute(
            select(func.count(Document.id)).where(Document.created_at >= week_ago)
        )
        current_docs_count = current_docs.scalar() or 0

        # Période précédente (7 jours avant)
        prev_users = await db.execute(
            select(func.count(User.id)).where(
                and_(
                    User.created_at >= two_weeks_ago,
                    User.created_at < week_ago
                )
            )
        )
        prev_users_count = prev_users.scalar() or 0

        prev_conv = await db.execute(
            select(func.count(Conversation.id)).where(
                and_(
                    Conversation.created_at >= two_weeks_ago,
                    Conversation.created_at < week_ago
                )
            )
        )
        prev_conv_count = prev_conv.scalar() or 0

        prev_docs = await db.execute(
            select(func.count(Document.id)).where(
                and_(
                    Document.created_at >= two_weeks_ago,
                    Document.created_at < week_ago
                )
            )
        )
        prev_docs_count = prev_docs.scalar() or 0

        # Calculer les pourcentages de croissance
        def calc_growth(current: int, previous: int) -> float:
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round(((current - previous) / previous) * 100, 2)

        # Récupérer les données quotidiennes pour le graphique
        daily_data = await DashboardService.get_usage_daily(db, days=7)

        return TrendData(
            period="weekly",
            data=daily_data,
            growth_users_percent=calc_growth(current_users_count, prev_users_count),
            growth_conversations_percent=calc_growth(current_conv_count, prev_conv_count),
            growth_documents_percent=calc_growth(current_docs_count, prev_docs_count)
        )
