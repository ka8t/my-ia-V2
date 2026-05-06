"""Tests d'intégration — Validation workflow (Phase 3.9.c)."""
from __future__ import annotations

import uuid as _uuid

import pytest
from fastapi_users.password import PasswordHelper
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.models import ApprovalStatus, User

pytestmark = pytest.mark.asyncio

PYTEST_USER_PREFIX = "pytestval-"


# ─────────────────────────────────────────────────────────────────────────────
#  Cleanup autouse — supprime les users de test
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
async def _cleanup_pending_users():
    yield
    async with async_session_maker() as s:
        result = await s.execute(
            select(User).where(User.email.like(f"{PYTEST_USER_PREFIX}%"))
        )
        for u in result.unique().scalars().all():
            await s.delete(u)
        await s.commit()


async def _create_pending_user(email_suffix: str = "") -> User:
    suffix = email_suffix or _uuid.uuid4().hex[:6]
    async with async_session_maker() as s:
        u = User(
            email=f"{PYTEST_USER_PREFIX}{suffix}@example.com",
            username=f"{PYTEST_USER_PREFIX}{suffix}",
            hashed_password=PasswordHelper().hash("Test12345!"),
            is_active=True,
            is_superuser=False,
            is_verified=False,
            approval_status=ApprovalStatus.PENDING,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


# ─────────────────────────────────────────────────────────────────────────────
#  Auth gate
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_validation_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/validation")
    assert r.status_code == 303


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/validation
# ─────────────────────────────────────────────────────────────────────────────
async def test_validation_page_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/validation")
    assert r.status_code == 200
    assert "Validation" in r.text


async def test_validation_page_lists_pending(admin_client: AsyncClient) -> None:
    user1 = await _create_pending_user("a")
    user2 = await _create_pending_user("b")
    r = await admin_client.get("/web/admin/validation")
    assert r.status_code == 200
    assert user1.email in r.text
    assert user2.email in r.text


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/validation/bulk-approve
# ─────────────────────────────────────────────────────────────────────────────
async def test_bulk_approve_changes_status(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    u = await _create_pending_user("approve")
    r = await admin_client.post(
        "/web/admin/validation/bulk-approve",
        data={"csrf_token": admin_csrf, "user_ids": str(u.id)},
    )
    assert r.status_code == 303

    async with async_session_maker() as s:
        refreshed = await s.get(User, u.id)
        assert refreshed.approval_status == ApprovalStatus.APPROVED


async def test_bulk_approve_no_selection_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/validation/bulk-approve",
        data={"csrf_token": admin_csrf},
    )
    assert r.status_code == 400


async def test_bulk_approve_csrf_invalid_400(admin_client: AsyncClient) -> None:
    u = await _create_pending_user("csrf")
    r = await admin_client.post(
        "/web/admin/validation/bulk-approve",
        data={"csrf_token": "wrong", "user_ids": str(u.id)},
    )
    assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/validation/bulk-reject
# ─────────────────────────────────────────────────────────────────────────────
async def test_bulk_reject_changes_status_with_reason(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    u = await _create_pending_user("reject")
    r = await admin_client.post(
        "/web/admin/validation/bulk-reject",
        data={
            "csrf_token": admin_csrf,
            "user_ids": str(u.id),
            "reason": "Domaine email non autorisé",
        },
    )
    assert r.status_code == 303

    async with async_session_maker() as s:
        refreshed = await s.get(User, u.id)
        assert refreshed.approval_status == ApprovalStatus.REJECTED
        assert refreshed.rejection_reason == "Domaine email non autorisé"


async def test_bulk_reject_no_selection_returns_400(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.post(
        "/web/admin/validation/bulk-reject",
        data={"csrf_token": admin_csrf, "reason": "test"},
    )
    assert r.status_code == 400
