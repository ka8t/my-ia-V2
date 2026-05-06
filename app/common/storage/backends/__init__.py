"""
Storage Backends

Ce module contient les différentes implémentations de StorageBackend.
"""

from app.common.storage.backends.local import LocalStorageBackend

__all__ = [
    "LocalStorageBackend",
]
