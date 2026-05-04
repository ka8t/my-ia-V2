"""
ReindexManager - Gestion centralisée des réindexations

Ce module fournit une abstraction commune pour :
- Suivre la progression des réindexations (documents et sources)
- Gérer les demandes d'annulation
- Permettre l'annulation en cascade (corpus -> documents + sources)

Architecture :
- Chaque élément indexable (document, source) a un ID unique sous forme "type-uuid"
- Les flags et progressions sont stockés en mémoire (dict)
- Les méthodes sont statiques pour un accès global facile
"""
import logging
from typing import Dict, Optional, List, Callable, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ReindexItemType(Enum):
    """Types d'éléments indexables."""
    DOCUMENT = "doc"
    SOURCE = "source"


class ReindexManager:
    """
    Gestionnaire centralisé des réindexations.

    Gère les progressions et annulations pour tous les types d'éléments indexables.
    """

    # Progression par élément : {item_id: {status, progress, message, ...}}
    _progress: Dict[str, dict] = {}

    # Flags d'annulation : {item_id: True}
    _cancel_flags: Dict[str, bool] = {}

    # Mapping corpus -> items en cours de réindexation
    _corpus_items: Dict[str, List[str]] = {}

    # === Helpers pour générer les IDs ===

    @staticmethod
    def make_id(item_type: ReindexItemType, uuid: str) -> str:
        """Génère un ID unique pour un élément."""
        return f"{item_type.value}-{uuid}"

    @staticmethod
    def parse_id(item_id: str) -> tuple[Optional[ReindexItemType], Optional[str]]:
        """Parse un ID en type et UUID."""
        if "-" not in item_id:
            return None, None
        parts = item_id.split("-", 1)
        try:
            item_type = ReindexItemType(parts[0])
            return item_type, parts[1]
        except ValueError:
            return None, None

    # === Gestion de la progression ===

    @classmethod
    def get_progress(cls, item_id: str) -> dict:
        """Retourne la progression d'un élément."""
        return cls._progress.get(item_id, {"status": "idle", "progress": 0})

    @classmethod
    def set_progress(
        cls,
        item_id: str,
        progress: int,
        message: str,
        status: str = "running",
        name: Optional[str] = None,
        documents_count: int = 0,
        error_message: Optional[str] = None,
        corpus_id: Optional[str] = None,
    ) -> None:
        """Met à jour la progression d'un élément."""
        data = {
            "status": status,
            "progress": progress,
            "progress_message": message,
            "documents_count": documents_count,
            "error_message": error_message,
        }

        # Conserver le nom si déjà défini
        if name:
            data["name"] = name
        elif item_id in cls._progress and "name" in cls._progress[item_id]:
            data["name"] = cls._progress[item_id]["name"]

        # Conserver le corpus_id si défini
        if corpus_id:
            data["corpus_id"] = corpus_id
        elif item_id in cls._progress and "corpus_id" in cls._progress[item_id]:
            data["corpus_id"] = cls._progress[item_id]["corpus_id"]

        cls._progress[item_id] = data

    @classmethod
    def clear_progress(cls, item_id: str) -> None:
        """Supprime le suivi de progression d'un élément."""
        cls._progress.pop(item_id, None)

    # === Gestion des annulations ===

    @classmethod
    def request_cancel(cls, item_id: str) -> bool:
        """
        Demande l'annulation d'une réindexation.

        Returns:
            True si une réindexation était en cours, False sinon.
        """
        progress = cls._progress.get(item_id, {})
        status = progress.get("status", "")

        if status in ("running", "pending", "queued"):
            cls._cancel_flags[item_id] = True
            logger.info(f"ReindexManager: Cancel requested for {item_id}")
            return True
        return False

    @classmethod
    def is_cancel_requested(cls, item_id: str) -> bool:
        """Vérifie si l'annulation a été demandée."""
        return cls._cancel_flags.get(item_id, False)

    @classmethod
    def clear_cancel_flag(cls, item_id: str) -> None:
        """Supprime le flag d'annulation."""
        cls._cancel_flags.pop(item_id, None)

    # === Gestion des corpus (cascade) ===

    @classmethod
    def register_corpus_item(cls, corpus_id: str, item_id: str) -> None:
        """Enregistre un élément comme faisant partie d'un corpus en cours de réindexation."""
        if corpus_id not in cls._corpus_items:
            cls._corpus_items[corpus_id] = []
        if item_id not in cls._corpus_items[corpus_id]:
            cls._corpus_items[corpus_id].append(item_id)

    @classmethod
    def unregister_corpus_item(cls, corpus_id: str, item_id: str) -> None:
        """Retire un élément du corpus."""
        if corpus_id in cls._corpus_items:
            if item_id in cls._corpus_items[corpus_id]:
                cls._corpus_items[corpus_id].remove(item_id)
            # Nettoyer si vide
            if not cls._corpus_items[corpus_id]:
                del cls._corpus_items[corpus_id]

    @classmethod
    def get_corpus_items(cls, corpus_id: str) -> List[str]:
        """Retourne les IDs des éléments en cours de réindexation pour un corpus."""
        return cls._corpus_items.get(corpus_id, []).copy()

    @classmethod
    def request_corpus_cancel(cls, corpus_id: str) -> int:
        """
        Demande l'annulation de tous les éléments d'un corpus.

        Returns:
            Nombre d'éléments pour lesquels l'annulation a été demandée.
        """
        items = cls.get_corpus_items(corpus_id)
        cancelled_count = 0

        for item_id in items:
            if cls.request_cancel(item_id):
                cancelled_count += 1

        logger.info(f"ReindexManager: Cancel requested for corpus {corpus_id}, {cancelled_count} items")
        return cancelled_count

    @classmethod
    def clear_corpus(cls, corpus_id: str) -> None:
        """Nettoie toutes les données d'un corpus."""
        items = cls.get_corpus_items(corpus_id)
        for item_id in items:
            cls.clear_progress(item_id)
            cls.clear_cancel_flag(item_id)
        cls._corpus_items.pop(corpus_id, None)

    # === Méthodes de commodité pour documents ===

    @classmethod
    def doc_id(cls, uuid: str) -> str:
        """Génère l'ID d'un document."""
        return cls.make_id(ReindexItemType.DOCUMENT, uuid)

    @classmethod
    def get_doc_progress(cls, uuid: str) -> dict:
        """Retourne la progression d'un document."""
        return cls.get_progress(cls.doc_id(uuid))

    @classmethod
    def set_doc_progress(
        cls,
        uuid: str,
        progress: int,
        message: str,
        status: str = "running",
        name: Optional[str] = None,
        documents_count: int = 0,
        error_message: Optional[str] = None,
        corpus_id: Optional[str] = None,
    ) -> None:
        """Met à jour la progression d'un document."""
        item_id = cls.doc_id(uuid)
        cls.set_progress(item_id, progress, message, status, name, documents_count, error_message, corpus_id)
        if corpus_id:
            cls.register_corpus_item(corpus_id, item_id)

    @classmethod
    def clear_doc_progress(cls, uuid: str) -> None:
        """Supprime le suivi de progression d'un document."""
        item_id = cls.doc_id(uuid)
        # Retirer du corpus si associé
        progress = cls._progress.get(item_id, {})
        corpus_id = progress.get("corpus_id")
        if corpus_id:
            cls.unregister_corpus_item(corpus_id, item_id)
        cls.clear_progress(item_id)

    @classmethod
    def request_doc_cancel(cls, uuid: str) -> bool:
        """Demande l'annulation d'un document."""
        return cls.request_cancel(cls.doc_id(uuid))

    @classmethod
    def is_doc_cancel_requested(cls, uuid: str) -> bool:
        """Vérifie si l'annulation est demandée pour un document."""
        return cls.is_cancel_requested(cls.doc_id(uuid))

    @classmethod
    def clear_doc_cancel_flag(cls, uuid: str) -> None:
        """Supprime le flag d'annulation d'un document."""
        cls.clear_cancel_flag(cls.doc_id(uuid))

    # === Méthodes de commodité pour sources ===

    @classmethod
    def source_id(cls, uuid: str) -> str:
        """Génère l'ID d'une source."""
        return cls.make_id(ReindexItemType.SOURCE, uuid)

    @classmethod
    def get_source_progress(cls, uuid: str) -> dict:
        """Retourne la progression d'une source."""
        return cls.get_progress(cls.source_id(uuid))

    @classmethod
    def set_source_progress(
        cls,
        uuid: str,
        progress: int,
        message: str,
        status: str = "running",
        name: Optional[str] = None,
        documents_count: int = 0,
        error_message: Optional[str] = None,
        corpus_id: Optional[str] = None,
    ) -> None:
        """Met à jour la progression d'une source."""
        item_id = cls.source_id(uuid)
        cls.set_progress(item_id, progress, message, status, name, documents_count, error_message, corpus_id)
        if corpus_id:
            cls.register_corpus_item(corpus_id, item_id)

    @classmethod
    def clear_source_progress(cls, uuid: str) -> None:
        """Supprime le suivi de progression d'une source."""
        item_id = cls.source_id(uuid)
        # Retirer du corpus si associé
        progress = cls._progress.get(item_id, {})
        corpus_id = progress.get("corpus_id")
        if corpus_id:
            cls.unregister_corpus_item(corpus_id, item_id)
        cls.clear_progress(item_id)

    @classmethod
    def request_source_cancel(cls, uuid: str) -> bool:
        """Demande l'annulation d'une source."""
        return cls.request_cancel(cls.source_id(uuid))

    @classmethod
    def is_source_cancel_requested(cls, uuid: str) -> bool:
        """Vérifie si l'annulation est demandée pour une source."""
        return cls.is_cancel_requested(cls.source_id(uuid))

    @classmethod
    def clear_source_cancel_flag(cls, uuid: str) -> None:
        """Supprime le flag d'annulation d'une source."""
        cls.clear_cancel_flag(cls.source_id(uuid))


