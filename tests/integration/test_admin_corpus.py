"""Tests d'intégration — Admin Corpus (Phase 3.7.b — Vague 1).

Couvre les routes ``/web/admin/corpus*``. Assertions sur status code, contenu
HTML retourné (rows partials) et état BDD post-action.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.models import Corpus
from tests.conftest import extract_csrf, fresh_slug

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers locaux
# ─────────────────────────────────────────────────────────────────────────────
async def _create_corpus_via_api(
    admin_client: AsyncClient, csrf: str, name: str, description: str = ""
) -> str:
    """POST /web/admin/corpus → renvoie le HTML du row créé. Retourne le HTML."""
    r = await admin_client.post(
        "/web/admin/corpus",
        data={"display_name": name, "description": description, "csrf_token": csrf},
    )
    assert r.status_code == 200, f"create failed: {r.status_code} — {r.text[:300]}"
    return r.text


async def _get_corpus_by_display_name(name: str) -> Corpus | None:
    async with async_session_maker() as s:
        res = await s.execute(select(Corpus).where(Corpus.display_name == name))
        return res.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
#  Auth gate
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_redirected_to_login(client: AsyncClient) -> None:
    r = await client.get("/web/admin/corpus")
    assert r.status_code == 303
    assert r.headers["location"] == "/web/login"


# ─────────────────────────────────────────────────────────────────────────────
#  Liste
# ─────────────────────────────────────────────────────────────────────────────
async def test_list_returns_200(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/corpus")
    assert r.status_code == 200
    assert "Corpus" in r.text
    # La table existe même quand vide (header rendu)
    assert 'id="corpus-table-body"' in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Création
# ─────────────────────────────────────────────────────────────────────────────
async def test_create_minimal(admin_client: AsyncClient, admin_csrf: str) -> None:
    name = f"Pytest Corpus {fresh_slug()}"
    html = await _create_corpus_via_api(admin_client, admin_csrf, name)
    assert name in html

    c = await _get_corpus_by_display_name(name)
    assert c is not None
    assert c.is_active is True
    assert c.name.startswith("pytest-")


async def test_create_with_description(admin_client: AsyncClient, admin_csrf: str) -> None:
    name = f"Pytest Corpus {fresh_slug()}"
    desc = "Description test"
    html = await _create_corpus_via_api(admin_client, admin_csrf, name, desc)
    assert desc in html


async def test_create_slug_collision_disambiguates(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Deux POST avec exactement le même nom → slugs distincts (suffixe -2)."""
    name = f"Pytest Twin {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    await _create_corpus_via_api(admin_client, admin_csrf, name)

    async with async_session_maker() as s:
        res = await s.execute(select(Corpus).where(Corpus.display_name == name))
        rows = list(res.scalars().all())
    assert len(rows) == 2
    slugs = {r.name for r in rows}
    assert len(slugs) == 2  # pas de doublon


async def test_create_empty_name_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/corpus",
        data={"display_name": "   ", "description": "", "csrf_token": admin_csrf},
    )
    assert r.status_code == 400


async def test_create_invalid_csrf_returns_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/corpus",
        data={"display_name": "x", "csrf_token": "wrong"},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  Edit / cancel partials
# ─────────────────────────────────────────────────────────────────────────────
async def test_edit_form_returns_edit_partial(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Edit {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    c = await _get_corpus_by_display_name(name)
    assert c is not None

    r = await admin_client.get(f"/web/admin/corpus/{c.id}/edit")
    assert r.status_code == 200
    assert 'admin-corpus-row--editing' in r.text
    assert f'id="corpus-{c.id}"' in r.text


async def test_cancel_returns_read_partial(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Cancel {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    c = await _get_corpus_by_display_name(name)
    assert c is not None

    r = await admin_client.post(f"/web/admin/corpus/{c.id}/cancel")
    assert r.status_code == 200
    assert 'admin-corpus-row--editing' not in r.text
    assert name in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Update
# ─────────────────────────────────────────────────────────────────────────────
async def test_update_changes_fields(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Upd {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    c = await _get_corpus_by_display_name(name)
    assert c is not None

    new_name = name + " (modifié)"
    r = await admin_client.patch(
        f"/web/admin/corpus/{c.id}",
        data={
            "display_name": new_name,
            "description": "nouvelle desc",
            "is_active": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert new_name in r.text

    async with async_session_maker() as s:
        refreshed = await s.get(Corpus, c.id)
        assert refreshed is not None
        assert refreshed.display_name == new_name
        assert refreshed.description == "nouvelle desc"
        assert refreshed.is_active is True


async def test_update_unchecked_active_means_false(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Quand la checkbox is_active n'est pas envoyée, le corpus passe inactif."""
    name = f"Pytest Inact {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    c = await _get_corpus_by_display_name(name)
    assert c is not None and c.is_active is True

    r = await admin_client.patch(
        f"/web/admin/corpus/{c.id}",
        data={
            "display_name": name,
            "description": "",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        refreshed = await s.get(Corpus, c.id)
        assert refreshed is not None
        assert refreshed.is_active is False


async def test_update_empty_name_keeps_edit_with_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Empty {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    c = await _get_corpus_by_display_name(name)
    assert c is not None

    r = await admin_client.patch(
        f"/web/admin/corpus/{c.id}",
        data={"display_name": "  ", "description": "", "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert 'admin-corpus-row--editing' in r.text
    assert "Le nom est requis" in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Delete
# ─────────────────────────────────────────────────────────────────────────────
async def test_delete_ok(admin_client: AsyncClient, admin_csrf: str) -> None:
    name = f"Pytest Del {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    c = await _get_corpus_by_display_name(name)
    assert c is not None

    r = await admin_client.delete(f"/web/admin/corpus/{c.id}")
    assert r.status_code == 200

    async with async_session_maker() as s:
        gone = await s.get(Corpus, c.id)
        assert gone is None


async def test_delete_unknown_returns_404(admin_client: AsyncClient) -> None:
    import uuid as _uuid

    r = await admin_client.delete(f"/web/admin/corpus/{_uuid.uuid4()}")
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  Détail
# ─────────────────────────────────────────────────────────────────────────────
async def test_detail_renders_when_exists(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Detail {fresh_slug()}"
    await _create_corpus_via_api(admin_client, admin_csrf, name)
    c = await _get_corpus_by_display_name(name)
    assert c is not None

    r = await admin_client.get(f"/web/admin/corpus/{c.id}")
    assert r.status_code == 200
    assert name in r.text
    # Sections rendered
    assert "Documents" in r.text
    assert "Sources" in r.text
    assert "Bibliothèques" in r.text
