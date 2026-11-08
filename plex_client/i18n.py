"""Interface translations.

English is the source language: every user-facing string in the code is
written in English and wrapped in ``_()``. Each other language has a catalog
in ``plex_client/locales/<code>.py`` that maps the English text to its
translation. Missing entries fall back to English.

Use named placeholders instead of f-strings so translators can move them:

    _("Connecting to {name}...", name=server_name)

Strings defined at import time (module constants) are marked with ``N_()``
and translated where they are shown, because the language is chosen after
the modules are imported.
"""
from __future__ import annotations

import importlib
import locale
import os
import sys
from typing import Dict, Optional

DEFAULT_LANGUAGE = "en"
SYSTEM_LANGUAGE = "auto"

# Language code -> name shown in the Language menu (in its own language).
SUPPORTED_LANGUAGES: Dict[str, str] = {
    "en": "English",
    "fr": "Français",
}

_language = DEFAULT_LANGUAGE
_catalog: Dict[str, str] = {}


def _(message: str, /, **kwargs: object) -> str:
    """Translate ``message`` and fill its ``{placeholders}`` from ``kwargs``."""
    text = _catalog.get(message, message)
    return text.format(**kwargs) if kwargs else text


def N_(message: str, /) -> str:
    """Mark a string for translation without translating it yet."""
    return message


def ngettext(singular: str, plural: str, count: int, /, **kwargs: object) -> str:
    """Translate a message that depends on ``count``.

    ``count`` is also available to the placeholders as ``{count}``.
    """
    kwargs.setdefault("count", count)
    if _language == "fr":
        use_singular = abs(count) < 2  # French treats 0 and 1 as singular.
    else:
        use_singular = count == 1
    return _(singular if use_singular else plural, **kwargs)


def get_language() -> str:
    return _language


def load_catalog(language: str) -> Dict[str, str]:
    if language == DEFAULT_LANGUAGE:
        return {}
    module = importlib.import_module(f"plex_client.locales.{language}")
    return dict(getattr(module, "MESSAGES", {}))


def set_language(language: Optional[str]) -> str:
    """Activate ``language`` ('auto', a supported code, or None for auto)."""
    global _language, _catalog
    resolved = resolve_language(language)
    try:
        catalog = load_catalog(resolved)
    except ImportError:
        resolved, catalog = DEFAULT_LANGUAGE, {}
    _language = resolved
    _catalog = catalog
    return resolved


def resolve_language(preference: Optional[str]) -> str:
    """Turn a stored preference into a supported language code."""
    override = os.environ.get("PLEXIBLE_LANGUAGE")
    if override:
        preference = override
    code = _normalise(preference)
    if code in SUPPORTED_LANGUAGES:
        return code
    return detect_system_language()


def detect_system_language() -> str:
    for candidate in _system_locale_names():
        code = _normalise(candidate)
        if code in SUPPORTED_LANGUAGES:
            return code
    return DEFAULT_LANGUAGE


def _normalise(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    value = value.strip().lower()
    if not value or value == SYSTEM_LANGUAGE:
        return None
    # "fr_FR.UTF-8", "fr-CA", "French_France.1252" -> "fr"
    for separator in ("_", "-", ".", "@"):
        value = value.split(separator, 1)[0]
    if value == "french":
        return "fr"
    if value == "english":
        return "en"
    return value


def _system_locale_names():
    if sys.platform == "win32":
        try:
            import ctypes

            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            name = locale.windows_locale.get(lang_id)
            if name:
                yield name
        except Exception:  # noqa: BLE001 - fall back to the C runtime locale
            pass
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value:
            # LANGUAGE can hold a priority list such as "fr:en".
            yield value.split(":", 1)[0]
    try:
        name = locale.getlocale()[0]
    except (ValueError, TypeError):
        name = None
    if name:
        yield name
