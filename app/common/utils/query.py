"""
Utilitaires de requête paginée.

Helper async pour exécuter des requêtes SQLAlchemy paginées
avec comptage total en une seule fonction.
"""
from typing import Any, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.common.utils.pagination import (
    PaginationInfo,
    create_pagination_info,
    normalize_pagination,
)


async def paginate_query(
    session: AsyncSession,
    query: Select,
    *,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    unique: bool = False,
) -> Tuple[List[Any], PaginationInfo]:
    """
    Exécute une requête paginée avec comptage total.

    Supporte deux formats d'entrée :
    - page/page_size (1-indexed)
    - limit/offset

    La requête DOIT inclure le order_by avant d'être passée.

    Args:
        session: Session async SQLAlchemy
        query: Requête SELECT avec filtres et order_by appliqués
        page: Numéro de page (1-indexed)
        page_size: Nombre d'items par page
        limit: Limite d'items (alternatif à page_size)
        offset: Décalage (alternatif à page)
        unique: Appeler .unique() sur le résultat (nécessaire avec joinedload)

    Returns:
        Tuple (liste des items, PaginationInfo)

    Examples:
        >>> items, info = await paginate_query(
        ...     session, query.order_by(Model.created_at.desc()),
        ...     page=2, page_size=20
        ... )
        >>> info.total, info.total_pages
        (100, 5)
    """
    # Normaliser les paramètres de pagination
    params = normalize_pagination(
        page=page, page_size=page_size, limit=limit, offset=offset
    )

    # Comptage total
    count_q = select(func.count()).select_from(query.subquery())
    total = (await session.execute(count_q)).scalar() or 0

    # Appliquer pagination
    paginated = query.offset(params.offset).limit(params.limit)

    # Exécuter
    result = await session.execute(paginated)
    if unique:
        items = list(result.unique().scalars().all())
    else:
        items = list(result.scalars().all())

    # Construire les infos de pagination
    info = create_pagination_info(total, params.limit, params.offset)

    return items, info
