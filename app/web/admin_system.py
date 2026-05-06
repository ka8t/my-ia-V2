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
from fastapi.responses import HTMLResponse
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
