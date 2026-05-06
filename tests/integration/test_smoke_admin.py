"""Smoke test admin V2 — parcours bout-en-bout post Vague 2.

Vérifie que :
- Le CSS statique sert toutes les classes ajoutées (pas de 404 ni résidu).
- Les pages admin Vague 2 contiennent les ancres CSS clés (rendu non cassé).
- Les bibliothèques client (HTMX, Alpine) sont incluses dans les layouts.

Ce test est indicatif : il ne remplace pas une smoke navigation visuelle
dans un navigateur. Il garantit juste qu'une page n'est pas vide / ne 500
pas après refactor / ajout CSS.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import fresh_slug

pytestmark = pytest.mark.asyncio


REQUIRED_CSS_CLASSES = [
    # Vague 2.1-2.3 — détail corpus + relations
    ".admin-section__header",
    ".admin-cta--small",
    ".admin-bare-list--picker",
    ".admin-bare-list__inline-form",
    ".admin-bare-list__actions",
    ".admin-bare-list__item--editable",
    ".admin-modal__panel--wide",
    ".admin-modal__body",
    # Vague 2.4 — reindex
    ".admin-reindex",
    ".admin-reindex--placeholder",
    ".admin-reindex__head",
    ".admin-reindex__bar",
    ".admin-reindex__msg",
    ".admin-reindex__flash",
    ".admin-reindex__actions",
    # Vague 2.5 — health-check
    ".admin-action-form--inline",
    # Vague 2.6 — source config
    ".admin-callout--success",
    ".admin-callout--danger",
    ".admin-form__textarea--code",
    ".admin-form--stacked",
    ".admin-config-fields",
]


async def test_admin_login_redirects_to_admin_console(client: AsyncClient) -> None:
    """Login d'un superuser → redirige direct sur /web/admin (pas /)."""
    from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, extract_csrf

    r = await client.get("/web/login")
    csrf = extract_csrf(r.text)
    r = await client.post(
        "/web/login",
        data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "csrf_token": csrf},
    )
    assert r.status_code in (302, 303)
    assert r.headers["location"] == "/web/admin"


async def test_static_css_contains_all_wave2_classes(client: AsyncClient) -> None:
    """Le fichier components.css est servi et contient toutes les nouvelles classes."""
    r = await client.get("/static/css/components.css")
    assert r.status_code == 200, "components.css introuvable"
    css = r.text
    missing = [cls for cls in REQUIRED_CSS_CLASSES if cls not in css]
    assert not missing, f"Classes CSS manquantes : {missing}"


async def test_admin_corpus_list_renders(admin_client: AsyncClient) -> None:
    r = await admin_client.get("/web/admin/corpus")
    assert r.status_code == 200
    # Topbar admin présente
    assert "MY-IA · Admin" in r.text
    # Bouton CTA "Nouveau corpus"
    assert "Nouveau corpus" in r.text
    # HTMX chargé (script src htmx)
    assert "htmx" in r.text.lower()


async def test_admin_corpus_detail_full_page(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Crée un corpus, ouvre son détail, vérifie toutes les sections Vague 2."""
    name = f"Pytest Smoke {fresh_slug()}"
    r = await admin_client.post(
        "/web/admin/corpus",
        data={"display_name": name, "description": "smoke", "csrf_token": admin_csrf},
    )
    assert r.status_code == 200
    # Récup id depuis BDD
    from app.db import async_session_maker
    from app.models import Corpus
    from sqlalchemy import select

    async with async_session_maker() as s:
        c = (
            await s.execute(select(Corpus).where(Corpus.display_name == name))
        ).scalar_one()

    r = await admin_client.get(f"/web/admin/corpus/{c.id}")
    assert r.status_code == 200
    # Sections Vague 2
    assert "Réindexation" in r.text
    assert "Documents" in r.text
    assert "Sources" in r.text
    assert "Bibliothèques" in r.text
    # Modal pickers déclarés (Alpine)
    assert "x-data" in r.text
    # Lien CSS chargé
    assert "components.css" in r.text


async def test_admin_source_config_page_renders(
    admin_client: AsyncClient, admin_csrf: str
) -> None:
    """Crée une source web, ouvre la page config, vérifie l'éditeur JSON."""
    from app.db import async_session_maker
    from app.models import ContextSource
    from sqlalchemy import select

    name = f"Pytest Smoke {fresh_slug()}"
    r = await admin_client.post(
        "/web/admin/sources",
        data={
            "display_name": name,
            "source_type": "web",
            "description": "",
            "csrf_token": admin_csrf,
        },
    )
    assert r.status_code == 200

    async with async_session_maker() as s:
        src = (
            await s.execute(
                select(ContextSource).where(ContextSource.display_name == name)
            )
        ).scalar_one()

    r = await admin_client.get(f"/web/admin/sources/{src.id}/config")
    assert r.status_code == 200
    # Textarea code visible
    assert 'name="config_text"' in r.text
    assert 'admin-form__textarea--code' in r.text
    # Tableau d'aide rendu pour le type web
    assert 'admin-config-fields' in r.text
    assert 'duckduckgo' in r.text
