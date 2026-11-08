"""wxWidgets' own translations: key names in menu shortcuts and stock labels.

The text after the tab in a menu label ("Play\tSpace") is both what screen
readers announce and what wx parses to register the shortcut. A French name
written by hand ("Espace") would not be recognised, so the shortcut would
stop working. With wx's French catalog loaded, wx both writes and reads
"Espace", "Ctrl+Haut", "Majuscule+Espace", so the text is built by wx itself.
"""
from __future__ import annotations

from typing import Optional

import wx

from .. import i18n

_translations: Optional[wx.Translations] = None


def install(language: str) -> bool:
    """Load wx's catalog for ``language``. Call after wx.App() exists.

    Only the message catalog is loaded; the C locale (number and date
    formats) is left alone.
    """
    global _translations
    if language == i18n.DEFAULT_LANGUAGE:
        return False
    try:
        translations = wx.Translations()
        translations.SetLanguage(language)
        if not translations.AddStdCatalog():
            return False
        wx.Translations.Set(translations)
    except Exception:  # noqa: BLE001 - keep English key names
        return False
    _translations = translations  # wx does not keep Python's reference alive
    return True


def menu_shortcut(keys: str) -> str:
    """Return ``"\\t" + keys`` with key names in the interface language.

    ``keys`` uses wx's English syntax ("Ctrl+Up"). The translated text is
    used only if wx reads it back as the same shortcut.
    """
    entry = wx.AcceleratorEntry()
    if entry.FromString("x\t" + keys):
        shown = entry.ToString()
        check = wx.AcceleratorEntry()
        if (
            shown
            and check.FromString("x\t" + shown)
            and check.GetFlags() == entry.GetFlags()
            and check.GetKeyCode() == entry.GetKeyCode()
        ):
            return "\t" + shown
    return "\t" + keys
