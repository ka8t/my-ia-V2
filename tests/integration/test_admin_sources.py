"""Tests d'intégration — Admin Sources (Phase 3.7.b — Vague 1)."""
from __future__ import annotations

import uuid as _uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.models import ContextSource
from tests.conftest import extract_csrf, fresh_slug

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers locaux
# ─────────────────────────────────────────────────────────────────────────────
async def _create_source_via_api(
    admin_client: AsyncClient,
    csrf: str,
    name: str,
    source_type: str = "web",
    description: str = "",
) -> str:
    r = await admin_client.post(
        "/web/admin/sources",
        data={
            "display_name": name,
            "source_type": source_type,
            "description": description,
            "csrf_token": csrf,
        },
    )
    assert r.status_code == 200, f"create failed: {r.status_code} — {r.text[:300]}"
    return r.text


async def _get_source_by_display_name(name: str) -> ContextSource | None:
    async with async_session_maker() as s:
        res = await s.execute(
            select(ContextSource).where(ContextSource.display_name == name)
        )
        return res.scalar_one_or_none()


# ─────────────────────────────────────────────────────────────────────────────
#  Auth gate
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_redirected_to_login(client: AsyncClient) -> None:
    r = await client.get("/web/admin/sources")
    assert r.status_code == 303


# ─────────────────────────────────────────────────────────────────────────────
#  Liste + filtres
# ─────────────────────────────────────────────────────────────────────────────
async def test_list_returns_200(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/sources")
    assert r.status_code == 200
    assert 'id="sources-table-body"' in r.text


async def test_list_filter_by_type_web(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    web_name = f"Pytest Web {fresh_slug()}"
    api_name = f"Pytest Api {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, web_name, source_type="web")
    await _create_source_via_api(admin_client, admin_csrf, api_name, source_type="api")

    r = await admin_client.get("/web/admin/sources?source_type=web")
    assert r.status_code == 200
    assert web_name in r.text
    assert api_name not in r.text


async def test_list_filter_by_enabled_no(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Une source créée est désactivée par défaut → visible avec ?enabled=no."""
    name = f"Pytest Disabled {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)

    r = await admin_client.get("/web/admin/sources?enabled=no")
    assert r.status_code == 200
    assert name in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Création
# ─────────────────────────────────────────────────────────────────────────────
async def test_create_default_disabled(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Source {fresh_slug()}"
    html = await _create_source_via_api(admin_client, admin_csrf, name)
    assert name in html

    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None
    assert s_obj.is_enabled is False  # désactivée par défaut (Vague 1)
    assert s_obj.source_type == "web"
    assert s_obj.config == {}


async def test_create_invalid_type_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/sources",
        data={
            "display_name": "x",
            "source_type": "not-a-type",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400


async def test_create_empty_name_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/sources",
        data={"display_name": "  ", "source_type": "web", "csrf_token": admin_csrf},
    )
    assert r.status_code == 400


async def test_create_slug_collision_disambiguates(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Twin {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    await _create_source_via_api(admin_client, admin_csrf, name)

    async with async_session_maker() as session:
        res = await session.execute(
            select(ContextSource).where(ContextSource.display_name == name)
        )
        rows = list(res.scalars().all())
    assert len(rows) == 2
    assert len({r.name for r in rows}) == 2


# ─────────────────────────────────────────────────────────────────────────────
#  Toggle / Update
# ─────────────────────────────────────────────────────────────────────────────
async def test_toggle_flips_enabled(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Toggle {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None and s_obj.is_enabled is False

    r = await admin_client.post(
        f"/web/admin/sources/{s_obj.id}/toggle",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200

    async with async_session_maker() as session:
        refreshed = await session.get(ContextSource, s_obj.id)
        assert refreshed is not None
        assert refreshed.is_enabled is True


async def test_update_priority_clamped_high(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Prio {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None

    r = await admin_client.patch(
        f"/web/admin/sources/{s_obj.id}",
        data={
            "display_name": name,
            "description": "",
            "priority": "99999",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200

    async with async_session_maker() as session:
        refreshed = await session.get(ContextSource, s_obj.id)
        assert refreshed is not None
        assert refreshed.priority == 9999


async def test_update_priority_clamped_low(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest PrioLow {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None

    r = await admin_client.patch(
        f"/web/admin/sources/{s_obj.id}",
        data={
            "display_name": name,
            "description": "",
            "priority": "-50",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200

    async with async_session_maker() as session:
        refreshed = await session.get(ContextSource, s_obj.id)
        assert refreshed is not None
        assert refreshed.priority == 0


async def test_update_empty_name_keeps_edit_with_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest Empty {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None

    r = await admin_client.patch(
        f"/web/admin/sources/{s_obj.id}",
        data={"display_name": "  ", "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert 'admin-corpus-row--editing' in r.text  # même classe d'édition partagée
    assert "Le nom est requis" in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Edit / cancel
# ─────────────────────────────────────────────────────────────────────────────
async def test_edit_form_returns_edit_partial(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest EditS {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None

    r = await admin_client.get(f"/web/admin/sources/{s_obj.id}/edit")
    assert r.status_code == 200
    assert f'id="source-{s_obj.id}"' in r.text


async def test_cancel_returns_read_partial(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"Pytest CancelS {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None

    r = await admin_client.post(f"/web/admin/sources/{s_obj.id}/cancel")
    assert r.status_code == 200
    assert 'admin-corpus-row--editing' not in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Delete
# ─────────────────────────────────────────────────────────────────────────────
async def test_delete_ok(admin_client: AsyncClient, admin_csrf: str) -> None:
    name = f"Pytest DelS {fresh_slug()}"
    await _create_source_via_api(admin_client, admin_csrf, name)
    s_obj = await _get_source_by_display_name(name)
    assert s_obj is not None

    r = await admin_client.delete(f"/web/admin/sources/{s_obj.id}")
    assert r.status_code == 200

    async with async_session_maker() as session:
        gone = await session.get(ContextSource, s_obj.id)
        assert gone is None


async def test_delete_unknown_returns_404(admin_client: AsyncClient) -> None:
    r = await admin_client.delete(f"/web/admin/sources/{_uuid.uuid4()}")
    assert r.status_code == 404
