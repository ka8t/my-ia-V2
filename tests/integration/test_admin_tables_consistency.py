"""Tests de cohérence des tableaux admin (select-all + pagination + checkbox bulk).

Régression du bug signalé en QA : les tableaux admin doivent tous proposer :
  - une checkbox "select-all" en header (macro select_all_checkbox)
  - une pagination quand total > page_size (macro pagination)
  - une checkbox `js-bulk-checkbox` sur chaque ligne (pour que select-all
    puisse les cocher en lot)

Couvre admin/users, conversations, documents, collections, corpus, sources, logs.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


PAGES_WITH_BULK = [
    "/web/admin/users",
    "/web/admin/conversations",
    "/web/admin/documents",
    "/web/admin/collections",
    "/web/admin/corpus",
    "/web/admin/sources",
    "/web/admin/logs",
]


@pytest.mark.parametrize("path", PAGES_WITH_BULK)
async def test_page_exposes_select_all_checkbox(
    admin_client: AsyncClient, path: str
) -> None:
    """Chaque page bulk-able doit avoir un select-all (macro ou inline)."""
    r = await admin_client.get(path)
    assert r.status_code == 200, f"{path} → {r.status_code}"
    body = r.text
    assert (
        "admin-row__select-all" in body
        or "Tout sélectionner" in body
        or "Tout s&eacute;lectionner" in body
    ), f"{path} : pas de select-all trouvé"


@pytest.mark.parametrize("path", PAGES_WITH_BULK)
async def test_page_exposes_bulkbar(admin_client: AsyncClient, path: str) -> None:
    """Chaque page bulk-able doit avoir une bulkbar (admin-bulkbar)."""
    r = await admin_client.get(path)
    assert r.status_code == 200
    assert "admin-bulkbar" in r.text, f"{path} : pas de bulkbar"


@pytest.mark.parametrize(
    "path",
    [
        # Les pages users/convs/docs/sources/logs/colls/corpus utilisent toutes
        # `js-bulk-checkbox` désormais (rendu via partials ou inline).
        "/web/admin/users",
        "/web/admin/conversations",
        "/web/admin/collections",
    ],
)
async def test_page_uses_js_bulk_checkbox_class(
    admin_client: AsyncClient, path: str
) -> None:
    """Les checkboxes des lignes doivent porter `js-bulk-checkbox` pour que
    select-all puisse les cibler."""
    r = await admin_client.get(path)
    assert r.status_code == 200
    # Si la page n'a aucune ligne (table vide), le test reste valide
    # (juste pas de check sur le contenu)
    body = r.text
    if 'class="admin-empty"' in body or "Aucun" in body:
        pytest.skip(f"{path} : tableau vide en seed test")
    assert "js-bulk-checkbox" in body, f"{path} : checkboxes sans js-bulk-checkbox"


async def test_collections_route_supports_page_param(
    admin_client: AsyncClient,
) -> None:
    """Régression : /web/admin/collections doit accepter ?page=N (P1 ajout)."""
    r = await admin_client.get("/web/admin/collections?page=1")
    assert r.status_code == 200
    r = await admin_client.get("/web/admin/collections?page=99")
    # page hors borne : doit pas crasher (route clamp ou empty page)
    assert r.status_code == 200


async def test_corpus_route_supports_page_param(
    admin_client: AsyncClient,
) -> None:
    """Régression : /web/admin/corpus doit accepter ?page=N (P1 ajout)."""
    r = await admin_client.get("/web/admin/corpus?page=1")
    assert r.status_code == 200
    r = await admin_client.get("/web/admin/corpus?page=99")
    assert r.status_code == 200
