"""Web chat routes (HTML — Phase 3.3.a).

Pattern HTMX + SSE pour le streaming :

  1. ``POST /web/chat/messages``
        - reçoit ``{ query, conversation_id? }`` (form data)
        - crée la conversation si nécessaire (collection personnelle auto-créée)
        - stocke ``{ query, conversation_id, user_id }`` dans un dict in-memory
          keyé par ``stream_id`` (TTL ~5 min, multi-worker non supporté en V2)
        - renvoie un fragment HTML : la bulle utilisateur + une bulle assistant
          *vide* avec ``sse-connect=/web/chat/stream/{stream_id}``

  2. ``GET /web/chat/stream/{stream_id}``
        - dépile le contexte mis de côté à l'étape 1
        - appelle ``ChatService.chat_stream`` (qui sauvegarde les messages)
        - convertit son flux NDJSON en événements SSE consommables par HTMX

Limitations connues V2 dev :
  - dict en mémoire ⇒ non multi-worker. À migrer vers Redis si UVICORN_WORKERS>1.
  - Pas de rendu Markdown (Phase 3.3.d).
"""
from __future__ import annotations

import asyncio
import html as _html
import json
import logging
import secrets
import time
import uuid
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.features.chat.service import ChatService
from app.features.conversations.repository import ConversationRepository, MessageRepository
from app.features.conversations.service import ConversationService
from app.models import Collection, Conversation, Message, User
from app.web.deps import require_web_auth
from app.web.jinja import TEMPLATES_DIR, make_templates, verify_csrf_token, web_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web/chat", tags=["Web - Chat"])
templates = make_templates(TEMPLATES_DIR)


# ─────────────────────────────────────────────────────────────────────────────
#  In-memory pending stream store
# ─────────────────────────────────────────────────────────────────────────────
_PENDING_STREAMS: dict[str, dict] = {}
_PENDING_TTL_SECONDS = 300  # 5 min


def _gc_pending_streams() -> None:
    """Drop entries older than the TTL."""
    cutoff = time.time() - _PENDING_TTL_SECONDS
    for sid in [s for s, v in _PENDING_STREAMS.items() if v["created_at"] < cutoff]:
        _PENDING_STREAMS.pop(sid, None)


def _put_pending(query: str, conversation_id: str, user_id: str) -> str:
    _gc_pending_streams()
    sid = secrets.token_urlsafe(24)
    _PENDING_STREAMS[sid] = {
        "query": query,
        "conversation_id": conversation_id,
        "user_id": user_id,
        "created_at": time.time(),
    }
    return sid


def _pop_pending(stream_id: str) -> dict | None:
    """One-shot consume — defeats replay even within TTL."""
    return _PENDING_STREAMS.pop(stream_id, None)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _get_or_create_user_collection(
    db: AsyncSession, user_id: uuid.UUID
) -> Collection:
    """Ensure the user has a personal Collection. Creates one if absent."""
    result = await db.execute(select(Collection).where(Collection.owner_id == user_id))
    coll = result.unique().scalar_one_or_none()
    if coll:
        return coll

    coll = Collection(
        name=f"user_{user_id}",
        display_name="Personnel",
        type="private",
        owner_id=user_id,
    )
    db.add(coll)
    await db.commit()
    await db.refresh(coll)
    logger.info("Created personal collection %s for user %s", coll.id, user_id)
    return coll


async def _load_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> tuple[Conversation | None, list[Message]]:
    """Return (conversation, ordered messages) or (None, []) if not found."""
    conv = await ConversationRepository.get_by_id(db, conversation_id, user_id)
    if conv is None:
        return None, []
    messages = await MessageRepository.list_by_conversation(db, conversation_id)
    return conv, messages


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/chat — empty state
#  GET /web/chat/{conversation_id} — with history
# ─────────────────────────────────────────────────────────────────────────────
SUGGESTIONS = [
    "Résume-moi les points clés de mes documents récents.",
    "Quelles sont les sources disponibles dans ma bibliothèque ?",
    "Aide-moi à rédiger un compte-rendu structuré.",
    "Compare deux documents et souligne les différences.",
]


