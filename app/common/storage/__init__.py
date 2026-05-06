"""
Module Storage - Abstraction pour le stockage de fichiers

Ce module fournit une couche d'abstraction pour le stockage de fichiers,
permettant de changer de backend (local, MinIO, S3) sans modifier le code métier.
"""

from app.common.storage.base import StorageBackend
from app.common.storage.service import StorageService
from app.common.storage.schemas import (
    FileInfo,
    StorageStats,
    UserStorageStats,
    QuotaConfig,
)
from app.common.storage.exceptions import (
    StorageError,
    StorageFileNotFoundError,
    QuotaExceededError,
    FileTooLargeError,
    InvalidFileTypeError,
)
from app.common.storage.backends.local import LocalStorageBackend

__all__ = [
    # Interface
    "StorageBackend",
    # Service
    "StorageService",
    # Schemas
    "FileInfo",
    "StorageStats",
    "UserStorageStats",
    "QuotaConfig",
    # Exceptions
    "StorageError",
    "StorageFileNotFoundError",
    "QuotaExceededError",
    "FileTooLargeError",
    "InvalidFileTypeError",
    # Backends
    "LocalStorageBackend",
]
