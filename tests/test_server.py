"""Tests for PlexService server administration features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestServerSettings:
    """Test server settings functionality."""

    def test_server_settings(self, plex_service, mock_server):
        """Test getting server settings."""
        settings = plex_service.server_settings()
        
        assert settings == mock_server.settings

    def test_server_identity(self, plex_service, mock_server):
        """Test getting server identity."""
        identity = plex_service.server_identity()
        
        assert identity == mock_server.identity

    def test_server_account(self, plex_service, mock_server):
        """Test getting server account."""
        account = plex_service.server_account()
        
        mock_server.account.assert_called_once()


class TestServerActivities:
    """Test server activity monitoring."""

    def test_server_activities(self, plex_service, mock_server):
        """Test getting server activities."""
        activity = MagicMock()
        activity.type = "library.scan"
        mock_server.activities.return_value = [activity]
        
        activities = plex_service.server_activities()
        
        assert len(activities) == 1
        mock_server.activities.assert_called_once()

    def test_server_sessions(self, plex_service, mock_server):
        """Test getting active sessions."""
        session = MagicMock()
        session.title = "Test Movie"
        mock_server.sessions.return_value = [session]
        
        sessions = plex_service.server_sessions()
        
        assert len(sessions) == 1
        mock_server.sessions.assert_called_once()

    def test_transcode_sessions(self, plex_service, mock_server):
        """Test getting transcode sessions."""
        session = MagicMock()
        mock_server.transcodeSessions.return_value = [session]
        
        sessions = plex_service.transcode_sessions()
        
        assert len(sessions) == 1
        mock_server.transcodeSessions.assert_called_once()

    def test_current_background_process(self, plex_service, mock_server):
        """Test getting current background process."""
        process = MagicMock()
        mock_server.currentBackgroundProcess.return_value = process
        
        result = plex_service.current_background_process()
        
        assert result == process


class TestButlerTasks:
    """Test butler task functionality."""

    def test_butler_tasks(self, plex_service, mock_server):
        """Test getting butler tasks."""
        task = MagicMock()
        task.name = "CleanOldBundles"
        mock_server.butlerTasks.return_value = [task]
        
        tasks = plex_service.butler_tasks()
        
        assert len(tasks) == 1
        mock_server.butlerTasks.assert_called_once()

    def test_run_butler_task(self, plex_service, mock_server):
        """Test running a butler task."""
        plex_service.run_butler_task("CleanOldBundles")
        
        mock_server.runButlerTask.assert_called_once_with("CleanOldBundles")


class TestServerUpdates:
    """Test server update functionality."""

    def test_check_for_update(self, plex_service, mock_server):
        """Test checking for updates."""
        update = MagicMock()
        mock_server.checkForUpdate.return_value = update
        
        result = plex_service.check_for_update(force=True, download=False)
        
        mock_server.checkForUpdate.assert_called_once_with(force=True, download=False)

    def test_is_latest_version(self, plex_service, mock_server):
        """Test checking if latest version."""
        mock_server.isLatest.return_value = True
        
        result = plex_service.is_latest_version()
        
        assert result is True
        mock_server.isLatest.assert_called_once()

    def test_can_install_update(self, plex_service, mock_server):
        """Test checking if update can be installed."""
        mock_server.canInstallUpdate.return_value = True
        
        result = plex_service.can_install_update()
        
        assert result is True
        mock_server.canInstallUpdate.assert_called_once()

    def test_install_update(self, plex_service, mock_server):
        """Test installing an update."""
        plex_service.install_update()
        
        mock_server.installUpdate.assert_called_once()


class TestSystemInfo:
    """Test system information features."""

    def test_system_accounts(self, plex_service, mock_server):
        """Test getting system accounts."""
        account = MagicMock()
        mock_server.systemAccounts.return_value = [account]
        
        accounts = plex_service.system_accounts()
        
        assert len(accounts) == 1
        mock_server.systemAccounts.assert_called_once()

    def test_system_devices(self, plex_service, mock_server):
        """Test getting system devices."""
        device = MagicMock()
        mock_server.systemDevices.return_value = [device]
        
        devices = plex_service.system_devices()
        
        assert len(devices) == 1
        mock_server.systemDevices.assert_called_once()


class TestOptimizedContent:
    """Test optimized content management."""

    def test_optimized_items(self, plex_service, mock_server):
        """Test getting optimized items."""
        item = MagicMock()
        mock_server.optimizedItems.return_value = [item]
        
        items = plex_service.optimized_items()
        
        assert len(items) == 1
        mock_server.optimizedItems.assert_called_once_with(removeAll=None)

    def test_optimized_items_remove_all(self, plex_service, mock_server):
        """Test removing all optimized items."""
        plex_service.optimized_items(remove_all=True)
        
        mock_server.optimizedItems.assert_called_once_with(removeAll=True)

    def test_conversions(self, plex_service, mock_server):
        """Test getting conversions."""
        conversion = MagicMock()
        mock_server.conversions.return_value = [conversion]
        
        conversions = plex_service.conversions()
        
        assert len(conversions) == 1
        mock_server.conversions.assert_called_once_with(pause=None)

    def test_conversions_pause(self, plex_service, mock_server):
        """Test pausing conversions."""
        plex_service.conversions(pause=True)
        
        mock_server.conversions.assert_called_once_with(pause=True)


class TestClients:
    """Test client management."""

    def test_clients(self, plex_service, mock_server):
        """Test getting connected clients."""
        client = MagicMock()
        client.title = "Plex for Windows"
        mock_server.clients.return_value = [client]
        
        clients = plex_service.clients()
        
        assert len(clients) == 1
        mock_server.clients.assert_called_once()

    def test_client_by_name(self, plex_service, mock_server):
        """Test getting a specific client."""
        client = MagicMock()
        mock_server.client.return_value = client
        
        result = plex_service.client("Plex for Windows")
        
        assert result == client
        mock_server.client.assert_called_once_with("Plex for Windows")


class TestBandwidth:
    """Test bandwidth statistics."""

    def test_bandwidth(self, plex_service, mock_server):
        """Test getting bandwidth stats."""
        stat = MagicMock()
        mock_server.bandwidth.return_value = [stat]
        
        stats = plex_service.bandwidth(timespan="days")
        
        assert len(stats) == 1
        mock_server.bandwidth.assert_called_once()
