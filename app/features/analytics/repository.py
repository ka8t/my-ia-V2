"""
Repository Analytics

Requetes base de donnees pour les statistiques.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, distinct, desc, literal_column

from app.models import (
    User, Conversation, Message, Document,
    AuditLog, AuditAction
)

logger = logging.getLogger(__name__)


class AnalyticsRepository:
    """Repository pour les requetes analytics."""

    # ========================================================================
    # Statistiques globales
    # ========================================================================

    @staticmethod
    async def get_global_stats(db: AsyncSession) -> Dict[str, Any]:
        """Recupere les statistiques globales."""
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        # Total users
        total_users = (await db.execute(
            select(func.count(User.id)).where(User.is_active == True)
        )).scalar() or 0

        # Active users (basé sur last_login)
        active_today = (await db.execute(
            select(func.count(User.id)).where(
                and_(User.is_active == True, User.last_login >= today_start)
            )
        )).scalar() or 0

        active_week = (await db.execute(
            select(func.count(User.id)).where(
                and_(User.is_active == True, User.last_login >= week_start)
            )
        )).scalar() or 0

        active_month = (await db.execute(
            select(func.count(User.id)).where(
                and_(User.is_active == True, User.last_login >= month_start)
            )
        )).scalar() or 0

        # Conversations
        total_conversations = (await db.execute(
            select(func.count(Conversation.id))
        )).scalar() or 0

        # Messages
        total_messages = (await db.execute(
            select(func.count(Message.id))
        )).scalar() or 0

        # Documents
        total_documents = (await db.execute(
            select(func.count(Document.id))
        )).scalar() or 0

        # Storage (somme file_size)
        storage_used = (await db.execute(
            select(func.coalesce(func.sum(Document.file_size), 0))
        )).scalar() or 0

        return {
            "total_users": total_users,
            "active_users_today": active_today,
            "active_users_week": active_week,
            "active_users_month": active_month,
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "total_documents": total_documents,
            "storage_used_bytes": storage_used
        }

    @staticmethod
    async def get_usage_today(db: AsyncSession) -> Dict[str, int]:
        """Recupere l'usage du jour."""
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # Messages aujourd'hui
        messages_today = (await db.execute(
            select(func.count(Message.id)).where(Message.created_at >= today_start)
        )).scalar() or 0

        # Conversations aujourd'hui
        conversations_today = (await db.execute(
            select(func.count(Conversation.id)).where(Conversation.created_at >= today_start)
        )).scalar() or 0

        # Documents aujourd'hui
        documents_today = (await db.execute(
            select(func.count(Document.id)).where(Document.created_at >= today_start)
        )).scalar() or 0

        # Nouveaux users aujourd'hui
        new_users_today = (await db.execute(
            select(func.count(User.id)).where(User.created_at >= today_start)
        )).scalar() or 0

        return {
            "messages": messages_today,
            "conversations": conversations_today,
            "documents": documents_today,
            "new_users": new_users_today
        }

    @staticmethod
    async def get_trends(db: AsyncSession, days: int = 7) -> Dict[str, float]:
        """
        Calcule les tendances (% changement vs periode precedente).
        """
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=days)
        previous_start = period_start - timedelta(days=days)

        async def get_count(model, date_field, start, end):
            return (await db.execute(
                select(func.count(model.id)).where(
                    and_(date_field >= start, date_field < end)
                )
            )).scalar() or 0

        def calc_trend(current, previous):
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round(((current - previous) / previous) * 100, 1)

        # Messages
        messages_current = await get_count(Message, Message.created_at, period_start, now)
        messages_previous = await get_count(Message, Message.created_at, previous_start, period_start)

        # Conversations
        conv_current = await get_count(Conversation, Conversation.created_at, period_start, now)
        conv_previous = await get_count(Conversation, Conversation.created_at, previous_start, period_start)

        # Users
        users_current = await get_count(User, User.created_at, period_start, now)
        users_previous = await get_count(User, User.created_at, previous_start, period_start)

        return {
            "messages": calc_trend(messages_current, messages_previous),
            "conversations": calc_trend(conv_current, conv_previous),
            "new_users": calc_trend(users_current, users_previous)
        }

    # ========================================================================
    # Usage au fil du temps
    # ========================================================================

    @staticmethod
    async def get_usage_over_time(
        db: AsyncSession,
        days: int = 30
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Recupere l'usage par jour sur les X derniers jours."""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        # Helper pour creer les colonnes date_trunc
        def day_trunc(date_col):
            return func.date_trunc('day', date_col)

        # Messages par jour
        msg_day = day_trunc(Message.created_at).label('day')
        messages_query = (
            select(msg_day, func.count(Message.id).label('count'))
            .where(Message.created_at >= start_date)
            .group_by(literal_column('day'))
            .order_by(literal_column('day'))
        )

        messages_result = await db.execute(messages_query)
        messages = [
            {"date": row.day.strftime("%Y-%m-%d"), "value": row.count}
            for row in messages_result
        ]

        # Conversations par jour
        conv_day = day_trunc(Conversation.created_at).label('day')
        conv_query = (
            select(conv_day, func.count(Conversation.id).label('count'))
            .where(Conversation.created_at >= start_date)
            .group_by(literal_column('day'))
            .order_by(literal_column('day'))
        )

        conv_result = await db.execute(conv_query)
        conversations = [
            {"date": row.day.strftime("%Y-%m-%d"), "value": row.count}
            for row in conv_result
        ]

        # Nouveaux users par jour
        user_day = day_trunc(User.created_at).label('day')
        users_query = (
            select(user_day, func.count(User.id).label('count'))
            .where(User.created_at >= start_date)
            .group_by(literal_column('day'))
            .order_by(literal_column('day'))
        )

        users_result = await db.execute(users_query)
        new_users = [
            {"date": row.day.strftime("%Y-%m-%d"), "value": row.count}
            for row in users_result
        ]

        # Users actifs par jour (basé sur audit logs de login)
        audit_day = day_trunc(AuditLog.created_at).label('day')
        active_query = (
            select(audit_day, func.count(distinct(AuditLog.user_id)).label('count'))
            .join(AuditAction, AuditLog.action_id == AuditAction.id)
            .where(
                and_(
                    AuditLog.created_at >= start_date,
                    AuditAction.name == 'login'
                )
            )
            .group_by(literal_column('day'))
            .order_by(literal_column('day'))
        )

        active_result = await db.execute(active_query)
        active_users = [
            {"date": row.day.strftime("%Y-%m-%d"), "value": row.count}
            for row in active_result
        ]

        return {
            "messages": messages,
            "conversations": conversations,
            "new_users": new_users,
            "active_users": active_users
        }

    # ========================================================================
    # Top N
    # ========================================================================

    @staticmethod
    async def get_top_users(
        db: AsyncSession,
        limit: int = 10,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Recupere les utilisateurs les plus actifs."""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        query = (
            select(
                User.id,
                User.username,
                User.email,
                func.count(distinct(Message.id)).label('messages_count'),
                func.count(distinct(Conversation.id)).label('conversations_count')
            )
            .outerjoin(Conversation, and_(
                Conversation.user_id == User.id,
                Conversation.created_at >= start_date
            ))
            .outerjoin(Message, and_(
                Message.conversation_id == Conversation.id,
                Message.created_at >= start_date,
                Message.sender_type == 'user'
            ))
            .where(User.is_active == True)
            .group_by(User.id, User.username, User.email)
            .order_by(desc(func.count(distinct(Message.id))))
            .limit(limit)
        )

        result = await db.execute(query)
        return [
            {
                "user_id": str(row.id),
                "username": row.username,
                "email": row.email,
                "activity_score": (row.messages_count or 0) + (row.conversations_count or 0)
            }
            for row in result
        ]

    @staticmethod
    async def get_top_queries(
        db: AsyncSession,
        limit: int = 10,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Recupere les questions les plus frequentes.
        Basé sur les messages utilisateur.
        """
        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        query = (
            select(
                Message.content,
                func.count(Message.id).label('count'),
                func.max(Message.created_at).label('last_asked')
            )
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                and_(
                    Message.sender_type == 'user',
                    Message.created_at >= start_date,
                    func.length(Message.content) > 10,  # Ignorer les messages trop courts
                    func.length(Message.content) < 500  # Ignorer les messages trop longs
                )
            )
            .group_by(Message.content)
            .order_by(desc(func.count(Message.id)))
            .limit(limit)
        )

        result = await db.execute(query)
        return [
            {
                "query": row.content[:200],  # Tronquer
                "count": row.count,
                "last_asked": row.last_asked.isoformat() if row.last_asked else None
            }
            for row in result
        ]
