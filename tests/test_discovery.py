"""Tests for PlexService history and discovery features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestHistory:
    """Test watch history functionality."""

    def test_history_server(self, plex_service, mock_server, mock_video):
        """Test getting server history."""
        mock_server.history.return_value = [mock_video]
        
        history = plex_service.history(maxresults=100)
        
        assert len(history) == 1
        mock_server.history.assert_called_once()

    def test_history_with_filters(self, plex_service, mock_server):
        """Test getting history with filters."""
        from datetime import datetime
        mindate = datetime(2024, 1, 1)
        
        plex_service.history(
            maxresults=50,
            mindate=mindate,
            rating_key=12345,
            account_id=1,
            library_section_id=1,
        )
        
        mock_server.history.assert_called_once_with(
            maxresults=50,
            mindate=mindate,
            ratingKey=12345,
            accountID=1,
            librarySectionID=1,
        )

    def test_section_history(self, plex_service, mock_library_section, mock_video):
        """Test getting section history."""
        mock_library_section.history.return_value = [mock_video]
        
        history = plex_service.section_history(mock_library_section, maxresults=50)
        
        assert len(history) == 1
        mock_library_section.history.assert_called_once_with(maxresults=50, mindate=None)

    def test_account_history(self, plex_service, mock_account, mock_video):
        """Test getting account history."""
        mock_account.history.return_value = [mock_video]
        
        history = plex_service.account_history(maxresults=100)
        
        assert len(history) == 1
        mock_account.history.assert_called_once_with(maxresults=100, mindate=None)


class TestDiscovery:
    """Test Plex Discover features."""

    def test_search_discover(self, plex_service, mock_account):
        """Test searching Plex Discover."""
        result = MagicMock()
        result.title = "The Matrix"
        mock_account.searchDiscover.return_value = [result]
        
        results = plex_service.search_discover("matrix", limit=10)
        
        assert len(results) == 1
        mock_account.searchDiscover.assert_called_once_with(
            query="matrix",
            limit=10,
            libtype=None,
            providers="discover",
        )

    def test_search_discover_with_libtype(self, plex_service, mock_account):
        """Test searching Discover with libtype filter."""
        plex_service.search_discover("action", libtype="movie")
        
        mock_account.searchDiscover.assert_called_once_with(
            query="action",
            limit=30,
            libtype="movie",
            providers="discover",
        )

    def test_video_on_demand(self, plex_service, mock_account):
        """Test getting VOD content."""
        vod = MagicMock()
        mock_account.videoOnDemand.return_value = vod
        
        result = plex_service.video_on_demand()
        
        assert result == vod
        mock_account.videoOnDemand.assert_called_once()

    def test_online_media_sources(self, plex_service, mock_account):
        """Test getting online media sources."""
        source = MagicMock()
        mock_account.onlineMediaSources.return_value = [source]
        
        sources = plex_service.online_media_sources()
        
        assert len(sources) == 1
        mock_account.onlineMediaSources.assert_called_once()


class TestWebhooks:
    """Test webhook functionality."""

    def test_webhooks(self, plex_service, mock_account):
        """Test getting webhooks."""
        mock_account.webhooks.return_value = ["https://example.com/webhook"]
        
        hooks = plex_service.webhooks()
        
        assert len(hooks) == 1
        assert hooks[0] == "https://example.com/webhook"
        mock_account.webhooks.assert_called_once()

    def test_add_webhook(self, plex_service, mock_account):
        """Test adding a webhook."""
        plex_service.add_webhook("https://example.com/new-webhook")
        
        mock_account.addWebhook.assert_called_once_with("https://example.com/new-webhook")

    def test_delete_webhook(self, plex_service, mock_account):
        """Test deleting a webhook."""
        plex_service.delete_webhook("https://example.com/old-webhook")
        
        mock_account.deleteWebhook.assert_called_once_with("https://example.com/old-webhook")

    def test_set_webhooks(self, plex_service, mock_account):
        """Test setting all webhooks."""
        urls = ["https://example.com/hook1", "https://example.com/hook2"]
        
        plex_service.set_webhooks(urls)
        
        mock_account.setWebhooks.assert_called_once_with(urls)


class TestAlertListener:
    """Test alert listener functionality."""

    def test_start_alert_listener(self, plex_service, mock_server):
        """Test starting alert listener."""
        listener = MagicMock()
        mock_server.startAlertListener.return_value = listener
        callback = MagicMock()
        error_callback = MagicMock()
        
        result = plex_service.start_alert_listener(
            callback=callback,
            callback_error=error_callback,
        )
        
        assert result == listener
        mock_server.startAlertListener.assert_called_once_with(
            callback=callback,
            callbackError=error_callback,
        )


class TestSyncFeatures:
    """Test sync functionality."""

    def test_sync_items(self, plex_service, mock_account):
        """Test getting sync items."""
        item = MagicMock()
        mock_account.syncItems.return_value = [item]
        
        items = plex_service.sync_items()
        
        assert len(items) == 1
        mock_account.syncItems.assert_called_once_with(client=None, clientId=None)

    def test_sync_items_for_client(self, plex_service, mock_account):
        """Test getting sync items for a specific client."""
        plex_service.sync_items(client_id="client123")
        
        mock_account.syncItems.assert_called_once_with(client=None, clientId="client123")

    def test_refresh_sync_list(self, plex_service, mock_server):
        """Test refreshing sync list."""
        plex_service.refresh_sync_list()
        
        mock_server.refreshSynclist.assert_called_once()

    def test_refresh_sync(self, plex_service, mock_server):
        """Test refreshing sync."""
        plex_service.refresh_sync()
        
        mock_server.refreshSync.assert_called_once()


class TestAccountFeatures:
    """Test account-level features."""

    def test_account_opt_out(self, plex_service, mock_account):
        """Test opting out of data collection."""
        plex_service.account_opt_out(playback=True, library=False)
        
        mock_account.optOut.assert_called_once_with(playback=True, library=False)

    def test_claim_token(self, plex_service, mock_account):
        """Test getting claim token."""
        result = plex_service.claim_token()
        
        assert result == "claim-token-123"
        mock_account.claimToken.assert_called_once()

    def test_devices(self, plex_service, mock_account):
        """Test getting devices."""
        device = MagicMock()
        mock_account.devices.return_value = [device]
        
        devices = plex_service.devices()
        
        assert len(devices) == 1
        mock_account.devices.assert_called_once()

    def test_device_by_name(self, plex_service, mock_account):
        """Test getting device by name."""
        device = MagicMock()
        mock_account.device.return_value = device
        
        result = plex_service.device(name="My Phone")
        
        assert result == device
        mock_account.device.assert_called_once_with(name="My Phone", clientId=None)


class TestUtilities:
    """Test utility methods."""

    def test_get_web_url_server(self, plex_service, mock_server):
        """Test getting web URL for server."""
        url = plex_service.get_web_url()
        
        assert "plex.tv" in url
        mock_server.getWebURL.assert_called_once()

    def test_get_web_url_item(self, plex_service, mock_video):
        """Test getting web URL for item."""
        url = plex_service.get_web_url(item=mock_video)
        
        mock_video.getWebURL.assert_called_once()

    def test_transcode_image(self, plex_service, mock_server):
        """Test getting transcoded image URL."""
        url = plex_service.transcode_image(
            image_url="/library/metadata/1/thumb",
            height=200,
            width=300,
        )
        
        assert "transcode" in url
        mock_server.transcodeImage.assert_called_once()

    def test_browse_server(self, plex_service, mock_server):
        """Test browsing server filesystem."""
        folder = MagicMock()
        mock_server.browse.return_value = [folder]
        
        results = plex_service.browse_server(path="/media")
        
        assert len(results) == 1
        mock_server.browse.assert_called_once_with(path="/media", includeFiles=True)

    def test_is_browsable(self, plex_service, mock_server):
        """Test checking if path is browsable."""
        result = plex_service.is_browsable("/media")
        
        assert result is True
        mock_server.isBrowsable.assert_called_once_with("/media")
