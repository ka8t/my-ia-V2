"""
Service Admin Export

Logique métier pour l'export de données en CSV/JSON.
"""
import csv
import json
import logging
from io import StringIO
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import joinedload

from app.models import User, Conversation, Document, AuditLog, Message

logger = logging.getLogger(__name__)


class ExportService:
    """Service pour l'export de données"""

    # ========================================================================
    # EXPORT UTILISATEURS
    # ========================================================================

    @staticmethod
    async def export_users(
        db: AsyncSession,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Exporte les utilisateurs.

        Args:
            db: Session de base de données
            created_after: Filtrer par date de création (après)
            created_before: Filtrer par date de création (avant)
            limit: Nombre max d'enregistrements

        Returns:
            Liste de dictionnaires représentant les utilisateurs
        """
        query = select(User).options(joinedload(User.role))

        conditions = []
        if created_after:
            conditions.append(User.created_at >= created_after)
        if created_before:
            conditions.append(User.created_at <= created_before)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(User.created_at.desc()).limit(limit)

        result = await db.execute(query)
        users = result.scalars().unique().all()

        return [
            {
                "id": str(user.id),
                "email": user.email,
                "username": user.username,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "role": user.role.name if user.role else "",
                "is_active": user.is_active,
                "is_verified": user.is_verified,
                "created_at": user.created_at.isoformat() if user.created_at else "",
                "last_login": user.last_login.isoformat() if user.last_login else ""
            }
            for user in users
        ]

    # ========================================================================
    # EXPORT CONVERSATIONS
    # ========================================================================

    @staticmethod
    async def export_conversations(
        db: AsyncSession,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Exporte les conversations.

        Args:
            db: Session de base de données
            created_after: Filtrer par date de création (après)
            created_before: Filtrer par date de création (avant)
            limit: Nombre max d'enregistrements

        Returns:
            Liste de dictionnaires représentant les conversations
        """
        query = select(Conversation).options(
            joinedload(Conversation.user),
            joinedload(Conversation.mode)
        )

        conditions = []
        if created_after:
            conditions.append(Conversation.created_at >= created_after)
        if created_before:
            conditions.append(Conversation.created_at <= created_before)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(Conversation.created_at.desc()).limit(limit)

        result = await db.execute(query)
        conversations = result.scalars().unique().all()

        return [
            {
                "id": str(conv.id),
                "user_id": str(conv.user_id),
                "user_email": conv.user.email if conv.user else "",
                "title": conv.title,
                "mode": conv.mode.name if conv.mode else "",
                "created_at": conv.created_at.isoformat() if conv.created_at else "",
                "updated_at": conv.updated_at.isoformat() if conv.updated_at else ""
            }
            for conv in conversations
        ]

    # ========================================================================
    # EXPORT DOCUMENTS
    # ========================================================================

    @staticmethod
    async def export_documents(
        db: AsyncSession,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Exporte les métadonnées des documents.

        Args:
            db: Session de base de données
            created_after: Filtrer par date de création (après)
            created_before: Filtrer par date de création (avant)
            limit: Nombre max d'enregistrements

        Returns:
            Liste de dictionnaires représentant les documents
        """
        query = select(Document).options(joinedload(Document.user))

        conditions = []
        if created_after:
            conditions.append(Document.created_at >= created_after)
        if created_before:
            conditions.append(Document.created_at <= created_before)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(Document.created_at.desc()).limit(limit)

        result = await db.execute(query)
        documents = result.scalars().unique().all()

        return [
            {
                "id": str(doc.id),
                "user_id": str(doc.user_id),
                "user_email": doc.user.email if doc.user else "",
                "filename": doc.filename,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "chunk_count": doc.chunk_count,
                "created_at": doc.created_at.isoformat() if doc.created_at else ""
            }
            for doc in documents
        ]

    # ========================================================================
    # EXPORT AUDIT LOGS
    # ========================================================================

    @staticmethod
    async def export_audit_logs(
        db: AsyncSession,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Exporte les logs d'audit.

        Args:
            db: Session de base de données
            created_after: Filtrer par date de création (après)
            created_before: Filtrer par date de création (avant)
            limit: Nombre max d'enregistrements

        Returns:
            Liste de dictionnaires représentant les logs d'audit
        """
        query = select(AuditLog).options(
            joinedload(AuditLog.user),
            joinedload(AuditLog.action),
            joinedload(AuditLog.resource_type)
        )

        conditions = []
        if created_after:
            conditions.append(AuditLog.created_at >= created_after)
        if created_before:
            conditions.append(AuditLog.created_at <= created_before)

        if conditions:
            query = query.where(and_(*conditions))

        query = query.order_by(AuditLog.created_at.desc()).limit(limit)

        result = await db.execute(query)
        logs = result.scalars().unique().all()

        return [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else "",
                "user_email": log.user.email if log.user else "",
                "action": log.action.name if log.action else "",
                "action_severity": log.action.severity if log.action else "",
                "resource_type": log.resource_type.name if log.resource_type else "",
                "resource_id": str(log.resource_id) if log.resource_id else "",
                "details": json.dumps(log.details) if log.details else "",
                "ip_address": log.ip_address or "",
                "user_agent": log.user_agent or "",
                "created_at": log.created_at.isoformat() if log.created_at else ""
            }
            for log in logs
        ]

    # ========================================================================
    # CONVERSION FORMATS
    # ========================================================================

    @staticmethod
    def to_csv(data: List[Dict[str, Any]]) -> str:
        """
        Convertit une liste de dictionnaires en CSV.

        Args:
            data: Liste de dictionnaires

        Returns:
            Contenu CSV en string
        """
        if not data:
            return ""

        output = StringIO()
        fieldnames = list(data[0].keys())
        writer = csv.DictWriter(output, fieldnames=fieldnames)

        writer.writeheader()
        writer.writerows(data)

        return output.getvalue()

    @staticmethod
    def to_json(data: List[Dict[str, Any]]) -> str:
        """
        Convertit une liste de dictionnaires en JSON.

        Args:
            data: Liste de dictionnaires

        Returns:
            Contenu JSON en string
        """
        return json.dumps(data, indent=2, ensure_ascii=False)
