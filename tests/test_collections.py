"""Tests for PlexService collection management features."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


class TestCollectionFeatures:
    """Test collection-related functionality."""

    def test_collections_returns_list(self, plex_service, mock_library_section, mock_collection):
        """Test getting all collections in a section."""
        mock_library_section.collections.return_value = [mock_collection]
        
        collections = plex_service.collections(mock_library_section)
        
        assert len(collections) == 1
        assert collections[0] == mock_collection

    def test_get_collection_by_title(self, plex_service, mock_library_section, mock_collection):
        """Test getting a specific collection by title."""
        mock_library_section.collection.return_value = mock_collection
        
        collection = plex_service.collection(mock_library_section, "Test Collection")
        
        assert collection == mock_collection
        mock_library_section.collection.assert_called_once_with("Test Collection")

    def test_create_collection(self, plex_service, mock_server, mock_collection, mock_library_section, mock_plex_object):
        """Test creating a new collection."""
        mock_server.createCollection.return_value = mock_collection
        
        result = plex_service.create_collection(
            title="New Collection",
            section=mock_library_section,
            items=[mock_plex_object],
        )
        
        assert result == mock_collection
        mock_server.createCollection.assert_called_once()

    def test_create_smart_collection(self, plex_service, mock_server, mock_collection, mock_library_section):
        """Test creating a smart collection."""
        mock_server.createCollection.return_value = mock_collection
        
        result = plex_service.create_collection(
            title="Smart Collection",
            section=mock_library_section,
            smart=True,
            limit=50,
            sort="rating:desc",
            filters={"contentRating": "R"},
        )
        
        assert result == mock_collection

    def test_collection_add_items(self, plex_service, mock_collection, mock_plex_object):
        """Test adding items to a collection."""
        items = [mock_plex_object]
        
        plex_service.collection_add_items(mock_collection, items)
        
        mock_collection.addItems.assert_called_once_with(items)

    def test_collection_remove_items(self, plex_service, mock_collection, mock_plex_object):
        """Test removing items from a collection."""
        items = [mock_plex_object]
        
        plex_service.collection_remove_items(mock_collection, items)
        
        mock_collection.removeItems.assert_called_once_with(items)

    def test_collection_move_item(self, plex_service, mock_collection, mock_plex_object):
        """Test moving an item within a collection."""
        after_item = MagicMock()
        
        plex_service.collection_move_item(mock_collection, mock_plex_object, after=after_item)
        
        mock_collection.moveItem.assert_called_once_with(mock_plex_object, after=after_item)

    def test_collection_delete(self, plex_service, mock_collection):
        """Test deleting a collection."""
        plex_service.collection_delete(mock_collection)
        
        mock_collection.delete.assert_called_once()
