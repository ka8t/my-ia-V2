"""
Repository Audit

Opérations de base de données pour l'audit.
"""
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case
from sqlalchemy.orm import selectinload, joinedload

from app.common.utils.query import paginate_query
from app.models import AuditLog, AuditAction, ResourceType, User

logger = logging.getLogger(__name__)


class AuditRepository:
    """Repository pour les opérations d'audit en base de données"""

    # ========================================================================
    # Lookups
    # ========================================================================

    @staticmethod
    async def get_action_by_name(db: AsyncSession, action_name: str) -> Optional[AuditAction]:
        """Récupère une action d'audit par son nom."""
        result = await db.execute(
            select(AuditAction).where(AuditAction.name == action_name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_resource_type_by_name(
        db: AsyncSession,
        resource_type_name: str
    ) -> Optional[ResourceType]:
        """Récupère un type de ressource par son nom."""
        result = await db.execute(
            select(ResourceType).where(ResourceType.name == resource_type_name)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all_actions(db: AsyncSession) -> List[AuditAction]:
        """Liste toutes les actions d'audit."""
        result = await db.execute(
            select(AuditAction).order_by(AuditAction.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def get_all_resource_types(db: AsyncSession) -> List[ResourceType]:
        """Liste tous les types de ressources."""
        result = await db.execute(
            select(ResourceType).order_by(ResourceType.name)
        )
        return list(result.scalars().all())

    # ========================================================================
    # Create
    # ========================================================================

    @staticmethod
    async def create_audit_log(
        db: AsyncSession,
        user_id: Optional[uuid.UUID],
        action_id: int,
        resource_type_id: Optional[int],
        resource_id: Optional[uuid.UUID],
        details: Optional[dict],
        ip_address: Optional[str],
        user_agent: Optional[str]
    ) -> Optional[AuditLog]:
        """Crée un log d'audit."""
        try:
            audit_log = AuditLog(
                user_id=user_id,
                action_id=action_id,
                resource_type_id=resource_type_id,
                resource_id=resource_id,
                details=details,
                ip_address=ip_address[:45] if ip_address else None,
                user_agent=user_agent[:500] if user_agent else None
            )

            db.add(audit_log)
            await db.commit()
            await db.refresh(audit_log)

            return audit_log

        except Exception as e:
            logger.error(f"Error creating audit log: {e}", exc_info=True)
            await db.rollback()
            return None

    # ========================================================================
    # List with filters and pagination
    # ========================================================================

    @staticmethod
    async def get_logs(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        user_id: Optional[uuid.UUID] = None,
        username: Optional[str] = None,
        action_name: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[uuid.UUID] = None,
        severity: Optional[str] = None,
        ip_address: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None
    ) -> Tuple[List[AuditLog], int]:
        """
        Liste les logs d'audit avec filtres et pagination.

        Returns:
            Tuple (liste des logs, total)
        """
        # Base query avec jointures
        query = (
            select(AuditLog)
            .options(
                joinedload(AuditLog.user).joinedload(User.role),
                joinedload(AuditLog.action),
                joinedload(AuditLog.resource_type)
            )
        )

        # Appliquer les filtres
        conditions = []
        user_joined = False

        if user_id:
            conditions.append(AuditLog.user_id == user_id)

        if username:
            # Recherche partielle sur le username (insensible à la casse)
            if not user_joined:
                query = query.join(User, AuditLog.user_id == User.id)
                user_joined = True
            conditions.append(User.username.ilike(f"%{username}%"))

        if action_name:
            # Joindre AuditAction si pas déjà fait
            conditions.append(AuditAction.name == action_name)
            query = query.join(AuditAction, AuditLog.action_id == AuditAction.id)

        if resource_type:
            conditions.append(ResourceType.name == resource_type)
            query = query.join(ResourceType, AuditLog.resource_type_id == ResourceType.id)

        if resource_id:
            conditions.append(AuditLog.resource_id == resource_id)

        if severity:
            # Joindre AuditAction pour filtrer par severity
            if action_name is None:  # Si pas déjà joint
                query = query.join(AuditAction, AuditLog.action_id == AuditAction.id)
            conditions.append(AuditAction.severity == severity)

        if ip_address:
            conditions.append(AuditLog.ip_address.ilike(f"%{ip_address}%"))

        if date_from:
            conditions.append(AuditLog.created_at >= date_from)

        if date_to:
            conditions.append(AuditLog.created_at <= date_to)

        if conditions:
            query = query.where(and_(*conditions))

        # Pagination
        query = query.order_by(AuditLog.created_at.desc())
        logs, pagination = await paginate_query(
            db, query, limit=limit, offset=skip, unique=True
        )

        return logs, pagination.total

    @staticmethod
    async def get_log_by_id(db: AsyncSession, log_id: uuid.UUID) -> Optional[AuditLog]:
        """Récupère un log par son ID."""
        result = await db.execute(
            select(AuditLog)
            .options(
                joinedload(AuditLog.user).joinedload(User.role),
                joinedload(AuditLog.action),
                joinedload(AuditLog.resource_type)
            )
            .where(AuditLog.id == log_id)
        )
        return result.unique().scalar_one_or_none()

    # ========================================================================
    # Statistics
    # ========================================================================

    @staticmethod
    async def get_stats(
        db: AsyncSession,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Calcule les statistiques d'audit.

        Args:
            db: Session DB
            days: Nombre de jours pour l'historique

        Returns:
            Dictionnaire de statistiques
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())
        month_start = today_start.replace(day=1)
        period_start = today_start - timedelta(days=days)

        # Total logs
        total_query = select(func.count(AuditLog.id))
        total_logs = (await db.execute(total_query)).scalar() or 0

        # Logs aujourd'hui
        today_query = select(func.count(AuditLog.id)).where(AuditLog.created_at >= today_start)
        logs_today = (await db.execute(today_query)).scalar() or 0

        # Logs cette semaine
        week_query = select(func.count(AuditLog.id)).where(AuditLog.created_at >= week_start)
        logs_this_week = (await db.execute(week_query)).scalar() or 0

        # Logs ce mois
        month_query = select(func.count(AuditLog.id)).where(AuditLog.created_at >= month_start)
        logs_this_month = (await db.execute(month_query)).scalar() or 0

        # Par action
        by_action_query = (
            select(
                AuditAction.name,
                AuditAction.display_name,
                AuditAction.severity,
                func.count(AuditLog.id).label("count")
            )
            .join(AuditAction, AuditLog.action_id == AuditAction.id)
            .where(AuditLog.created_at >= period_start)
            .group_by(AuditAction.name, AuditAction.display_name, AuditAction.severity)
            .order_by(func.count(AuditLog.id).desc())
        )

        by_action_result = await db.execute(by_action_query)
        by_action = [
            {
                "action_name": row.name,
                "action_display_name": row.display_name,
                "severity": row.severity,
                "count": row.count
            }
            for row in by_action_result
        ]

        # Par sévérité
        by_severity_query = (
            select(
                AuditAction.severity,
                func.count(AuditLog.id).label("count")
            )
            .join(AuditAction, AuditLog.action_id == AuditAction.id)
            .where(AuditLog.created_at >= period_start)
            .group_by(AuditAction.severity)
        )

        by_severity_result = await db.execute(by_severity_query)
        by_severity = {row.severity: row.count for row in by_severity_result}

        # Par jour (30 derniers jours)
        by_day_query = (
            select(
                func.date_trunc('day', AuditLog.created_at).label("day"),
                func.count(AuditLog.id).label("count")
            )
            .where(AuditLog.created_at >= period_start)
            .group_by(func.date_trunc('day', AuditLog.created_at))
            .order_by(func.date_trunc('day', AuditLog.created_at))
        )

        by_day_result = await db.execute(by_day_query)
        by_day = [
            {
                "date": row.day.strftime("%Y-%m-%d") if row.day else "",
                "count": row.count
            }
            for row in by_day_result
        ]

        # Top utilisateurs
        top_users_query = (
            select(
                User.id,
                User.username,
                User.email,
                func.count(AuditLog.id).label("action_count")
            )
            .join(User, AuditLog.user_id == User.id)
            .where(AuditLog.created_at >= period_start)
            .group_by(User.id, User.username, User.email)
            .order_by(func.count(AuditLog.id).desc())
            .limit(10)
        )

        top_users_result = await db.execute(top_users_query)
        top_users = [
            {
                "user_id": str(row.id),
                "username": row.username,
                "email": row.email,
                "action_count": row.action_count
            }
            for row in top_users_result
        ]

        return {
            "total_logs": total_logs,
            "logs_today": logs_today,
            "logs_this_week": logs_this_week,
            "logs_this_month": logs_this_month,
            "by_action": by_action,
            "by_severity": by_severity,
            "by_day": by_day,
            "top_users": top_users
        }

    # ========================================================================
    # Export
    # ========================================================================

    @staticmethod
    async def get_logs_for_export(
        db: AsyncSession,
        max_rows: int = 10000,
        **filters
    ) -> List[Dict[str, Any]]:
        """
        Récupère les logs pour export (sans pagination, avec limite).

        Returns:
            Liste de dictionnaires pour export CSV/JSON
        """
        logs, _ = await AuditRepository.get_logs(
            db,
            skip=0,
            limit=max_rows,
            **filters
        )

        export_data = []
        for log in logs:
            export_data.append({
                "id": str(log.id),
                "timestamp": log.created_at.isoformat() if log.created_at else "",
                "user_id": str(log.user_id) if log.user_id else "",
                "username": log.user.username if log.user else "",
                "email": log.user.email if log.user else "",
                "user_role": log.user.role.name if log.user and log.user.role else "",
                "action": log.action.name if log.action else "",
                "action_display": log.action.display_name if log.action else "",
                "severity": log.action.severity if log.action else "",
                "resource_type": log.resource_type.name if log.resource_type else "",
                "resource_id": str(log.resource_id) if log.resource_id else "",
                "ip_address": log.ip_address or "",
                "user_agent": log.user_agent or "",
                "details": log.details or {}
            })

        return export_data

    # ========================================================================
    # Cleanup
    # ========================================================================

    @staticmethod
    async def delete_old_logs(db: AsyncSession, days: int = 365) -> int:
        """
        Supprime les logs plus anciens que X jours.

        Args:
            db: Session DB
            days: Nombre de jours à conserver (0 = tout supprimer)

        Returns:
            Nombre de logs supprimés
        """
        from sqlalchemy import delete

        if days == 0:
            # Tout supprimer
            result = await db.execute(delete(AuditLog))
            await db.commit()
            deleted_count = result.rowcount
            logger.info(f"Deleted ALL {deleted_count} audit logs")
        else:
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            result = await db.execute(
                delete(AuditLog).where(AuditLog.created_at < cutoff_date)
            )
            await db.commit()
            deleted_count = result.rowcount
            logger.info(f"Deleted {deleted_count} audit logs older than {days} days")

        return deleted_count
