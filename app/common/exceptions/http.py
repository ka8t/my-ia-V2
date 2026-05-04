"""
Exceptions HTTP personnalisées

Ce module définit les exceptions HTTP réutilisables
pour améliorer la gestion des erreurs.

Utilisation des ErrorCode:
    from app.common.exceptions.http import ErrorCode, not_found, bad_request

    # Lever une erreur avec code
    raise not_found(ErrorCode.USER_NOT_FOUND)
    raise bad_request(ErrorCode.INVALID_INPUT, {"field": "email"})
"""
from enum import Enum
from typing import Any, Optional, Dict
from fastapi import HTTPException, status

from app.common.i18n import t


# =============================================================================
# ERROR CODES
# =============================================================================

class ErrorCode(str, Enum):
    """Codes d'erreur standardisés pour le frontend."""

    # Génériques
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    FORBIDDEN = "forbidden"
    INVALID_INPUT = "invalid_input"
    UNAUTHORIZED = "unauthorized"

    # Users
    USER_NOT_FOUND = "user_not_found"
    USER_EMAIL_EXISTS = "user_email_exists"
    USER_USERNAME_EXISTS = "user_username_exists"
    USER_CANNOT_DELETE_SELF = "user_cannot_delete_self"
    USER_CANNOT_CHANGE_OWN_ROLE = "user_cannot_change_own_role"
    USER_INVALID_PASSWORD = "user_invalid_password"

    # Documents
    DOC_NOT_FOUND = "doc_not_found"
    DOC_TOO_LARGE = "doc_too_large"
    DOC_INVALID_TYPE = "doc_invalid_type"
    DOC_ALREADY_INDEXED = "doc_already_indexed"

    # Collections
    COLLECTION_NOT_FOUND = "collection_not_found"
    COLLECTION_PRIVATE = "collection_private"
    COLLECTION_NAME_EXISTS = "collection_name_exists"

    # Conversations
    CONV_NOT_FOUND = "conv_not_found"
    CONV_ARCHIVED = "conv_archived"

    # Sources
    SOURCE_NOT_FOUND = "source_not_found"
    SOURCE_CONNECTION_FAILED = "source_connection_failed"

    # Auth
    AUTH_INVALID_CREDENTIALS = "auth_invalid_credentials"
    AUTH_TOKEN_EXPIRED = "auth_token_expired"
    AUTH_NOT_VERIFIED = "auth_not_verified"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def not_found(code: ErrorCode = ErrorCode.NOT_FOUND, params: Dict = None) -> HTTPException:
    """Crée une exception 404 avec code d'erreur standardisé."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code.value, "params": params or {}}
    )


def bad_request(code: ErrorCode = ErrorCode.INVALID_INPUT, params: Dict = None) -> HTTPException:
    """Crée une exception 400 avec code d'erreur standardisé."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code.value, "params": params or {}}
    )


def conflict(code: ErrorCode = ErrorCode.ALREADY_EXISTS, params: Dict = None) -> HTTPException:
    """Crée une exception 409 avec code d'erreur standardisé."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code.value, "params": params or {}}
    )


def forbidden(code: ErrorCode = ErrorCode.FORBIDDEN, params: Dict = None) -> HTTPException:
    """Crée une exception 403 avec code d'erreur standardisé."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code.value, "params": params or {}}
    )


def unauthorized(code: ErrorCode = ErrorCode.UNAUTHORIZED, params: Dict = None) -> HTTPException:
    """Crée une exception 401 avec code d'erreur standardisé."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": code.value, "params": params or {}}
    )


# =============================================================================
# EXCEPTION CLASSES (legacy, pour compatibilité)
# =============================================================================


class BadRequestException(HTTPException):
    """Exception 400 Bad Request"""

    def __init__(self, detail: Optional[str] = None, lang: str = "fr"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail or t("http_bad_request", lang)
        )


class UnauthorizedException(HTTPException):
    """Exception 401 Unauthorized"""

    def __init__(self, detail: Optional[str] = None, lang: str = "fr"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail or t("http_unauthorized", lang)
        )


class ForbiddenException(HTTPException):
    """Exception 403 Forbidden"""

    def __init__(self, detail: Optional[str] = None, lang: str = "fr"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail or t("http_forbidden", lang)
        )


class NotFoundException(HTTPException):
    """Exception 404 Not Found"""

    def __init__(self, detail: Optional[str] = None, lang: str = "fr"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail or t("http_not_found", lang)
        )


class ConflictException(HTTPException):
    """Exception 409 Conflict"""

    def __init__(self, detail: Optional[str] = None, lang: str = "fr"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail or t("http_conflict", lang)
        )


class InternalServerException(HTTPException):
    """Exception 500 Internal Server Error"""

    def __init__(self, detail: Optional[str] = None, lang: str = "fr"):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=detail or t("http_internal_error", lang)
        )


class ServiceUnavailableException(HTTPException):
    """Exception 503 Service Unavailable"""

    def __init__(self, detail: Optional[str] = None, lang: str = "fr"):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail or t("http_service_unavailable", lang)
        )
