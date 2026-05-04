"""
Module FileTypes - Mapping des types de fichiers supportes.

Ce module centralise la configuration des types de fichiers:
- Extensions
- Types MIME
- Librairies de parsing
- Categorie (document, image, data)
"""

from app.common.filetypes.registry import (
    FILE_TYPES_REGISTRY,
    FileTypeInfo,
    get_all_file_types,
    get_enabled_extensions,
    get_enabled_mime_types,
    get_file_type_by_extension,
    get_file_type_by_mime,
    is_extension_supported,
    is_mime_supported,
)

__all__ = [
    "FILE_TYPES_REGISTRY",
    "FileTypeInfo",
    "get_all_file_types",
    "get_enabled_extensions",
    "get_enabled_mime_types",
    "get_file_type_by_extension",
    "get_file_type_by_mime",
    "is_extension_supported",
    "is_mime_supported",
]
