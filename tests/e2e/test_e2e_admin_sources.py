"""E2E — parcours admin sources (Phase 3.7.b Vagues 1, 2.5, 2.6).

Vérifie dans un vrai navigateur :
- Création source via modal Alpine
- Health-check : POST + swap row avec nouvelle valeur santé
- Page config technique : édition JSON, validation par type, sauvegarde
"""
from __future__ import annotations

import pytest
from playwright.async_api import Page, expect

from tests.e2e.conftest import fresh_e2e_slug

pytestmark = pytest.mark.asyncio


async def test_create_source_via_modal(admin_page: Page) -> None:
    """Liste sources, modal de création, submit, voit la nouvelle ligne."""
    await admin_page.goto("/web/admin/sources")
    await admin_page.wait_for_selector('#sources-table-body', timeout=3000)

    await admin_page.click('button:has-text("Nouvelle source")')

    name_input = admin_page.locator('input[name="display_name"]')
    await expect(name_input).to_be_visible(timeout=2000)

    name = f"E2E Source {fresh_e2e_slug()}"
    await name_input.fill(name)
    # Le select source_type est rendu — choisir "web" (default)
    await admin_page.select_option('select[name="source_type"]', "web")
    await admin_page.click('button[type="submit"]:has-text("Créer")')

    # Le row apparaît en début de table (afterbegin)
    await expect(admin_page.locator(f'text={name}').first).to_be_visible(timeout=3000)


async def test_health_check_updates_row(admin_page: Page) -> None:
    """Health-check sur une source créée : la requête POST passe et le row est swapé."""
    # Créer une source web
    await admin_page.goto("/web/admin/sources")
    await admin_page.wait_for_selector('#sources-table-body')
    await admin_page.click('button:has-text("Nouvelle source")')
    name = f"E2E Health {fresh_e2e_slug()}"
    await admin_page.fill('input[name="display_name"]', name)
    await admin_page.select_option('select[name="source_type"]', "web")
    await admin_page.click('button[type="submit"]:has-text("Créer")')

    target_row = admin_page.locator(f'text={name}').first
    await expect(target_row).to_be_visible(timeout=3000)

    # Cliquer sur le bouton "Sonder maintenant" de la même ligne
    row_id = await target_row.evaluate("el => el.closest('.admin-source-row').id")
    health_btn = admin_page.locator(f'#{row_id} form[hx-post*="health-check"] button')

    async with admin_page.expect_response(
        lambda r: "/health-check" in r.url and r.status == 200
    ):
        await health_btn.click()

    # Le row est swapé — il contient maintenant un statut santé "healthy" ou "unhealthy"
    refreshed_row = admin_page.locator(f'#{row_id}')
    await expect(refreshed_row).to_contain_text(
        "healthy", timeout=5000, ignore_case=True
    )


async def test_source_config_page_save_valid_web(admin_page: Page) -> None:
    """Navigation vers /web/admin/sources/{id}/config, édition JSON valide, sauvegarde."""
    # Créer la source d'abord
    await admin_page.goto("/web/admin/sources")
    await admin_page.wait_for_selector('#sources-table-body')
    await admin_page.click('button:has-text("Nouvelle source")')
    name = f"E2E Cfg {fresh_e2e_slug()}"
    await admin_page.fill('input[name="display_name"]', name)
    await admin_page.select_option('select[name="source_type"]', "web")
    await admin_page.click('button[type="submit"]:has-text("Créer")')

    # Cliquer sur le lien "Configuration technique"
    target_row = admin_page.locator(f'text={name}').first
    await expect(target_row).to_be_visible(timeout=3000)
    row_id = await target_row.evaluate("el => el.closest('.admin-source-row').id")

    config_link = admin_page.locator(f'#{row_id} a[href*="/config"]')
    await config_link.click()

    # Page config chargée
    await admin_page.wait_for_selector('textarea[name="config_text"]')
    # Tableau d'aide rendu pour le type web
    await expect(admin_page.locator(".admin-config-fields")).to_be_visible()
    await expect(admin_page.locator("text=duckduckgo, google")).to_be_visible()

    # Remplir avec une config web valide et soumettre
    await admin_page.fill(
        'textarea[name="config_text"]',
        '{"provider": "duckduckgo", "language": "fr"}',
    )
    await admin_page.click('button[type="submit"]:has-text("Enregistrer")')

    # Callout succès rendu
    await expect(admin_page.locator(".admin-callout--success")).to_contain_text(
        "Configuration enregistrée", timeout=3000
    )


async def test_source_config_invalid_json_shows_error(admin_page: Page) -> None:
    """JSON invalide → callout danger, page reste sur l'éditeur, pas de save."""
    await admin_page.goto("/web/admin/sources")
    await admin_page.wait_for_selector('#sources-table-body')
    await admin_page.click('button:has-text("Nouvelle source")')
    name = f"E2E Invalid {fresh_e2e_slug()}"
    await admin_page.fill('input[name="display_name"]', name)
    await admin_page.select_option('select[name="source_type"]', "web")
    await admin_page.click('button[type="submit"]:has-text("Créer")')

    target_row = admin_page.locator(f'text={name}').first
    await expect(target_row).to_be_visible(timeout=3000)
    row_id = await target_row.evaluate("el => el.closest('.admin-source-row').id")
    await admin_page.locator(f'#{row_id} a[href*="/config"]').click()
    await admin_page.wait_for_selector('textarea[name="config_text"]')

    await admin_page.fill('textarea[name="config_text"]', "not valid {")
    await admin_page.click('button[type="submit"]:has-text("Enregistrer")')

    await expect(admin_page.locator(".admin-callout--danger")).to_contain_text(
        "JSON invalide", timeout=3000
    )
