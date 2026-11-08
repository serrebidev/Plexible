"""Menu shortcut key names follow the interface language and keep working."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import wx

from plex_client.ui import wx_language


@pytest.fixture
def wx_app():
    app = wx.App.Get() or wx.App(False)
    yield app
    wx.Translations.Set(None)
    wx_language._translations = None


def _parse(shortcut_text: str) -> tuple[int, int]:
    entry = wx.AcceleratorEntry()
    assert entry.FromString("x" + shortcut_text), f"wx cannot read {shortcut_text!r}"
    return entry.GetFlags(), entry.GetKeyCode()


def test_english_shortcuts_are_left_as_written(wx_app):
    assert wx_language.install("en") is False
    assert wx_language.menu_shortcut("Ctrl+Up") == "\tCtrl+Up"
    assert wx_language.menu_shortcut("Space") == "\tSpace"


@pytest.mark.parametrize(
    ("keys", "flags", "key_code"),
    [
        ("Space", wx.ACCEL_NORMAL, wx.WXK_SPACE),
        ("Shift+Space", wx.ACCEL_SHIFT, wx.WXK_SPACE),
        ("Ctrl+Up", wx.ACCEL_CTRL, wx.WXK_UP),
        ("Ctrl+Left", wx.ACCEL_CTRL, wx.WXK_LEFT),
        ("Ctrl+Shift+A", wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("A")),
        ("F5", wx.ACCEL_NORMAL, wx.WXK_F5),
    ],
)
def test_french_key_names_still_register_the_same_shortcut(wx_app, keys, flags, key_code):
    """A hand-written "Espace" would not be recognised; wx's own text is."""
    assert wx_language.install("fr") is True
    text = wx_language.menu_shortcut(keys)
    assert _parse(text) == (flags, key_code)


def test_space_and_arrows_are_spoken_in_french(wx_app):
    assert wx_language.install("fr") is True
    assert wx_language.menu_shortcut("Space") == "\tEspace"
    assert wx_language.menu_shortcut("Ctrl+Up") == "\tCtrl+Haut"


def test_every_menu_shortcut_is_readable_by_wx(wx_app):
    source = Path(wx_language.__file__).with_name("main_frame.py").read_text(encoding="utf-8")
    shortcuts = re.findall(r'menu_shortcut\("([^"]+)"\)', source)
    assert len(shortcuts) >= 17
    for keys in shortcuts:
        _parse("\t" + keys)
    assert '+ "\\t' not in source, "menu labels must build their shortcut with menu_shortcut()"
