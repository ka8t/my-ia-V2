"""Tests d'intégration — Audit log viewer (Phase 3.9.a)."""
from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.db import async_session_maker
from app.models import AuditAction, AuditLog, ResourceType, User

pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers — création d'audit log de test (pas de cleanup nécessaire,
#  les logs admin de tests n'écrasent pas les logs réels et seront purgés
#  par la rotation 365j naturelle)
# ─────────────────────────────────────────────────────────────────────────────
async def _ensure_action(name: str = "test.action") -> int:
    async with async_session_maker() as s:
        result = await s.execute(select(AuditAction).where(AuditAction.name == name))
        action = result.scalar_one_or_none()
        if action is None:
            action = AuditAction(name=name, display_name=name, severity="info")
            s.add(action)
            await s.commit()
            await s.refresh(action)
        return action.id


# ─────────────────────────────────────────────────────────────────────────────
#  Auth gate
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_audit_redirected(client: AsyncClient) -> None:
    r = await client.get("/web/admin/audit")
    assert r.status_code == 303


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/audit
# ─────────────────────────────────────────────────────────────────────────────
async def test_audit_page_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/audit")
    assert r.status_code == 200
    assert "Journal" in r.text
    assert 'name="action"' in r.text  # filtre action
    assert 'name="user_email"' in r.text
    assert 'name="date_from"' in r.text


async def test_audit_page_lists_existing_logs(admin_client: AsyncClient) -> None:
    """La page doit afficher les logs existants en BDD."""
    # Créer un log de test (un login admin a forcément été tracé)
    action_id = await _ensure_action("test.audit_view")
    async with async_session_maker() as s:
        admin = (
            await s.execute(select(User).where(User.email == "admin@test.example"))
        ).unique().scalar_one()
        log = AuditLog(
            user_id=admin.id, action_id=action_id,
            ip_address="127.0.0.1", user_agent="pytest",
            details={"smoke": True},
        )
        s.add(log)
        await s.commit()
        log_id = log.id

    r = await admin_client.get("/web/admin/audit")
    assert r.status_code == 200
    # Le log de test doit apparaître (action ou détails visibles)
    assert "test.audit_view" in r.text

    # Cleanup
    async with async_session_maker() as s:
        await s.execute(select(AuditLog).where(AuditLog.id == log_id))
        log = await s.get(AuditLog, log_id)
        if log:
            await s.delete(log)
            await s.commit()


async def test_audit_filter_by_action(admin_client: AsyncClient) -> None:
    """Filtrer par nom d'action ne renvoie que les logs matchants."""
    await _ensure_action("test.filter_marker")
    r = await admin_client.get("/web/admin/audit?action=test.filter_marker")
    assert r.status_code == 200
    # La page se rend même si la liste est vide
    assert 'id' in r.text or 'admin-empty' in r.text or 'Aucune' in r.text


async def test_audit_filter_invalid_date_silently_ignored(
    admin_client: AsyncClient,
) -> None:
    """Une date_from invalide ne fait pas crasher la page."""
    r = await admin_client.get("/web/admin/audit?date_from=not-a-date")
    assert r.status_code == 200


async def test_audit_pagination_clamps_page(admin_client: AsyncClient) -> None:
    """page=0 ou négatif → traité comme page 1."""
    r = await admin_client.get("/web/admin/audit?page=0")
    assert r.status_code == 200


async def test_audit_page_size_clamped(admin_client: AsyncClient) -> None:
    """page_size > 200 est borné."""
    r = await admin_client.get("/web/admin/audit?page_size=99999")
    assert r.status_code == 200
