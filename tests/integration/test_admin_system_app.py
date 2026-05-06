"""Tests d'intégration — Pages admin Système Application (Phase 3.8.e).

Couvre Geo, Chat, Appearance, Conversation Modes (CRUD).
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.db import async_session_maker
from app.features.system.service import SystemConfigService
from app.models import ConversationMode, SystemConfig
from app.web.admin_system import APPEARANCE_KEYS, CHAT_KEYS, GEO_KEYS

pytestmark = pytest.mark.asyncio

ALL_KEYS = GEO_KEYS + CHAT_KEYS + APPEARANCE_KEYS
E2E_MODE_PREFIX = "pytestmode_"


@pytest.fixture(autouse=True)
async def _snapshot_app_keys():
    async with async_session_maker() as s:
        rows = (
            await s.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_KEYS)))
        ).scalars().all()
        snapshot = {r.key: (r.value, r.value_type) for r in rows}
    yield
    async with async_session_maker() as s:
        rows = (
            await s.execute(select(SystemConfig).where(SystemConfig.key.in_(ALL_KEYS)))
        ).scalars().all()
        for r in rows:
            if r.key in snapshot:
                r.value, r.value_type = snapshot[r.key]
            else:
                await s.delete(r)
        # Cleanup des modes de test
        await s.execute(
            delete(ConversationMode).where(ConversationMode.name.like(f"{E2E_MODE_PREFIX}%"))
        )
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Geo
# ─────────────────────────────────────────────────────────────────────────────
async def test_geo_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/geo")
    assert r.status_code == 200
    assert "geo.default_country" in r.text


async def test_geo_post_uppercases_code(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/geo",
        data={
            "default_country": "us",
            "allow_change": "true", "require_city": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("geo.default_country") == "US"
        assert await svc.get("geo.require_city") is True
        assert await svc.get("geo.auto_import") is False


async def test_geo_invalid_country_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/geo",
        data={"default_country": "FR1", "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "Code pays invalide" in r.text


async def test_geo_csrf_invalid_400(admin_client: AsyncClient) -> None:
    r = await admin_client.post(
        "/web/admin/system/geo", data={"default_country": "FR", "csrf_token": "wrong"}
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  Chat
# ─────────────────────────────────────────────────────────────────────────────
async def test_chat_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/chat")
    assert r.status_code == 200
    assert "chat.history_max_tokens" in r.text


async def test_chat_post_saves(admin_client: AsyncClient, admin_csrf: str) -> None:
    r = await admin_client.post(
        "/web/admin/system/chat",
        data={
            "history_enabled": "true",
            "history_max_tokens": "8192",
            "history_max_turns": "10",
            "rag_reinjection_enabled": "true",
            "summary_enabled": "true",
            "summary_max_tokens": "1000",
            "summary_trigger_messages": "20",
            "topic_detection_enabled": "true",
            "topic_similarity_threshold": "0.4",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("chat.history_max_tokens") == 8192
        assert await svc.get("chat.history_max_turns") == 10
        assert await svc.get("chat.summary_trigger_messages") == 20
        assert await svc.get("chat.topic_similarity_threshold") == 0.4


async def test_chat_threshold_out_of_range_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/chat",
        data={
            "history_enabled": "true",
            "history_max_tokens": "4096", "history_max_turns": "5",
            "summary_max_tokens": "500", "summary_trigger_messages": "10",
            "topic_similarity_threshold": "1.5",  # > 1.0
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "topic_similarity_threshold" in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  Appearance
# ─────────────────────────────────────────────────────────────────────────────
async def test_appearance_get_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/appearance")
    assert r.status_code == 200
    assert "app.name" in r.text


async def test_appearance_post_saves(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/appearance",
        data={
            "name": "MY-IA Custom",
            "title": "MY-IA Custom Assistant",
            "description": "Une description test",
            "icon": "🦊",
            "name_prefix": "myia_custom",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        svc = SystemConfigService(s)
        assert await svc.get("app.name") == "MY-IA Custom"
        assert await svc.get("app.icon") == "🦊"
        assert await svc.get("app.name_prefix") == "myia_custom"


async def test_appearance_empty_name_returns_error(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/appearance",
        data={
            "name": "  ",
            "title": "x", "description": "", "icon": "🤖",
            "name_prefix": "x",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    assert "requis" in r.text


async def test_appearance_empty_icon_uses_default(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/appearance",
        data={
            "name": "X", "title": "X", "description": "",
            "icon": "",  # vide → 🤖 default
            "name_prefix": "x",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        assert await SystemConfigService(s).get("app.icon") == "🤖"


# ─────────────────────────────────────────────────────────────────────────────
#  Conversation Modes (CRUD)
# ─────────────────────────────────────────────────────────────────────────────
async def test_modes_get_lists(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/system/modes")
    assert r.status_code == 200
    assert "Modes de conversation" in r.text


async def test_modes_create_ok(admin_client: AsyncClient, admin_csrf: str) -> None:
    name = f"{E2E_MODE_PREFIX}custom1"
    r = await admin_client.post(
        "/web/admin/system/modes",
        data={
            "name": name,
            "display_name": "Custom 1",
            "description": "Test mode",
            "system_prompt": "Tu es un assistant test.",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        result = await s.execute(
            select(ConversationMode).where(ConversationMode.name == name)
        )
        mode = result.scalar_one()
        assert mode.display_name == "Custom 1"
        assert mode.system_prompt == "Tu es un assistant test."


async def test_modes_create_duplicate_returns_409(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    name = f"{E2E_MODE_PREFIX}dup"
    await admin_client.post(
        "/web/admin/system/modes",
        data={
            "name": name, "display_name": "Dup", "description": "",
            "system_prompt": "", "csrf_token": admin_csrf,
        },
    )
    r = await admin_client.post(
        "/web/admin/system/modes",
        data={
            "name": name, "display_name": "Dup2", "description": "",
            "system_prompt": "", "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 409
    assert "existe déjà" in r.text


async def test_modes_create_empty_name_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/system/modes",
        data={
            "name": "  ", "display_name": "X", "description": "",
            "system_prompt": "", "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400
    assert "requis" in r.text


async def test_modes_delete_ok(admin_client: AsyncClient, admin_csrf: str) -> None:
    name = f"{E2E_MODE_PREFIX}todelete"
    await admin_client.post(
        "/web/admin/system/modes",
        data={
            "name": name, "display_name": "Del", "description": "",
            "system_prompt": "", "csrf_token": admin_csrf,
        },
    )
    async with async_session_maker() as s:
        mode = (
            await s.execute(select(ConversationMode).where(ConversationMode.name == name))
        ).scalar_one()

    r = await admin_client.delete(f"/web/admin/system/modes/{mode.id}")
    assert r.status_code == 200

    async with async_session_maker() as s:
        result = await s.execute(
            select(ConversationMode).where(ConversationMode.name == name)
        )
        assert result.scalar_one_or_none() is None


async def test_modes_delete_unknown_returns_404(admin_client: AsyncClient) -> None:
    r = await admin_client.delete("/web/admin/system/modes/999999")
    assert r.status_code == 404
