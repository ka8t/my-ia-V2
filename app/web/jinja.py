"""Jinja2 helpers for web templates (Phase 2.4).

Provides:
- ``t(key)``                 — i18n lookup against ``app/locales/{lang}.json``
- ``get_or_create_csrf_token`` / ``get_current_user`` — request-scoped helpers
- ``web_context(request)``   — standard context dict for HTML routes
- ``make_templates()``       — factory wiring globals into Jinja2Templates
"""
from __future__ import annotations

import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).parent.parent
LOCALES_DIR = APP_DIR / "locales"
TEMPLATES_DIR = APP_DIR / "templates"

DEFAULT_LANG = "fr"
SUPPORTED_LANGS = ("fr", "en")


# ─────────────────────────────────────────────────────────────────────────────
#  i18n
# ─────────────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=8)
def _load_locale(lang: str) -> dict:
    """Load and cache a locale JSON file. Returns empty dict if missing."""
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def t(key: str, lang: str = DEFAULT_LANG, default: str | None = None, **kwargs: Any) -> str:
    """Lookup a (dot-nested) key in the locale dict.

    Supports ``{placeholder}`` style interpolation via kwargs:
        t('greeting', name='Alice')  →  'Bonjour, Alice.'

    Falls back to ``default`` (or the key itself) when missing.
    """
    parts = key.split(".")
    value: Any = _load_locale(lang)
    for p in parts:
        if isinstance(value, dict) and p in value:
            value = value[p]
        else:
            return default if default is not None else key

    if not isinstance(value, str):
        return default if default is not None else key

    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value


# ─────────────────────────────────────────────────────────────────────────────
#  Request-scoped helpers
# ─────────────────────────────────────────────────────────────────────────────
def get_or_create_csrf_token(request: Request) -> str:
    """Get the CSRF token from the session, creating one if absent."""
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def verify_csrf_token(request: Request, submitted: str | None) -> bool:
    """Constant-time comparison of submitted token vs session token."""
    expected = request.session.get("csrf_token")
    if not expected or not submitted:
        return False
    return secrets.compare_digest(expected, submitted)


def get_current_user(request: Request) -> dict | None:
    """Return the user dict stored in the session, or None.

    Populated by ``POST /web/login`` (Phase 2.5).
    Shape: ``{"id": str, "email": str, "is_superuser": bool, ...}``
    """
    return request.session.get("user")


def web_context(request: Request, **extra: Any) -> dict:
    """Build the standard Jinja context for any HTML route.

    Always includes: ``csrf_token``, ``current_user``, ``user_theme``,
    ``user_lang``, ``debug_mode``. Stocké en session pour éviter un
    aller-retour DB à chaque render. La session est mise à jour à
    /web/preferences/settings et au login.
    """
    user = get_current_user(request)
    theme = (user or {}).get("theme") or "auto"
    lang = (user or {}).get("language") or "fr"
    # Debug banner activé si debug_endpoints_enabled en BDD
    try:
        from app.features.admin.config.service import _runtime_overrides
        debug_mode = bool(_runtime_overrides.get("debug_endpoints_enabled", False))
    except Exception:
        debug_mode = False
    return {
        "csrf_token": get_or_create_csrf_token(request),
        "current_user": user,
        "user_theme": theme,
        "user_lang": lang,
        "debug_mode": debug_mode,
        **extra,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Factory
# ─────────────────────────────────────────────────────────────────────────────
def make_templates(directory: str | Path = TEMPLATES_DIR) -> Jinja2Templates:
    """Return a ``Jinja2Templates`` with project globals wired in.

    Globals available in every template (without explicit import):
      - ``t(key, lang='fr', default=None, **kwargs)`` — i18n lookup
    """
    templates = Jinja2Templates(directory=str(directory))
    templates.env.globals["t"] = t
    return templates
