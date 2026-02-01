"""Pytest configuration and fixtures for Plexible tests."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, Mock, patch
from typing import Any, List, Optional

# Mock plexapi classes
@pytest.fixture
def mock_plex_object():
    """Create a mock PlexObject."""
    obj = MagicMock()
    obj.title = "Test Item"
    obj.type = "movie"
    obj.ratingKey = "12345"
    obj.key = "/library/metadata/12345"
    obj.duration = 7200000  # 2 hours in ms
    obj.viewOffset = 0
    return obj


@pytest.fixture
def mock_video():
    """Create a mock Video object."""
    video = MagicMock()
    video.title = "Test Movie"
    video.type = "movie"
    video.ratingKey = "12345"
    video.key = "/library/metadata/12345"
    video.duration = 7200000
    video.viewOffset = 0
    video.year = 2024
    video.summary = "A test movie"
    video.removeFromContinueWatching = MagicMock()
    video.markWatched = MagicMock()
    video.markUnwatched = MagicMock()
    video.uploadSubtitles = MagicMock()
    video.searchSubtitles = MagicMock(return_value=[])
    video.downloadSubtitles = MagicMock()
    video.removeSubtitles = MagicMock()
    video.optimize = MagicMock()
    video.delete = MagicMock()
    video.refresh = MagicMock()
    video.analyze = MagicMock()
    video.download = MagicMock(return_value=["/path/to/file.mp4"])
    video.getWebURL = MagicMock(return_value="https://app.plex.tv/...")
    return video


@pytest.fixture
def mock_episode():
    """Create a mock Episode object."""
    episode = MagicMock()
    episode.title = "Test Episode"
    episode.type = "episode"
    episode.ratingKey = "67890"
    episode.key = "/library/metadata/67890"
    episode.duration = 3600000
    episode.viewOffset = 1800000
    episode.seasonNumber = 1
    episode.episodeNumber = 5
    episode.grandparentTitle = "Test Show"
    episode.parentTitle = "Season 1"
    return episode


@pytest.fixture
def mock_track():
    """Create a mock Track object."""
    track = MagicMock()
    track.title = "Test Track"
    track.type = "track"
    track.ratingKey = "11111"
    track.key = "/library/metadata/11111"
    track.duration = 240000
    track.parentTitle = "Test Album"
    track.grandparentTitle = "Test Artist"
    return track


@pytest.fixture
def mock_playlist():
    """Create a mock Playlist object."""
    playlist = MagicMock()
    playlist.title = "Test Playlist"
    playlist.type = "playlist"
    playlist.ratingKey = "99999"
    playlist.smart = False
    playlist.items = MagicMock(return_value=[])
    playlist.addItems = MagicMock()
    playlist.removeItems = MagicMock()
    playlist.moveItem = MagicMock()
    playlist.delete = MagicMock()
    playlist.copyToUser = MagicMock()
    return playlist


@pytest.fixture
def mock_collection():
    """Create a mock Collection object."""
    collection = MagicMock()
    collection.title = "Test Collection"
    collection.type = "collection"
    collection.ratingKey = "88888"
    collection.smart = False
    collection.items = MagicMock(return_value=[])
    collection.addItems = MagicMock()
    collection.removeItems = MagicMock()
    collection.moveItem = MagicMock()
    collection.delete = MagicMock()
    return collection


@pytest.fixture
def mock_library_section():
    """Create a mock LibrarySection."""
    section = MagicMock()
    section.title = "Movies"
    section.type = "movie"
    section.key = "1"
    section.uuid = "abc123"
    section.all = MagicMock(return_value=[])
    section.search = MagicMock(return_value=[])
    section.recentlyAdded = MagicMock(return_value=[])
    section.onDeck = MagicMock(return_value=[])
    section.continueWatching = MagicMock(return_value=[])
    section.hubs = MagicMock(return_value=[])
    section.collections = MagicMock(return_value=[])
    section.collection = MagicMock()
    section.playlists = MagicMock(return_value=[])
    section.playlist = MagicMock()
    section.update = MagicMock()
    section.cancelUpdate = MagicMock()
    section.emptyTrash = MagicMock()
    section.refresh = MagicMock()
    section.analyze = MagicMock()
    section.history = MagicMock(return_value=[])
    return section


@pytest.fixture
def mock_music_section():
    """Create a mock MusicSection."""
    section = MagicMock()
    section.title = "Music"
    section.type = "artist"
    section.key = "2"
    section.uuid = "def456"
    section.all = MagicMock(return_value=[])
    section.albums = MagicMock(return_value=[])
    section.stations = MagicMock(return_value=[])
    section.hubs = MagicMock(return_value=[])
    section.recentlyAddedAlbums = MagicMock(return_value=[])
    section.recentlyAddedTracks = MagicMock(return_value=[])
    return section


@pytest.fixture
def mock_server():
    """Create a mock PlexServer."""
    server = MagicMock()
    server.friendlyName = "Test Server"
    server.machineIdentifier = "server123"
    server._baseurl = "http://localhost:32400"
    server._token = "test_token"
    
    # Library
    server.library = MagicMock()
    server.library.sections = MagicMock(return_value=[])
    server.library.section = MagicMock()
    server.library.sectionByID = MagicMock()
    server.library.onDeck = MagicMock(return_value=[])
    server.library.recentlyAdded = MagicMock(return_value=[])
    server.library.hubs = MagicMock(return_value=[])
    server.library.update = MagicMock()
    server.library.cancelUpdate = MagicMock()
    server.library.emptyTrash = MagicMock()
    server.library.cleanBundles = MagicMock()
    server.library.optimize = MagicMock()
    
    # Playlists
    server.playlists = MagicMock(return_value=[])
    server.playlist = MagicMock()
    server.createPlaylist = MagicMock()
    
    # Collections
    server.createCollection = MagicMock()
    
    # PlayQueue
    server.createPlayQueue = MagicMock()
    
    # Search
    server.search = MagicMock(return_value=[])
    
    # Sessions
    server.sessions = MagicMock(return_value=[])
    server.transcodeSessions = MagicMock(return_value=[])
    
    # Activities
    server.activities = MagicMock(return_value=[])
    
    # Butler
    server.butlerTasks = MagicMock(return_value=[])
    server.runButlerTask = MagicMock()
    
    # Updates
    server.checkForUpdate = MagicMock(return_value=None)
    server.isLatest = MagicMock(return_value=True)
    server.canInstallUpdate = MagicMock(return_value=False)
    server.installUpdate = MagicMock()
    
    # Identity/Account
    server.identity = MagicMock()
    server.account = MagicMock()
    server.systemAccounts = MagicMock(return_value=[])
    server.systemDevices = MagicMock(return_value=[])
    
    # Settings
    server.settings = MagicMock()
    
    # Clients
    server.clients = MagicMock(return_value=[])
    server.client = MagicMock()
    
    # Download
    server.downloadDatabases = MagicMock(return_value="/path/to/db.zip")
    server.downloadLogs = MagicMock(return_value="/path/to/logs.zip")
    
    # Continue Watching
    server.continueWatching = MagicMock(return_value=[])
    
    # History
    server.history = MagicMock(return_value=[])
    
    # Optimized/Conversions
    server.optimizedItems = MagicMock(return_value=[])
    server.conversions = MagicMock(return_value=[])
    server.currentBackgroundProcess = MagicMock(return_value=None)
    
    # Sync
    server.refreshSynclist = MagicMock()
    server.refreshSync = MagicMock()
    
    # Bandwidth
    server.bandwidth = MagicMock(return_value=[])
    
    # Web URL
    server.getWebURL = MagicMock(return_value="https://app.plex.tv/...")
    
    # Image transcoding
    server.transcodeImage = MagicMock(return_value="http://localhost:32400/photo/:/transcode")
    
    # Browse
    server.browse = MagicMock(return_value=[])
    server.walk = MagicMock(return_value=iter([]))
    server.isBrowsable = MagicMock(return_value=True)
    
    # Alerts
    server.startAlertListener = MagicMock()
    
    # Switch user
    server.switchUser = MagicMock()
    
    return server


@pytest.fixture
def mock_account():
    """Create a mock MyPlexAccount."""
    account = MagicMock()
    account.username = "testuser"
    account.email = "test@example.com"
    account.authToken = "auth_token_123"
    
    # Resources
    account.resources = MagicMock(return_value=[])
    account.resource = MagicMock()
    
    # Watchlist
    account.watchlist = MagicMock(return_value=[])
    account.addToWatchlist = MagicMock()
    account.removeFromWatchlist = MagicMock()
    account.onWatchlist = MagicMock(return_value=False)
    
    # Users
    account.users = MagicMock(return_value=[])
    account.user = MagicMock()
    account.inviteFriend = MagicMock()
    account.removeFriend = MagicMock()
    account.updateFriend = MagicMock()
    account.pendingInvites = MagicMock(return_value=[])
    account.acceptInvite = MagicMock()
    account.cancelInvite = MagicMock()
    
    # Home users
    account.createHomeUser = MagicMock()
    account.removeHomeUser = MagicMock()
    account.switchHomeUser = MagicMock()
    
    # History
    account.history = MagicMock(return_value=[])
    
    # Discovery
    account.searchDiscover = MagicMock(return_value=[])
    account.videoOnDemand = MagicMock()
    account.onlineMediaSources = MagicMock(return_value=[])
    
    # Webhooks
    account.webhooks = MagicMock(return_value=[])
    account.addWebhook = MagicMock()
    account.deleteWebhook = MagicMock()
    account.setWebhooks = MagicMock()
    
    # Sync
    account.syncItems = MagicMock(return_value=[])
    
    # Opt out
    account.optOut = MagicMock()
    
    # Claim token
    account.claimToken = MagicMock(return_value="claim-token-123")
    
    # Devices
    account.devices = MagicMock(return_value=[])
    account.device = MagicMock()
    
    return account


@pytest.fixture
def mock_resource():
    """Create a mock MyPlexResource."""
    resource = MagicMock()
    resource.name = "Test Server"
    resource.clientIdentifier = "server123"
    resource.provides = ["server"]
    resource.connect = MagicMock()
    return resource


@pytest.fixture
def mock_config():
    """Create a mock ConfigStore."""
    config = MagicMock()
    config.get_client_id = MagicMock(return_value="client123")
    config.get_auth_token = MagicMock(return_value="auth_token")
    config.get_selected_server = MagicMock(return_value="server123")
    config.get_selected_server_name = MagicMock(return_value="Test Server")
    config.get_preferred_servers = MagicMock(return_value=[])
    config.set_selected_server = MagicMock()
    config.set_selected_server_name = MagicMock()
    config.promote_preferred_server = MagicMock()
    return config


@pytest.fixture
def plex_service(mock_account, mock_config, mock_server, mock_resource):
    """Create a PlexService instance with mocked dependencies."""
    with patch('plex_client.plex_service.PlexService._connect_with_strategy', return_value=mock_server):
        from plex_client.plex_service import PlexService
        service = PlexService(mock_account, mock_config)
        service._server = mock_server
        service._resources = [mock_resource]
        service._current_resource_id = mock_resource.clientIdentifier
        return service
