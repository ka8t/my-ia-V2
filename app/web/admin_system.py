"""Web routes — Admin Système (Phase 3.8 — pages structurées par module).

Chaque page édite un sous-ensemble de clés ``system_configs`` via un formulaire
typé. Les valeurs sont lues/écrites via :class:`SystemConfigService`.

Phase 3.8.a couvre :
- LLM : provider, ollama, llamacpp
- RAG : chunking, search, behavior, overrides
"""
from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.features.system.service import SystemConfigService
from app.web.deps import require_web_admin
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/web/admin/system", tags=["Web - Admin Système"])
templates = make_templates(TEMPLATES_DIR)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _csrf_or_400(request: Request, csrf_token: str | None) -> HTMLResponse | None:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée.</div>", status_code=400
        )
    return None


def _to_bool(value: Any) -> bool:
    """Coerce value (string from form, or actual bool/int) into bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    return s in ("1", "true", "yes", "on")


def _to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


async def _bulk_set(
    db: AsyncSession,
    user: dict,
    updates: dict[str, Any],
) -> tuple[int, list[str]]:
    """Persist ``updates`` (key → value) via SystemConfigService.set."""
    service = SystemConfigService(db)
    saved = 0
    errors: list[str] = []
    for key, value in updates.items():
        try:
            await service.set(key, value, updated_by=user.get("id"))
            saved += 1
        except Exception as e:
            logger.error("Erreur set system_config %s: %s", key, e)
            errors.append(f"{key}: {e}")
    return saved, errors


async def _render_page(
    request: Request,
    template_name: str,
    *,
    title: str,
    active_section: str,
    user: dict,
    values: dict[str, Any],
    success: str | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> HTMLResponse:
    ctx = web_context(
        request,
        title=title,
        active_section=active_section,
        user=user,
        values=values,
        success=success,
        error=error,
    )
    if extra:
        ctx.update(extra)
    return templates.TemplateResponse(request, template_name, ctx)


# ═════════════════════════════════════════════════════════════════════════════
#  Page 1/3 — LLM Provider
# ═════════════════════════════════════════════════════════════════════════════
LLM_PROVIDER_KEYS = ["llm.provider", "llm.embedding_provider"]


async def _load_keys(db: AsyncSession, keys: list[str]) -> dict[str, Any]:
    service = SystemConfigService(db)
    return {k: await service.get(k, None) for k in keys}


@router.get("/llm/provider", response_class=HTMLResponse)
async def llm_provider_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    values = await _load_keys(db, LLM_PROVIDER_KEYS)
    return await _render_page(
        request,
        "pages/admin/system/llm-provider.html",
        title="LLM · Provider",
        active_section="system_llm_provider",
        user=user,
        values=values,
    )


@router.post("/llm/provider", response_class=HTMLResponse)
async def llm_provider_post(
    request: Request,
    provider: Annotated[str, Form()] = "ollama",
    embedding_provider: Annotated[str, Form()] = "ollama",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    if provider not in ("ollama", "llamacpp"):
        return await _render_page(
            request, "pages/admin/system/llm-provider.html",
            title="LLM · Provider", active_section="system_llm_provider", user=user,
            values={"llm.provider": provider, "llm.embedding_provider": embedding_provider},
            error="Provider invalide.",
        )
    if embedding_provider not in ("ollama", "llamacpp"):
        return await _render_page(
            request, "pages/admin/system/llm-provider.html",
            title="LLM · Provider", active_section="system_llm_provider", user=user,
            values={"llm.provider": provider, "llm.embedding_provider": embedding_provider},
            error="Embedding provider invalide.",
        )

    saved, errors = await _bulk_set(db, user, {
        "llm.provider": provider,
        "llm.embedding_provider": embedding_provider,
    })
    return await _render_page(
        request, "pages/admin/system/llm-provider.html",
        title="LLM · Provider", active_section="system_llm_provider", user=user,
        values=await _load_keys(db, LLM_PROVIDER_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Page 2/3 — LLM Ollama
# ═════════════════════════════════════════════════════════════════════════════
LLM_OLLAMA_KEYS = [
    "llm.ollama.llm_model", "llm.ollama.embedding_model",
    "llm.ollama_host", "llm.ollama_port",
    "llm.ollama.num_ctx", "llm.ollama.num_gpu", "llm.ollama.num_parallel",
    "llm.ollama.keep_alive", "llm.ollama.auto_preload",
]


@router.get("/llm/ollama", response_class=HTMLResponse)
async def llm_ollama_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    values = await _load_keys(db, LLM_OLLAMA_KEYS)
    return await _render_page(
        request, "pages/admin/system/llm-ollama.html",
        title="LLM · Ollama", active_section="system_llm_ollama", user=user, values=values,
    )


@router.post("/llm/ollama", response_class=HTMLResponse)
async def llm_ollama_post(
    request: Request,
    llm_model: Annotated[str, Form()] = "",
    embedding_model: Annotated[str, Form()] = "",
    host: Annotated[str, Form()] = "",
    port: Annotated[int, Form()] = 11434,
    num_ctx: Annotated[int, Form()] = 2048,
    num_gpu: Annotated[int, Form()] = 0,
    num_parallel: Annotated[int, Form()] = 1,
    keep_alive: Annotated[str, Form()] = "5m",
    auto_preload: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    updates = {
        "llm.ollama.llm_model": llm_model.strip(),
        "llm.ollama.embedding_model": embedding_model.strip(),
        "llm.ollama_host": host.strip(),
        "llm.ollama_port": _to_int(port, 11434),
        "llm.ollama.num_ctx": _to_int(num_ctx, 2048),
        "llm.ollama.num_gpu": _to_int(num_gpu, 0),
        "llm.ollama.num_parallel": _to_int(num_parallel, 1),
        "llm.ollama.keep_alive": keep_alive.strip(),
        "llm.ollama.auto_preload": _to_bool(auto_preload),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/llm-ollama.html",
        title="LLM · Ollama", active_section="system_llm_ollama", user=user,
        values=await _load_keys(db, LLM_OLLAMA_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Page 3/3 — LLM llama.cpp
# ═════════════════════════════════════════════════════════════════════════════
LLM_LLAMACPP_KEYS = [
    "llm.llamacpp.llm_model", "llm.llamacpp.embedding_model",
    "llm.llamacpp.host", "llm.llamacpp.port",
    "llm.llamacpp.server_path", "llm.llamacpp.models_dir",
    "llm.llamacpp.ctx_size", "llm.llamacpp.batch_size",
    "llm.llamacpp.gpu_layers", "llm.llamacpp.threads", "llm.llamacpp.parallel",
    "llm.llamacpp.mlock", "llm.llamacpp.mmap", "llm.llamacpp.flash_attn",
    "llm.llamacpp.embedding_mode", "llm.llamacpp.metrics_enabled",
]


@router.get("/llm/llamacpp", response_class=HTMLResponse)
async def llm_llamacpp_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    values = await _load_keys(db, LLM_LLAMACPP_KEYS)
    return await _render_page(
        request, "pages/admin/system/llm-llamacpp.html",
        title="LLM · llama.cpp", active_section="system_llm_llamacpp", user=user, values=values,
    )


@router.post("/llm/llamacpp", response_class=HTMLResponse)
async def llm_llamacpp_post(
    request: Request,
    llm_model: Annotated[str, Form()] = "",
    embedding_model: Annotated[str, Form()] = "",
    host: Annotated[str, Form()] = "",
    port: Annotated[int, Form()] = 8081,
    server_path: Annotated[str, Form()] = "",
    models_dir: Annotated[str, Form()] = "",
    ctx_size: Annotated[int, Form()] = 4096,
    batch_size: Annotated[int, Form()] = 512,
    gpu_layers: Annotated[int, Form()] = 0,
    threads: Annotated[int, Form()] = 4,
    parallel: Annotated[int, Form()] = 1,
    mlock: Annotated[str | None, Form()] = None,
    mmap: Annotated[str | None, Form()] = None,
    flash_attn: Annotated[str | None, Form()] = None,
    embedding_mode: Annotated[str | None, Form()] = None,
    metrics_enabled: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    updates = {
        "llm.llamacpp.llm_model": llm_model.strip(),
        "llm.llamacpp.embedding_model": embedding_model.strip(),
        "llm.llamacpp.host": host.strip(),
        "llm.llamacpp.port": _to_int(port, 8081),
        "llm.llamacpp.server_path": server_path.strip(),
        "llm.llamacpp.models_dir": models_dir.strip(),
        "llm.llamacpp.ctx_size": _to_int(ctx_size, 4096),
        "llm.llamacpp.batch_size": _to_int(batch_size, 512),
        "llm.llamacpp.gpu_layers": _to_int(gpu_layers, 0),
        "llm.llamacpp.threads": _to_int(threads, 4),
        "llm.llamacpp.parallel": _to_int(parallel, 1),
        "llm.llamacpp.mlock": _to_bool(mlock),
        "llm.llamacpp.mmap": _to_bool(mmap),
        "llm.llamacpp.flash_attn": _to_bool(flash_attn),
        "llm.llamacpp.embedding_mode": _to_bool(embedding_mode),
        "llm.llamacpp.metrics_enabled": _to_bool(metrics_enabled),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/llm-llamacpp.html",
        title="LLM · llama.cpp", active_section="system_llm_llamacpp", user=user,
        values=await _load_keys(db, LLM_LLAMACPP_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Page 4/7 — RAG Chunking
# ═════════════════════════════════════════════════════════════════════════════
RAG_CHUNKING_KEYS = [
    "rag.chunk_size", "rag.chunk_overlap", "rag.chunking_strategy", "rag.min_chunk_length",
]


@router.get("/rag/chunking", response_class=HTMLResponse)
async def rag_chunking_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/rag-chunking.html",
        title="RAG · Chunking", active_section="system_rag_chunking", user=user,
        values=await _load_keys(db, RAG_CHUNKING_KEYS),
    )


@router.post("/rag/chunking", response_class=HTMLResponse)
async def rag_chunking_post(
    request: Request,
    chunk_size: Annotated[int, Form()] = 800,
    chunk_overlap: Annotated[int, Form()] = 100,
    chunking_strategy: Annotated[str, Form()] = "recursive",
    min_chunk_length: Annotated[int, Form()] = 50,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    if chunking_strategy not in ("recursive", "fixed", "semantic", "sentence"):
        return await _render_page(
            request, "pages/admin/system/rag-chunking.html",
            title="RAG · Chunking", active_section="system_rag_chunking", user=user,
            values=await _load_keys(db, RAG_CHUNKING_KEYS),
            error="Stratégie de chunking invalide.",
        )

    updates = {
        "rag.chunk_size": _to_int(chunk_size, 800),
        "rag.chunk_overlap": _to_int(chunk_overlap, 100),
        "rag.chunking_strategy": chunking_strategy,
        "rag.min_chunk_length": _to_int(min_chunk_length, 50),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/rag-chunking.html",
        title="RAG · Chunking", active_section="system_rag_chunking", user=user,
        values=await _load_keys(db, RAG_CHUNKING_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Page 5/7 — RAG Recherche
# ═════════════════════════════════════════════════════════════════════════════
RAG_SEARCH_KEYS = [
    "rag.top_k", "rag.similarity_threshold", "rag.keyword_boost",
    "rag.stopwords_language", "rag.temperature",
]


@router.get("/rag/search", response_class=HTMLResponse)
async def rag_search_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/rag-search.html",
        title="RAG · Recherche", active_section="system_rag_search", user=user,
        values=await _load_keys(db, RAG_SEARCH_KEYS),
    )


@router.post("/rag/search", response_class=HTMLResponse)
async def rag_search_post(
    request: Request,
    top_k: Annotated[int, Form()] = 10,
    similarity_threshold: Annotated[float, Form()] = 0.0,
    keyword_boost: Annotated[float, Form()] = 0.0,
    stopwords_language: Annotated[str, Form()] = "fr",
    temperature: Annotated[float, Form()] = 0.7,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    if not (0.0 <= similarity_threshold <= 1.0):
        return await _render_page(
            request, "pages/admin/system/rag-search.html",
            title="RAG · Recherche", active_section="system_rag_search", user=user,
            values=await _load_keys(db, RAG_SEARCH_KEYS),
            error="similarity_threshold doit être entre 0.0 et 1.0.",
        )
    if not (0.0 <= temperature <= 2.0):
        return await _render_page(
            request, "pages/admin/system/rag-search.html",
            title="RAG · Recherche", active_section="system_rag_search", user=user,
            values=await _load_keys(db, RAG_SEARCH_KEYS),
            error="temperature doit être entre 0.0 et 2.0.",
        )

    updates = {
        "rag.top_k": max(1, min(_to_int(top_k, 10), 200)),
        "rag.similarity_threshold": _to_float(similarity_threshold, 0.0),
        "rag.keyword_boost": _to_float(keyword_boost, 0.0),
        "rag.stopwords_language": stopwords_language.strip(),
        "rag.temperature": _to_float(temperature, 0.7),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/rag-search.html",
        title="RAG · Recherche", active_section="system_rag_search", user=user,
        values=await _load_keys(db, RAG_SEARCH_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Page 6/7 — RAG Comportement
# ═════════════════════════════════════════════════════════════════════════════
RAG_BEHAVIOR_KEYS = [
    "rag.use_corpus", "rag.include_global_sources",
    "rag.default_group", "rag.source_filter_by_collection",
]


@router.get("/rag/behavior", response_class=HTMLResponse)
async def rag_behavior_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/rag-behavior.html",
        title="RAG · Comportement", active_section="system_rag_behavior", user=user,
        values=await _load_keys(db, RAG_BEHAVIOR_KEYS),
    )


@router.post("/rag/behavior", response_class=HTMLResponse)
async def rag_behavior_post(
    request: Request,
    use_corpus: Annotated[str | None, Form()] = None,
    include_global_sources: Annotated[str | None, Form()] = None,
    default_group: Annotated[str, Form()] = "",
    source_filter_by_collection: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    updates = {
        "rag.use_corpus": _to_bool(use_corpus),
        "rag.include_global_sources": _to_bool(include_global_sources),
        "rag.default_group": default_group.strip(),
        "rag.source_filter_by_collection": _to_bool(source_filter_by_collection),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/rag-behavior.html",
        title="RAG · Comportement", active_section="system_rag_behavior", user=user,
        values=await _load_keys(db, RAG_BEHAVIOR_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Page 7/7 — RAG Overrides (per-provider et per-mode)
# ═════════════════════════════════════════════════════════════════════════════
def _provider_override_keys(provider: str) -> list[str]:
    return [f"rag.{provider}.{k}" for k in (
        "chunk_size", "chunk_overlap", "chunking_strategy", "min_chunk_length",
        "top_k", "similarity_threshold", "keyword_boost", "stopwords_language",
        "temperature", "use_corpus", "require_sources",
    )]


def _mode_override_keys(mode: str) -> list[str]:
    return [f"rag.mode.{mode}.{k}" for k in (
        "max_context_tokens", "rerank_enabled", "temperature", "top_k",
    )]


RAG_OVERRIDES_KEYS = (
    _provider_override_keys("ollama")
    + _provider_override_keys("llamacpp")
    + _mode_override_keys("fast")
    + _mode_override_keys("full")
)


@router.get("/rag/overrides", response_class=HTMLResponse)
async def rag_overrides_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/rag-overrides.html",
        title="RAG · Overrides", active_section="system_rag_overrides", user=user,
        values=await _load_keys(db, RAG_OVERRIDES_KEYS),
    )


@router.post("/rag/overrides", response_class=HTMLResponse)
async def rag_overrides_post(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Sauvegarde générique : itère sur les champs reçus.

    Le formulaire envoie les clés sous leur nom complet (rag.ollama.top_k, ...).
    On filtre sur la liste blanche RAG_OVERRIDES_KEYS pour éviter d'écrire
    des clés inattendues.
    """
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    form = await request.form()
    updates: dict[str, Any] = {}
    for key in RAG_OVERRIDES_KEYS:
        if key not in form:
            # Champ booléen non coché → False, sinon on laisse la valeur actuelle
            if key.endswith(("rerank_enabled", "use_corpus", "require_sources")):
                updates[key] = False
            continue
        raw = form.get(key)
        if key.endswith(("temperature", "similarity_threshold", "keyword_boost")):
            updates[key] = _to_float(raw, 0.0)
        elif key.endswith((
            "chunk_size", "chunk_overlap", "min_chunk_length", "top_k",
            "max_context_tokens",
        )):
            updates[key] = _to_int(raw, 0)
        elif key.endswith(("rerank_enabled", "use_corpus", "require_sources")):
            updates[key] = _to_bool(raw)
        else:
            updates[key] = (raw or "").strip() if isinstance(raw, str) else raw

    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/rag-overrides.html",
        title="RAG · Overrides", active_section="system_rag_overrides", user=user,
        values=await _load_keys(db, RAG_OVERRIDES_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.b — Storage
# ═════════════════════════════════════════════════════════════════════════════
STORAGE_KEYS = [
    "storage.backend", "storage.local_path",
    "storage.max_file_size_mb", "storage.default_quota_mb",
    "storage.allowed_mime_types", "storage.blocked_extensions",
]


def _parse_list_textarea(raw: str) -> list[str]:
    """Parse un textarea (1 valeur par ligne, ou séparées par virgule).

    Vide les blanks, conserve l'ordre, dédupe.
    """
    if not raw:
        return []
    items: list[str] = []
    seen: set[str] = set()
    for line in raw.replace(",", "\n").splitlines():
        v = line.strip()
        if v and v not in seen:
            items.append(v)
            seen.add(v)
    return items


def _list_to_textarea(value: Any) -> str:
    """Inverse de _parse_list_textarea pour le rendu (1 item par ligne)."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    if isinstance(value, str):
        # Peut être déjà une liste sérialisée si _convert_value n'a pas été appelé
        return value
    return str(value)


@router.get("/storage", response_class=HTMLResponse)
async def storage_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/storage.html",
        title="Stockage", active_section="system_storage", user=user,
        values=await _load_keys(db, STORAGE_KEYS),
    )


@router.post("/storage", response_class=HTMLResponse)
async def storage_post(
    request: Request,
    backend: Annotated[str, Form()] = "local",
    local_path: Annotated[str, Form()] = "/data/uploads",
    max_file_size_mb: Annotated[int, Form()] = 50,
    default_quota_mb: Annotated[int, Form()] = 100,
    allowed_mime_types: Annotated[str, Form()] = "",
    blocked_extensions: Annotated[str, Form()] = "",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    if backend not in ("local", "s3", "minio"):
        return await _render_page(
            request, "pages/admin/system/storage.html",
            title="Stockage", active_section="system_storage", user=user,
            values=await _load_keys(db, STORAGE_KEYS),
            error="Backend invalide (attendu : local, s3, minio).",
        )

    mime_types = _parse_list_textarea(allowed_mime_types)
    extensions = _parse_list_textarea(blocked_extensions)
    # Normaliser les extensions : doivent commencer par "."
    extensions = [e if e.startswith(".") else f".{e}" for e in extensions]

    updates = {
        "storage.backend": backend,
        "storage.local_path": local_path.strip(),
        "storage.max_file_size_mb": max(1, _to_int(max_file_size_mb, 50)),
        "storage.default_quota_mb": max(1, _to_int(default_quota_mb, 100)),
        "storage.allowed_mime_types": mime_types,
        "storage.blocked_extensions": extensions,
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/storage.html",
        title="Stockage", active_section="system_storage", user=user,
        values=await _load_keys(db, STORAGE_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.b — Speech (STT + TTS)
# ═════════════════════════════════════════════════════════════════════════════
SPEECH_KEYS = [
    "speech.enabled", "speech.default_language", "speech.model",
    "speech.max_duration", "speech.timeout",
    "speech.silence_duration_ms", "speech.silence_threshold",
    "speech.auto_send_enabled",
    "speech.tts_enabled", "speech.tts_mode", "speech.tts_default_rate",
    "whisper.host", "whisper.port",
]


@router.get("/speech", response_class=HTMLResponse)
async def speech_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/speech.html",
        title="Speech (STT/TTS)", active_section="system_speech", user=user,
        values=await _load_keys(db, SPEECH_KEYS),
    )


@router.post("/speech", response_class=HTMLResponse)
async def speech_post(
    request: Request,
    enabled: Annotated[str | None, Form()] = None,
    default_language: Annotated[str, Form()] = "fr",
    model: Annotated[str, Form()] = "small",
    max_duration: Annotated[int, Form()] = 60,
    timeout: Annotated[int, Form()] = 120,
    silence_duration_ms: Annotated[int, Form()] = 1500,
    silence_threshold: Annotated[float, Form()] = 0.01,
    auto_send_enabled: Annotated[str | None, Form()] = None,
    tts_enabled: Annotated[str | None, Form()] = None,
    tts_mode: Annotated[str, Form()] = "native",
    tts_default_rate: Annotated[float, Form()] = 1.0,
    whisper_host: Annotated[str, Form()] = "whisper",
    whisper_port: Annotated[int, Form()] = 8000,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    if model not in ("tiny", "base", "small", "medium", "large", "large-v2", "large-v3"):
        return await _render_page(
            request, "pages/admin/system/speech.html",
            title="Speech (STT/TTS)", active_section="system_speech", user=user,
            values=await _load_keys(db, SPEECH_KEYS),
            error="Modèle Whisper invalide.",
        )
    if tts_mode not in ("native", "server", "off"):
        return await _render_page(
            request, "pages/admin/system/speech.html",
            title="Speech (STT/TTS)", active_section="system_speech", user=user,
            values=await _load_keys(db, SPEECH_KEYS),
            error="Mode TTS invalide.",
        )
    if not (0.5 <= tts_default_rate <= 2.0):
        return await _render_page(
            request, "pages/admin/system/speech.html",
            title="Speech (STT/TTS)", active_section="system_speech", user=user,
            values=await _load_keys(db, SPEECH_KEYS),
            error="tts_default_rate doit être entre 0.5 et 2.0.",
        )

    updates = {
        "speech.enabled": _to_bool(enabled),
        "speech.default_language": default_language.strip() or "fr",
        "speech.model": model,
        "speech.max_duration": max(1, _to_int(max_duration, 60)),
        "speech.timeout": max(1, _to_int(timeout, 120)),
        "speech.silence_duration_ms": max(0, _to_int(silence_duration_ms, 1500)),
        "speech.silence_threshold": max(0.0, min(_to_float(silence_threshold, 0.01), 1.0)),
        "speech.auto_send_enabled": _to_bool(auto_send_enabled),
        "speech.tts_enabled": _to_bool(tts_enabled),
        "speech.tts_mode": tts_mode,
        "speech.tts_default_rate": _to_float(tts_default_rate, 1.0),
        "whisper.host": whisper_host.strip(),
        "whisper.port": max(1, min(_to_int(whisper_port, 8000), 65535)),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/speech.html",
        title="Speech (STT/TTS)", active_section="system_speech", user=user,
        values=await _load_keys(db, SPEECH_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.c — SMTP (config générale email + serveur sortant)
# ═════════════════════════════════════════════════════════════════════════════
SMTP_KEYS = [
    "email.backend", "email.from", "email.from_name",
    "notification.email_smtp_host", "notification.email_smtp_port",
    "notification.email_smtp_user", "notification.email_smtp_password",
    "notification.email_smtp_tls",
]


# Marqueur des champs "sensibles" : si vide à la soumission, on conserve la
# valeur stockée (au lieu de l'écraser par "").
_SENSITIVE_PRESERVE_EMPTY = {
    "notification.email_smtp_password",
    "notification.webhook_secret",
}


async def _bulk_set_with_secret_preserve(
    db: AsyncSession, user: dict, updates: dict[str, Any]
) -> tuple[int, list[str]]:
    """Variante de _bulk_set : pour les clés _SENSITIVE_PRESERVE_EMPTY, si la
    valeur fournie est vide ou None, on saute le set (la valeur en BDD reste)."""
    filtered: dict[str, Any] = {}
    for k, v in updates.items():
        if k in _SENSITIVE_PRESERVE_EMPTY and (v is None or v == ""):
            continue
        filtered[k] = v
    return await _bulk_set(db, user, filtered)


@router.get("/smtp", response_class=HTMLResponse)
async def smtp_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    values = await _load_keys(db, SMTP_KEYS)
    # On masque le password à l'affichage : la page indique seulement s'il
    # existe une valeur stockée (l'admin ne le revoit jamais en clair).
    has_password = bool(values.get("notification.email_smtp_password"))
    return await _render_page(
        request, "pages/admin/system/smtp.html",
        title="SMTP", active_section="system_smtp", user=user, values=values,
        extra={"has_password": has_password},
    )


@router.post("/smtp", response_class=HTMLResponse)
async def smtp_post(
    request: Request,
    backend: Annotated[str, Form()] = "console",
    email_from: Annotated[str, Form(alias="email_from")] = "",
    email_from_name: Annotated[str, Form(alias="email_from_name")] = "",
    smtp_host: Annotated[str, Form()] = "",
    smtp_port: Annotated[int, Form()] = 587,
    smtp_user: Annotated[str, Form()] = "",
    smtp_password: Annotated[str, Form()] = "",
    smtp_tls: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    if backend not in ("console", "smtp"):
        return await _render_page(
            request, "pages/admin/system/smtp.html",
            title="SMTP", active_section="system_smtp", user=user,
            values=await _load_keys(db, SMTP_KEYS),
            error="Backend email invalide (attendu : console, smtp).",
            extra={"has_password": bool(smtp_password)},
        )

    updates = {
        "email.backend": backend,
        "email.from": email_from.strip(),
        "email.from_name": email_from_name.strip(),
        "notification.email_smtp_host": smtp_host.strip(),
        "notification.email_smtp_port": max(1, min(_to_int(smtp_port, 587), 65535)),
        "notification.email_smtp_user": smtp_user.strip(),
        "notification.email_smtp_password": smtp_password,  # preserve si vide
        "notification.email_smtp_tls": _to_bool(smtp_tls),
    }
    saved, errors = await _bulk_set_with_secret_preserve(db, user, updates)
    refreshed = await _load_keys(db, SMTP_KEYS)
    return await _render_page(
        request, "pages/admin/system/smtp.html",
        title="SMTP", active_section="system_smtp", user=user, values=refreshed,
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
        extra={"has_password": bool(refreshed.get("notification.email_smtp_password"))},
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.c — Notifications (Email alertes + Slack + Webhook)
# ═════════════════════════════════════════════════════════════════════════════
NOTIFICATIONS_KEYS = [
    "notification.email_enabled", "notification.email_from_address",
    "notification.email_to_addresses",
    "notification.slack_enabled", "notification.slack_webhook_url",
    "notification.webhook_enabled", "notification.webhook_url",
    "notification.webhook_secret",
]


@router.get("/notifications", response_class=HTMLResponse)
async def notifications_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    values = await _load_keys(db, NOTIFICATIONS_KEYS)
    has_secret = bool(values.get("notification.webhook_secret"))
    return await _render_page(
        request, "pages/admin/system/notifications.html",
        title="Notifications", active_section="system_notifications", user=user,
        values=values, extra={"has_secret": has_secret},
    )


@router.post("/notifications", response_class=HTMLResponse)
async def notifications_post(
    request: Request,
    email_enabled: Annotated[str | None, Form()] = None,
    email_from_address: Annotated[str, Form()] = "",
    email_to_addresses: Annotated[str, Form()] = "",
    slack_enabled: Annotated[str | None, Form()] = None,
    slack_webhook_url: Annotated[str, Form()] = "",
    webhook_enabled: Annotated[str | None, Form()] = None,
    webhook_url: Annotated[str, Form()] = "",
    webhook_secret: Annotated[str, Form()] = "",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    updates = {
        "notification.email_enabled": _to_bool(email_enabled),
        "notification.email_from_address": email_from_address.strip(),
        "notification.email_to_addresses": email_to_addresses.strip(),
        "notification.slack_enabled": _to_bool(slack_enabled),
        "notification.slack_webhook_url": slack_webhook_url.strip(),
        "notification.webhook_enabled": _to_bool(webhook_enabled),
        "notification.webhook_url": webhook_url.strip(),
        "notification.webhook_secret": webhook_secret,  # preserve si vide
    }
    saved, errors = await _bulk_set_with_secret_preserve(db, user, updates)
    refreshed = await _load_keys(db, NOTIFICATIONS_KEYS)
    return await _render_page(
        request, "pages/admin/system/notifications.html",
        title="Notifications", active_section="system_notifications", user=user,
        values=refreshed,
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
        extra={"has_secret": bool(refreshed.get("notification.webhook_secret"))},
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.d — Debug
# ═════════════════════════════════════════════════════════════════════════════
DEBUG_KEYS = [
    "debug.verbose_logging", "debug.timing_headers_enabled", "debug.endpoints_enabled",
]


@router.get("/debug", response_class=HTMLResponse)
async def debug_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/debug.html",
        title="Debug", active_section="system_debug", user=user,
        values=await _load_keys(db, DEBUG_KEYS),
    )


@router.post("/debug", response_class=HTMLResponse)
async def debug_post(
    request: Request,
    verbose_logging: Annotated[str | None, Form()] = None,
    timing_headers_enabled: Annotated[str | None, Form()] = None,
    endpoints_enabled: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    updates = {
        "debug.verbose_logging": _to_bool(verbose_logging),
        "debug.timing_headers_enabled": _to_bool(timing_headers_enabled),
        "debug.endpoints_enabled": _to_bool(endpoints_enabled),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/debug.html",
        title="Debug", active_section="system_debug", user=user,
        values=await _load_keys(db, DEBUG_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.d — Logging
# ═════════════════════════════════════════════════════════════════════════════
LOGGING_KEYS = [
    "logging.level", "logging.format", "logging.db_enabled",
    "logging.alert_cooldown_minutes",
    "logging.level_access", "logging.level_audit", "logging.level_infra",
    "logging.level_security", "logging.level_technical",
    "logging.retention_access_days", "logging.retention_audit_days",
    "logging.retention_infra_days", "logging.retention_security_days",
    "logging.retention_technical_days",
]
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


@router.get("/logging", response_class=HTMLResponse)
async def logging_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/logging.html",
        title="Logging", active_section="system_logging", user=user,
        values=await _load_keys(db, LOGGING_KEYS),
    )


@router.post("/logging", response_class=HTMLResponse)
async def logging_post(
    request: Request,
    level: Annotated[str, Form()] = "INFO",
    format: Annotated[str, Form()] = "",
    db_enabled: Annotated[str | None, Form()] = None,
    alert_cooldown_minutes: Annotated[int, Form()] = 15,
    level_access: Annotated[str, Form()] = "INFO",
    level_audit: Annotated[str, Form()] = "INFO",
    level_infra: Annotated[str, Form()] = "INFO",
    level_security: Annotated[str, Form()] = "INFO",
    level_technical: Annotated[str, Form()] = "INFO",
    retention_access_days: Annotated[int, Form()] = 30,
    retention_audit_days: Annotated[int, Form()] = 365,
    retention_infra_days: Annotated[int, Form()] = 14,
    retention_security_days: Annotated[int, Form()] = 365,
    retention_technical_days: Annotated[int, Form()] = 30,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    levels = {
        "level": level, "level_access": level_access, "level_audit": level_audit,
        "level_infra": level_infra, "level_security": level_security,
        "level_technical": level_technical,
    }
    for name, value in levels.items():
        if value not in _LOG_LEVELS:
            return await _render_page(
                request, "pages/admin/system/logging.html",
                title="Logging", active_section="system_logging", user=user,
                values=await _load_keys(db, LOGGING_KEYS),
                error=f"Niveau de log invalide pour {name} : {value}",
            )

    updates = {
        "logging.level": level,
        "logging.format": format.strip(),
        "logging.db_enabled": _to_bool(db_enabled),
        "logging.alert_cooldown_minutes": max(0, _to_int(alert_cooldown_minutes, 15)),
        "logging.level_access": level_access,
        "logging.level_audit": level_audit,
        "logging.level_infra": level_infra,
        "logging.level_security": level_security,
        "logging.level_technical": level_technical,
        "logging.retention_access_days": max(1, _to_int(retention_access_days, 30)),
        "logging.retention_audit_days": max(1, _to_int(retention_audit_days, 365)),
        "logging.retention_infra_days": max(1, _to_int(retention_infra_days, 14)),
        "logging.retention_security_days": max(1, _to_int(retention_security_days, 365)),
        "logging.retention_technical_days": max(1, _to_int(retention_technical_days, 30)),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/logging.html",
        title="Logging", active_section="system_logging", user=user,
        values=await _load_keys(db, LOGGING_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.d — Perf
# ═════════════════════════════════════════════════════════════════════════════
PERF_KEYS = [
    "perf.embedding_batch_size", "perf.embedding_cache_size",
    "perf.embedding_max_concurrent",
    "perf.metrics_window_size",
    "perf.pin_access_threshold", "perf.pinned_cache_size",
    "perf.query_cache_size", "perf.query_cache_ttl",
    "perf.rag_config_cache_ttl",
    "perf.rerank_timeout_ms", "perf.rerank_top_k",
]


@router.get("/perf", response_class=HTMLResponse)
async def perf_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/perf.html",
        title="Performance", active_section="system_perf", user=user,
        values=await _load_keys(db, PERF_KEYS),
    )


@router.post("/perf", response_class=HTMLResponse)
async def perf_post(
    request: Request,
    embedding_batch_size: Annotated[int, Form()] = 100,
    embedding_cache_size: Annotated[int, Form()] = 1000,
    embedding_max_concurrent: Annotated[int, Form()] = 3,
    metrics_window_size: Annotated[int, Form()] = 1000,
    pin_access_threshold: Annotated[int, Form()] = 5,
    pinned_cache_size: Annotated[int, Form()] = 100,
    query_cache_size: Annotated[int, Form()] = 500,
    query_cache_ttl: Annotated[float, Form()] = 300.0,
    rag_config_cache_ttl: Annotated[float, Form()] = 30.0,
    rerank_timeout_ms: Annotated[int, Form()] = 100,
    rerank_top_k: Annotated[int, Form()] = 5,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    updates = {
        "perf.embedding_batch_size": max(1, _to_int(embedding_batch_size, 100)),
        "perf.embedding_cache_size": max(0, _to_int(embedding_cache_size, 1000)),
        "perf.embedding_max_concurrent": max(1, min(_to_int(embedding_max_concurrent, 3), 64)),
        "perf.metrics_window_size": max(10, _to_int(metrics_window_size, 1000)),
        "perf.pin_access_threshold": max(1, _to_int(pin_access_threshold, 5)),
        "perf.pinned_cache_size": max(0, _to_int(pinned_cache_size, 100)),
        "perf.query_cache_size": max(0, _to_int(query_cache_size, 500)),
        "perf.query_cache_ttl": max(0.0, _to_float(query_cache_ttl, 300.0)),
        "perf.rag_config_cache_ttl": max(0.0, _to_float(rag_config_cache_ttl, 30.0)),
        "perf.rerank_timeout_ms": max(0, _to_int(rerank_timeout_ms, 100)),
        "perf.rerank_top_k": max(1, _to_int(rerank_top_k, 5)),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/perf.html",
        title="Performance", active_section="system_perf", user=user,
        values=await _load_keys(db, PERF_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.d — Password Policy (table dédiée, pas system_configs)
# ═════════════════════════════════════════════════════════════════════════════
async def _get_or_create_default_policy(db: AsyncSession):
    """Charge la 1ère policy active, ou en crée une 'default' si aucune existe."""
    from app.features.admin.password_policy.service import PasswordPolicyService
    from sqlalchemy import select
    from app.models import PasswordPolicy

    result = await db.execute(
        select(PasswordPolicy).where(PasswordPolicy.is_active == True).limit(1)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        policy = await PasswordPolicyService.create_policy(
            db, name="default",
            min_length=8, max_length=128,
            require_uppercase=True, require_lowercase=True,
            require_digit=True, require_special=True,
        )
    return policy


@router.get("/password-policy", response_class=HTMLResponse)
async def password_policy_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    policy = await _get_or_create_default_policy(db)
    return templates.TemplateResponse(
        request,
        "pages/admin/system/password-policy.html",
        web_context(
            request,
            title="Politique de mot de passe",
            active_section="system_password",
            user=user,
            policy=policy,
            success=None,
            error=None,
        ),
    )


@router.post("/password-policy", response_class=HTMLResponse)
async def password_policy_post(
    request: Request,
    min_length: Annotated[int, Form()] = 8,
    max_length: Annotated[int, Form()] = 128,
    require_uppercase: Annotated[str | None, Form()] = None,
    require_lowercase: Annotated[str | None, Form()] = None,
    require_digit: Annotated[str | None, Form()] = None,
    require_special: Annotated[str | None, Form()] = None,
    special_characters: Annotated[str, Form()] = "!@#$%^&*()_+-=[]{}|;:,.<>?",
    expire_days: Annotated[int, Form()] = 0,
    history_count: Annotated[int, Form()] = 0,
    max_failed_attempts: Annotated[int, Form()] = 5,
    lockout_duration_minutes: Annotated[int, Form()] = 30,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    policy = await _get_or_create_default_policy(db)

    error: str | None = None
    if min_length < 4:
        error = "min_length doit être ≥ 4."
    elif max_length > 256 or max_length < min_length:
        error = "max_length doit être entre min_length et 256."
    elif expire_days < 0 or history_count < 0 or max_failed_attempts < 0:
        error = "Les durées et compteurs doivent être ≥ 0."

    if error:
        return templates.TemplateResponse(
            request, "pages/admin/system/password-policy.html",
            web_context(
                request, title="Politique de mot de passe",
                active_section="system_password", user=user,
                policy=policy, success=None, error=error,
            ),
            status_code=400,
        )

    from app.features.admin.password_policy.service import PasswordPolicyService

    updated = await PasswordPolicyService.update_policy(
        db, policy.id,
        min_length=int(min_length), max_length=int(max_length),
        require_uppercase=_to_bool(require_uppercase),
        require_lowercase=_to_bool(require_lowercase),
        require_digit=_to_bool(require_digit),
        require_special=_to_bool(require_special),
        special_characters=special_characters,
        expire_days=int(expire_days), history_count=int(history_count),
        max_failed_attempts=int(max_failed_attempts),
        lockout_duration_minutes=int(lockout_duration_minutes),
    )
    return templates.TemplateResponse(
        request, "pages/admin/system/password-policy.html",
        web_context(
            request, title="Politique de mot de passe",
            active_section="system_password", user=user,
            policy=updated, success="Politique enregistrée.", error=None,
        ),
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.e — Geo
# ═════════════════════════════════════════════════════════════════════════════
GEO_KEYS = ["geo.default_country", "geo.allow_change", "geo.require_city", "geo.auto_import"]


@router.get("/geo", response_class=HTMLResponse)
async def geo_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/geo.html",
        title="Géolocalisation", active_section="system_geo", user=user,
        values=await _load_keys(db, GEO_KEYS),
    )


@router.post("/geo", response_class=HTMLResponse)
async def geo_post(
    request: Request,
    default_country: Annotated[str, Form()] = "FR",
    allow_change: Annotated[str | None, Form()] = None,
    require_city: Annotated[str | None, Form()] = None,
    auto_import: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    code = default_country.strip().upper()
    if not (2 <= len(code) <= 3) or not code.isalpha():
        return await _render_page(
            request, "pages/admin/system/geo.html",
            title="Géolocalisation", active_section="system_geo", user=user,
            values=await _load_keys(db, GEO_KEYS),
            error="Code pays invalide (attendu : 2 ou 3 lettres ISO, ex FR, USA).",
        )

    updates = {
        "geo.default_country": code,
        "geo.allow_change": _to_bool(allow_change),
        "geo.require_city": _to_bool(require_city),
        "geo.auto_import": _to_bool(auto_import),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/geo.html",
        title="Géolocalisation", active_section="system_geo", user=user,
        values=await _load_keys(db, GEO_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.e — Chat
# ═════════════════════════════════════════════════════════════════════════════
CHAT_KEYS = [
    "chat.history_enabled", "chat.history_max_tokens", "chat.history_max_turns",
    "chat.rag_reinjection_enabled",
    "chat.summary_enabled", "chat.summary_max_tokens", "chat.summary_trigger_messages",
    "chat.topic_detection_enabled", "chat.topic_similarity_threshold",
]


@router.get("/chat", response_class=HTMLResponse)
async def chat_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/chat.html",
        title="Chat", active_section="system_chat", user=user,
        values=await _load_keys(db, CHAT_KEYS),
    )


@router.post("/chat", response_class=HTMLResponse)
async def chat_post(
    request: Request,
    history_enabled: Annotated[str | None, Form()] = None,
    history_max_tokens: Annotated[int, Form()] = 4096,
    history_max_turns: Annotated[int, Form()] = 5,
    rag_reinjection_enabled: Annotated[str | None, Form()] = None,
    summary_enabled: Annotated[str | None, Form()] = None,
    summary_max_tokens: Annotated[int, Form()] = 500,
    summary_trigger_messages: Annotated[int, Form()] = 10,
    topic_detection_enabled: Annotated[str | None, Form()] = None,
    topic_similarity_threshold: Annotated[float, Form()] = 0.3,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    if not (0.0 <= topic_similarity_threshold <= 1.0):
        return await _render_page(
            request, "pages/admin/system/chat.html",
            title="Chat", active_section="system_chat", user=user,
            values=await _load_keys(db, CHAT_KEYS),
            error="topic_similarity_threshold doit être entre 0.0 et 1.0.",
        )

    updates = {
        "chat.history_enabled": _to_bool(history_enabled),
        "chat.history_max_tokens": max(0, _to_int(history_max_tokens, 4096)),
        "chat.history_max_turns": max(0, min(_to_int(history_max_turns, 5), 100)),
        "chat.rag_reinjection_enabled": _to_bool(rag_reinjection_enabled),
        "chat.summary_enabled": _to_bool(summary_enabled),
        "chat.summary_max_tokens": max(0, _to_int(summary_max_tokens, 500)),
        "chat.summary_trigger_messages": max(1, _to_int(summary_trigger_messages, 10)),
        "chat.topic_detection_enabled": _to_bool(topic_detection_enabled),
        "chat.topic_similarity_threshold": _to_float(topic_similarity_threshold, 0.3),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/chat.html",
        title="Chat", active_section="system_chat", user=user,
        values=await _load_keys(db, CHAT_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.e — Appearance / Branding (sous app.*)
# ═════════════════════════════════════════════════════════════════════════════
APPEARANCE_KEYS = [
    "app.name", "app.title", "app.description", "app.icon", "app.name_prefix",
]


@router.get("/appearance", response_class=HTMLResponse)
async def appearance_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    return await _render_page(
        request, "pages/admin/system/appearance.html",
        title="Apparence / Branding", active_section="system_appearance", user=user,
        values=await _load_keys(db, APPEARANCE_KEYS),
    )


@router.post("/appearance", response_class=HTMLResponse)
async def appearance_post(
    request: Request,
    name: Annotated[str, Form()] = "MY-IA",
    title: Annotated[str, Form()] = "MY-IA Assistant",
    description: Annotated[str, Form()] = "",
    icon: Annotated[str, Form()] = "🤖",
    name_prefix: Annotated[str, Form()] = "MY-IA",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    name_v = name.strip()
    title_v = title.strip()
    if not name_v:
        return await _render_page(
            request, "pages/admin/system/appearance.html",
            title="Apparence / Branding", active_section="system_appearance", user=user,
            values=await _load_keys(db, APPEARANCE_KEYS),
            error="Le nom de l'application est requis.",
        )

    updates = {
        "app.name": name_v,
        "app.title": title_v or name_v,
        "app.description": description.strip(),
        "app.icon": icon.strip() or "🤖",
        "app.name_prefix": name_prefix.strip() or name_v,
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request, "pages/admin/system/appearance.html",
        title="Apparence / Branding", active_section="system_appearance", user=user,
        values=await _load_keys(db, APPEARANCE_KEYS),
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error=" ; ".join(errors) if errors else None,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.8.e — Conversation Modes (table dédiée, CRUD list+create+delete)
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/modes", response_class=HTMLResponse)
async def modes_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    from sqlalchemy import select
    from app.models import ConversationMode

    result = await db.execute(select(ConversationMode).order_by(ConversationMode.name))
    modes = list(result.scalars().all())
    return templates.TemplateResponse(
        request, "pages/admin/system/modes.html",
        web_context(
            request, title="Modes de conversation",
            active_section="system_modes", user=user,
            modes=modes, success=None, error=None,
        ),
    )


@router.post("/modes", response_class=HTMLResponse)
async def modes_create(
    request: Request,
    name: Annotated[str, Form()],
    display_name: Annotated[str, Form()],
    description: Annotated[str, Form()] = "",
    system_prompt: Annotated[str, Form()] = "",
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err

    from sqlalchemy import select
    from app.models import ConversationMode

    name_v = name.strip().lower()
    display = display_name.strip()
    if not name_v or not display:
        existing = (
            await db.execute(select(ConversationMode).order_by(ConversationMode.name))
        ).scalars().all()
        return templates.TemplateResponse(
            request, "pages/admin/system/modes.html",
            web_context(
                request, title="Modes de conversation",
                active_section="system_modes", user=user,
                modes=list(existing),
                error="Nom et libellé sont requis.", success=None,
            ),
            status_code=400,
        )

    duplicate = await db.execute(
        select(ConversationMode).where(ConversationMode.name == name_v)
    )
    if duplicate.scalar_one_or_none() is not None:
        existing = (
            await db.execute(select(ConversationMode).order_by(ConversationMode.name))
        ).scalars().all()
        return templates.TemplateResponse(
            request, "pages/admin/system/modes.html",
            web_context(
                request, title="Modes de conversation",
                active_section="system_modes", user=user,
                modes=list(existing),
                error=f"Le mode '{name_v}' existe déjà.", success=None,
            ),
            status_code=409,
        )

    new_mode = ConversationMode(
        name=name_v, display_name=display,
        description=description.strip() or None,
        system_prompt=system_prompt.strip() or None,
    )
    db.add(new_mode)
    await db.commit()
    logger.info("Admin %s created conversation mode '%s'", user.get("email"), name_v)

    refreshed = (
        await db.execute(select(ConversationMode).order_by(ConversationMode.name))
    ).scalars().all()
    return templates.TemplateResponse(
        request, "pages/admin/system/modes.html",
        web_context(
            request, title="Modes de conversation",
            active_section="system_modes", user=user,
            modes=list(refreshed),
            success=f"Mode '{name_v}' créé.", error=None,
        ),
    )


@router.delete("/modes/{mode_id}", response_class=Response)
async def modes_delete(
    request: Request,
    mode_id: int,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> Response:
    from sqlalchemy import select
    from app.models import ConversationMode

    mode = (
        await db.execute(select(ConversationMode).where(ConversationMode.id == mode_id))
    ).scalar_one_or_none()
    if mode is None:
        return Response(status_code=404)
    try:
        await db.delete(mode)
        await db.commit()
        logger.info("Admin %s deleted conversation mode '%s'", user.get("email"), mode.name)
    except Exception as e:
        await db.rollback()
        logger.error("Erreur suppression mode %s: %s", mode_id, e)
        return HTMLResponse(
            "<div class='toast toast--error'>Suppression impossible.</div>", status_code=500
        )
    return Response(status_code=200, content="")


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.5.a — LLM admin actions (modèles, start/stop, health, RAG test)
# ═════════════════════════════════════════════════════════════════════════════
import httpx as _httpx

# --- Health check live ---

@router.get("/llm/health", response_class=HTMLResponse)
async def llm_health(
    request: Request,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    """Health check live des providers (parité V1 system/llm.js healthCheck)."""
    out = []
    # Ollama
    try:
        from app.features.admin.config.service import _runtime_overrides
        host = _runtime_overrides.get("llm.ollama_host", "host.docker.internal")
        port = _runtime_overrides.get("llm.ollama_port", 11434)
        async with _httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{host}:{port}/api/tags")
        ok = r.status_code == 200
        nb = len(r.json().get("models", [])) if ok else 0
        out.append({"name": "Ollama", "ok": ok, "info": f"{nb} modèle(s)" if ok else f"HTTP {r.status_code}"})
    except Exception as exc:
        out.append({"name": "Ollama", "ok": False, "info": str(exc)[:60]})
    # llamacpp (port défaut 8081)
    try:
        from app.features.admin.config.service import _runtime_overrides
        host = _runtime_overrides.get("llm.llamacpp_host", "host.docker.internal")
        port = _runtime_overrides.get("llm.llamacpp_port", 8081)
        async with _httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{host}:{port}/health")
        ok = r.status_code == 200
        out.append({"name": "llamacpp", "ok": ok, "info": "OK" if ok else f"HTTP {r.status_code}"})
    except Exception as exc:
        out.append({"name": "llamacpp", "ok": False, "info": str(exc)[:60]})
    # Render
    parts = ["<div class='llm-health'>"]
    for p in out:
        cls = "ok" if p["ok"] else "error"
        icon = "✓" if p["ok"] else "✗"
        parts.append(
            f"<div class='llm-health__row llm-health__row--{cls}'>"
            f"<strong>{icon} {p['name']}</strong> <small>{p['info']}</small></div>"
        )
    parts.append("</div>")
    return HTMLResponse("".join(parts))


# --- Ollama models ---

@router.get("/llm/ollama/models", response_class=HTMLResponse)
async def ollama_models_list(
    request: Request,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    """Liste modèles Ollama installés (parité V1)."""
    try:
        from app.features.admin.config.service import _runtime_overrides
        host = _runtime_overrides.get("llm.ollama_host", "host.docker.internal")
        port = _runtime_overrides.get("llm.ollama_port", 11434)
        async with _httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"http://{host}:{port}/api/tags")
            r.raise_for_status()
        models = r.json().get("models", [])
    except Exception as exc:
        return HTMLResponse(
            f"<div class='toast toast--error'>Erreur Ollama : {exc}</div>", status_code=200
        )
    if not models:
        return HTMLResponse("<p style='color:var(--color-fg-muted)'>Aucun modèle installé.</p>")
    parts = ["<table class='admin-mini-table'><thead><tr><th>Nom</th><th>Taille</th><th>Modifié</th><th></th></tr></thead><tbody>"]
    for m in models:
        name = m.get("name", "")
        size_mb = round(m.get("size", 0) / 1024 / 1024, 1)
        modified = m.get("modified_at", "")[:10]
        parts.append(
            f"<tr><td><code>{name}</code></td><td>{size_mb} Mo</td><td>{modified}</td>"
            f"<td><button type='button' class='admin-action admin-action--danger' "
            f"hx-delete='/web/admin/system/llm/ollama/models/{name}' "
            f"hx-confirm='Supprimer le modèle {name} ?' "
            f"hx-target='#ollama-models' hx-swap='outerHTML'>×</button></td></tr>"
        )
    parts.append("</tbody></table>")
    return HTMLResponse(f"<div id='ollama-models'>{''.join(parts)}</div>")


@router.post("/llm/ollama/models/pull", response_class=HTMLResponse)
async def ollama_pull_model(
    request: Request,
    model: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    name = (model or "").strip()
    if not name:
        return HTMLResponse("<div class='toast toast--error'>Nom requis.</div>", status_code=400)
    try:
        from app.features.admin.config.service import _runtime_overrides
        host = _runtime_overrides.get("llm.ollama_host", "host.docker.internal")
        port = _runtime_overrides.get("llm.ollama_port", 11434)
        # Pull synchrone (bloquant — Ollama API stream)
        async with _httpx.AsyncClient(timeout=600.0) as c:
            r = await c.post(f"http://{host}:{port}/api/pull", json={"name": name})
            r.raise_for_status()
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Pull échoué : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>Modèle {name} téléchargé.</div>",
        headers={"HX-Trigger": "ollama-models-refresh"},
    )


@router.delete("/llm/ollama/models/{model_name:path}", response_class=HTMLResponse)
async def ollama_delete_model(
    request: Request,
    model_name: str,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    try:
        from app.features.admin.config.service import _runtime_overrides
        host = _runtime_overrides.get("llm.ollama_host", "host.docker.internal")
        port = _runtime_overrides.get("llm.ollama_port", 11434)
        async with _httpx.AsyncClient(timeout=30.0) as c:
            r = await c.request("DELETE", f"http://{host}:{port}/api/delete", json={"name": model_name})
            r.raise_for_status()
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>Modèle {model_name} supprimé.</div>",
        headers={"HX-Trigger": "ollama-models-refresh"},
    )


# --- llamacpp control + models ---

@router.post("/llm/llamacpp/start", response_class=HTMLResponse)
async def llamacpp_start(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    try:
        from app.features.admin.llm_control.service import LLMControlService
        await LLMControlService.start_llamacpp()
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Start échoué : {exc}</div>", status_code=500)
    return HTMLResponse("<div class='toast toast--success'>llamacpp démarré.</div>")


@router.post("/llm/llamacpp/stop", response_class=HTMLResponse)
async def llamacpp_stop(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    try:
        from app.features.admin.llm_control.service import LLMControlService
        await LLMControlService.stop_llamacpp()
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Stop échoué : {exc}</div>", status_code=500)
    return HTMLResponse("<div class='toast toast--success'>llamacpp arrêté.</div>")


@router.post("/llm/llamacpp/restart", response_class=HTMLResponse)
async def llamacpp_restart(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    try:
        from app.features.admin.llm_control.service import LLMControlService
        await LLMControlService.restart_llamacpp()
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Restart échoué : {exc}</div>", status_code=500)
    return HTMLResponse("<div class='toast toast--success'>llamacpp redémarré.</div>")


@router.get("/llm/llamacpp/models", response_class=HTMLResponse)
async def llamacpp_models_list(
    request: Request,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    """Liste modèles GGUF locaux (parité V1)."""
    import os
    models_dir = "/code/models"
    rows = []
    try:
        if os.path.isdir(models_dir):
            for fn in sorted(os.listdir(models_dir)):
                if fn.endswith(".gguf"):
                    full = os.path.join(models_dir, fn)
                    size_mb = round(os.path.getsize(full) / 1024 / 1024, 1)
                    rows.append({"name": fn, "size": size_mb})
    except Exception:
        pass
    if not rows:
        return HTMLResponse("<p style='color:var(--color-fg-muted)'>Aucun modèle GGUF dans /code/models.</p>")
    parts = ["<table class='admin-mini-table'><thead><tr><th>Fichier</th><th>Taille</th><th></th></tr></thead><tbody>"]
    for r in rows:
        parts.append(
            f"<tr><td><code>{r['name']}</code></td><td>{r['size']} Mo</td>"
            f"<td><button type='button' class='admin-action admin-action--danger' "
            f"hx-delete='/web/admin/system/llm/llamacpp/models/{r['name']}' "
            f"hx-confirm='Supprimer {r['name']} ?' "
            f"hx-target='#llamacpp-models' hx-swap='outerHTML'>×</button></td></tr>"
        )
    parts.append("</tbody></table>")
    return HTMLResponse(f"<div id='llamacpp-models'>{''.join(parts)}</div>")


@router.delete("/llm/llamacpp/models/{filename:path}", response_class=HTMLResponse)
async def llamacpp_delete_model(
    request: Request,
    filename: str,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    import os
    if "/" in filename or ".." in filename:
        return HTMLResponse("<div class='toast toast--error'>Nom invalide.</div>", status_code=400)
    full = f"/code/models/{filename}"
    try:
        if os.path.isfile(full):
            os.remove(full)
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{filename} supprimé.</div>",
        headers={"HX-Trigger": "llamacpp-models-refresh"},
    )


# --- RAG search test ---

@router.post("/rag/test", response_class=HTMLResponse)
async def rag_test_search(
    request: Request,
    query: Annotated[str, Form()],
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    """Test interactif RAG (parité V1 testRagSearch)."""
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    q = (query or "").strip()
    if not q:
        return HTMLResponse("<div class='toast toast--error'>Question vide.</div>", status_code=400)
    try:
        from app.features.sources.context import get_smart_context
        from app.models import User as _U
        admin_user = (await db.execute(__import__("sqlalchemy").select(_U).where(_U.id == __import__("uuid").UUID(user["id"])))).unique().scalar_one_or_none()
        ctx = await get_smart_context(
            db=db, user=admin_user, query=q, top_k=5,
        )
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Erreur : {exc}</div>", status_code=500)
    if not ctx or not getattr(ctx, "chunks", None):
        return HTMLResponse("<div class='toast'>Aucun chunk trouvé.</div>")
    parts = [f"<div><strong>{len(ctx.chunks)} chunk(s) trouvé(s)</strong></div><ul>"]
    for c in ctx.chunks[:10]:
        text = (c.get("content", "") if isinstance(c, dict) else getattr(c, "content", ""))[:300]
        score = c.get("score", 0) if isinstance(c, dict) else getattr(c, "score", 0)
        parts.append(f"<li><small>score={score:.3f}</small><br>{text}…</li>")
    parts.append("</ul>")
    return HTMLResponse("".join(parts))


# ═════════════════════════════════════════════════════════════════════════════
#  Phase 3.5.b — Geo + Indexation
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/geo/stats", response_class=HTMLResponse)
async def geo_stats(
    request: Request,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    try:
        from app.features.admin.geo.service import GeoAdminService
        stats = await GeoAdminService.get_stats(db)
        cd = stats.cities_by_country if hasattr(stats, "cities_by_country") else {}
        items = []
        for code, n in (cd.items() if isinstance(cd, dict) else []):
            items.append(f"<li><code>{code}</code> · {n} ville(s)</li>")
        countries_total = getattr(stats, "countries_total", 0)
        countries_active = getattr(stats, "countries_active", 0)
        cities_total = getattr(stats, "cities_total", 0)
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Erreur stats : {exc}</div>")
    return HTMLResponse(
        f"""<dl class='docs-modal__meta'>
        <dt>Pays total</dt><dd>{countries_total}</dd>
        <dt>Pays actifs</dt><dd>{countries_active}</dd>
        <dt>Villes total</dt><dd>{cities_total}</dd>
        </dl>
        <ul style='font-size:var(--text-xs); columns:2'>{''.join(items)}</ul>"""
    )


@router.post("/geo/import/countries", response_class=HTMLResponse)
async def geo_import_countries(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    try:
        from app.features.admin.geo.service import GeoAdminService
        result = await GeoAdminService.import_countries(db)
        n = getattr(result, "imported", 0)
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(f"<div class='toast toast--success'>{n} pays importés.</div>")


@router.post("/geo/export/countries", response_class=HTMLResponse)
async def geo_export_countries(
    request: Request,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    try:
        from app.features.admin.geo.service import GeoAdminService
        result = await GeoAdminService.export_countries(db)
        n = getattr(result, "exported", 0)
        path = getattr(result, "file_path", "")
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(f"<div class='toast toast--success'>{n} pays exportés vers <code>{path}</code>.</div>")


@router.post("/geo/countries/{code}/toggle", response_class=HTMLResponse)
async def geo_toggle_country(
    request: Request,
    code: str,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db=Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse("<div class='toast toast--error'>Session expirée.</div>", status_code=400)
    try:
        from app.features.admin.geo.service import GeoAdminService
        await GeoAdminService.toggle_country_active(db, code.upper())
    except Exception as exc:
        return HTMLResponse(f"<div class='toast toast--error'>Échec : {exc}</div>", status_code=500)
    return HTMLResponse(
        f"<div class='toast toast--success'>{code.upper()} basculé.</div>",
        headers={"HX-Trigger": "geo-stats-refresh"},
    )


# --- Indexation page (nouvelle, BLOQUANT V1 absent) ---

_INDEXATION_KEYS = [
    "sources.scheduler_enabled",
    "sources.scheduler_check_interval_minutes",
    "sources.scheduler_cleanup_docs_interval_hours",
    "sources.scheduler_cleanup_logs_interval_days",
    "sources.freshness_warning_hours",
    "sources.freshness_expired_hours",
]


@router.get("/indexation", response_class=HTMLResponse)
async def indexation_get(
    request: Request,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    """Page configuration scheduler indexation (parité V1 system/indexation)."""
    values = await _load_keys(db, _INDEXATION_KEYS)
    return await _render_page(
        request,
        "pages/admin/system/indexation.html",
        title="Scheduler Indexation",
        active_section="system_indexation",
        user=user,
        values=values,
    )


@router.post("/indexation", response_class=HTMLResponse)
async def indexation_post(
    request: Request,
    scheduler_enabled: Annotated[str | None, Form()] = None,
    check_interval: Annotated[int, Form()] = 15,
    cleanup_docs_hours: Annotated[int, Form()] = 1,
    cleanup_logs_days: Annotated[int, Form()] = 1,
    freshness_warning: Annotated[int, Form()] = 12,
    freshness_expired: Annotated[int, Form()] = 24,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_admin),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if (err := _csrf_or_400(request, csrf_token)):
        return err
    updates = {
        "sources.scheduler_enabled": bool(scheduler_enabled),
        "sources.scheduler_check_interval_minutes": _to_int(check_interval, 15),
        "sources.scheduler_cleanup_docs_interval_hours": _to_int(cleanup_docs_hours, 1),
        "sources.scheduler_cleanup_logs_interval_days": _to_int(cleanup_logs_days, 1),
        "sources.freshness_warning_hours": _to_int(freshness_warning, 12),
        "sources.freshness_expired_hours": _to_int(freshness_expired, 24),
    }
    saved, errors = await _bulk_set(db, user, updates)
    return await _render_page(
        request,
        "pages/admin/system/indexation.html",
        title="Scheduler Indexation",
        active_section="system_indexation",
        user=user,
        values=updates,
        success=f"{saved} clé(s) enregistrée(s)." if not errors else None,
        error="; ".join(errors) if errors else None,
    )
