"""Tests P2 (modes édition, geo toggle web, RAG dynamique, visibility upload)."""
from __future__ import annotations

import io
import re

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.db import async_session_maker
from app.models import ConversationMode, Country, Document, User

pytestmark = pytest.mark.asyncio

USER_EMAIL = "user@test.example"
USER_PASSWORD = "5#d%o3x3^7%uOwrZw_UIRS60"


@pytest_asyncio.fixture
async def user_client(client: AsyncClient) -> AsyncClient:
    r = await client.get("/web/login")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text).group(1)
    await client.post(
        "/web/login",
        data={"email": USER_EMAIL, "password": USER_PASSWORD, "csrf_token": csrf},
    )
    return client


# ─────────────────────────────────────────────────────────────────────────────
#  P2.1 — Édition mode (PATCH /web/admin/system/modes/{id})
# ─────────────────────────────────────────────────────────────────────────────
async def test_modes_page_exposes_edit_button(admin_client: AsyncClient) -> None:
    """Bug audit Z3 corrigé : le bouton Éditer doit exister sur chaque mode."""
    r = await admin_client.get("/web/admin/system/modes")
    assert r.status_code == 200
    # Présence d'un bouton qui déclenche editingId Alpine
    assert "editingId =" in r.text or 'x-on:click="editingId' in r.text
    # Présence du form hx-patch
    assert "hx-patch=\"/web/admin/system/modes/" in r.text


async def test_mode_edit_updates_display_name(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """PATCH du mode 1 → vérifier que display_name change en BDD."""
    async with async_session_maker() as s:
        mode = (await s.execute(select(ConversationMode).limit(1))).scalar_one()
        original_label = mode.display_name
        mode_id = mode.id

    new_label = f"{original_label} (test pytest)"
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/system/modes/{mode_id}",
        data={
            "display_name": new_label,
            "description": "edited",
            "system_prompt": "test prompt",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200, r.text[:300]

    async with async_session_maker() as s:
        m = (await s.execute(select(ConversationMode).where(ConversationMode.id == mode_id))).scalar_one()
        assert m.display_name == new_label
        assert m.description == "edited"
        # restaure
        m.display_name = original_label
        m.description = None
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  P2.2 — Geo countries toggle web
# ─────────────────────────────────────────────────────────────────────────────
async def test_geo_countries_list_renders(admin_client: AsyncClient) -> None:
    """La page Geo expose maintenant la liste des pays via partial."""
    r = await admin_client.get("/web/admin/system/geo/countries")
    assert r.status_code == 200
    body = r.text
    # Soit un message vide, soit au moins une row (FR seedée)
    assert "Aucun pays" in body or "admin-geo-country-row" in body


async def test_geo_toggle_returns_updated_list(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Toggle FR doit retourner le partial mis à jour avec FR sur l'autre statut."""
    # Vérifier que FR existe en BDD
    async with async_session_maker() as s:
        fr = (await s.execute(select(Country).where(Country.code == "FR"))).unique().scalar_one_or_none()
    if fr is None:
        pytest.skip("FR pas en BDD")

    initial = fr.is_active

    r = await admin_client.post(
        "/web/admin/system/geo/countries/FR/toggle",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    # La réponse doit être le partial mis à jour (contient une row FR)
    assert "admin-geo-country-row" in r.text or "Aucun pays" in r.text

    async with async_session_maker() as s:
        fr2 = (await s.execute(select(Country).where(Country.code == "FR"))).unique().scalar_one()
        assert fr2.is_active != initial
        # Restaure
        fr2.is_active = initial
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  P2.3 — RAG overrides modes dynamiques
# ─────────────────────────────────────────────────────────────────────────────
async def test_rag_overrides_renders_dynamic_modes(admin_client: AsyncClient) -> None:
    """La page RAG overrides doit lister une section par mode en BDD,
    pas hardcoder fast/full."""
    # Récupérer les modes BDD pour vérifier
    async with async_session_maker() as s:
        modes = (await s.execute(select(ConversationMode.name))).all()
    mode_names = [m for (m,) in modes]
    if not mode_names:
        pytest.skip("Aucun mode en BDD")

    r = await admin_client.get("/web/admin/system/rag/overrides")
    assert r.status_code == 200
    # Au moins un mode BDD doit être référencé dans le HTML
    found = any(f"rag.mode.{name}.top_k" in r.text for name in mode_names)
    assert found, f"aucun mode parmi {mode_names} rendu dans /rag/overrides"


# ─────────────────────────────────────────────────────────────────────────────
#  P2.6 — Visibilité explicite à l'upload (parité V1)
# ─────────────────────────────────────────────────────────────────────────────
async def test_upload_form_exposes_visibility_checkbox(
    user_client: AsyncClient,
) -> None:
    """Le form upload user doit exposer une checkbox visibility_public (P2.6)."""
    r = await user_client.get("/web/documents")
    assert r.status_code == 200
    assert 'name="visibility_public"' in r.text


async def test_upload_with_visibility_public_param_accepted(
    user_client: AsyncClient,
) -> None:
    """Upload avec visibility_public=true sur collection privée → reste private
    (sécurité). Sur collection publique → public si demandé."""
    r = await user_client.get("/web/documents")
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text).group(1)

    # Upload simple txt avec visibility_public=true mais sans collection_id
    # → doit fallback sur la collection privée user → visibility=private
    txt = b"Pytest content for P2.6 visibility test"
    r = await user_client.post(
        "/web/documents/upload",
        data={"csrf_token": csrf, "visibility_public": "true"},
        files={"file": ("e2e-p26-test.txt", txt, "text/plain")},
    )
    assert r.status_code == 200, r.text[:300]
    m = re.search(r'id="doc-([0-9a-f-]+)"', r.text)
    assert m, "doc id manquant dans la réponse"
    doc_id = m.group(1)

    async with async_session_maker() as s:
        doc = (await s.execute(select(Document).where(Document.id == doc_id))).unique().scalar_one()
        # Collection privée user → visibilité forcée à private
        assert doc.visibility == "private"
        await s.execute(delete(Document).where(Document.id == doc_id))
        await s.commit()
