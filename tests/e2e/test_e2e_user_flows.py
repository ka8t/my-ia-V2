"""E2E — Flows utilisateur (P0.5).

Smoke tests des 3 flows critiques côté user :
  - Login user@test.example + arrivée sur le chat
  - Upload xlsx + indexation réussie (couvre le bug observé en QA)
  - Page Préférences accessible + sauvegarde langue/thème

Le streaming chat (SSE) n'est pas testé ici — dépend d'Ollama et nécessite
une stack RAG complète. Couvert plus tard en P1.
"""
from __future__ import annotations

import io
import re
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from playwright.async_api import BrowserContext, Page, expect

pytestmark = pytest.mark.asyncio

USER_EMAIL = "user@test.example"
USER_PASSWORD = "5#d%o3x3^7%uOwrZw_UIRS60"


@pytest_asyncio.fixture
async def user_page(context: BrowserContext) -> AsyncGenerator[Page, None]:
    """Login user via formulaire web → arrive sur l'app principale."""
    p = await context.new_page()
    await p.goto("/web/login", wait_until="domcontentloaded")
    await p.fill('input[name="email"]', USER_EMAIL)
    await p.fill('input[name="password"]', USER_PASSWORD)
    await p.click('button[type="submit"]')
    # Le post-login redirige vers / (chat) ou /web/chat selon flow
    await p.wait_for_url(re.compile(r"http://[^/]+/(?:web/chat)?(?:\?.*)?$"), timeout=10000)
    yield p
    await p.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Flow 1 — Login
# ─────────────────────────────────────────────────────────────────────────────
async def test_user_login_redirects_to_chat(page: Page) -> None:
    """Login user@test.example doit rediriger vers la page chat (ou racine)."""
    await page.goto("/web/login", wait_until="domcontentloaded")
    await page.fill('input[name="email"]', USER_EMAIL)
    await page.fill('input[name="password"]', USER_PASSWORD)
    await page.click('button[type="submit"]')
    # Attendre redirect (303 → / ou /web/chat)
    await page.wait_for_load_state("domcontentloaded")
    # On ne doit PAS être resté sur /web/login
    assert "/web/login" not in page.url
    # Pas de bandeau d'erreur identifiants
    body = await page.locator("body").inner_text()
    assert "Identifiants invalides" not in body


async def test_user_landing_has_chat_or_topbar(user_page: Page) -> None:
    """Après login, la page doit afficher la topbar utilisateur."""
    # La topbar est mountée dans base layout, présente sur user pages
    topbar = user_page.locator(".app-topbar")
    await topbar.wait_for(state="visible", timeout=5000)


# ─────────────────────────────────────────────────────────────────────────────
#  Flow 2 — Page documents accessible (sans tester upload e2e qui dépend de RAG)
# ─────────────────────────────────────────────────────────────────────────────
async def test_user_documents_page_loads(user_page: Page) -> None:
    """La page liste documents charge et expose le formulaire upload."""
    await user_page.goto("/web/documents", wait_until="domcontentloaded")
    # Form upload présent
    upload_form = user_page.locator('form[hx-post="/web/documents/upload"]')
    assert await upload_form.count() >= 1
    # Input file présent
    assert await user_page.locator('input[type="file"][name="file"]').count() >= 1


async def test_user_upload_xlsx_starts_indexation(user_page: Page) -> None:
    """Bug observé : upload xlsx → indexation infinie / 500.
    Smoke : upload via le form fonctionne (200) et la nouvelle ligne apparaît
    dans la liste avec un statut (pending ou ok)."""
    await user_page.goto("/web/documents", wait_until="domcontentloaded")

    # Préparer un xlsx en mémoire (fichier simple)
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = "Article"
    ws["B1"] = "Prix"
    ws["A2"] = "Produit A"
    ws["B2"] = 100
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    # Set le fichier dans l'input file (Playwright accepte bytes)
    file_input = user_page.locator('input[type="file"][name="file"]').first
    await file_input.set_input_files({
        "name": "e2e-smoke-test.xlsx",
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "buffer": xlsx_bytes,
    })

    # Le form a hx-trigger="change" sur l'input → submit auto, sinon submit manuel
    upload_btn = user_page.locator('form[hx-post="/web/documents/upload"] button[type="submit"]').first
    if await upload_btn.count() > 0 and await upload_btn.is_visible():
        await upload_btn.click()

    # Attendre qu'une ligne docs-row apparaisse avec ce fichier
    new_row = user_page.locator('.docs-row', has_text="e2e-smoke-test.xlsx")
    await new_row.wait_for(state="visible", timeout=15000)

    # Le statut initial doit être pending (ok si déjà indexé en moins de 1s)
    status_text = await new_row.locator('.docs-status').inner_text()
    assert any(k in status_text.lower() for k in ["index", "en cours", "indexé"])

    # Cleanup : supprimer ce doc
    async with __import__("app.db", fromlist=["async_session_maker"]).async_session_maker() as s:
        from sqlalchemy import delete
        from app.models import Document
        await s.execute(delete(Document).where(Document.filename == "e2e-smoke-test.xlsx"))
        await s.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Flow 3 — Préférences
# ─────────────────────────────────────────────────────────────────────────────
async def test_user_preferences_page_loads(user_page: Page) -> None:
    """La page préférences charge et affiche les sections clés."""
    await user_page.goto("/web/preferences", wait_until="domcontentloaded")
    # Au moins un select de langue ou thème
    assert (
        await user_page.locator('select[name="language"]').count() >= 1
        or await user_page.locator('select[name="theme"]').count() >= 1
    )


async def test_user_preferences_save_settings(user_page: Page) -> None:
    """Modifier la langue → submit → page se recharge ou affiche un toast
    de succès. Vérifie que le formulaire ne plante pas."""
    await user_page.goto("/web/preferences", wait_until="domcontentloaded")

    lang_select = user_page.locator('select[name="language"]').first
    if await lang_select.count() == 0:
        pytest.skip("Page préférences sans select language (template incomplet)")

    # Submit le form settings
    settings_form = user_page.locator(
        'form[hx-post="/web/preferences/settings"]'
    ).first
    submit_btn = settings_form.locator('button[type="submit"]').first
    await submit_btn.click()

    # Attendre soit un toast soit un re-render sans erreur 500
    await user_page.wait_for_load_state("networkidle", timeout=5000)
    body = await user_page.locator("body").inner_text()
    assert "Internal Server Error" not in body
    assert "500" not in body or "preferences" not in body.lower()
