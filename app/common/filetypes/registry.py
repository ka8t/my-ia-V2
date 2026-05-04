"""
Registry des types de fichiers supportes.

Ce registre definit tous les types de fichiers avec:
- Extension et type MIME
- Librairie de parsing utilisee
- Categorie (documents, images, data)
- Description lisible
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set


@dataclass
class FileTypeInfo:
    """Information sur un type de fichier supporte."""
    extension: str
    mime_type: str
    name: str
    description: str
    parser: str
    category: str  # 'documents', 'images', 'data'
    enabled_by_default: bool = True


# Registre complet des types de fichiers supportes
FILE_TYPES_REGISTRY: Dict[str, FileTypeInfo] = {
    # === DOCUMENTS ===
    "pdf": FileTypeInfo(
        extension=".pdf",
        mime_type="application/pdf",
        name="PDF",
        description="Documents PDF (avec OCR automatique si scannes)",
        parser="Unstructured + Tesseract OCR",
        category="documents",
        enabled_by_default=True,
    ),
    "docx": FileTypeInfo(
        extension=".docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        name="Word DOCX",
        description="Documents Microsoft Word (format moderne)",
        parser="Unstructured + python-docx",
        category="documents",
        enabled_by_default=True,
    ),
    "doc": FileTypeInfo(
        extension=".doc",
        mime_type="application/msword",
        name="Word DOC",
        description="Documents Microsoft Word (format legacy)",
        parser="Unstructured",
        category="documents",
        enabled_by_default=True,
    ),
    "xlsx": FileTypeInfo(
        extension=".xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        name="Excel XLSX",
        description="Feuilles de calcul Excel (format moderne)",
        parser="Unstructured + openpyxl",
        category="documents",
        enabled_by_default=True,
    ),
    "xls": FileTypeInfo(
        extension=".xls",
        mime_type="application/vnd.ms-excel",
        name="Excel XLS",
        description="Feuilles de calcul Excel (format legacy)",
        parser="Unstructured",
        category="documents",
        enabled_by_default=True,
    ),
    "pptx": FileTypeInfo(
        extension=".pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        name="PowerPoint PPTX",
        description="Presentations PowerPoint (format moderne)",
        parser="Unstructured",
        category="documents",
        enabled_by_default=True,
    ),
    "ppt": FileTypeInfo(
        extension=".ppt",
        mime_type="application/vnd.ms-powerpoint",
        name="PowerPoint PPT",
        description="Presentations PowerPoint (format legacy)",
        parser="Unstructured",
        category="documents",
        enabled_by_default=True,
    ),
    "txt": FileTypeInfo(
        extension=".txt",
        mime_type="text/plain",
        name="Texte brut",
        description="Fichiers texte simples",
        parser="Unstructured",
        category="documents",
        enabled_by_default=True,
    ),
    "md": FileTypeInfo(
        extension=".md",
        mime_type="text/markdown",
        name="Markdown",
        description="Documents Markdown avec structure preservee",
        parser="Unstructured + MarkdownSplitter",
        category="documents",
        enabled_by_default=True,
    ),
    "html": FileTypeInfo(
        extension=".html",
        mime_type="text/html",
        name="HTML",
        description="Pages web HTML",
        parser="Unstructured + BeautifulSoup",
        category="documents",
        enabled_by_default=True,
    ),
    "htm": FileTypeInfo(
        extension=".htm",
        mime_type="text/html",
        name="HTM",
        description="Pages web HTM (alias HTML)",
        parser="Unstructured + BeautifulSoup",
        category="documents",
        enabled_by_default=True,
    ),

    # === IMAGES (OCR) ===
    "png": FileTypeInfo(
        extension=".png",
        mime_type="image/png",
        name="PNG",
        description="Images PNG (extraction texte par OCR)",
        parser="Tesseract OCR",
        category="images",
        enabled_by_default=True,
    ),
    "jpg": FileTypeInfo(
        extension=".jpg",
        mime_type="image/jpeg",
        name="JPEG",
        description="Images JPEG (extraction texte par OCR)",
        parser="Tesseract OCR",
        category="images",
        enabled_by_default=True,
    ),
    "jpeg": FileTypeInfo(
        extension=".jpeg",
        mime_type="image/jpeg",
        name="JPEG",
        description="Images JPEG (extraction texte par OCR)",
        parser="Tesseract OCR",
        category="images",
        enabled_by_default=True,
    ),

    # === DONNEES STRUCTUREES ===
    "json": FileTypeInfo(
        extension=".json",
        mime_type="application/json",
        name="JSON",
        description="Donnees structurees JSON",
        parser="Unstructured",
        category="data",
        enabled_by_default=True,
    ),
    "jsonl": FileTypeInfo(
        extension=".jsonl",
        mime_type="application/jsonl",
        name="JSON Lines",
        description="JSON Lines (un objet par ligne)",
        parser="Unstructured",
        category="data",
        enabled_by_default=True,
    ),
    "csv": FileTypeInfo(
        extension=".csv",
        mime_type="text/csv",
        name="CSV",
        description="Fichiers CSV (valeurs separees par virgules)",
        parser="Unstructured",
        category="data",
        enabled_by_default=True,
    ),
}


def get_all_file_types() -> List[Dict]:
    """
    Retourne tous les types de fichiers avec leurs informations.

    Returns:
        Liste de dictionnaires avec les infos de chaque type
    """
    return [
        {
            "id": key,
            "extension": info.extension,
            "mime_type": info.mime_type,
            "name": info.name,
            "description": info.description,
            "parser": info.parser,
            "category": info.category,
            "enabled_by_default": info.enabled_by_default,
        }
        for key, info in FILE_TYPES_REGISTRY.items()
    ]


def get_file_type_by_extension(extension: str) -> Optional[FileTypeInfo]:
    """
    Trouve un type de fichier par son extension.

    Args:
        extension: Extension avec ou sans point (ex: '.pdf' ou 'pdf')

    Returns:
        FileTypeInfo ou None
    """
    ext = extension.lower().lstrip(".")
    return FILE_TYPES_REGISTRY.get(ext)


def get_file_type_by_mime(mime_type: str) -> Optional[FileTypeInfo]:
    """
    Trouve un type de fichier par son type MIME.

    Args:
        mime_type: Type MIME (ex: 'application/pdf')

    Returns:
        FileTypeInfo ou None (retourne le premier match)
    """
    for info in FILE_TYPES_REGISTRY.values():
        if info.mime_type == mime_type:
            return info
    return None


def get_enabled_extensions(enabled_types: Optional[List[str]] = None) -> Set[str]:
    """
    Retourne les extensions activees.

    Args:
        enabled_types: Liste des IDs de types actives (None = tous par defaut)

    Returns:
        Set des extensions (ex: {'.pdf', '.docx', ...})
    """
    if enabled_types is None:
        # Retourner ceux actives par defaut
        return {
            info.extension
            for info in FILE_TYPES_REGISTRY.values()
            if info.enabled_by_default
        }

    return {
        FILE_TYPES_REGISTRY[type_id].extension
        for type_id in enabled_types
        if type_id in FILE_TYPES_REGISTRY
    }


def get_enabled_mime_types(enabled_types: Optional[List[str]] = None) -> List[str]:
    """
    Retourne les types MIME actives.

    Args:
        enabled_types: Liste des IDs de types actives (None = tous par defaut)

    Returns:
        Liste des types MIME uniques
    """
    if enabled_types is None:
        # Retourner ceux actives par defaut
        mime_types = {
            info.mime_type
            for info in FILE_TYPES_REGISTRY.values()
            if info.enabled_by_default
        }
    else:
        mime_types = {
            FILE_TYPES_REGISTRY[type_id].mime_type
            for type_id in enabled_types
            if type_id in FILE_TYPES_REGISTRY
        }

    return sorted(mime_types)


def is_extension_supported(
    extension: str, enabled_types: Optional[List[str]] = None
) -> bool:
    """
    Verifie si une extension est supportee.

    Args:
        extension: Extension a verifier
        enabled_types: Liste des IDs de types actives

    Returns:
        True si supportee
    """
    ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    return ext in get_enabled_extensions(enabled_types)


def is_mime_supported(
    mime_type: str, enabled_types: Optional[List[str]] = None
) -> bool:
    """
    Verifie si un type MIME est supporte.

    Args:
        mime_type: Type MIME a verifier
        enabled_types: Liste des IDs de types actives

    Returns:
        True si supporte
    """
    return mime_type in get_enabled_mime_types(enabled_types)
