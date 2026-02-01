"""Tests for PlexService playlist management features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestPlaylistFeatures:
    """Test playlist-related functionality."""

    def test_playlists_returns_list(self, plex_service, mock_server, mock_playlist):
        """Test getting all playlists."""
        mock_server.playlists.return_value = [mock_playlist]
        
        playlists = plex_service.playlists()
        
        assert len(playlists) == 1
        assert playlists[0] == mock_playlist

    def test_playlists_with_filters(self, plex_service, mock_server):
        """Test getting playlists with filters."""
        plex_service.playlists(
            playlist_type="audio",
            section_id=1,
            title="Test",
            sort="lastViewedAt",
        )
        
        mock_server.playlists.assert_called_once_with(
            playlistType="audio",
            sectionId=1,
            title="Test",
            sort="lastViewedAt",
        )

    def test_get_playlist_by_title(self, plex_service, mock_server, mock_playlist):
        """Test getting a specific playlist by title."""
        mock_server.playlist.return_value = mock_playlist
        
        playlist = plex_service.playlist("Test Playlist")
        
        assert playlist == mock_playlist
        mock_server.playlist.assert_called_once_with("Test Playlist")

    def test_create_playlist(self, plex_service, mock_server, mock_playlist, mock_plex_object):
        """Test creating a new playlist."""
        mock_server.createPlaylist.return_value = mock_playlist
        
        result = plex_service.create_playlist(
            title="New Playlist",
            items=[mock_plex_object],
        )
        
        assert result == mock_playlist
        mock_server.createPlaylist.assert_called_once()

    def test_create_smart_playlist(self, plex_service, mock_server, mock_playlist, mock_library_section):
        """Test creating a smart playlist."""
        mock_server.createPlaylist.return_value = mock_playlist
        
        result = plex_service.create_playlist(
            title="Smart Playlist",
            section=mock_library_section,
            smart=True,
            limit=100,
            sort="year:desc",
            filters={"year>>": 2020},
        )
        
        assert result == mock_playlist

    def test_playlist_add_items(self, plex_service, mock_playlist, mock_plex_object):
        """Test adding items to a playlist."""
        items = [mock_plex_object]
        
        plex_service.playlist_add_items(mock_playlist, items)
        
        mock_playlist.addItems.assert_called_once_with(items)

    def test_playlist_remove_items(self, plex_service, mock_playlist, mock_plex_object):
        """Test removing items from a playlist."""
        items = [mock_plex_object]
        
        plex_service.playlist_remove_items(mock_playlist, items)
        
        mock_playlist.removeItems.assert_called_once_with(items)

    def test_playlist_move_item(self, plex_service, mock_playlist, mock_plex_object):
        """Test moving an item within a playlist."""
        after_item = MagicMock()
        
        plex_service.playlist_move_item(mock_playlist, mock_plex_object, after=after_item)
        
        mock_playlist.moveItem.assert_called_once_with(mock_plex_object, after=after_item)

    def test_playlist_delete(self, plex_service, mock_playlist):
        """Test deleting a playlist."""
        plex_service.playlist_delete(mock_playlist)
        
        mock_playlist.delete.assert_called_once()

    def test_playlist_copy_to_user(self, plex_service, mock_playlist):
        """Test copying a playlist to another user."""
        plex_service.playlist_copy_to_user(mock_playlist, "friend@example.com")
        
        mock_playlist.copyToUser.assert_called_once_with("friend@example.com")
