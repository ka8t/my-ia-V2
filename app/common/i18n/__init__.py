"""
Service d'internationalisation (i18n) pour le backend MY-IA.

Usage:
    from app.common.i18n import t, get_lang_from_request

    # Dans un endpoint avec Request
    @router.get("/example")
    async def example(request: Request):
        lang = get_lang_from_request(request)
        message = t("error_not_found", lang)
        raise HTTPException(status_code=404, detail=message)

    # Avec placeholders
    message = t("error_user_exists", lang, email="test@example.com")
    # -> "L'utilisateur avec l'email 'test@example.com' existe deja"
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional
from functools import lru_cache

from fastapi import Request

logger = logging.getLogger(__name__)

# Langues supportees
SUPPORTED_LANGUAGES = ["fr", "en"]
DEFAULT_LANGUAGE = "fr"

# Cache des traductions
_translations: dict[str, dict] = {}


def _load_translations() -> None:
    """Charge les fichiers de traduction JSON."""
    global _translations

    locales_dir = Path(__file__).parent / "locales"
    base_dir = os.path.realpath(str(locales_dir))

    for lang in SUPPORTED_LANGUAGES:
        # Validation : le code langue doit etre alphanumerique (pas de path traversal)
        if not re.match(r'^[a-z]{2}$', lang):
            logger.warning(f"Invalid language code skipped: '{lang}'")
            continue
        file_path = locales_dir / f"{lang}.json"
        # Securite : verifier que le chemin reste dans le dossier locales
        real_path = os.path.realpath(str(file_path))
        if not real_path.startswith(base_dir + os.sep) and real_path != base_dir:
            logger.warning(f"Path traversal attempt blocked for lang '{lang}'")
            continue
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    _translations[lang] = json.load(f)
                logger.info(f"Loaded {len(_translations[lang])} translations for '{lang}'")
            except Exception as e:
                logger.error(f"Error loading translations for '{lang}': {e}")
                _translations[lang] = {}
        else:
            logger.warning(f"Translation file not found: {file_path}")
            _translations[lang] = {}


def reload_translations() -> None:
    """Recharge les traductions depuis les fichiers."""
    global _translations
    _translations = {}
    _load_translations()


def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """
    Traduit une cle dans la langue specifiee.

    Args:
        key: Cle de traduction (ex: "error_not_found")
        lang: Code langue (fr, en). Si None, utilise DEFAULT_LANGUAGE
        **kwargs: Variables a injecter dans le message

    Returns:
        Message traduit ou la cle si non trouve

    Examples:
        t("error_not_found", "fr")
        t("error_user_exists", "en", email="test@example.com")
    """
    # Charger les traductions si pas encore fait
    if not _translations:
        _load_translations()

    # Langue par defaut si non specifiee
    if lang is None or lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE

    # Recuperer la traduction
    translations = _translations.get(lang, {})
    message = translations.get(key)

    # Fallback sur la langue par defaut
    if message is None and lang != DEFAULT_LANGUAGE:
        message = _translations.get(DEFAULT_LANGUAGE, {}).get(key)

    # Si toujours pas trouve, retourner la cle
    if message is None:
        logger.debug(f"Translation not found: '{key}' for lang '{lang}'")
        return key

    # Injecter les variables
    if kwargs:
        try:
            message = message.format(**kwargs)
        except KeyError as e:
            logger.warning(f"Missing placeholder in translation '{key}': {e}")

    return message


def get_lang_from_request(request: Request) -> str:
    """
    Detecte la langue preferee depuis la requete HTTP.

    Ordre de priorite:
    1. Query param ?lang=xx
    2. Header Accept-Language
    3. Langue par defaut (fr)

    Args:
        request: Objet Request FastAPI

    Returns:
        Code langue (fr ou en)
    """
    # 1. Query param
    lang_param = request.query_params.get("lang")
    if lang_param and lang_param in SUPPORTED_LANGUAGES:
        return lang_param

    # 2. Header Accept-Language
    accept_language = request.headers.get("Accept-Language", "")
    if accept_language:
        # Parse le header (format: "fr-FR,fr;q=0.9,en;q=0.8")
        for part in accept_language.split(","):
            lang_code = part.split(";")[0].strip().split("-")[0].lower()
            if lang_code in SUPPORTED_LANGUAGES:
                return lang_code

    # 3. Defaut
    return DEFAULT_LANGUAGE


async def get_lang_from_user(request: Request, db_session=None) -> str:
    """
    Detecte la langue preferee en incluant les preferences utilisateur.

    Ordre de priorite:
    1. Query param ?lang=xx
    2. Preference utilisateur en BDD (si authentifie)
    3. Header Accept-Language
    4. Langue par defaut (fr)

    Args:
        request: Objet Request FastAPI
        db_session: Session DB (optionnel)

    Returns:
        Code langue (fr ou en)
    """
    # 1. Query param
    lang_param = request.query_params.get("lang")
    if lang_param and lang_param in SUPPORTED_LANGUAGES:
        return lang_param

    # 2. Preference utilisateur (si authentifie et session DB disponible)
    if db_session:
        try:
            from app.features.preferences.service import PreferencesService

            user = getattr(request.state, "user", None)
            if user:
                prefs = await PreferencesService.get_preferences(db_session, user.id)
                if prefs and hasattr(prefs, "language") and prefs.language in SUPPORTED_LANGUAGES:
                    return prefs.language
        except Exception:
            pass  # Ignore errors, fallback to other methods

    # 3. Header Accept-Language
    return get_lang_from_request(request)


# Charger les traductions au demarrage du module
_load_translations()
