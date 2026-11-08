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


class TestSearchCompatibility:
    """Test PlexService search compatibility across plexapi versions."""

    def test_search_supports_maxresults_alias(self, plex_service, mock_server, mock_plex_object):
        """Map search(limit=...) to alternate search(maxresults=...) signatures."""
        captured = {}

        def search(query, *, maxresults=None):
            captured["query"] = query
            captured["maxresults"] = maxresults
            return [mock_plex_object]

        mock_server.search = search

        results = plex_service.search("matrix", limit=7)

        assert len(results) == 1
        assert captured == {"query": "matrix", "maxresults": 7}


def test_failed_timeline_is_not_reported_as_confirmed_progress(plex_service):
    from plex_client.plex_service import PlayableMedia

    item = MagicMock()
    item.duration = 60000
    item.viewOffset = 12000
    item.updateTimeline.side_effect = RuntimeError("offline")
    media = PlayableMedia("Movie", "movie", "/library/metadata/1", "", None, 12000, item)
    with pytest.raises(RuntimeError, match="offline"):
        plex_service.update_timeline(media, "paused", 20000, 60000)


def test_failed_progress_reload_does_not_fabricate_confirmation(plex_service):
    from plex_client.plex_service import PlayableMedia

    item = MagicMock()
    item.duration = 60000
    item.viewOffset = 12000
    item.reload.side_effect = RuntimeError("offline")
    media = PlayableMedia("Movie", "movie", "/library/metadata/1", "", None, 12000, item)
    assert plex_service.update_timeline(media, "paused", 20000, 60000) == ("paused", 0)


def test_zero_server_progress_does_not_confirm_local_position(plex_service):
    from plex_client.plex_service import PlayableMedia

    item = MagicMock()
    item.duration = 60000
    item.viewOffset = 0
    media = PlayableMedia("Movie", "movie", "/library/metadata/1", "", None, 0, item)
    assert plex_service.update_timeline(media, "playing", 20000, 60000) == ("playing", 0)


def _no_waiting(monkeypatch):
    from plex_client import plex_service as service_module

    def fail_sleep(_seconds):
        raise AssertionError("update_timeline waited for a resume point")

    monkeypatch.setattr(service_module.time, "sleep", fail_sleep)


def test_track_stop_does_not_wait_for_a_resume_point(plex_service, monkeypatch):
    """Plex keeps no viewOffset for music tracks, so Stop must not spin for 8 s."""
    from plex_client.plex_service import PlayableMedia

    _no_waiting(monkeypatch)
    item = MagicMock()
    item.type = "track"
    item.duration = 184580
    item.viewOffset = 0
    media = PlayableMedia("Song", "track", "/library/metadata/1", "", None, 0, item)
    assert plex_service.update_timeline(media, "stopped", 21845, 184580) == ("paused", 21845)
    assert item.reload.call_count == 1


def test_track_progress_flush_confirms_so_it_is_not_resent(plex_service, mock_server, monkeypatch):
    """A cached track position is confirmed once the server accepts it."""
    _no_waiting(monkeypatch)
    item = MagicMock()
    item.type = "track"
    item.title = "Song"
    item.key = "/library/metadata/1"
    item.duration = 184580
    item.viewOffset = 0
    mock_server.fetchItem = MagicMock(return_value=item)
    assert plex_service.update_progress_by_key("1", 21845, 184580, "paused") == ("paused", 21845)


def test_track_keeps_a_real_server_resume_point(plex_service, monkeypatch):
    """When the server does keep a track offset (audiobooks), report the real value."""
    from plex_client.plex_service import PlayableMedia

    _no_waiting(monkeypatch)
    item = MagicMock()
    item.type = "track"
    item.duration = 3600000
    item.viewOffset = 600000
    media = PlayableMedia("Chapter", "track", "/library/metadata/1", "", None, 0, item)
    assert plex_service.update_timeline(media, "stopped", 600500, 3600000) == ("paused", 600000)


def test_failed_track_reload_does_not_fabricate_confirmation(plex_service, monkeypatch):
    from plex_client.plex_service import PlayableMedia

    _no_waiting(monkeypatch)
    item = MagicMock()
    item.type = "track"
    item.duration = 184580
    item.viewOffset = 0
    item.reload.side_effect = RuntimeError("offline")
    media = PlayableMedia("Song", "track", "/library/metadata/1", "", None, 0, item)
    assert plex_service.update_timeline(media, "stopped", 21845, 184580) == ("paused", 0)


