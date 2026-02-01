"""Tests for UI components."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
import sys


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


@pytest.mark.skipif(not wx_available, reason="wxPython not available")
class TestPlayback:
    """Test Playback UI component."""

    def test_playback_import(self):
        """Test that PlaybackPanel can be imported."""
        from plex_client.ui.playback import PlaybackPanel
        assert PlaybackPanel is not None