# === Fonctions de compatibilité (pour migration progressive) ===

def get_doc_reindex_progress(document_id: str) -> dict:
    """
    Compatibilité avec l'ancien code.

    Retourne un dict avec 'document_name' (mappé depuis 'name' interne).
    """
    progress = ReindexManager.get_doc_progress(document_id)
    # Mapper 'name' vers 'document_name' pour l'API
    if "name" in progress:
        progress["document_name"] = progress["name"]
    return progress


def set_doc_reindex_progress(
    document_id: str,
    progress: int,
    message: str,
    status: str = "running",
    documents_count: int = 0,
    error_message: Optional[str] = None,
    document_name: Optional[str] = None,
    corpus_id: Optional[str] = None,
) -> None:
    """Compatibilité avec l'ancien code."""
    ReindexManager.set_doc_progress(
        document_id, progress, message, status, document_name,
        documents_count, error_message, corpus_id
    )


def clear_doc_reindex_progress(document_id: str) -> None:
    """Compatibilité avec l'ancien code."""
    ReindexManager.clear_doc_progress(document_id)


def request_doc_cancel(document_id: str) -> bool:
    """Compatibilité avec l'ancien code."""
    return ReindexManager.request_doc_cancel(document_id)


def is_doc_cancel_requested(document_id: str) -> bool:
    """Compatibilité avec l'ancien code."""
    return ReindexManager.is_doc_cancel_requested(document_id)


def clear_doc_cancel_flag(document_id: str) -> None:
    """Compatibilité avec l'ancien code."""
    ReindexManager.clear_doc_cancel_flag(document_id)


def request_source_cancel(source_id: str) -> bool:
    """Compatibilité avec l'ancien code."""
    return ReindexManager.request_source_cancel(source_id)


def is_source_cancel_requested(source_id: str) -> bool:
    """Compatibilité avec l'ancien code."""
    return ReindexManager.is_source_cancel_requested(source_id)


def clear_source_cancel_flag(source_id: str) -> None:
    """Compatibilité avec l'ancien code."""
    ReindexManager.clear_source_cancel_flag(source_id)
