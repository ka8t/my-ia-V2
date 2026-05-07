"""
LocalStorageBackend

Implémentation du StorageBackend pour le système de fichiers local.
Structure:
    /data/uploads/
    ├── {user_id}/
    │   ├── {document_id}/
    │   │   ├── v1_{filename}
    │   │   ├── v2_{filename}
    │   │   └── ...
"""

import asyncio
import logging
import mimetypes
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, List
from uuid import UUID

from app.common.storage.base import StorageBackend
from app.common.storage.exceptions import (
    StorageFileNotFoundError,
    StorageIOError,
    StoragePermissionError,
)
from app.common.storage.schemas import FileInfo, StorageStats, UserStorageStats

logger = logging.getLogger(__name__)


class LocalStorageBackend(StorageBackend):
    """
    Backend de stockage utilisant le système de fichiers local.

    Structure des fichiers:
        base_path/
        ├── {user_id}/
        │   ├── {document_id}/
        │   │   ├── v1_{filename}
        │   │   ├── v2_{filename}
        │   │   └── ...
    """

    def __init__(self, base_path: str = "/data/uploads"):
        """
        Initialise le backend local.

        Args:
            base_path: Chemin racine du stockage
        """
        self.base_path = Path(base_path)
        self._ensure_base_path()

    def _ensure_base_path(self) -> None:
        """Crée le répertoire de base s'il n'existe pas."""
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            logger.error(f"Permission refusée pour créer {self.base_path}: {e}")
            raise StoragePermissionError(str(self.base_path), "create")

    def _get_user_path(self, user_id: UUID) -> Path:
        """Retourne le chemin du dossier utilisateur."""
        return self.base_path / str(user_id)

    def _get_document_path(self, user_id: UUID, document_id: UUID) -> Path:
        """Retourne le chemin du dossier document."""
        return self._get_user_path(user_id) / str(document_id)

    def _get_version_filename(self, filename: str, version: int) -> str:
        """Génère le nom de fichier versionné."""
        return f"v{version}_{filename}"

    def _sanitize_filename(self, filename: str) -> str:
        """Nettoie le nom de fichier pour éviter les problèmes."""
        # Remplacer les traversées de répertoire
        sanitized = filename.replace("..", "_")
        # Remplacer les caractères problématiques
        sanitized = sanitized.replace("/", "_").replace("\\", "_")
        sanitized = sanitized.replace("\x00", "")
        # Limiter la longueur
        if len(sanitized) > 200:
            name, ext = os.path.splitext(sanitized)
            sanitized = name[:200 - len(ext)] + ext
        return sanitized

    async def save(
        self,
        user_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        version: int = 1,
    ) -> str:
        """Sauvegarde un fichier."""
        # Préparer les chemins en dehors du try pour qu'ils soient définis
        # dans les except handlers (sinon UnboundLocalError si mkdir échoue).
        doc_path = self._get_document_path(user_id, document_id)
        safe_filename = self._sanitize_filename(filename)
        version_filename = self._get_version_filename(safe_filename, version)
        file_path = doc_path / version_filename

        try:
            # Créer le dossier du document
            doc_path.mkdir(parents=True, exist_ok=True)

            # Écrire le fichier de manière asynchrone
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, file_path.write_bytes, content)

            # Retourner le chemin relatif
            relative_path = str(file_path.relative_to(self.base_path))
            logger.info(
                f"Fichier sauvegardé: {relative_path} ({len(content)} bytes)"
            )
            return relative_path

        except PermissionError as e:
            logger.error(f"Permission refusée pour sauvegarder {file_path}: {e}")
            raise StoragePermissionError(str(file_path), "write")
        except OSError as e:
            logger.error(f"Erreur I/O lors de la sauvegarde {file_path}: {e}")
            raise StorageIOError(str(file_path), "write", str(e))

    async def get(self, file_path: str) -> bytes:
        """Récupère le contenu d'un fichier."""
        full_path = self.base_path / file_path

        if not full_path.exists():
            raise StorageFileNotFoundError(file_path)

        try:
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(None, full_path.read_bytes)
            return content
        except PermissionError:
            raise StoragePermissionError(file_path, "read")
        except OSError as e:
            raise StorageIOError(file_path, "read", str(e))

    async def delete(self, file_path: str) -> bool:
        """Supprime un fichier."""
        full_path = self.base_path / file_path

        if not full_path.exists():
            logger.warning(f"Fichier à supprimer non trouvé: {file_path}")
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, full_path.unlink)
            logger.info(f"Fichier supprimé: {file_path}")
            return True
        except PermissionError:
            raise StoragePermissionError(file_path, "delete")
        except OSError as e:
            raise StorageIOError(file_path, "delete", str(e))

    async def delete_document_folder(self, user_id: UUID, document_id: UUID) -> bool:
        """Supprime le dossier complet d'un document."""
        doc_path = self._get_document_path(user_id, document_id)

        if not doc_path.exists():
            logger.warning(f"Dossier document non trouvé: {doc_path}")
            return False

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, shutil.rmtree, doc_path)
            logger.info(f"Dossier document supprimé: {doc_path}")
            return True
        except PermissionError:
            raise StoragePermissionError(str(doc_path), "delete")
        except OSError as e:
            raise StorageIOError(str(doc_path), "delete", str(e))

    async def exists(self, file_path: str) -> bool:
        """Vérifie si un fichier existe."""
        full_path = self.base_path / file_path
        return full_path.exists()

    async def get_file_info(self, file_path: str) -> FileInfo:
        """Retourne les métadonnées d'un fichier."""
        full_path = self.base_path / file_path

        if not full_path.exists():
            raise StorageFileNotFoundError(file_path)

        try:
            stat = full_path.stat()
            mime_type, _ = mimetypes.guess_type(str(full_path))

            return FileInfo(
                path=file_path,
                filename=full_path.name,
                size=stat.st_size,
                mime_type=mime_type or "application/octet-stream",
                created_at=datetime.fromtimestamp(stat.st_ctime),
                modified_at=datetime.fromtimestamp(stat.st_mtime),
            )
        except OSError as e:
            raise StorageIOError(file_path, "stat", str(e))

    async def list_user_files(self, user_id: UUID) -> List[str]:
        """Liste les chemins de tous les fichiers d'un utilisateur."""
        user_path = self._get_user_path(user_id)

        if not user_path.exists():
            return []

        files = []
        try:
            for doc_folder in user_path.iterdir():
                if doc_folder.is_dir():
                    for file in doc_folder.iterdir():
                        if file.is_file():
                            files.append(str(file.relative_to(self.base_path)))
        except OSError as e:
            logger.error(f"Erreur lors du listage des fichiers: {e}")

        return files

    async def list_document_versions(
        self, user_id: UUID, document_id: UUID
    ) -> List[str]:
        """Liste les chemins de toutes les versions d'un document."""
        doc_path = self._get_document_path(user_id, document_id)

        if not doc_path.exists():
            return []

        versions = []
        try:
            for file in doc_path.iterdir():
                if file.is_file() and file.name.startswith("v"):
                    versions.append(str(file.relative_to(self.base_path)))
            # Trier par numéro de version
            versions.sort(key=lambda x: int(x.split("/")[-1].split("_")[0][1:]))
        except (OSError, ValueError) as e:
            logger.error(f"Erreur lors du listage des versions: {e}")

        return versions

    async def get_storage_stats(self) -> StorageStats:
        """Retourne les statistiques globales du storage."""
        try:
            # Statistiques du disque
            disk_usage = shutil.disk_usage(self.base_path)

            # Compter les fichiers et utilisateurs
            file_count = 0
            user_ids = set()

            if self.base_path.exists():
                for user_folder in self.base_path.iterdir():
                    if user_folder.is_dir():
                        user_ids.add(user_folder.name)
                        for doc_folder in user_folder.iterdir():
                            if doc_folder.is_dir():
                                file_count += sum(
                                    1 for f in doc_folder.iterdir() if f.is_file()
                                )

            return StorageStats(
                total_bytes=disk_usage.total,
                used_bytes=disk_usage.used,
                free_bytes=disk_usage.free,
                file_count=file_count,
                user_count=len(user_ids),
            )
        except OSError as e:
            logger.error(f"Erreur lors du calcul des stats: {e}")
            return StorageStats(
                total_bytes=0,
                used_bytes=0,
                free_bytes=0,
                file_count=0,
                user_count=0,
            )

    async def get_user_stats(self, user_id: UUID) -> UserStorageStats:
        """Retourne les statistiques de stockage d'un utilisateur."""
        user_path = self._get_user_path(user_id)

        used_bytes = 0
        file_count = 0

        if user_path.exists():
            try:
                for doc_folder in user_path.iterdir():
                    if doc_folder.is_dir():
                        for file in doc_folder.iterdir():
                            if file.is_file():
                                used_bytes += file.stat().st_size
                                file_count += 1
            except OSError as e:
                logger.error(f"Erreur lors du calcul des stats utilisateur: {e}")

        return UserStorageStats(
            user_id=user_id,
            used_bytes=used_bytes,
            file_count=file_count,
            quota_bytes=None,  # Sera défini par StorageService
            quota_used_percent=0.0,
        )

    async def get_download_path(self, file_path: str) -> str:
        """Retourne le chemin absolu pour téléchargement."""
        full_path = self.base_path / file_path

        if not full_path.exists():
            raise StorageFileNotFoundError(file_path)

        return str(full_path.absolute())

    async def stream_file(
        self, file_path: str, chunk_size: int = 8192
    ) -> AsyncIterator[bytes]:
        """Stream le fichier par chunks."""
        full_path = self.base_path / file_path

        if not full_path.exists():
            raise StorageFileNotFoundError(file_path)

        try:
            with open(full_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except PermissionError:
            raise StoragePermissionError(file_path, "read")
        except OSError as e:
            raise StorageIOError(file_path, "stream", str(e))
