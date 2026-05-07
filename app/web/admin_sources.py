"""Web routes — Admin sources de contexte (Phase 3.7.b — Vagues 1, 2.5, 2.6).

CRUD + health-check + éditeur de config technique JSON par source_type.

Routes
------
GET    /web/admin/sources             — liste filtrable (type, enabled)
POST   /web/admin/sources             — create (champs simples : nom, type, description)
GET    /web/admin/sources/{id}/edit   — partial mode édition
POST   /web/admin/sources/{id}/cancel — sortir du mode édition
PATCH  /web/admin/sources/{id}        — update champs simples
POST   /web/admin/sources/{id}/toggle — toggle is_enabled
POST   /web/admin/sources/{id}/health-check — sonder la santé
DELETE /web/admin/sources/{id}        — delete

Config technique (Vague 2.6)
----------------------------
GET    /web/admin/sources/{id}/config — page éditeur JSON par type
POST   /web/admin/sources/{id}/config — validation + save (champs requis selon type)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import ApprovalStatus, ContextSource, SourceType, User
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/admin/sources", tags=["Web - Admin Sources"])
templates = make_templates(TEMPLATES_DIR)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _pending_users_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count(User.id)).where(User.approval_status == ApprovalStatus.PENDING)
    )
    return result.scalar_one() or 0


async def _admin_context(db: AsyncSession, request: Request, **extra) -> dict:
    pending = await _pending_users_count(db)
    return web_context(request, pending_users_count=pending, **extra)


_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = _SLUG_RE.sub("", value)
    return value[:100] or "source"


def _csrf_or_400(request: Request, csrf_token: str | None) -> HTMLResponse | None:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>",
            status_code=400,
        )
    return None


async def _get_source_or_404(db: AsyncSession, source_id: uuid.UUID) -> ContextSource | None:
    result = await db.execute(select(ContextSource).where(ContextSource.id == source_id))
    return result.scalar_one_or_none()


async def _render_row(
    request: Request,
    s: ContextSource,
    *,
    edit: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    template = (
        "partials/admin/source-row-edit.html" if edit else "partials/admin/source-row.html"
    )
    return templates.TemplateResponse(
        request,
        template,
        web_context(request, source=s, error=error, source_types=[t.value for t in SourceType]),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/sources — liste filtrée
# ─────────────────────────────────────────────────────────────────────────────
@router.get("", response_class=HTMLResponse)
async def admin_sources_list(
    request: Request,
    source_type: str | None = None,
    enabled: str | None = None,
    q: str | None = None,
    page: int = 1,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    page_size = 25
    query = select(ContextSource).order_by(ContextSource.priority, ContextSource.display_name)

    valid_types = {t.value for t in SourceType}
    if source_type in valid_types:
        query = query.where(ContextSource.source_type == source_type)
    if enabled in {"yes", "no"}:
        query = query.where(ContextSource.is_enabled == (enabled == "yes"))
    if q:
        like = f"%{q.strip()}%"
        query = query.where(
            (ContextSource.display_name.ilike(like)) | (ContextSource.name.ilike(like))
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    page = max(1, page)
    offset = (page - 1) * page_size
    result = await db.execute(query.offset(offset).limit(page_size))
    sources = list(result.scalars().all())
    total_pages = max(1, (total + page_size - 1) // page_size)

    return templates.TemplateResponse(
        request,
        "pages/admin/sources.html",
        await _admin_context(
            db,
            request,
            title="Sources de contexte",
            active_section="sources",
            user=user,
            sources=sources,
            source_types=sorted(valid_types),
            filter_type=source_type,
            filter_enabled=enabled,
            q=q or "",
            page=page,
            total=total,
            total_pages=total_pages,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/sources — create (champs simples seulement)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("", response_class=HTMLResponse)
async def admin_sources_create(
    request: Request,
    display_name: Annotated[str, Form()],
    source_type: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    name = (display_name or "").strip()
    if not name:
        return HTMLResponse(
            "<div class='toast toast--error'>Le nom est requis.</div>", status_code=400
        )
    if source_type not in {t.value for t in SourceType}:
        return HTMLResponse(
            "<div class='toast toast--error'>Type de source invalide.</div>", status_code=400
        )

    slug = _slugify(name)
    base = slug
    i = 2
    while True:
        existing = await db.execute(select(ContextSource).where(ContextSource.name == slug))
        if existing.scalar_one_or_none() is None:
            break
        slug = f"{base}-{i}"
        i += 1

    try:
        s = ContextSource(
            name=slug,
            display_name=name,
            description=(description or "").strip() or None,
            source_type=source_type,
            config={},  # config JSON renseignée plus tard via admin V1 (Vague 2 V2)
            is_enabled=False,  # désactivée par défaut tant que la config n'est pas posée
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        logger.info("Admin %s created source '%s' (type=%s)", user.get("email"), slug, source_type)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur création source '%s': %s", slug, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur création de la source.</div>",
            status_code=500,
        )

    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/admin/sources/{id}/edit — partial édition
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/{source_id}/edit", response_class=HTMLResponse)
async def admin_sources_edit_form(
    request: Request,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, s, edit=True)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/sources/{id}/cancel
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{source_id}/cancel", response_class=HTMLResponse)
async def admin_sources_cancel(
    request: Request,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/sources/{id}/toggle — toggle is_enabled
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{source_id}/toggle", response_class=HTMLResponse)
async def admin_sources_toggle(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)

    try:
        s.is_enabled = not s.is_enabled
        await db.commit()
        await db.refresh(s)
        logger.info(
            "Admin %s toggled source '%s' → enabled=%s",
            user.get("email"), s.name, s.is_enabled,
        )
    except Exception as e:
        await db.rollback()
        logger.error("Erreur toggle source '%s': %s", s.name, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors du toggle.</div>", status_code=500
        )
    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/admin/sources/{id}/health-check — sonde la source (Vague 2.5)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/{source_id}/health-check", response_class=HTMLResponse)
async def admin_sources_health_check(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    # Vérifier que la source existe avant d'appeler le service partagé.
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)

    # Réutiliser le service V1 (même logique que /api/admin/sources/{id}/health).
    # Il met à jour health_status / last_health_check / last_latency_ms en BDD
    # et avale les exceptions du connector → unhealthy en cas d'échec.
    from app.features.sources.service import SourceService

    try:
        await SourceService.health_check(db, source_id)
    except Exception as e:
        logger.error("Erreur health-check source '%s': %s", s.name, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Erreur lors de la sonde.</div>",
            status_code=500,
        )

    # Recharger pour avoir les valeurs fraîches dans le row.
    refreshed = await _get_source_or_404(db, source_id)
    if refreshed is None:
        return HTMLResponse("", status_code=404)
    return await _render_row(request, refreshed, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  PATCH /web/admin/sources/{id} — update champs simples
# ─────────────────────────────────────────────────────────────────────────────
@router.patch("/{source_id}", response_class=HTMLResponse)
async def admin_sources_update(
    request: Request,
    source_id: uuid.UUID,
    display_name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    priority: Annotated[int, Form()] = 100,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)

    name = (display_name or "").strip()
    if not name:
        return await _render_row(request, s, edit=True, error="Le nom est requis.")

    try:
        s.display_name = name
        s.description = (description or "").strip() or None
        s.priority = max(0, min(int(priority), 9999))
        await db.commit()
        await db.refresh(s)
        logger.info("Admin %s updated source '%s'", user.get("email"), s.name)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur update source '%s': %s", s.name, e)
        return await _render_row(
            request, s, edit=True, error="Erreur lors de la sauvegarde."
        )

    return await _render_row(request, s, edit=False)


# ─────────────────────────────────────────────────────────────────────────────
#  DELETE /web/admin/sources/{id}
# ─────────────────────────────────────────────────────────────────────────────
@router.delete("/{source_id}", response_class=Response)
async def admin_sources_delete(
    request: Request,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return Response(status_code=404)
    try:
        slug = s.name
        await db.delete(s)
        await db.commit()
        logger.info("Admin %s deleted source '%s'", user.get("email"), slug)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur suppression source %s: %s", source_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Suppression impossible.</div>", status_code=500
        )
    return Response(status_code=200, content="")


# ═════════════════════════════════════════════════════════════════════════════
#  Vague 2.6 — Éditeur de config technique JSON par type
# ═════════════════════════════════════════════════════════════════════════════
def _validate_source_config(source_type: str, config: dict) -> str | None:
    """Valide les champs requis selon le ``source_type``. Renvoie un message
    d'erreur lisible si invalide, ``None`` sinon.

    Les règles reflètent ce que les connectors V1 (web/api/database/mcp)
    attendent au minimum dans ``config``. Les champs optionnels et avancés
    sont laissés à la main de l'utilisateur (JSON libre).
    """
    if source_type == "web":
        provider = (config.get("provider") or "").strip().lower()
        if not provider:
            return "Champ 'provider' requis (ex : duckduckgo, google, url, scrape)."
        if provider == "google":
            for key in ("api_key", "search_engine_id"):
                if not config.get(key):
                    return f"Champ '{key}' requis pour le provider Google."
        elif provider in ("url", "scrape"):
            if not config.get("url") and not config.get("urls"):
                return "Champ 'url' (ou 'urls') requis pour ce provider."
    elif source_type == "api":
        if not config.get("base_url"):
            return "Champ 'base_url' requis."
        if not config.get("endpoint"):
            return "Champ 'endpoint' requis."
    elif source_type == "database":
        if not config.get("db_type"):
            return "Champ 'db_type' requis (postgres, mysql, ...)."
        if not config.get("query_template"):
            return "Champ 'query_template' requis."
        for key in ("host", "database", "username"):
            if not config.get(key):
                return f"Champ '{key}' requis."
    elif source_type == "mcp":
        if not config.get("server_command") and not config.get("server_url"):
            return "Champ 'server_command' ou 'server_url' requis."
    return None


# Champs documentés par type pour aider l'utilisateur à composer son JSON.
# Affichés sous forme d'aide (label → description) dans la page éditeur.
_FIELD_HINTS: dict[str, list[tuple[str, str, bool]]] = {
    "web": [
        ("provider", "Fournisseur : duckduckgo, google, url, scrape", True),
        ("api_key", "Clé API (provider=google)", False),
        ("search_engine_id", "CX Google (provider=google)", False),
        ("language", "Langue de recherche, ex: 'fr'", False),
        ("url", "URL unique (provider=url/scrape)", False),
        ("urls", "Liste d'URLs (provider=url/scrape)", False),
        ("max_depth", "Profondeur de crawl (default 0)", False),
        ("max_pages", "Nombre max de pages (default 50)", False),
    ],
    "api": [
        ("base_url", "URL de base de l'API", True),
        ("endpoint", "Chemin de l'endpoint, ex : /search", True),
        ("method", "GET, POST, PUT (default GET)", False),
        ("headers", "Objet JSON { 'Authorization': '...' }", False),
        ("query_param", "Nom du paramètre de query (default 'q')", False),
        ("response_path", "Chemin JSON vers la liste des résultats", False),
        ("content_field", "Champ texte dans chaque résultat (default 'content')", False),
        ("metadata_fields", "Liste des champs métadonnées à conserver", False),
        ("body_template", "Template de body POST (objet JSON)", False),
    ],
    "database": [
        ("db_type", "postgres | mysql | sqlite", True),
        ("host", "Hôte de la BDD", True),
        ("port", "Port (default 5432 pour postgres)", False),
        ("database", "Nom de la base", True),
        ("username", "Utilisateur", True),
        ("password", "Mot de passe (sera stocké en clair, à protéger)", False),
        ("query_template", "Requête SQL paramétrée, ex : SELECT ... WHERE x ILIKE :q", True),
    ],
    "mcp": [
        ("server_command", "Commande à lancer pour le serveur MCP local", False),
        ("server_url", "URL d'un serveur MCP distant", False),
    ],
}


@router.get("/{source_id}/config", response_class=HTMLResponse)
async def admin_sources_config_get(
    request: Request,
    source_id: uuid.UUID,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("Source introuvable.", status_code=404)

    config_text = json.dumps(s.config or {}, indent=2, ensure_ascii=False)
    return templates.TemplateResponse(
        request,
        "pages/admin/source-config.html",
        web_context(
            request,
            title=f"Source · {s.display_name} · config",
            active_section="sources",
            user=user,
            source=s,
            config_text=config_text,
            field_hints=_FIELD_HINTS.get(s.source_type, []),
            error=None,
        ),
    )


@router.post("/{source_id}/config", response_class=HTMLResponse)
async def admin_sources_config_post(
    request: Request,
    source_id: uuid.UUID,
    config_text: Annotated[str, Form()] = "",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("Source introuvable.", status_code=404)

    def _render_with_error(msg: str, raw: str, status_code: int = 400) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "pages/admin/source-config.html",
            web_context(
                request,
                title=f"Source · {s.display_name} · config",
                active_section="sources",
                user=user,
                source=s,
                config_text=raw,
                field_hints=_FIELD_HINTS.get(s.source_type, []),
                error=msg,
            ),
            status_code=status_code,
        )

    raw = (config_text or "").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        return _render_with_error(f"JSON invalide : {e.msg} (ligne {e.lineno}, col {e.colno}).", raw)

    if not isinstance(parsed, dict):
        return _render_with_error("La config doit être un objet JSON (pas une liste, ni une string).", raw)

    err_msg = _validate_source_config(s.source_type, parsed)
    if err_msg:
        return _render_with_error(err_msg, raw)

    try:
        s.config = parsed
        await db.commit()
        await db.refresh(s)
        logger.info("Admin %s a mis à jour config source '%s' (type=%s)",
                    user.get("email"), s.name, s.source_type)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur save config source '%s': %s", s.name, e)
        return _render_with_error(
            "Erreur lors de la sauvegarde — voir les logs serveur.",
            json.dumps(parsed, indent=2, ensure_ascii=False),
            status_code=500,
        )

    # Rendu du formulaire avec le JSON re-formaté + flash de succès
    return templates.TemplateResponse(
        request,
        "pages/admin/source-config.html",
        web_context(
            request,
            title=f"Source · {s.display_name} · config",
            active_section="sources",
            user=user,
            source=s,
            config_text=json.dumps(s.config, indent=2, ensure_ascii=False),
            field_hints=_FIELD_HINTS.get(s.source_type, []),
            error=None,
            success="Configuration enregistrée.",
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.4.c — Test, reindex, clear-index, bulk (parité V1 sources.js)
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/{source_id}/test", response_class=HTMLResponse)
async def admin_source_test(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Teste une source (parité V1 sources.js:testSource)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)
    try:
        from app.features.sources.service import SourceService as _SrcService
        result = await _SrcService.test_source(db, source_id, query="test")
        ok = bool(getattr(result, "success", False))
        msg = getattr(result, "error", None) or ("Test réussi." if ok else "Échec du test.")
    except Exception as exc:
        logger.exception("Test source failed")
        ok = False
        msg = f"Erreur : {exc}"
    cls = "toast--success" if ok else "toast--error"
    return HTMLResponse(
        f"<div class='toast {cls}'>{msg}</div>", status_code=200 if ok else 500
    )


@router.post("/{source_id}/reindex", response_class=HTMLResponse)
async def admin_source_reindex(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Trigger réindexation d'une source (parité V1 sources.js:reindexSource)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)
    try:
        from app.features.sources.service import SourceService as _SrcService
        await _SrcService.trigger_initial_indexation(source_id)
    except Exception as exc:
        logger.exception("Reindex source failed")
        return HTMLResponse(
            f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500
        )
    return HTMLResponse(
        f"<div class='toast toast--success'>Réindexation lancée pour « {s.display_name} ».</div>"
    )


@router.post("/{source_id}/clear-index", response_class=HTMLResponse)
async def admin_source_clear_index(
    request: Request,
    source_id: uuid.UUID,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Vide l'index d'une source sans la supprimer (parité V1 clearSourceIndex)."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    s = await _get_source_or_404(db, source_id)
    if s is None:
        return HTMLResponse("", status_code=404)
    try:
        from app.features.sources.service import SourceService as _SrcService
        await _SrcService.clear_source_index(db, source_id)
    except Exception as exc:
        logger.exception("Clear index failed")
        return HTMLResponse(
            f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500
        )
    return HTMLResponse(
        f"<div class='toast toast--success'>Index vidé pour « {s.display_name} ».</div>",
        headers={"HX-Trigger": "sources-refresh"},
    )


@router.post("/bulk-action", response_class=HTMLResponse)
async def admin_sources_bulk(
    request: Request,
    action: Annotated[str, Form()],
    source_ids: Annotated[list[str], Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Bulk : enable / disable / reindex / clear-index / delete."""
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if action not in {"enable", "disable", "reindex", "clear-index", "delete"}:
        return HTMLResponse("<div class='toast toast--error'>Action invalide.</div>", status_code=400)
    affected = 0
    from app.features.sources.service import SourceService as _SrcService
    for raw in source_ids:
        try:
            sid = uuid.UUID(raw)
        except ValueError:
            continue
        s = await _get_source_or_404(db, sid)
        if s is None:
            continue
        try:
            if action == "enable":
                s.is_enabled = True
                await db.commit()
            elif action == "disable":
                s.is_enabled = False
                await db.commit()
            elif action == "reindex":
                await _SrcService.trigger_initial_indexation(sid)
            elif action == "clear-index":
                await _SrcService.clear_source_index(db, sid)
            elif action == "delete":
                await db.delete(s)
                await db.commit()
            affected += 1
        except Exception:
            logger.exception("Bulk source action %s failed for %s", action, sid)
    return HTMLResponse(
        f"<div class='toast toast--success'>{affected} source(s) traitée(s).</div>",
        headers={"HX-Trigger": "sources-refresh"},
    )
