"""Tests for direct screen reader speech."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from plex_client import screen_reader


class FakeNvda:
    def __init__(self, running: bool = True):
        self.running = running
        self.calls = []

    def nvdaController_testIfRunning(self):
        return 0 if self.running else 1

    def nvdaController_cancelSpeech(self):
        self.calls.append("cancel")
        return 0

    def nvdaController_speakText(self, text):
        self.calls.append(("speak", text))
        return 0


@pytest.fixture
def nvda(monkeypatch):
    fake = FakeNvda()
    monkeypatch.setattr(screen_reader.sys, "platform", "win32")
    monkeypatch.setattr(screen_reader, "_load_nvda_controller", lambda: fake)
    return fake


def test_status_is_spoken_without_cutting_off_nvda(nvda):
    assert screen_reader.speak("Connected to Home.") is True
    assert nvda.calls == [("speak", "Connected to Home.")]


def test_interrupting_message_cancels_current_speech_first(nvda):
    assert screen_reader.speak("Paused", interrupt=True) is True
    assert nvda.calls == ["cancel", ("speak", "Paused")]


@pytest.mark.parametrize("message", ["", "   ", None])
def test_empty_message_is_not_spoken(nvda, message):
    assert screen_reader.speak(message) is False
    assert nvda.calls == []


def test_nothing_is_spoken_when_nvda_is_not_running(nvda):
    nvda.running = False
    assert screen_reader.speak("Paused", interrupt=True) is False
    assert nvda.calls == []


def test_missing_controller_dll_fails_closed(monkeypatch):
    monkeypatch.setattr(screen_reader.sys, "platform", "win32")
    monkeypatch.setattr(screen_reader, "_load_nvda_controller", lambda: None)
    assert screen_reader.speak("Paused") is False


def test_other_platforms_never_load_the_dll(monkeypatch):
    loader = MagicMock()
    monkeypatch.setattr(screen_reader.sys, "platform", "darwin")
    monkeypatch.setattr(screen_reader, "_load_nvda_controller", loader)
    assert screen_reader.speak("Paused") is False
    loader.assert_not_called()


def test_dll_is_found_in_bin_next_to_the_app(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    dll = tmp_path / "bin" / "nvdaControllerClient.dll"
    dll.write_bytes(b"")
    monkeypatch.setattr(screen_reader.sys, "executable", str(tmp_path / "Plexible.exe"))
    monkeypatch.delenv("PLEXIBLE_NVDA_CONTROLLER_DLL", raising=False)
    assert dll in screen_reader._controller_candidates()


def test_main_window_status_does_not_interrupt(monkeypatch):
    from plex_client.ui.main_frame import MainFrame

    spoken = []
    monkeypatch.setattr(screen_reader, "speak", lambda text, interrupt=False: spoken.append((text, interrupt)))
    frame = SimpleNamespace(_closing=False)
    MainFrame._announce_screen_reader(frame, "Connected to Home.")
    MainFrame._announce_screen_reader(frame, "Nothing is playing.", interrupt=True)
    assert spoken == [("Connected to Home.", False), ("Nothing is playing.", True)]


def test_main_window_is_silent_once_closing(monkeypatch):
    from plex_client.ui.main_frame import MainFrame

    speak = MagicMock()
    monkeypatch.setattr(screen_reader, "speak", speak)
    MainFrame._announce_screen_reader(SimpleNamespace(_closing=True), "Signed out.")
    speak.assert_not_called()


def test_player_shortcut_answer_interrupts(monkeypatch):
    from plex_client.ui.main_frame import MainFrame

    spoken = []
    frame = SimpleNamespace(
        _playback_panel=SimpleNamespace(get_state=lambda: {"has_media": False}),
        _announce_screen_reader=lambda text, interrupt=False: spoken.append((text, interrupt)),
    )
    MainFrame._handle_player_announce(frame, None)
    assert spoken == [("Nothing is playing.", True)]


def test_transport_change_interrupts_and_still_flashes_header(monkeypatch):
    from plex_client.ui import playback

    spoken = []
    monkeypatch.setattr(screen_reader, "speak", lambda text, interrupt=False: spoken.append((text, interrupt)))
    monkeypatch.setattr(playback.wx, "CallLater", lambda *args: "timer")
    header = MagicMock()
    header.GetLabel.return_value = "Playing (LibVLC): Song"
    panel = SimpleNamespace(_header=header, _label_restore_target=None, _cancel_label_restore=lambda: None,
                            _restore_header_label=lambda *args: None)
    playback.PlaybackPanel._announce_accessible(panel, "Paused")
    assert spoken == [("Paused", True)]
    header.SetLabel.assert_called_once_with("Paused")
