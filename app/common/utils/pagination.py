"""
Utilitaires de pagination.

Fournit des helpers pour normaliser et gerer la pagination
entre les differents formats (limit/offset vs page/page_size).
"""
from typing import NamedTuple


class PaginationParams(NamedTuple):
    """Parametres de pagination normalises."""
    limit: int
    offset: int


class PaginationInfo(NamedTuple):
    """Informations de pagination pour les reponses."""
    total: int
    page: int
    page_size: int
    total_pages: int
    has_next: bool
    has_prev: bool


def normalize_pagination(
    page: int = None,
    page_size: int = None,
    limit: int = None,
    offset: int = None,
    max_limit: int = 200
) -> PaginationParams:
    """
    Normalise les parametres de pagination vers limit/offset.

    Supporte deux formats d'entree:
    - page/page_size: Pagination par page (1-indexed)
    - limit/offset: Pagination directe

    Args:
        page: Numero de page (1-indexed, prioritaire)
        page_size: Taille de page
        limit: Limite d'items
        offset: Decalage
        max_limit: Limite maximale autorisee

    Returns:
        PaginationParams avec limit et offset normalises

    Examples:
        >>> normalize_pagination(page=2, page_size=20)
        PaginationParams(limit=20, offset=20)

        >>> normalize_pagination(limit=50, offset=100)
        PaginationParams(limit=50, offset=100)
    """
    if page is not None and page_size is not None:
        # Format page/page_size -> conversion vers limit/offset
        page = max(1, page)
        page_size = min(max(1, page_size), max_limit)
        return PaginationParams(
            limit=page_size,
            offset=(page - 1) * page_size
        )
    else:
        # Format limit/offset direct
        effective_limit = min(limit or 50, max_limit)
        effective_offset = max(offset or 0, 0)
        return PaginationParams(
            limit=effective_limit,
            offset=effective_offset
        )


def create_pagination_info(
    total: int,
    limit: int,
    offset: int
) -> PaginationInfo:
    """
    Cree les informations de pagination depuis limit/offset.

    Args:
        total: Nombre total d'items
        limit: Limite utilisee
        offset: Decalage utilise

    Returns:
        PaginationInfo avec toutes les informations

    Examples:
        >>> create_pagination_info(total=100, limit=20, offset=40)
        PaginationInfo(total=100, page=3, page_size=20, total_pages=5, has_next=True, has_prev=True)
    """
    if limit <= 0:
        limit = 1

    page_size = limit
    page = (offset // limit) + 1 if limit > 0 else 1
    total_pages = max(1, (total + limit - 1) // limit) if limit > 0 else 1

    return PaginationInfo(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1
    )


def paginate_response(
    items: list,
    total: int,
    limit: int,
    offset: int
) -> dict:
    """
    Cree une reponse paginee complete.

    Args:
        items: Liste des items de la page courante
        total: Nombre total d'items
        limit: Limite utilisee
        offset: Decalage utilise

    Returns:
        Dict avec items et informations de pagination
    """
    info = create_pagination_info(total, limit, offset)

    return {
        "items": items,
        "total": info.total,
        "page": info.page,
        "page_size": info.page_size,
        "total_pages": info.total_pages,
        "has_next": info.has_next,
        "has_prev": info.has_prev
    }
