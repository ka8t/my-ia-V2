"""
StorageService

Service de haut niveau pour la gestion du stockage avec quotas et validations.
"""

import logging
from pathlib import Path
from typing import AsyncIterator, List, Optional
from uuid import UUID

from app.common.storage.base import StorageBackend
from app.common.storage.exceptions import (
    FileTooLargeError,
    InvalidFileTypeError,
    QuotaExceededError,
)
from app.common.storage.schemas import (
    FileInfo,
    QuotaConfig,
    StorageStats,
    UserStorageStats,
)

logger = logging.getLogger(__name__)


class StorageService:
    """
    Service de haut niveau pour la gestion du stockage.

    Ce service encapsule le backend de stockage et ajoute:
    - Validation des quotas utilisateur
    - Validation des types de fichiers
    - Validation de la taille des fichiers
    - Statistiques avec calcul des quotas
    """

    def __init__(self, backend: StorageBackend, quota_config: QuotaConfig):
        """
        Initialise le service de stockage.

        Args:
            backend: Backend de stockage (local, MinIO, S3)
            quota_config: Configuration des quotas
        """
        self.backend = backend
        self.config = quota_config

    def update_config(self, quota_config: QuotaConfig) -> None:
        """
        Met a jour la configuration des quotas.

        Permet de rafraichir la configuration depuis la base de donnees.

        Args:
            quota_config: Nouvelle configuration des quotas
        """
        self.config = quota_config
        logger.debug(
            f"QuotaConfig updated: mime_types={len(quota_config.allowed_mime_types)}, "
            f"max_size={quota_config.max_file_size_mb}MB"
        )

    # === Validation ===

    def _validate_file_size(self, content: bytes) -> None:
        """Valide la taille du fichier."""
        if len(content) > self.config.max_file_size_bytes:
            raise FileTooLargeError(len(content), self.config.max_file_size_bytes)

    def _validate_mime_type(self, mime_type: str) -> None:
        """Valide le type MIME du fichier."""
        if self.config.allowed_mime_types:
            if mime_type not in self.config.allowed_mime_types:
                raise InvalidFileTypeError(mime_type, self.config.allowed_mime_types)

    def _validate_extension(self, filename: str) -> None:
        """Valide l'extension du fichier."""
        if self.config.blocked_extensions:
            ext = Path(filename).suffix.lower()
            if ext in self.config.blocked_extensions:
                raise InvalidFileTypeError(ext, reason="extension bloquée")

    async def _validate_quota(
        self, user_id: UUID, file_size: int, user_quota: Optional[int] = None
    ) -> None:
        """Valide le quota utilisateur."""
        quota = user_quota or self.config.default_quota_bytes

        if quota <= 0:
            # Quota illimité
            return

        user_stats = await self.backend.get_user_stats(user_id)
        new_total = user_stats.used_bytes + file_size

        if new_total > quota:
            raise QuotaExceededError(user_id, quota, new_total)

    # === Upload ===

    async def upload(
        self,
        user_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        mime_type: str,
        version: int = 1,
        check_quota: bool = True,
        user_quota: Optional[int] = None,
    ) -> str:
        """
        Upload un fichier avec toutes les validations.

        Args:
            user_id: ID de l'utilisateur
            document_id: ID du document
            filename: Nom du fichier original
            content: Contenu du fichier
            mime_type: Type MIME du fichier
            version: Numéro de version
            check_quota: Vérifier le quota utilisateur
            user_quota: Quota personnalisé (None = quota par défaut)

        Returns:
            Chemin relatif du fichier sauvegardé

        Raises:
            FileTooLargeError: Fichier trop volumineux
            InvalidFileTypeError: Type de fichier non autorisé
            QuotaExceededError: Quota dépassé
        """
        # Validations
        self._validate_file_size(content)
        self._validate_mime_type(mime_type)
        self._validate_extension(filename)

        if check_quota:
            await self._validate_quota(user_id, len(content), user_quota)

        # Sauvegarder
        file_path = await self.backend.save(
            user_id=user_id,
            document_id=document_id,
            filename=filename,
            content=content,
            version=version,
        )

        logger.info(
            f"Upload réussi: user={user_id}, doc={document_id}, "
            f"version={version}, size={len(content)}"
        )

        return file_path

    # === Download ===

    async def download(self, file_path: str) -> bytes:
        """Télécharge un fichier."""
        return await self.backend.get(file_path)

    async def get_download_path(self, file_path: str) -> str:
        """Retourne le chemin/URL de téléchargement."""
        return await self.backend.get_download_path(file_path)

    async def stream_file(
        self, file_path: str, chunk_size: int = 8192
    ) -> AsyncIterator[bytes]:
        """Stream un fichier par chunks."""
        async for chunk in self.backend.stream_file(file_path, chunk_size):
            yield chunk

    # === Suppression ===

    async def delete(self, file_path: str) -> bool:
        """Supprime un fichier."""
        return await self.backend.delete(file_path)

    async def delete_document(self, user_id: UUID, document_id: UUID) -> bool:
        """Supprime un document et toutes ses versions."""
        return await self.backend.delete_document_folder(user_id, document_id)

    # === Métadonnées ===

    async def get_file_info(self, file_path: str) -> FileInfo:
        """Retourne les métadonnées d'un fichier."""
        return await self.backend.get_file_info(file_path)

    async def exists(self, file_path: str) -> bool:
        """Vérifie si un fichier existe."""
        return await self.backend.exists(file_path)

    async def file_exists(self, file_path: str) -> bool:
        """Alias pour exists() - vérifie si un fichier existe."""
        return await self.exists(file_path)

    async def list_document_versions(
        self, user_id: UUID, document_id: UUID
    ) -> List[str]:
        """Liste les versions d'un document."""
        return await self.backend.list_document_versions(user_id, document_id)

    # === Statistiques ===

    async def get_global_stats(self) -> StorageStats:
        """Retourne les statistiques globales du storage."""
        return await self.backend.get_storage_stats()

    async def get_user_stats(
        self, user_id: UUID, user_quota: Optional[int] = None
    ) -> UserStorageStats:
        """
        Retourne les statistiques d'un utilisateur avec quota.

        Args:
            user_id: ID de l'utilisateur
            user_quota: Quota personnalisé (None = quota par défaut)

        Returns:
            UserStorageStats avec quota_used_percent calculé
        """
        stats = await self.backend.get_user_stats(user_id)

        # Appliquer le quota
        quota = user_quota or self.config.default_quota_bytes
        stats.quota_bytes = quota if quota > 0 else None

        # Calculer le pourcentage
        if stats.quota_bytes and stats.quota_bytes > 0:
            stats.quota_used_percent = (stats.used_bytes / stats.quota_bytes) * 100
        else:
            stats.quota_used_percent = 0.0

        return stats

    # === Vérifications Quota ===

    async def check_can_upload(
        self, user_id: UUID, file_size: int, user_quota: Optional[int] = None
    ) -> bool:
        """
        Vérifie si l'utilisateur peut uploader un fichier.

        Args:
            user_id: ID de l'utilisateur
            file_size: Taille du fichier en bytes
            user_quota: Quota personnalisé (None = quota par défaut)

        Returns:
            True si l'upload est possible
        """
        try:
            await self._validate_quota(user_id, file_size, user_quota)
            return True
        except QuotaExceededError:
            return False

    async def get_remaining_quota(
        self, user_id: UUID, user_quota: Optional[int] = None
    ) -> Optional[int]:
        """
        Retourne l'espace restant pour un utilisateur.

        Args:
            user_id: ID de l'utilisateur
            user_quota: Quota personnalisé (None = quota par défaut)

        Returns:
            Espace restant en bytes (None si quota illimité)
        """
        quota = user_quota or self.config.default_quota_bytes

        if quota <= 0:
            return None  # Illimité

        user_stats = await self.backend.get_user_stats(user_id)
        return max(0, quota - user_stats.used_bytes)

    # === Validation Fichier ===

    def validate_file(self, filename: str, content: bytes, mime_type: str) -> None:
        """
        Valide un fichier avant upload (sans vérifier le quota).

        Utile pour valider côté frontend avant l'upload effectif.

        Args:
            filename: Nom du fichier
            content: Contenu du fichier
            mime_type: Type MIME

        Raises:
            FileTooLargeError: Fichier trop volumineux
            InvalidFileTypeError: Type de fichier non autorisé
        """
        self._validate_file_size(content)
        self._validate_mime_type(mime_type)
        self._validate_extension(filename)
