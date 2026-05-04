"""
Codes d'erreur standardisés pour l'API MY-IA.

Ce module définit des codes d'erreur constants utilisés dans toute l'application.
Le frontend utilise ces codes pour afficher les messages traduits.
"""

from enum import Enum
from typing import Any, Optional
from fastapi import HTTPException


class ErrorCode(str, Enum):
    """Codes d'erreur standardisés pour l'API."""

    # === GENERIC ===
    GENERIC_ERROR = "GENERIC_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    ACCESS_DENIED = "ACCESS_DENIED"
    UNAUTHORIZED = "UNAUTHORIZED"

    # === DOCUMENTS ===
    DOC_NOT_FOUND = "DOC_NOT_FOUND"
    DOC_ACCESS_DENIED = "DOC_ACCESS_DENIED"
    DOC_ALREADY_EXISTS = "DOC_ALREADY_EXISTS"
    DOC_FILE_NOT_FOUND = "DOC_FILE_NOT_FOUND"
    DOC_FILE_TYPE_NOT_ALLOWED = "DOC_FILE_TYPE_NOT_ALLOWED"
    DOC_FILE_IDENTICAL = "DOC_FILE_IDENTICAL"
    DOC_VERSION_NOT_FOUND = "DOC_VERSION_NOT_FOUND"
    DOC_QUERY_TOO_SHORT = "DOC_QUERY_TOO_SHORT"
    DOC_QUOTA_EXCEEDED = "DOC_QUOTA_EXCEEDED"
    DOC_NO_CUSTOM_QUOTA = "DOC_NO_CUSTOM_QUOTA"
    DOC_DELETE_FAILED = "DOC_DELETE_FAILED"

    # === CONVERSATIONS ===
    CONV_NOT_FOUND = "CONV_NOT_FOUND"
    CONV_ACCESS_DENIED = "CONV_ACCESS_DENIED"

    # === MESSAGES ===
    MSG_NOT_FOUND = "MSG_NOT_FOUND"
    MSG_DELETE_FAILED = "MSG_DELETE_FAILED"

    # === USERS ===
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_ACCESS_DENIED = "USER_ACCESS_DENIED"
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"

    # === COLLECTIONS ===
    COLLECTION_NOT_FOUND = "COLLECTION_NOT_FOUND"
    COLLECTION_ACCESS_DENIED = "COLLECTION_ACCESS_DENIED"

    # === CORPUS ===
    CORPUS_NOT_FOUND = "CORPUS_NOT_FOUND"

    # === INGESTION ===
    INGESTION_FILE_TYPE_NOT_SUPPORTED = "INGESTION_FILE_TYPE_NOT_SUPPORTED"
    INGESTION_ALREADY_INDEXED = "INGESTION_ALREADY_INDEXED"
    INGESTION_FAILED = "INGESTION_FAILED"

    # === STORAGE ===
    STORAGE_FILE_TYPE_NOT_ALLOWED = "STORAGE_FILE_TYPE_NOT_ALLOWED"
    STORAGE_PERMISSION_DENIED = "STORAGE_PERMISSION_DENIED"
    STORAGE_FILE_NOT_FOUND = "STORAGE_FILE_NOT_FOUND"

    # === CHROMADB ===
    CHROMADB_DELETE_FAILED = "CHROMADB_DELETE_FAILED"

    # === CRYPTO ===
    CRYPTO_DECRYPTION_ERROR = "CRYPTO_DECRYPTION_ERROR"


def api_error(
    status_code: int,
    code: ErrorCode,
    params: Optional[dict[str, Any]] = None
) -> HTTPException:
    """
    Crée une HTTPException avec un code d'erreur standardisé.

    Args:
        status_code: Code HTTP (400, 401, 403, 404, etc.)
        code: Code d'erreur de l'enum ErrorCode
        params: Paramètres optionnels pour le message (ex: {"id": "xxx"})

    Returns:
        HTTPException avec detail structuré

    Example:
        raise api_error(404, ErrorCode.DOC_NOT_FOUND, {"id": doc_id})
    """
    detail = {"code": code.value}
    if params:
        detail["params"] = params
    return HTTPException(status_code=status_code, detail=detail)


# Raccourcis pour les erreurs courantes
def not_found(code: ErrorCode, params: Optional[dict[str, Any]] = None) -> HTTPException:
    """Erreur 404 Not Found."""
    return api_error(404, code, params)


def forbidden(code: ErrorCode, params: Optional[dict[str, Any]] = None) -> HTTPException:
    """Erreur 403 Forbidden."""
    return api_error(403, code, params)


def bad_request(code: ErrorCode, params: Optional[dict[str, Any]] = None) -> HTTPException:
    """Erreur 400 Bad Request."""
    return api_error(400, code, params)


def unauthorized(code: ErrorCode = ErrorCode.UNAUTHORIZED, params: Optional[dict[str, Any]] = None) -> HTTPException:
    """Erreur 401 Unauthorized."""
    return api_error(401, code, params)