def test_movie_stop_still_waits_for_server_confirmation(plex_service, monkeypatch):
    """Video keeps the confirm loop: a zero offset is not proof of a saved position."""
    from plex_client import plex_service as service_module
    from plex_client.plex_service import PlayableMedia

    clock = iter(range(0, 1000))
    monkeypatch.setattr(service_module.time, "time", lambda: float(next(clock)))
    sleeps = []
    monkeypatch.setattr(service_module.time, "sleep", sleeps.append)
    item = MagicMock()
    item.type = "movie"
    item.duration = 60000
    item.viewOffset = 0
    media = PlayableMedia("Movie", "movie", "/library/metadata/1", "", None, 0, item)
    assert plex_service.update_timeline(media, "stopped", 20000, 60000) == ("paused", 0)
    assert sleeps, "the movie path should still poll the server"


def test_listing_synthetic_radios_does_not_query_the_server(plex_service):
    """Radio options are listed on every music selection; they must stay free."""
    section = MagicMock()
    section.librarySectionID = 3
    options = plex_service._synthetic_radio_options(section)
    assert [option.action for option in options] == ["library_radio", "recent_radio", "shuffle_radio"]
    assert all(option.data["seed_rating_key"] is None for option in options)
    section.searchTracks.assert_not_called()
    section.recentlyAddedTracks.assert_not_called()