async def _load_sidebar_conversations(
    db: AsyncSession, user_id: uuid.UUID, limit: int = 50
) -> list:
    """Return the user's most recent (non-archived) conversations for the sidebar."""
    convs, _total = await ConversationRepository.list_by_user(
        db, user_id, limit=limit, offset=0
    )
    return [c for c in convs if c.archived_at is None]


@router.get("", response_class=HTMLResponse)
async def chat_index(
    request: Request,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    sidebar_convs = await _load_sidebar_conversations(db, uuid.UUID(user["id"]))
    return templates.TemplateResponse(
        request,
        "pages/chat/chat.html",
        web_context(
            request,
            title="Chat",
            user=user,
            conversation=None,
            messages=[],
            suggestions=SUGGESTIONS,
            sidebar_conversations=sidebar_convs,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/chat/sidebar — partial used by HTMX to refresh the sidebar
#  (must be declared BEFORE the dynamic /{conversation_id} route below)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/sidebar", response_class=HTMLResponse)
async def chat_sidebar(
    request: Request,
    active: str | None = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    sidebar_convs = await _load_sidebar_conversations(db, uuid.UUID(user["id"]))
    active_id: uuid.UUID | None = None
    if active:
        try:
            active_id = uuid.UUID(active)
        except ValueError:
            active_id = None
    return templates.TemplateResponse(
        request,
        "partials/chat/sidebar-list.html",
        web_context(
            request,
            sidebar_conversations=sidebar_convs,
            active_id=active_id,
        ),
    )


@router.get("/{conversation_id}", response_class=HTMLResponse)
async def chat_conversation(
    request: Request,
    conversation_id: uuid.UUID,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    user_uuid = uuid.UUID(user["id"])
    conv, messages = await _load_conversation(db, conversation_id, user_uuid)
    sidebar_convs = await _load_sidebar_conversations(db, user_uuid)

    if conv is None:
        return templates.TemplateResponse(
            request,
            "pages/chat/chat.html",
            web_context(
                request,
                title="Chat",
                user=user,
                conversation=None,
                messages=[],
                suggestions=SUGGESTIONS,
                sidebar_conversations=sidebar_convs,
                not_found=True,
            ),
        )

    return templates.TemplateResponse(
        request,
        "pages/chat/chat.html",
        web_context(
            request,
            title=conv.title,
            user=user,
            conversation=conv,
            messages=messages,
            suggestions=[],
            sidebar_conversations=sidebar_convs,
        ),
    )


# ─────────────────────────────────────────────────────────────────────────────
#  POST /web/chat/messages — submit user query, return user+assistant bubbles
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/messages", response_class=HTMLResponse)
async def submit_message(
    request: Request,
    query: Annotated[str, Form()],
    conversation_id: Annotated[str | None, Form()] = None,
    csrf_token: Annotated[str | None, Form()] = None,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
) -> HTMLResponse:
    if not verify_csrf_token(request, csrf_token):
        return HTMLResponse(
            "<div class='toast toast--error'>Session expirée. Rechargez la page.</div>",
            status_code=400,
        )

    query = (query or "").strip()
    if not query:
        return HTMLResponse(
            "<div class='toast toast--error'>Le message est vide.</div>",
            status_code=400,
        )

    user_id = uuid.UUID(user["id"])

    # 1) Get-or-create conversation
    coll = await _get_or_create_user_collection(db, user_id)

    if conversation_id:
        try:
            conv = await ConversationRepository.get_by_id(
                db, uuid.UUID(conversation_id), user_id
            )
        except ValueError:
            conv = None
    else:
        conv = None

    if conv is None:
        conv = await ConversationRepository.create(
            db,
            user_id=user_id,
            title=query[:80] or "Nouvelle conversation",
            collection_id=coll.id,
            mode_id=1,
        )

    # 2) Stash the query for the SSE GET that follows
    stream_id = _put_pending(query, str(conv.id), str(user_id))

    # 3) Render two bubbles back-to-back. The assistant bubble carries the
    #    sse-connect attribute that opens the stream.
    response = templates.TemplateResponse(
        request,
        "partials/chat/message-pair.html",
        web_context(
            request,
            query=query,
            stream_id=stream_id,
            conversation_id=str(conv.id),
        ),
    )
    # Push the URL so a browser refresh stays on the conversation
    response.headers["HX-Push-Url"] = f"/web/chat/{conv.id}"
    return response


# ─────────────────────────────────────────────────────────────────────────────
#  GET /web/chat/stream/{stream_id} — SSE wrapper around ChatService
# ─────────────────────────────────────────────────────────────────────────────
def _sse(event: str, data: str = "") -> bytes:
    """Format an SSE frame. Multi-line data is split into ``data:`` lines."""
    out = [f"event: {event}"]
    for line in (data or "").splitlines() or [""]:
        out.append(f"data: {line}")
    out.append("")  # blank line terminates the frame
    out.append("")
    return ("\n".join(out)).encode("utf-8")


def _render_sources_html(sources: list) -> str:
    """Render the sources list as a static HTML fragment swapped into the bubble."""
    if not sources:
        return ""
    parts = ['<div class="chat-sources" data-rendered="1">']
    parts.append(
        '<div class="chat-sources__header">'
        '<span class="chat-sources__count">'
        f'{len(sources)} source{"s" if len(sources) > 1 else ""}'
        '</span>'
        '<span class="chat-sources__label">RÉFÉRENCES UTILISÉES</span>'
        '</div>'
    )
    parts.append('<ul class="chat-sources__list">')
    for s in sources:
        display = _html.escape(str(s.get("display_name") or s.get("technical_name") or "—"))
        kind = "document" if s.get("type") == "document" else "source"
        kind_label = "Document" if kind == "document" else "Source"
        parts.append(
            f'<li class="chat-source chat-source--{kind}">'
            f'<span class="chat-source__kind">{kind_label}</span>'
            f'<span class="chat-source__name" title="{display}">{display}</span>'
            f'</li>'
        )
    parts.append('</ul></div>')
    return "".join(parts)


async def _ndjson_to_sse(
    ndjson_stream: AsyncIterator[str],
) -> AsyncIterator[bytes]:
    """Translate the ChatService NDJSON stream into HTMX-friendly SSE events.

    Events emitted:
      - ``event: sources``  ``data: <html fragment with source cards>``
      - ``event: token``    ``data: <html-escaped chunk>``
      - ``event: done``     ``data:``  (closes the stream client-side)
      - ``event: error``    ``data: <html-escaped message>``
    """
    try:
        async for raw in ndjson_stream:
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if "response" in payload:
                # token chunk — html-escape so '<' / '&' don't break the DOM
                yield _sse("token", _html.escape(payload["response"]))
                await asyncio.sleep(0)  # flush

            elif "sources" in payload:
                html_fragment = _render_sources_html(payload["sources"] or [])
                if html_fragment:
                    yield _sse("sources", html_fragment)
                    await asyncio.sleep(0)

            elif payload.get("error"):
                yield _sse("error", _html.escape(str(payload.get("error"))))
                yield _sse("done", "")
                return

            elif payload.get("done"):
                yield _sse("done", "")
                return

            # ignore other payload kinds (suggestions, metadata…)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("SSE adapter crashed: %s", exc)
        yield _sse("error", "Une erreur interne est survenue.")
        yield _sse("done", "")


@router.get("/stream/{stream_id}")
async def chat_stream(
    stream_id: str,
    user: dict = Depends(require_web_auth),
    db: AsyncSession = Depends(get_async_session),
):
    pending = _pop_pending(stream_id)
    if pending is None:
        # Unknown / expired / replayed — close immediately
        async def _gone() -> AsyncIterator[bytes]:
            yield _sse("error", "Lien de stream invalide ou expiré.")
            yield _sse("done", "")

        return StreamingResponse(
            _gone(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if pending["user_id"] != user["id"]:
        # Don't leak someone else's stream
        async def _forbidden() -> AsyncIterator[bytes]:
            yield _sse("error", "Stream non autorisé.")
            yield _sse("done", "")

        return StreamingResponse(
            _forbidden(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ChatService.chat_stream handles message persistence (user + assistant).
    # We let it set the conversation_id so it knows where to save.
    ndjson_iter = ChatService.chat_stream(
        pending["query"],
        user_id=pending["user_id"],
        db=db,
        collection_name=None,
        collection_display_name=None,
        source_ids=None,
        conversation_id=pending["conversation_id"],
        language="fr",
        mode_id=None,
        rag_mode="auto",
    )

    return StreamingResponse(
        _ndjson_to_sse(ndjson_iter),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
