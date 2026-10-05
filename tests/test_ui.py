"""Tests for UI components."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
import sys
from types import SimpleNamespace


# Skip UI tests if wx is not available
wx_available = False
try:
    import wx
    wx_available = True
except ImportError:
    pass


@pytest.mark.skipif(not wx_available, reason="wxPython not available")
class TestMetadataPanel:
    """Test MetadataPanel UI component."""

    @pytest.fixture
    def app(self):
        """Create wx App for tests."""
        app = wx.App(False)
        yield app
        app.Destroy()

    def test_metadata_panel_import(self):
        """Test that MetadataPanel can be imported."""
        from plex_client.ui.content_panel import MetadataPanel
        assert MetadataPanel is not None


@pytest.mark.skipif(not wx_available, reason="wxPython not available")
class TestQueuesPanel:
    """Test QueuesPanel UI component."""

    def test_queues_panel_import(self):
        """Test that QueuesPanel can be imported."""
        from plex_client.ui.content_panel import QueuesPanel
        assert QueuesPanel is not None


@pytest.mark.skipif(not wx_available, reason="wxPython not available")
class TestMainFrame:
    """Test MainFrame UI component."""

    def test_main_frame_import(self):
        """Test that MainFrame can be imported."""
        from plex_client.ui.main_frame import MainFrame
        assert MainFrame is not None

    @pytest.mark.parametrize("server_offset", [1000, 15000])
    def test_stale_server_offset_keeps_pending_progress(self, tmp_path, monkeypatch, server_offset):
        from plex_client.config import ConfigStore
        from plex_client.ui.main_frame import MainFrame

        monkeypatch.setenv("PLEXIBLE_CONFIG_DIR", str(tmp_path))
        config = ConfigStore()
        config.upsert_pending_progress("1", 20000, 60000, "paused")
        panel = SimpleNamespace(_config=config, _last_positions={},
                                _service=SimpleNamespace(update_progress_by_key=lambda *args: ("paused", server_offset)))
        changed = MainFrame._process_pending_progress(panel, list(config.get_pending_progress().items()))
        assert config.get_pending_entry("1")["position"] == 20000
        assert changed is False

    def test_flush_does_not_delete_a_newer_pending_snapshot(self, tmp_path, monkeypatch):
        from plex_client.config import ConfigStore
        from plex_client.ui.main_frame import MainFrame

        monkeypatch.setenv("PLEXIBLE_CONFIG_DIR", str(tmp_path))
        config = ConfigStore()
        config.upsert_pending_progress("1", 20000, 60000, "paused")

        def update(*args):
            config.upsert_pending_progress("1", 30000, 60000, "paused")
            return "paused", 20000

        panel = SimpleNamespace(_config=config, _last_positions={},
                                _service=SimpleNamespace(update_progress_by_key=update))
        MainFrame._process_pending_progress(panel, list(config.get_pending_progress().items()))
        assert config.get_pending_entry("1")["position"] == 30000

    def test_shutdown_does_not_start_overlapping_flush(self, monkeypatch):
        from plex_client.ui import main_frame

        times = iter([0.0, 3.0])
        monkeypatch.setattr(main_frame.time, "monotonic", lambda: next(times))
        panel = SimpleNamespace(_progress_flush_active=True, _service=object(), _config=MagicMock(),
                                _process_pending_progress=MagicMock(return_value=False),
                                _cancel_progress_flush_timer=lambda: None)
        main_frame.MainFrame._flush_pending_progress_sync(panel)
        panel._process_pending_progress.assert_not_called()

    def test_delayed_timeline_acknowledgment_preserves_newer_progress(self, tmp_path, monkeypatch):
        from plex_client.config import ConfigStore
        from plex_client.ui.main_frame import MainFrame

        monkeypatch.setenv("PLEXIBLE_CONFIG_DIR", str(tmp_path))
        config = ConfigStore()
        config.upsert_pending_progress("1", 30000, 60000, "paused")
        panel = SimpleNamespace(_config=config, _last_positions={"1": 30000}, _closing=True)
        MainFrame._ingest_progress(panel, "1", 20000, 60000, "paused", 20000)
        assert config.get_pending_entry("1")["position"] == 30000
        assert panel._last_positions["1"] == 30000


@pytest.mark.skipif(not wx_available, reason="wxPython not available")
class TestPlayback:
    """Test Playback UI component."""

    def test_playback_import(self):
        """Test that PlaybackPanel can be imported."""
        from plex_client.ui.playback import PlaybackPanel
        assert PlaybackPanel is not None

    @pytest.mark.parametrize("state, expected_position", [("Stopped", 12000), ("Ended", 60000)])
    def test_poll_reports_actual_position_unless_media_ended(self, state, expected_position, monkeypatch):
        from plex_client.ui import playback

        reports = []
        player = SimpleNamespace(get_state=lambda: getattr(playback.vlc.State, state), get_time=lambda: 12000)
        panel = SimpleNamespace(_timeline_timer=None, _is_destroying=lambda: False, _current=object(),
                                _mode="libvlc", _vlc_player=player, _current_duration=lambda: 60000,
                                _notify_timeline_state=lambda *args: reports.append(args), stop=lambda: None)
        monkeypatch.setattr(playback.wx, "CallAfter", lambda *args: None)
        playback.PlaybackPanel._poll_timeline(panel)
        assert reports == [("stopped", expected_position, 60000)]
