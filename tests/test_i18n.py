"""Tests for interface translations (plex_client/i18n.py and the catalogs)."""
from __future__ import annotations

import ast
import string
from pathlib import Path

import pytest

from plex_client import i18n
from plex_client.locales import fr

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "plex_client"
TRANSLATION_FUNCTIONS = {"_": 1, "N_": 1, "ngettext": 2}


@pytest.fixture(autouse=True)
def english_afterwards(monkeypatch):
    monkeypatch.delenv("PLEXIBLE_LANGUAGE", raising=False)
    yield
    i18n.set_language("en")


def _placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


def _wrapped_literals():
    """Yield (location, text) for every literal passed to _(), N_() or ngettext()."""
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        if "locales" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            count = TRANSLATION_FUNCTIONS.get(node.func.id)
            if not count:
                continue
            for arg in node.args[:count]:
                location = f"{path.relative_to(PACKAGE_DIR.parent)}:{node.lineno}"
                assert not isinstance(arg, ast.JoinedStr), f"f-string inside {node.func.id}() at {location}"
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    yield location, arg.value


def test_english_is_the_default_and_formats_placeholders():
    assert i18n.get_language() == "en"
    assert i18n._("Connecting to {name}...", name="Home") == "Connecting to Home..."
    assert i18n._("Untranslated text") == "Untranslated text"


def test_french_catalog_is_used_after_set_language():
    assert i18n.set_language("fr") == "fr"
    assert i18n._("Loading...") == "Chargement..."
    assert i18n._("Text with no translation") == "Text with no translation"


def test_ngettext_uses_french_plural_rules():
    i18n.set_language("en")
    assert i18n.ngettext("{count} item", "{count} items", 0) == "0 items"
    assert i18n.ngettext("{count} item", "{count} items", 1) == "1 item"
    i18n.set_language("fr")
    # French uses the singular for 0 and 1. Untranslated text still follows the rule.
    assert i18n.ngettext("{count} item", "{count} items", 0) == "0 item"
    assert i18n.ngettext("{count} item", "{count} items", 2) == "2 items"


@pytest.mark.parametrize(
    "preference, expected",
    [("fr", "fr"), ("FR", "fr"), ("fr_CA", "fr"), ("en", "en"), ("de", "en")],
)
def test_resolve_language_from_preference(preference, expected, monkeypatch):
    monkeypatch.setattr(i18n, "detect_system_language", lambda: "en")
    assert i18n.resolve_language(preference) == expected


@pytest.mark.parametrize(
    "system_name, expected",
    [("fr_FR.UTF-8", "fr"), ("French_France", "fr"), ("fr-BE", "fr"), ("en_US", "en"), ("es_ES", "en")],
)
def test_auto_follows_the_system_language(system_name, expected, monkeypatch):
    monkeypatch.setattr(i18n, "_system_locale_names", lambda: iter([system_name]))
    assert i18n.resolve_language("auto") == expected


def test_environment_variable_overrides_the_preference(monkeypatch):
    monkeypatch.setenv("PLEXIBLE_LANGUAGE", "fr")
    assert i18n.resolve_language("en") == "fr"


def test_every_wrapped_string_has_a_french_translation():
    missing = [f"{where}: {text!r}" for where, text in _wrapped_literals() if text not in fr.MESSAGES]
    assert not missing, "Missing French translations:\n" + "\n".join(missing)


def test_french_translations_keep_the_same_placeholders():
    mismatched = [
        f"{source!r} -> {target!r}"
        for source, target in fr.MESSAGES.items()
        if _placeholders(source) != _placeholders(target)
    ]
    assert not mismatched, "Placeholder mismatch:\n" + "\n".join(mismatched)


def test_french_catalog_has_no_unused_entries():
    used = {text for _, text in _wrapped_literals()}
    unused = sorted(set(fr.MESSAGES) - used)
    assert not unused, "Unused French entries (remove them):\n" + "\n".join(map(repr, unused))
