"""
Exceptions Storage

Ce module définit les exceptions spécifiques au storage.
"""

from typing import List, Optional
from uuid import UUID


class StorageError(Exception):
    """Erreur de base pour le storage."""

    def __init__(self, message: str = "Storage error"):
        self.message = message
        super().__init__(self.message)


class StorageFileNotFoundError(StorageError):
    """Fichier non trouvé dans le storage."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        super().__init__(f"Fichier non trouvé: {file_path}")


class QuotaExceededError(StorageError):
    """Quota utilisateur dépassé."""

    def __init__(self, user_id: UUID, quota_bytes: int, requested_bytes: int):
        self.user_id = user_id
        self.quota_bytes = quota_bytes
        self.requested_bytes = requested_bytes
        self.quota_mb = quota_bytes / (1024**2)
        self.requested_mb = requested_bytes / (1024**2)
        super().__init__(
            f"Quota dépassé pour l'utilisateur {user_id}: "
            f"demandé {self.requested_mb:.1f} MB, quota {self.quota_mb:.1f} MB"
        )


class FileTooLargeError(StorageError):
    """Fichier trop volumineux."""

    def __init__(self, file_size: int, max_size: int):
        self.file_size = file_size
        self.max_size = max_size
        self.file_size_mb = file_size / (1024**2)
        self.max_size_mb = max_size / (1024**2)
        super().__init__(
            f"Fichier trop volumineux: {self.file_size_mb:.1f} MB "
            f"(max: {self.max_size_mb:.1f} MB)"
        )


class InvalidFileTypeError(StorageError):
    """Type de fichier non autorisé."""

    def __init__(
        self,
        file_type: str,
        allowed_types: Optional[List[str]] = None,
        reason: Optional[str] = None,
    ):
        self.file_type = file_type
        self.allowed_types = allowed_types
        self.reason = reason

        if reason:
            message = f"Type de fichier non autorisé: {file_type} ({reason})"
        elif allowed_types:
            message = (
                f"Type de fichier non autorisé: {file_type}. "
                f"Types acceptés: {', '.join(allowed_types[:5])}"
            )
        else:
            message = f"Type de fichier non autorisé: {file_type}"

        super().__init__(message)


class StoragePermissionError(StorageError):
    """Erreur de permission sur le storage."""

    def __init__(self, file_path: str, operation: str = "access"):
        self.file_path = file_path
        self.operation = operation
        super().__init__(
            f"Permission refusée pour {operation} sur: {file_path}"
        )


class StorageIOError(StorageError):
    """Erreur d'entrée/sortie sur le storage."""

    def __init__(self, file_path: str, operation: str, original_error: str):
        self.file_path = file_path
        self.operation = operation
        self.original_error = original_error
        super().__init__(
            f"Erreur I/O lors de {operation} sur {file_path}: {original_error}"
        )
