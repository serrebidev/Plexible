"""Tests for core PlexService functionality."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


class TestServerConnection:
    """Test server connection functionality."""

    def test_ensure_server_returns_existing(self, plex_service, mock_server):
        """Test that ensure_server returns existing server."""
        result = plex_service.ensure_server()
        
        assert result == mock_server

    def test_server_property(self, plex_service, mock_server):
        """Test server property."""
        assert plex_service.server == mock_server

    def test_available_servers(self, plex_service, mock_resource):
        """Test getting available servers."""
        servers = plex_service.available_servers()
        
        assert len(servers) == 1
        assert servers[0] == mock_resource

    def test_current_resource_id(self, plex_service, mock_resource):
        """Test getting current resource ID."""
        result = plex_service.current_resource_id()
        
        assert result == mock_resource.clientIdentifier

    def test_current_resource(self, plex_service, mock_resource):
        """Test getting current resource."""
        result = plex_service.current_resource()
        
        assert result == mock_resource


class TestPlayableMedia:
    """Test PlayableMedia dataclass."""

    def test_playable_media_creation(self):
        """Test creating PlayableMedia."""
        from plex_client.plex_service import PlayableMedia
        
        item = MagicMock()
        media = PlayableMedia(
            title="Test Movie",
            media_type="movie",
            key="/library/metadata/12345",
            stream_url="http://localhost:32400/library/parts/...",
            browser_url="https://app.plex.tv/...",
            resume_offset=0,
            item=item,
        )
        
        assert media.title == "Test Movie"
        assert media.media_type == "movie"
        assert media.resume_offset == 0


class TestSearchHit:
    """Test SearchHit dataclass."""

    def test_search_hit_creation(self, mock_resource, mock_server, mock_plex_object):
        """Test creating SearchHit."""
        from plex_client.plex_service import SearchHit
        
        hit = SearchHit(
            resource=mock_resource,
            server=mock_server,
            item=mock_plex_object,
        )
        
        assert hit.resource == mock_resource
        assert hit.server == mock_server
        assert hit.item == mock_plex_object


class TestMusicRadioStation:
    """Test MusicRadioStation dataclass."""

    def test_radio_station_creation(self, mock_plex_object):
        """Test creating MusicRadioStation."""
        from plex_client.plex_service import MusicRadioStation
        
        station = MusicRadioStation(
            identifier="station123",
            title="Test Radio",
            summary="A test radio station",
            key="/library/sections/2/stations/1",
            station_type="artist",
            category="radio",
            library_section_id="2",
            hub_title="Artist Radio",
            hub_context="hub.music.artistradio",
            item=mock_plex_object,
        )
        
        assert station.identifier == "station123"
        assert station.type == "radio_station"


class TestRadioOption:
    """Test RadioOption dataclass."""

    def test_radio_option_creation(self):
        """Test creating RadioOption."""
        from plex_client.plex_service import RadioOption
        
        option = RadioOption(
            id="library_radio",
            label="Library Radio",
            description="Shuffle your entire library",
            category="synthetic",
            action="play_synthetic_radio",
            data={"mode": "library"},
        )
        
        assert option.id == "library_radio"
        assert option.action == "play_synthetic_radio"


class TestMusicCategory:
    """Test MusicCategory dataclass."""

    def test_music_category_creation(self, mock_music_section):
        """Test creating MusicCategory."""
        from plex_client.plex_service import MusicCategory
        
        category = MusicCategory(
            identifier="recently_added",
            title="Recently Added",
            summary="Recently added music",
            category="music",
            section=mock_music_section,
        )
        
        assert category.identifier == "recently_added"
        assert category.type == "category"


class TestMusicAlphaBucket:
    """Test MusicAlphaBucket dataclass."""

    def test_alpha_bucket_creation(self, mock_music_section):
        """Test creating MusicAlphaBucket."""
        from plex_client.plex_service import MusicAlphaBucket
        
        bucket = MusicAlphaBucket(
            identifier="artists_a",
            title="A",
            key="/library/sections/2/all?type=8&sort=titleSort&firstCharacter=A",
            category="alphabetical",
            libtype="artist",
            section=mock_music_section,
            count=42,
            character="A",
        )
        
        assert bucket.identifier == "artists_a"
        assert bucket.count == 42
        assert bucket.type == "alpha_bucket"
