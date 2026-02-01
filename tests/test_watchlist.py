"""Tests for PlexService watchlist features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestWatchlistFeatures:
    """Test watchlist-related functionality."""

    def test_watchlist_returns_items(self, plex_service, mock_account, mock_plex_object):
        """Test getting watchlist items."""
        mock_account.watchlist.return_value = [mock_plex_object]
        
        items = plex_service.watchlist()
        
        assert len(items) == 1
        assert items[0] == mock_plex_object
        mock_account.watchlist.assert_called_once()

    def test_watchlist_with_filters(self, plex_service, mock_account):
        """Test getting watchlist with filters."""
        plex_service.watchlist(
            filter="released",
            sort="titleSort",
            libtype="movie",
            maxresults=50,
        )
        
        mock_account.watchlist.assert_called_once_with(
            filter="released",
            sort="titleSort",
            libtype="movie",
            maxresults=50,
        )

    def test_add_to_watchlist(self, plex_service, mock_account, mock_plex_object):
        """Test adding item to watchlist."""
        plex_service.add_to_watchlist(mock_plex_object)
        
        mock_account.addToWatchlist.assert_called_once_with(mock_plex_object)

    def test_remove_from_watchlist(self, plex_service, mock_account, mock_plex_object):
        """Test removing item from watchlist."""
        plex_service.remove_from_watchlist(mock_plex_object)
        
        mock_account.removeFromWatchlist.assert_called_once_with(mock_plex_object)

    def test_on_watchlist_true(self, plex_service, mock_account, mock_plex_object):
        """Test checking if item is on watchlist (true case)."""
        mock_account.onWatchlist.return_value = True
        
        result = plex_service.on_watchlist(mock_plex_object)
        
        assert result is True
        mock_account.onWatchlist.assert_called_once_with(mock_plex_object)

    def test_on_watchlist_false(self, plex_service, mock_account, mock_plex_object):
        """Test checking if item is on watchlist (false case)."""
        mock_account.onWatchlist.return_value = False
        
        result = plex_service.on_watchlist(mock_plex_object)
        
        assert result is False
