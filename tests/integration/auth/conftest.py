"""Fixtures spécifiques tests Auth (P1.8.c).

Réutilise le conftest racine V2 (``async_session_maker``, ASGI app), ajoute
juste les fixtures spécifiques aux scénarios d'inscription/login.
"""
from __future__ import annotations

import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_maker
from app.main import app
from app.models import User


# ─────────────────────────────────────────────────────────────────────────────
#  Client asynchrone et session DB
#  (reprend le pattern V2 racine, alias pour compat avec tests V1 portés)
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Alias V1 → utilise le conftest V2 ASGITransport sur app principal."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=False
    ) as c:
        yield c


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Session DB pour les fixtures auth (création users de test)."""
    async with async_session_maker() as s:
        yield s


# ─────────────────────────────────────────────────────────────────────────────
#  Données d'inscription
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def unique_email() -> str:
    return f"pytest_auth_{uuid.uuid4().hex[:8]}@test.example"


@pytest.fixture
def unique_username() -> str:
    return f"pytest_auth_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def registration_data(unique_email: str, unique_username: str) -> dict:
    """Données d'inscription standard (UserCreate complet)."""
    return {
        "email": unique_email,
        "password": "Test1234!",
        "username": unique_username,
        "first_name": "Test",
        "last_name": "User",
        "phone": "+33612345678",
        "address_line1": "123 Rue de Test",
        "country_code": "FR",
    }


@pytest.fixture
def debug_registration_data() -> dict:
    """Données pour le mode debug (champs requis)."""
    suffix = uuid.uuid4().hex[:8]
    return {
        "email": f"pytest_debug_{suffix}@test.example",
        "password": "Test1234!",
        "username": f"pytest_debug_{suffix}",
        "first_name": "Debug",
        "last_name": "User",
        "phone": "+33612345678",
        "address_line1": "123 Rue Debug",
        "country_code": "FR",
    }


@pytest.fixture
def weak_password_data(unique_email: str, unique_username: str) -> dict:
    return {
        "email": unique_email,
        "password": "weak",
        "username": unique_username,
        "first_name": "Weak",
        "last_name": "Password",
        "phone": "+33612345678",
        "address_line1": "123 Rue Weak",
        "country_code": "FR",
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Mode debug runtime (parité V1 helper)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def enable_debug_mode():
    """Active debug_endpoints_enabled via runtime overrides."""
    from app.features.admin.config.service import _runtime_overrides
    _runtime_overrides["debug_endpoints_enabled"] = True
    yield
    _runtime_overrides.pop("debug_endpoints_enabled", None)


@pytest.fixture
def disable_debug_mode():
    from app.features.admin.config.service import _runtime_overrides
    _runtime_overrides["debug_endpoints_enabled"] = False
    yield
    _runtime_overrides.pop("debug_endpoints_enabled", None)


# ─────────────────────────────────────────────────────────────────────────────
#  Existing user (pour les tests de duplication)
#  V1 utilisait passlib.bcrypt ; V2 utilise pwdlib (fastapi-users PasswordHelper).
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def existing_user(db_session: AsyncSession) -> AsyncGenerator[User, None]:
    """Crée un user en BDD pour tester les cas de duplication, cleanup post-test."""
    from fastapi_users.password import PasswordHelper

    from app.models import ApprovalStatus

    pwd_helper = PasswordHelper()
    suffix = uuid.uuid4().hex[:8]
    user = User(
        email=f"pytest_existing_{suffix}@test.example",
        username=f"pytest_existing_{suffix}",
        hashed_password=pwd_helper.hash("Test1234!"),
        role_id=2,
        is_active=True,
        is_verified=False,
        is_superuser=False,
        approval_status=ApprovalStatus.PENDING,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    # Cleanup
    async with async_session_maker() as s:
        await s.execute(delete(User).where(User.id == user.id))
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  pending_user / rejected_user / approved_user (parité V1 conftest)
# ─────────────────────────────────────────────────────────────────────────────
async def _create_status_user(
    db_session: AsyncSession, status_value: str, prefix: str
) -> User:
    from datetime import datetime, timezone

    from fastapi_users.password import PasswordHelper

    from app.models import ApprovalStatus

    pwd_helper = PasswordHelper()
    suffix = uuid.uuid4().hex[:8]
    status_enum = ApprovalStatus(status_value)
    user = User(
        email=f"pytest_{prefix}_{suffix}@test.example",
        username=f"pytest_{prefix}_{suffix}",
        hashed_password=pwd_helper.hash("Test1234!"),
        role_id=2,
        is_active=True,
        is_verified=True,
        is_superuser=False,
        approval_status=status_enum,
        approved_at=datetime.now(timezone.utc) if status_value == "approved" else None,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def pending_user(db_session: AsyncSession) -> AsyncGenerator[User, None]:
    user = await _create_status_user(db_session, "pending", "pending")
    yield user


@pytest_asyncio.fixture
async def rejected_user(db_session: AsyncSession) -> AsyncGenerator[User, None]:
    user = await _create_status_user(db_session, "rejected", "rejected")
    yield user


@pytest_asyncio.fixture
async def approved_user(db_session: AsyncSession) -> AsyncGenerator[User, None]:
    user = await _create_status_user(db_session, "approved", "approved")
    yield user


@pytest_asyncio.fixture
async def test_roles(db_session: AsyncSession):
    """Vérifie que les rôles existent (sinon skip)."""
    from sqlalchemy import select

    from app.models import Role

    result = await db_session.execute(select(Role).order_by(Role.id))
    roles = list(result.scalars().all())
    if not roles:
        pytest.skip("Aucun rôle en BDD — exécuter les migrations.")
    return roles


# ─────────────────────────────────────────────────────────────────────────────
#  Cleanup global users créés par les tests auth (préfixe pytest_*)
# ─────────────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(autouse=True)
async def _cleanup_auth_test_users() -> AsyncGenerator[None, None]:
    yield
    async with async_session_maker() as s:
        for prefix in ("auth", "debug", "existing", "pending", "rejected", "approved"):
            await s.execute(
                delete(User).where(User.email.like(f"pytest_{prefix}_%@test.example"))
            )
        await s.commit()
