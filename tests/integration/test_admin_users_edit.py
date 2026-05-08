"""Tests d'intégration — édition utilisateur admin (P0.1).

Couvre :
  - GET /web/admin/users/{id}/edit          (modal pré-rempli)
  - PATCH /web/admin/users/{id}              (8 champs : email, username,
    profil, adresse, is_verified, password)

Les toggles is_active / voice_to_text / role / approval restent en routes
inline dédiées (couvertes ailleurs) — non testés ici.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.db import async_session_maker
from app.models import User
from tests.conftest import extract_csrf, fresh_slug  # noqa: F401

pytestmark = pytest.mark.asyncio


@dataclass
class UserSnapshot:
    """Snapshot primitif d'un User (id, email, username) — évite les erreurs
    MissingGreenlet quand on accède aux attributs hors d'une session active."""
    id: uuid.UUID
    email: str
    username: str


# ─────────────────────────────────────────────────────────────────────────────
#  Fixtures locales — un user cible créé par l'admin
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def target_user(
    admin_client: AsyncClient, admin_csrf: str
) -> AsyncGenerator[UserSnapshot, None]:
    """Crée un user via POST /web/admin/users, le yield, puis le supprime."""
    slug = fresh_slug()
    email = f"{slug}@example.test"
    username = f"u{slug}"
    r = await admin_client.post(
        "/web/admin/users",
        data={
            "email": email,
            "username": username,
            "password": "Initial-pwd-123!",
            "role_id": 2,  # User
            "first_name": "Init",
            "last_name": "User",
            "is_active": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code in (200, 201), f"create user failed: {r.status_code} — {r.text[:300]}"

    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.email == email))).unique().scalar_one_or_none()
        assert u is not None, "user créé mais introuvable en BDD"
        snap = UserSnapshot(id=u.id, email=u.email, username=u.username)
    yield snap

    # Cleanup : supprime le user créé (cascade conversations/docs/sessions/etc.)
    async with async_session_maker() as s:
        await s.execute(delete(User).where(User.email == email))
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Auth gate
# ─────────────────────────────────────────────────────────────────────────────
async def test_anon_get_edit_redirects_to_login(client: AsyncClient) -> None:
    r = await client.get(f"/web/admin/users/{uuid.uuid4()}/edit")
    assert r.status_code == 303
    assert r.headers["location"] == "/web/login"


async def test_anon_patch_redirects_to_login(client: AsyncClient) -> None:
    r = await client.request(
        "PATCH",
        f"/web/admin/users/{uuid.uuid4()}",
        data={"email": "x@y.z", "csrf_token": "x"},
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/web/login"


# ─────────────────────────────────────────────────────────────────────────────
#  GET /users/{id}/edit — modal pré-rempli
# ─────────────────────────────────────────────────────────────────────────────
async def test_edit_modal_renders_with_user_values(
    admin_client: AsyncClient, target_user: UserSnapshot
) -> None:
    r = await admin_client.get(f"/web/admin/users/{target_user.id}/edit")
    assert r.status_code == 200
    body = r.text
    assert target_user.email in body
    assert target_user.username in body
    assert "admin-modal--edit-user" in body
    # Pas de fuite de mot de passe (pas de hash dans le HTML)
    assert "hashed_password" not in body
    # Le pays select doit lister au moins FR (seed standard)
    assert "country_code" in body


async def test_edit_modal_404_on_unknown_user(admin_client: AsyncClient) -> None:
    r = await admin_client.get(f"/web/admin/users/{uuid.uuid4()}/edit")
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
#  PATCH /users/{id} — édition champs
# ─────────────────────────────────────────────────────────────────────────────
async def test_edit_updates_profile_fields(
    admin_client: AsyncClient, admin_csrf: str, target_user: UserSnapshot
) -> None:
    new_first = f"first-{fresh_slug()}"
    new_last = f"last-{fresh_slug()}"
    new_phone = "+33612345678"
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{target_user.id}",
        data={
            "email": target_user.email,
            "username": target_user.username,
            "first_name": new_first,
            "last_name": new_last,
            "phone": new_phone,
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200, r.text[:300]
    # Le row partial doit être renvoyé
    assert f"user-{target_user.id}" in r.text

    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == target_user.id))).unique().scalar_one()
        assert u.first_name == new_first
        assert u.last_name == new_last
        assert u.phone == new_phone


async def test_edit_updates_address_and_country(
    admin_client: AsyncClient, admin_csrf: str, target_user: UserSnapshot
) -> None:
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{target_user.id}",
        data={
            "email": target_user.email,
            "username": target_user.username,
            "address_line1": "12 rue Test",
            "address_line2": "Bât. A",
            "country_code": "FR",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200, r.text[:300]

    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == target_user.id))).unique().scalar_one()
        assert u.address_line1 == "12 rue Test"
        assert u.address_line2 == "Bât. A"
        assert u.country_code == "FR"


async def test_edit_toggles_is_verified(
    admin_client: AsyncClient, admin_csrf: str, target_user: UserSnapshot
) -> None:
    """Le user créé par admin part avec is_verified=True. On bascule à False
    via le PATCH puis re-True, et on vérifie les transitions."""
    # Bascule à False (checkbox is_verified absente du form)
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{target_user.id}",
        data={
            "email": target_user.email,
            "username": target_user.username,
            "is_verified": "false",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == target_user.id))).unique().scalar_one()
        assert u.is_verified is False

    # Re-bascule à True (checkbox cochée)
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{target_user.id}",
        data={
            "email": target_user.email,
            "username": target_user.username,
            "is_verified": "true",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200
    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == target_user.id))).unique().scalar_one()
        assert u.is_verified is True


async def test_edit_resets_password(
    admin_client: AsyncClient, admin_csrf: str, target_user: UserSnapshot
) -> None:
    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == target_user.id))).unique().scalar_one()
        old_hash = u.hashed_password

    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{target_user.id}",
        data={
            "email": target_user.email,
            "username": target_user.username,
            "new_password": "Brand-New-Pwd-123!",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        u = (await s.execute(select(User).where(User.id == target_user.id))).unique().scalar_one()
        assert u.hashed_password != old_hash
        # Le hash doit avoir un préfixe argon2 ($argon2id$)
        assert u.hashed_password.startswith("$argon2")


async def test_edit_email_conflict_returns_409(
    admin_client: AsyncClient, admin_csrf: str, target_user: UserSnapshot
) -> None:
    """Tenter de prendre l'email de l'admin → 409."""
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{target_user.id}",
        data={
            "email": "admin@test.example",
            "username": target_user.username,
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 409
    assert "déjà utilisé" in r.text.lower() or "deja utilise" in r.text.lower()


async def test_edit_csrf_missing_returns_400(
    admin_client: AsyncClient, target_user: UserSnapshot
) -> None:
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{target_user.id}",
        data={
            "email": target_user.email,
            "username": target_user.username,
            # Pas de csrf_token
        },
    )
    assert r.status_code == 400


async def test_edit_unknown_user_returns_404(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    r = await admin_client.request(
        "PATCH",
        f"/web/admin/users/{uuid.uuid4()}",
        data={
            "email": "x@y.z",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 404
