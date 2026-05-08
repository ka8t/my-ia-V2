"""Tests d'intégration — P1.4 archive/unarchive conversations admin.

Couvre les nouvelles routes :
  - POST /web/admin/conversations/{cid}/archive — toggle individuel
  - POST /web/admin/conversations/bulk-archive — action=archive|unarchive
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.db import async_session_maker
from app.models import Collection, Conversation, User
from tests.conftest import fresh_slug

pytestmark = pytest.mark.asyncio


@dataclass
class ConvSnapshot:
    id: uuid.UUID
    title: str
    archived_at: datetime | None


@pytest_asyncio.fixture
async def admin_conv(
    admin_client: AsyncClient,
) -> AsyncGenerator[ConvSnapshot, None]:
    """Crée une conversation appartenant à un user (admin pour tests),
    yield, puis supprime."""
    async with async_session_maker() as s:
        admin = (
            await s.execute(select(User).where(User.email == "admin@test.example"))
        ).unique().scalar_one()
        # Récupère la collection privée de admin (NOT NULL en BDD)
        col = (
            await s.execute(
                select(Collection).where(
                    Collection.owner_id == admin.id, Collection.type == "private"
                )
            )
        ).unique().scalar_one_or_none()
        if col is None:
            # Fallback : 1ère collection accessible
            col = (
                await s.execute(select(Collection).limit(1))
            ).unique().scalar_one()

        slug = fresh_slug()
        conv = Conversation(
            id=uuid.uuid4(),
            user_id=admin.id,
            collection_id=col.id,
            title=f"{slug}-conv",
        )
        s.add(conv)
        await s.commit()
        snap = ConvSnapshot(id=conv.id, title=conv.title, archived_at=None)
    yield snap
    async with async_session_maker() as s:
        await s.execute(delete(Conversation).where(Conversation.id == snap.id))
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Toggle individuel
# ─────────────────────────────────────────────────────────────────────────────
async def test_toggle_archive_individual_archives_then_unarchives(
    admin_client: AsyncClient, admin_csrf: str, admin_conv: ConvSnapshot
) -> None:
    # 1er appel : archive
    r = await admin_client.post(
        f"/web/admin/conversations/{admin_conv.id}/archive",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200, r.text[:300]
    assert "archivée" in r.text.lower()
    async with async_session_maker() as s:
        c = (await s.execute(select(Conversation).where(Conversation.id == admin_conv.id))).unique().scalar_one()
        assert c.archived_at is not None

    # 2e appel : désarchive
    r = await admin_client.post(
        f"/web/admin/conversations/{admin_conv.id}/archive",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    assert "désarchivée" in r.text.lower()
    async with async_session_maker() as s:
        c = (await s.execute(select(Conversation).where(Conversation.id == admin_conv.id))).unique().scalar_one()
        assert c.archived_at is None


async def test_toggle_archive_csrf_missing_400(
    admin_client: AsyncClient, admin_conv: ConvSnapshot
) -> None:
    r = await admin_client.post(
        f"/web/admin/conversations/{admin_conv.id}/archive",
        data={},
    )
    assert r.status_code == 400


async def test_toggle_archive_unknown_404(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        f"/web/admin/conversations/{uuid.uuid4()}/archive",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  Bulk archive / unarchive
# ─────────────────────────────────────────────────────────────────────────────
async def test_bulk_archive_action(
    admin_client: AsyncClient, admin_csrf: str, admin_conv: ConvSnapshot
) -> None:
    r = await admin_client.post(
        "/web/admin/conversations/bulk-archive",
        data={
            "conversation_ids": [str(admin_conv.id)],
            "action": "archive",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200, r.text[:300]
    assert "archivée" in r.text.lower()
    async with async_session_maker() as s:
        c = (await s.execute(select(Conversation).where(Conversation.id == admin_conv.id))).unique().scalar_one()
        assert c.archived_at is not None


async def test_bulk_archive_invalid_action_400(
    admin_client: AsyncClient, admin_csrf: str, admin_conv: ConvSnapshot
) -> None:
    r = await admin_client.post(
        "/web/admin/conversations/bulk-archive",
        data={
            "conversation_ids": [str(admin_conv.id)],
            "action": "noop",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 400


async def test_bulk_archive_csrf_missing_400(
    admin_client: AsyncClient, admin_conv: ConvSnapshot
) -> None:
    r = await admin_client.post(
        "/web/admin/conversations/bulk-archive",
        data={
            "conversation_ids": [str(admin_conv.id)],
            "action": "archive",
        },
    )
    assert r.status_code == 400


async def test_bulk_unarchive_only_affects_archived(
    admin_client: AsyncClient, admin_csrf: str, admin_conv: ConvSnapshot
) -> None:
    """unarchive sur une conv déjà active ne doit rien faire (count=0)."""
    r = await admin_client.post(
        "/web/admin/conversations/bulk-archive",
        data={
            "conversation_ids": [str(admin_conv.id)],
            "action": "unarchive",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    # 0 conv désarchivée car la conv était déjà active
    assert "0 conversation" in r.text.lower()


# ─────────────────────────────────────────────────────────────────────────────
#  Page admin/conversations contient les actions UI (régression visuelle)
# ─────────────────────────────────────────────────────────────────────────────
async def test_admin_conversations_page_shows_archive_button(
    admin_client: AsyncClient, admin_conv: ConvSnapshot
) -> None:
    r = await admin_client.get("/web/admin/conversations")
    assert r.status_code == 200
    body = r.text
    # Bouton archive individuel présent
    assert f"/web/admin/conversations/{admin_conv.id}/archive" in body
    # Bulk bar contient les options archive/unarchive/delete
    assert "Archiver" in body
    assert "Désarchiver" in body
    # Action bulk-archive en bind dynamique
    assert "/web/admin/conversations/bulk-archive" in body or "bulk-archive" in body


async def test_admin_logs_page_has_bulk_delete_ui(
    admin_client: AsyncClient,
) -> None:
    """Régression P1.7 : la page admin/logs expose désormais checkbox +
    barre d'actions bulk-delete."""
    r = await admin_client.get("/web/admin/logs")
    assert r.status_code == 200
    body = r.text
    # Checkbox de sélection sur chaque ligne (au moins le sélecteur all en header)
    assert "admin-logs-row__checkbox" in body or 'class="admin-logs-row admin-logs-row--with-select' in body
    # Barre d'actions bulk-delete
    assert "/web/admin/logs/bulk-delete" in body