def test_starting_synthetic_radio_loads_only_the_chosen_seed(plex_service, monkeypatch):
    """The seed is picked on start from one search, without loading every candidate."""
    tracks = []
    for index in range(200):
        track = MagicMock()
        track.type = "track"
        track.ratingKey = str(index)
        tracks.append(track)
    section = MagicMock()
    section.librarySectionID = 3
    section.searchTracks = MagicMock(return_value=tracks)
    loaded = []
    monkeypatch.setattr(plex_service, "_ensure_item_loaded", lambda item: loaded.append(item) or item)
    monkeypatch.setattr(plex_service, "_create_play_queue", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr(plex_service, "_initialize_radio_session", lambda queue, **kwargs: ("media", "session"))

    assert plex_service._start_synthetic_radio(section, "library_radio", "Library Radio") == ("media", "session")
    assert section.searchTracks.call_count == 1
    assert len(loaded) == 1
def _letter(key, title, size):
    from types import SimpleNamespace

    return SimpleNamespace(key=key, title=title, size=str(size))


@pytest.mark.parametrize(
    ("category", "type_id"), [("artists", 8), ("albums", 9), ("tracks", 10)]
)
def test_letter_list_is_requested_by_type_and_title(plex_service, category, type_id):
    """libtype= is ignored by Plex; type= plus a title sort keeps sizes and items aligned."""
    from plexapi.library import FirstCharacter

    section = MagicMock()
    section.key = 4
    section.fetchItems.return_value = [_letter("A", "A", 3)]
    entries = plex_service._fetch_first_character_entries(section, category)
    assert len(entries) == 1
    section.fetchItems.assert_called_once_with(
        f"/library/sections/4/firstCharacter?type={type_id}&sort=titleSort", cls=FirstCharacter
    )


def test_letter_buckets_use_server_paths_and_real_titles(plex_service):
    """Bare letter keys become full paths, and album letters keep their name and size."""
    section = MagicMock()
    section.key = 4
    section.fetchItems.return_value = [_letter("%23", "#", 105), _letter("A", "A", 151)]
    buckets = plex_service._music_alpha_buckets(section, "albums")
    assert buckets[0].title == "Browse All Albums (256)"
    assert [bucket.character for bucket in buckets[1:]] == ["#", "A"]
    assert buckets[2].count == 151
    assert buckets[1].key == "/library/sections/4/firstCharacter/%23?type=9&sort=titleSort"
    assert buckets[2].key == "/library/sections/4/firstCharacter/A?type=9&sort=titleSort"


def test_opening_a_letter_does_not_reload_each_item(plex_service, monkeypatch):
    """One paged request opens a letter; no per-item round trip to the server."""
    from plex_client.plex_service import MusicAlphaBucket

    def fail_reload(_item):
        raise AssertionError("letter items were reloaded one by one")

    monkeypatch.setattr(plex_service, "_ensure_item_loaded", fail_reload)
    section = MagicMock()
    artists = [MagicMock(type="artist") for _ in range(3)]
    section.fetchItems.return_value = artists
    bucket = MusicAlphaBucket(
        identifier="music:artists:A", title="A · 3 artists",
        key="/library/sections/4/firstCharacter/A?type=8&sort=titleSort",
        category="artists", libtype="artist", section=section, count=3, summary="", character="A",
    )
    assert plex_service._music_alpha_bucket_items(bucket) == artists
    section.fetchItems.assert_called_once_with(bucket.key, container_size=1000)


def _media_node(kind, view_offset):
    node = MagicMock()
    node.type = kind
    node.title = "Item"
    node.key = "/library/metadata/1"
    node.viewOffset = view_offset
    node.media = None
    node.getStreamURL.return_value = "http://server:32400/stream?a=1"
    return node


def test_playing_a_track_again_starts_from_the_beginning(plex_service):
    """Stop records the position; replaying a track must not resume it like a pause."""
    node = _media_node("track", 15220)
    with patch.object(plex_service, "ensure_server", return_value=MagicMock(_token="t")):
        playable = plex_service.to_playable(node)
    assert playable.resume_offset == 0
    node.getStreamURL.assert_called_once_with(offset=0)


@pytest.mark.parametrize("kind", ["movie", "episode"])
def test_videos_still_resume_where_they_were_left(plex_service, kind):
    node = _media_node(kind, 15220)
    with patch.object(plex_service, "ensure_server", return_value=MagicMock(_token="t")):
        playable = plex_service.to_playable(node)
    assert playable.resume_offset == 15220
    node.getStreamURL.assert_called_once_with(offset=15220)


def _hub(hub_type, items, identifier="hub"):
    from types import SimpleNamespace

    return SimpleNamespace(type=hub_type, hubIdentifier=identifier, title=identifier, context="", items=lambda: list(items))


def _station(index):
    from types import SimpleNamespace

    return SimpleNamespace(
        type="playlist",
        key=f"/library/sections/5/stations/{index}",
        title=f"Station {index}",
        summary="",
        ratingKey=None,
        librarySectionID=5,
    )


def test_radios_list_only_station_hubs_without_reloading(plex_service, monkeypatch):
    """Album hubs such as "Recently added" can hold the whole library; they are not stations."""
    from types import SimpleNamespace

    albums = [SimpleNamespace(type="album", key=f"/library/metadata/{i}", ratingKey=str(i)) for i in range(500)]
    stations = [_station(1), _station(2)]
    section = MagicMock()
    section.key = 5
    section.librarySectionID = 5
    section.hubs = MagicMock(
        return_value=[_hub("album", albums, "music.recent.added.5"), _hub("station", stations, "music.stations.5")]
    )
    section.stations = MagicMock(return_value=[])
    monkeypatch.setattr(plex_service, "_fetch_section_station_directory", lambda section: [])
    reloaded = []
    monkeypatch.setattr(plex_service, "_ensure_item_loaded", lambda item: reloaded.append(item) or item)

    result = plex_service._radio_stations_for_section(section)

    assert [station.key for station in result] == [s.key for s in stations]
    assert reloaded == [], "station entries are used as listed, never reloaded one by one"


def test_station_entries_are_read_without_plexapi_auto_reload(plex_service):
    """Reading an empty field of a partial plexapi object would query the server."""
    from plexapi.playlist import Playlist

    station = Playlist.__new__(Playlist)
    station.__dict__.update(type="playlist", key="/library/sections/5/stations/1", _autoReload=True)
    assert plex_service._station_key(station) == "/library/sections/5/stations/1"
    assert station._autoReload is False
def test_opening_a_playlist_does_not_reload_each_track(plex_service, monkeypatch):
    """A 58,000-track smart playlist took about 20 minutes when every entry was reloaded."""
    tracks = []
    for index in range(300):
        track = MagicMock()
        track.type = "track"
        track.ratingKey = str(index)
        tracks.append(track)
    playlist = MagicMock()
    playlist.ratingKey = "77"
    playlist.items = MagicMock(return_value=tracks)
    reloaded = []
    monkeypatch.setattr(plex_service, "_ensure_item_loaded", lambda item: reloaded.append(item) or item)

    assert plex_service._playlist_items(playlist) == tracks
    assert reloaded == []
    assert playlist.items.call_count == 1
    assert plex_service._playlist_items(playlist) == tracks, "second open comes from the cache"
    assert playlist.items.call_count == 1
