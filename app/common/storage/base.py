"""
Interface abstraite StorageBackend

Ce module définit l'interface que tous les backends de stockage doivent implémenter.
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, List
from uuid import UUID

from app.common.storage.schemas import FileInfo, StorageStats, UserStorageStats


class StorageBackend(ABC):
    """
    Interface abstraite pour les backends de stockage.

    Tous les backends (local, MinIO, S3) doivent implémenter cette interface
    pour garantir l'interchangeabilité.
    """

    # === CRUD Fichiers ===

    @abstractmethod
    async def save(
        self,
        user_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        version: int = 1,
    ) -> str:
        """
        Sauvegarde un fichier.

        Args:
            user_id: ID de l'utilisateur propriétaire
            document_id: ID du document
            filename: Nom du fichier original
            content: Contenu du fichier en bytes
            version: Numéro de version (1 par défaut)

        Returns:
            Chemin relatif du fichier sauvegardé
        """
        pass

    @abstractmethod
    async def get(self, file_path: str) -> bytes:
        """
        Récupère le contenu d'un fichier.

        Args:
            file_path: Chemin relatif du fichier

        Returns:
            Contenu du fichier en bytes

        Raises:
            StorageFileNotFoundError: Si le fichier n'existe pas
        """
        pass

    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        """
        Supprime un fichier.

        Args:
            file_path: Chemin relatif du fichier

        Returns:
            True si le fichier a été supprimé, False sinon
        """
        pass

    @abstractmethod
    async def delete_document_folder(self, user_id: UUID, document_id: UUID) -> bool:
        """
        Supprime le dossier complet d'un document (toutes versions).

        Args:
            user_id: ID de l'utilisateur
            document_id: ID du document

        Returns:
            True si le dossier a été supprimé
        """
        pass

    @abstractmethod
    async def exists(self, file_path: str) -> bool:
        """
        Vérifie si un fichier existe.

        Args:
            file_path: Chemin relatif du fichier

        Returns:
            True si le fichier existe
        """
        pass

    # === Métadonnées ===

    @abstractmethod
    async def get_file_info(self, file_path: str) -> FileInfo:
        """
        Retourne les métadonnées d'un fichier.

        Args:
            file_path: Chemin relatif du fichier

        Returns:
            FileInfo avec les métadonnées

        Raises:
            StorageFileNotFoundError: Si le fichier n'existe pas
        """
        pass

    @abstractmethod
    async def list_user_files(self, user_id: UUID) -> List[str]:
        """
        Liste les chemins de tous les fichiers d'un utilisateur.

        Args:
            user_id: ID de l'utilisateur

        Returns:
            Liste des chemins relatifs
        """
        pass

    @abstractmethod
    async def list_document_versions(
        self, user_id: UUID, document_id: UUID
    ) -> List[str]:
        """
        Liste les chemins de toutes les versions d'un document.

        Args:
            user_id: ID de l'utilisateur
            document_id: ID du document

        Returns:
            Liste des chemins relatifs des versions
        """
        pass

    # === Statistiques ===

    @abstractmethod
    async def get_storage_stats(self) -> StorageStats:
        """
        Retourne les statistiques globales du storage.

        Returns:
            StorageStats avec les statistiques
        """
        pass

    @abstractmethod
    async def get_user_stats(self, user_id: UUID) -> UserStorageStats:
        """
        Retourne les statistiques de stockage d'un utilisateur.

        Args:
            user_id: ID de l'utilisateur

        Returns:
            UserStorageStats avec les statistiques
        """
        pass

    # === Téléchargement ===

    @abstractmethod
    async def get_download_path(self, file_path: str) -> str:
        """
        Retourne le chemin absolu ou URL pour téléchargement.

        Args:
            file_path: Chemin relatif du fichier

        Returns:
            Chemin absolu (local) ou URL signée (S3/MinIO)
        """
        pass

    @abstractmethod
    async def stream_file(self, file_path: str, chunk_size: int = 8192) -> AsyncIterator[bytes]:
        """
        Stream le fichier par chunks (pour gros fichiers).

        Args:
            file_path: Chemin relatif du fichier
            chunk_size: Taille des chunks en bytes

        Yields:
            Chunks du fichier

        Raises:
            StorageFileNotFoundError: Si le fichier n'existe pas
        """
        pass
