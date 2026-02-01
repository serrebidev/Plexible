"""Tests for PlexService library management features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestLibraryManagement:
    """Test library management functionality."""

    def test_library_sections(self, plex_service, mock_server, mock_library_section):
        """Test getting all library sections."""
        mock_server.library.sections.return_value = [mock_library_section]
        
        sections = plex_service.library_sections()
        
        assert len(sections) == 1
        mock_server.library.sections.assert_called_once()

    def test_library_section_by_title(self, plex_service, mock_server, mock_library_section):
        """Test getting a library section by title."""
        mock_server.library.section.return_value = mock_library_section
        
        section = plex_service.library_section("Movies")
        
        assert section == mock_library_section
        mock_server.library.section.assert_called_once_with("Movies")

    def test_library_section_by_id(self, plex_service, mock_server, mock_library_section):
        """Test getting a library section by ID."""
        mock_server.library.sectionByID.return_value = mock_library_section
        
        section = plex_service.library_section_by_id(1)
        
        assert section == mock_library_section
        mock_server.library.sectionByID.assert_called_once_with(1)

    def test_library_update_all(self, plex_service, mock_server):
        """Test triggering a full library update."""
        plex_service.library_update()
        
        mock_server.library.update.assert_called_once()

    def test_library_update_section(self, plex_service, mock_library_section):
        """Test triggering a section-specific update."""
        plex_service.library_update(section=mock_library_section)
        
        mock_library_section.update.assert_called_once_with(path=None)

    def test_library_update_section_path(self, plex_service, mock_library_section):
        """Test triggering an update for a specific path."""
        plex_service.library_update(section=mock_library_section, path="/media/movies/new")
        
        mock_library_section.update.assert_called_once_with(path="/media/movies/new")

    def test_library_cancel_update_all(self, plex_service, mock_server):
        """Test canceling all library updates."""
        plex_service.library_cancel_update()
        
        mock_server.library.cancelUpdate.assert_called_once()

    def test_library_cancel_update_section(self, plex_service, mock_library_section):
        """Test canceling a section update."""
        plex_service.library_cancel_update(section=mock_library_section)
        
        mock_library_section.cancelUpdate.assert_called_once()

    def test_library_empty_trash_all(self, plex_service, mock_server):
        """Test emptying trash for all libraries."""
        plex_service.library_empty_trash()
        
        mock_server.library.emptyTrash.assert_called_once()

    def test_library_empty_trash_section(self, plex_service, mock_library_section):
        """Test emptying trash for a specific section."""
        plex_service.library_empty_trash(section=mock_library_section)
        
        mock_library_section.emptyTrash.assert_called_once()

    def test_library_clean_bundles(self, plex_service, mock_server):
        """Test cleaning unused bundles."""
        plex_service.library_clean_bundles()
        
        mock_server.library.cleanBundles.assert_called_once()

    def test_library_optimize(self, plex_service, mock_server):
        """Test optimizing the library database."""
        plex_service.library_optimize()
        
        mock_server.library.optimize.assert_called_once()

    def test_library_refresh(self, plex_service, mock_library_section):
        """Test refreshing a library section."""
        plex_service.library_refresh(mock_library_section)
        
        mock_library_section.refresh.assert_called_once()

    def test_library_analyze(self, plex_service, mock_library_section):
        """Test analyzing a library section."""
        plex_service.library_analyze(mock_library_section)
        
        mock_library_section.analyze.assert_called_once()


class TestLibraryDiscovery:
    """Test library discovery/browsing features."""

    def test_library_recently_added_all(self, plex_service, mock_server, mock_plex_object):
        """Test getting recently added from all libraries."""
        mock_server.library.recentlyAdded.return_value = [mock_plex_object]
        
        items = plex_service.library_recently_added()
        
        assert len(items) == 1
        mock_server.library.recentlyAdded.assert_called_once()

    def test_library_recently_added_section(self, plex_service, mock_library_section, mock_plex_object):
        """Test getting recently added from a section."""
        mock_library_section.recentlyAdded.return_value = [mock_plex_object]
        
        items = plex_service.library_recently_added(section=mock_library_section, maxresults=25)
        
        assert len(items) == 1
        mock_library_section.recentlyAdded.assert_called_once_with(maxresults=25, libtype=None)

    def test_library_on_deck_all(self, plex_service, mock_server, mock_episode):
        """Test getting on-deck from all libraries."""
        mock_server.library.onDeck.return_value = [mock_episode]
        
        items = plex_service.library_on_deck()
        
        assert len(items) == 1
        mock_server.library.onDeck.assert_called_once()

    def test_library_on_deck_section(self, plex_service, mock_library_section, mock_episode):
        """Test getting on-deck from a section."""
        mock_library_section.onDeck.return_value = [mock_episode]
        
        items = plex_service.library_on_deck(section=mock_library_section)
        
        assert len(items) == 1
        mock_library_section.onDeck.assert_called_once()

    def test_library_continue_watching_server(self, plex_service, mock_server, mock_video):
        """Test getting continue watching from server."""
        mock_server.continueWatching.return_value = [mock_video]
        
        items = plex_service.library_continue_watching()
        
        assert len(items) == 1
        mock_server.continueWatching.assert_called_once()

    def test_library_continue_watching_section(self, plex_service, mock_library_section, mock_video):
        """Test getting continue watching from a section."""
        mock_library_section.continueWatching.return_value = [mock_video]
        
        items = plex_service.library_continue_watching(section=mock_library_section)
        
        assert len(items) == 1
        mock_library_section.continueWatching.assert_called_once()

    def test_library_hubs_server(self, plex_service, mock_server):
        """Test getting hubs from server."""
        hub = MagicMock()
        hub.title = "Continue Watching"
        mock_server.library.hubs.return_value = [hub]
        
        hubs = plex_service.library_hubs()
        
        assert len(hubs) == 1
        mock_server.library.hubs.assert_called_once()

    def test_library_hubs_section(self, plex_service, mock_library_section):
        """Test getting hubs from a section."""
        hub = MagicMock()
        hub.title = "Recently Added"
        mock_library_section.hubs.return_value = [hub]
        
        hubs = plex_service.library_hubs(section=mock_library_section)
        
        assert len(hubs) == 1
        mock_library_section.hubs.assert_called_once()
