"""Tests for Help > Language in the main window."""
from __future__ import annotations

import pytest

wx = pytest.importorskip("wx")

from plex_client import i18n  # noqa: E402
from plex_client.auth import AuthManager  # noqa: E402
from plex_client.config import ConfigStore  # noqa: E402
from plex_client.ui import main_frame  # noqa: E402


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("PLEXIBLE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("PLEXIBLE_LANGUAGE", raising=False)
    store = ConfigStore()
    store.set_auto_check_updates(False)
    store.set_language("en")
    return store


@pytest.fixture
def make_frame(config):
    app = wx.App(False)
    frames = []

    def build(on_restart=None):
        frame = main_frame.MainFrame(config, AuthManager(config), on_restart_requested=on_restart)
        frame.Show()
        frames.append(frame)
        return frame

    yield build
    for frame in frames:
        if frame:
            frame.Destroy()
    app.Destroy()
    i18n.set_language("en")


@pytest.fixture
def answers(monkeypatch):
    """Record message boxes and answer them with the queued replies."""
    shown = []
    replies = []

    def fake_message_box(message, caption="", style=0, parent=None):
        shown.append(message)
        return replies.pop(0) if replies else wx.OK

    monkeypatch.setattr(main_frame.wx, "MessageBox", fake_message_box)
    return shown, replies


def _language_labels(frame):
    help_menu = frame.GetMenuBar().GetMenu(frame.GetMenuBar().FindMenu("Help"))
    language_item = next(item for item in help_menu.GetMenuItems() if item.GetSubMenu())
    return {item.GetItemLabelText(): item.IsChecked() for item in language_item.GetSubMenu().GetMenuItems()}


def test_menu_lists_languages_and_checks_the_saved_one(make_frame):
    labels = _language_labels(make_frame())
    assert labels == {"System Default": False, "English": True, "Français": False}


def test_choosing_a_language_saves_it_and_restarts_on_yes(make_frame, config, answers):
    shown, replies = answers
    restarts = []
    frame = make_frame(on_restart=lambda: restarts.append(True))
    replies.append(wx.YES)

    frame._handle_language_choice("fr")

    assert config.get_language() == "fr"
    # The question is asked in the language the user just picked.
    assert shown == ["Plexible doit redémarrer pour utiliser la nouvelle langue. Redémarrer maintenant ?"]
    assert restarts == [True]


def test_answering_no_keeps_running_and_applies_later(make_frame, config, answers):
    shown, replies = answers
    restarts = []
    frame = make_frame(on_restart=lambda: restarts.append(True))
    replies.append(wx.NO)

    frame._handle_language_choice("fr")

    assert config.get_language() == "fr"
    assert restarts == []
    assert frame.IsShown()


def test_choosing_the_current_language_does_nothing(make_frame, config, answers):
    shown, _replies = answers
    frame = make_frame(on_restart=lambda: None)

    frame._handle_language_choice("en")

    assert shown == []
    assert config.get_language() == "en"
