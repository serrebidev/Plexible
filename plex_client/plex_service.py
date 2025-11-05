from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import time
import random
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from plexapi.base import PlexObject
from plexapi.exceptions import NotFound
from plexapi.library import Folder, LibrarySection, MusicSection, Hub
from plexapi.media import MediaPart
from plexapi.myplex import MyPlexAccount, MyPlexResource
from plexapi.playqueue import PlayQueue
from plexapi.server import PlexServer

from .config import ConfigStore


@dataclass
class PlayableMedia:
    title: str
    media_type: str
    key: str
    stream_url: str
    browser_url: Optional[str]
    resume_offset: int
    item: PlexObject


@dataclass
class SearchHit:
    resource: MyPlexResource
    server: PlexServer
    item: PlexObject


@dataclass(frozen=True)
class MusicRadioStation:
    identifier: str
    title: str
    summary: str
    key: str
    station_type: str
    category: str
    library_section_id: Optional[str]
    hub_title: str
    hub_context: str
    item: PlexObject
    type: str = "radio_station"


@dataclass
class RadioOption:
    id: str
    label: str
    description: str
    category: str
    action: str
    data: Dict[str, Any]


@dataclass
class RadioSession:
    kind: str
    description: str
    queue: PlayQueue
    current_index: int
    play_queue_id: int
    library_section_id: Optional[str] = None
    station: Optional[MusicRadioStation] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class MusicCategory:
    identifier: str
    title: str
    summary: str
    category: str
    section: MusicSection
    key: str = ""
    type: str = "category"


@dataclass(frozen=True)
class MusicAlphaBucket:
    identifier: str
    title: str
    key: str
    category: str
    libtype: str
    section: MusicSection
    count: int = 0
    summary: str = ""
    character: str = ""
    type: str = "alpha_bucket"

@dataclass(frozen=True)
class MusicRadioOption:
    identifier: str
    label: str
    description: str
    option: RadioOption
    type: str = "radio_option"

    @property
    def title(self) -> str:
        return self.label


    @property
    def summary(self) -> str:
        return self.description


_RADIO_KEYWORDS: Dict[str, List[str]] = {
    "library_radio": ["library radio", "library station"],
    "time_travel_radio": ["time travel", "time-travel"],
    "random_album_radio": ["random album", "random-album"],
    "genre_radio": ["genre radio", "genre station"],
    "style_radio": ["style radio", "style station"],
    "mood_radio": ["mood radio", "mood station"],
    "decade_radio": ["decade radio", "decade station", "decades radio"],
    "artist_mix_builder": ["artist mix builder", "artist mix"],
    "album_mix_builder": ["album mix builder", "album mix"],
    "sonic_adventure": ["sonic adventure", "sonic adventure radio"],
    "deep_cuts_radio": ["deep cuts", "deep cut radio"],
    "artist_radio": ["artist radio"],
    "album_radio": ["album radio", "album mix"],
    "track_radio": ["track radio"],
}

_RADIO_DISPLAY_NAMES: Dict[str, str] = {
    "library_radio": "Library Radio",
    "time_travel_radio": "Time Travel Radio",
    "random_album_radio": "Random Album Radio",
    "genre_radio": "Genre Radio",
    "style_radio": "Style Radio",
    "mood_radio": "Mood Radio",
    "decade_radio": "Decade Radio",
    "artist_mix_builder": "Artist Mix Builder",
    "album_mix_builder": "Album Mix Builder",
    "sonic_adventure": "Sonic Adventure",
    "deep_cuts_radio": "Deep Cuts Radio",
    "artist_radio": "Artist Radio",
    "album_radio": "Album Radio",
    "track_radio": "Track Radio",
}

_MUSIC_CATEGORY_DEFINITIONS: Tuple[Tuple[str, str, str], ...] = (
    (
        "recently_added",
        "Recently Added",
        "Latest albums and songs added to this library.",
    ),
    (
        "radios",
        "Radios",
        "Plex radio stations and mixes available for this music library.",
    ),
    (
        "artists",
        "Artists",
        "Browse all artists in this library.",
    ),
    (
        "albums",
        "Albums",
        "Browse every album in this library.",
    ),
    (
        "tracks",
        "Songs",
        "Browse all songs in this library.",
    ),
    (
        "playlists",
        "Playlists",
        "Audio playlists that include music from this server.",
    ),
)


class PlexService:
    """Wraps common operations against the Plex API for the UI layer."""

    def __init__(self, account: MyPlexAccount, config: ConfigStore) -> None:
        self._account = account
        self._config = config
        self._resources: List[MyPlexResource] = []
        self._server: Optional[PlexServer] = None
        self._current_resource_id: Optional[str] = None
        self._last_search_errors: List[str] = []
        self._radio_station_cache: Dict[str, List[MusicRadioStation]] = {}
        self._music_category_cache: Dict[str, List[MusicCategory]] = {}
        self._music_alpha_cache: Dict[str, List[MusicAlphaBucket]] = {}
        self._music_alpha_items_cache: Dict[str, List[PlexObject]] = {}
        self._playlist_items_cache: Dict[str, List[PlexObject]] = {}

    @property
    def server(self) -> Optional[PlexServer]:
        return self._server

    def refresh_servers(self) -> List[MyPlexResource]:
        self._resources = [
            resource
            for resource in self._account.resources()
            if "server" in (resource.provides or [])
        ]
        return self._resources

    def available_servers(self) -> List[MyPlexResource]:
        if not self._resources:
            return self.refresh_servers()
        return self._resources

    def connect(self, identifier: Optional[str] = None) -> PlexServer:
        servers = self.available_servers()
        if not servers:
            raise RuntimeError("No Plex servers are available for this account.")

        def normalize(value: Optional[str]) -> Optional[str]:
            if not isinstance(value, str):
                return None
            trimmed = value.strip()
            return trimmed if trimmed else None

        def match_token(token: str) -> Optional[MyPlexResource]:
            direct = normalize(token)
            if not direct:
                return None
            direct_lower = direct.lower()
            for resource in servers:
                candidate = normalize(resource.clientIdentifier)
                if candidate and candidate == direct:
                    return resource
            for resource in servers:
                candidate = normalize(resource.clientIdentifier)
                if candidate and candidate.lower() == direct_lower:
                    return resource
            for resource in servers:
                candidate = normalize(resource.name)
                if candidate and candidate.lower() == direct_lower:
                    return resource
            return None

        preference_tokens: List[str] = []
        for token in self._config.get_preferred_servers():
            normalized = normalize(token)
            if normalized and normalized not in preference_tokens:
                preference_tokens.append(normalized)
        selected_name = normalize(self._config.get_selected_server_name())
        if selected_name and selected_name not in preference_tokens:
            preference_tokens.append(selected_name)
        primary_identifier = normalize(identifier)
        if primary_identifier and primary_identifier not in preference_tokens:
            preference_tokens.append(primary_identifier)

        target: Optional[MyPlexResource] = None
        for token in preference_tokens:
            candidate = match_token(token)
            if candidate:
                target = candidate
                break

        if target is None:
            target = servers[0]
        return self.connect_resource(target)

    def connect_resource(self, resource: MyPlexResource) -> PlexServer:
        if resource not in self._resources:
            self._resources.append(resource)
        server = self._connect_with_strategy(resource, reason="connect")
        self._server = server
        self._current_resource_id = resource.clientIdentifier
        self._config.set_selected_server(resource.clientIdentifier)
        self._config.set_selected_server_name(resource.name or resource.clientIdentifier)
        self._config.promote_preferred_server(resource.clientIdentifier, resource.name)
        self._radio_station_cache.clear()
        self._music_category_cache.clear()
        self._music_alpha_cache.clear()
        self._music_alpha_items_cache.clear()
        self._playlist_items_cache.clear()
        return server

    def _connect_with_strategy(
        self,
        resource: MyPlexResource,
        *,
        prefer_local: bool = True,
        reason: str = "connect",
    ) -> PlexServer:
        name = resource.name or resource.clientIdentifier or "Plex Server"
        attempts: List[Tuple[str, Dict[str, Optional[object]]]] = []
        base_locations = ["local", "remote", "relay"]
        base_timeout = 6
        if prefer_local:
            attempts.append(
                (
                    "local-first",
                    {"ssl": None, "timeout": base_timeout, "locations": base_locations},
                )
            )
        attempts.append(
            (
                "secure-only",
                {"ssl": True, "timeout": base_timeout, "locations": ["remote", "relay"]},
            )
        )
        attempts.append(
            (
                "fallback",
                {"ssl": None, "timeout": None, "locations": base_locations},
            )
        )
        last_exc: Optional[Exception] = None
        for label, kwargs in attempts:
            try:
                server = resource.connect(**kwargs)
                print(f"[PlexService] Connected to {name} via {label} strategy.")
                return server
            except Exception as exc:
                last_exc = exc
                print(f"[PlexService] {reason} attempt '{label}' failed for {name}: {exc}")
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Unable to connect to Plex resource '{name}'.")

    def ensure_server(self) -> PlexServer:
        if self._server:
            return self._server
        stored_identifier = self._config.get_selected_server()
        return self.connect(identifier=stored_identifier)

    def libraries(self) -> Sequence[LibrarySection]:
        server = self.ensure_server()
        return server.library.sections()

    def list_children(self, node: object) -> Iterable[object]:
        if isinstance(node, MusicSection):
            return self._music_categories_for_section(node)
        if isinstance(node, MusicCategory):
            return self._music_category_items(node)
        if isinstance(node, MusicAlphaBucket):
            return self._music_alpha_bucket_items(node)
        if isinstance(node, LibrarySection):
            return node.all()
        if isinstance(node, Folder):
            try:
                return list(node.subfolders())
            except Exception:
                return []
        obj_type = getattr(node, "type", "")
        if obj_type == "show":
            return node.seasons()
        if obj_type == "season":
            return node.episodes()
        if obj_type == "episode":
            return []
        if obj_type == "artist":
            return node.albums()
        if obj_type == "album":
            return node.tracks()
        if obj_type == "track":
            return []
        if obj_type == "playlist":
            return self._playlist_items(node)
        if obj_type in {"photo", "clip"}:
            return []
        if obj_type == "photoalbum":
            return node.photos()
        if obj_type == "collection":
            return node.children()
        try:
            return node.children()
        except (NotFound, AttributeError):
            return []

    @staticmethod
    def _normalize_section_id(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                return None
            return trimmed
        try:
            return str(int(value))
        except Exception:
            try:
                return str(value)
            except Exception:
                return None

    def _music_section_for(self, plex_object: Optional[PlexObject]) -> Optional[MusicSection]:
        try:
            server = self.ensure_server()
        except Exception:
            return None
        if isinstance(plex_object, MusicSection):
            return plex_object
        if isinstance(plex_object, LibrarySection) and getattr(plex_object, "type", "") == "artist":
            return cast(MusicSection, plex_object)
        section_id = getattr(plex_object, "librarySectionID", None) if plex_object else None
        section_uuid = getattr(plex_object, "librarySectionUUID", None) if plex_object else None
        try:
            sections = list(server.library.sections())
        except Exception:
            return None
        if section_id is not None:
            section_id_str = str(section_id)
            for section in sections:
                if getattr(section, "type", "") != "artist":
                    continue
                if str(getattr(section, "key", "")) == section_id_str or str(getattr(section, "librarySectionID", "")) == section_id_str:
                    return cast(MusicSection, section)
        if section_uuid:
            section_uuid_str = str(section_uuid)
            for section in sections:
                if getattr(section, "type", "") != "artist":
                    continue
                if str(getattr(section, "uuid", "")) == section_uuid_str:
                    return cast(MusicSection, section)
        for section in sections:
            if getattr(section, "type", "") == "artist":
                return cast(MusicSection, section)
        return None

    @staticmethod
    def _radio_cache_key(section: MusicSection) -> str:
        for attr in ("uuid", "key", "librarySectionID", "title"):
            value = getattr(section, attr, None)
            if value:
                return str(value)
        return f"music-section-{id(section)}"

    def _music_category_cache_key(self, section: MusicSection) -> str:
        return self._radio_cache_key(section)

    def _music_categories_for_section(self, section: MusicSection) -> List[MusicCategory]:
        cache_key = self._music_category_cache_key(section)
        cached = self._music_category_cache.get(cache_key)
        if cached is not None:
            return cached
        categories: List[MusicCategory] = []
        section_id = self._normalize_section_id(getattr(section, "librarySectionID", None) or getattr(section, "key", None))
        for ident, title, summary in _MUSIC_CATEGORY_DEFINITIONS:
            category_id = f"{cache_key}:{ident}"
            categories.append(
                MusicCategory(
                    identifier=category_id,
                    title=title,
                    summary=summary,
                    category=ident,
                    section=section,
                    key=category_id,
                )
            )
        self._music_category_cache[cache_key] = categories
        return categories

    def _music_category_items(self, category: MusicCategory) -> List[object]:
        section = category.section
        cat = category.category
        try:
            if cat == "recently_added":
                return self._music_recently_added(section)
            if cat == "radios":
                station_items: List[object] = []
                stations = self._radio_stations_for_section(section)
                station_ids = {st.identifier for st in stations}
                station_ids.update({f"station:{st.identifier}" for st in stations})
                station_items.extend(stations)
                try:
                    options = self.radio_options_for(section)
                except Exception as exc:  # noqa: BLE001
                    print(f"[MusicCategory] Unable to load radio options: {exc}")
                    options = []
                for option in options:
                    if option.id in station_ids:
                        continue
                    station_items.append(
                        MusicRadioOption(
                            identifier=option.id,
                            label=option.label or option.category or option.id,
                            description=option.description or option.category or option.label or option.id,
                            option=option,
                        )
                    )
                station_items.sort(key=lambda obj: (getattr(obj, "title", getattr(obj, "label", str(obj))) or "").lower())
                return station_items
            if cat in {"artists", "albums", "tracks"}:
                return self._music_alpha_buckets(section, cat)
            if cat == "playlists":
                return self._music_audio_playlists(section)
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Unable to load '{cat}' items: {exc}")
        return self._music_category_direct_items(section, cat)
    def _music_alpha_buckets(self, section: MusicSection, category: str) -> List[MusicAlphaBucket]:
        cache_key = f"{self._music_category_cache_key(section)}:{category}"
        cached = self._music_alpha_cache.get(cache_key)
        if cached is not None:
            return cached
        characters = self._fetch_first_character_entries(section, category)
        buckets: List[MusicAlphaBucket] = []
        if characters:
            libtype_map = {"artists": "artist", "albums": "album", "tracks": "track"}
            libtype = libtype_map.get(category, category.rstrip("s"))
            for character in characters:
                key = getattr(character, "key", None)
                if not key:
                    continue
                raw_title = str(getattr(character, "title", "")) or "#"
                count = int(getattr(character, "size", 0) or 0)
                bucket_id = f"{cache_key}:{raw_title}"
                summary = f"{count} item{'s' if count != 1 else ''} starting with '{raw_title}'"
                display_title = f"{raw_title} ({count})" if count else raw_title
                buckets.append(
                    MusicAlphaBucket(
                        identifier=bucket_id,
                        title=display_title,
                        key=key,
                        category=category,
                        libtype=libtype,
                        section=section,
                        count=count,
                        summary=summary,
                        character=raw_title,
                    )
                )
        if not buckets:
            return self._music_category_direct_items(section, category)
        self._music_alpha_cache[cache_key] = buckets
        return buckets

    def _music_alpha_bucket_items(self, bucket: MusicAlphaBucket) -> List[PlexObject]:
        cached = self._music_alpha_items_cache.get(bucket.identifier)
        if cached is not None:
            return cached
        try:
            items = list(bucket.section.fetchItems(bucket.key))
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Unable to load items for bucket '{bucket.title}': {exc}")
            items = []
        hydrated = [self._ensure_item_loaded(item) for item in items]
        if not hydrated:
            fallback_items = self._music_alpha_bucket_search(bucket)
            if fallback_items:
                print(f"[MusicCategory] Falling back to search for bucket '{bucket.title}'.")
            hydrated = fallback_items
        self._music_alpha_items_cache[bucket.identifier] = hydrated
        return hydrated

    def _playlist_items(self, playlist: PlexObject) -> List[PlexObject]:
        if playlist is None:
            return []
        cache_key = f"playlist:{getattr(playlist, 'ratingKey', '')}"
        cached = self._playlist_items_cache.get(cache_key)
        if cached is not None:
            return cached
        items: List[PlexObject] = []
        items_attr = getattr(playlist, "items", None)
        try:
            items = list(items_attr()) if callable(items_attr) else list(items_attr or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[Playlist] Unable to enumerate playlist items via items(): {exc}")
            items = []
        if not items:
            key = getattr(playlist, "key", None)
            if key:
                try:
                    items = list(self.ensure_server().fetchItems(key))
                except Exception as exc:  # noqa: BLE001
                    print(f"[Playlist] Unable to load playlist items via fetchItems: {exc}")
                    items = []
        hydrated = [self._ensure_item_loaded(item) for item in items]
        self._playlist_items_cache[cache_key] = hydrated
        return hydrated

    def _music_alpha_bucket_search(self, bucket: MusicAlphaBucket) -> List[PlexObject]:
        section = bucket.section
        libtype = bucket.libtype
        if not libtype:
            return []
        letter = (bucket.character or "").strip()
        normalized_letter = letter.upper()
        search_kwargs: Dict[str, Any] = {
            "libtype": libtype,
            "sort": "titleSort:asc",
            "maxresults": 200,
        }
        filters: Dict[str, Any] = {}
        if letter:
            target = "0-9" if normalized_letter == "#" else normalized_letter
            filters["titleStartsWith"] = target
            search_kwargs["filters"] = filters
        try:
            results = list(section.search(**search_kwargs))
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Filtered search failed for bucket '{bucket.title}': {exc}")
            results = []
            if filters:
                search_kwargs.pop("filters", None)
                try:
                    if normalized_letter and normalized_letter != "#":
                        results = list(section.search(**{**search_kwargs, "title__istartswith": normalized_letter}))
                    elif normalized_letter == "#":
                        results = list(section.search(**{**search_kwargs, "title__iregex": r"^[0-9]"}))
                except Exception as fallback_exc:  # noqa: BLE001
                    print(f"[MusicCategory] Secondary search failed for bucket '{bucket.title}': {fallback_exc}")
                    results = []
        hydrated = [self._ensure_item_loaded(item) for item in results]
        return hydrated

    def _fetch_first_character_entries(self, section: MusicSection, category: str) -> List[PlexObject]:
        if category == "artists":
            try:
                return list(section.firstCharacter() or [])
            except Exception as exc:  # noqa: BLE001
                print(f"[MusicCategory] Unable to load artist characters: {exc}")
                return []
        raw_key = getattr(section, "key", None)
        key = str(raw_key or "").strip()
        if not key:
            return []
        libtype_map = {"albums": "album", "tracks": "track"}
        libtype = libtype_map.get(category)
        if not libtype:
            return []
        try:
            server = self.ensure_server()
        except Exception:
            return []
        path = f"/library/sections/{key}/firstCharacter?libtype={libtype}"
        try:
            data = server.query(path)
            return list(section.findItems(data) or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Unable to load {category} character buckets: {exc}")
            return []

    def _fetch_section_station_directory(self, section: MusicSection) -> List[PlexObject]:
        raw_key = getattr(section, "key", None)
        key = str(raw_key or "").strip()
        if not key:
            return []
        try:
            server = self.ensure_server()
        except Exception:
            return []
        path = f"/library/sections/{key}/stations"
        try:
            data = server.query(path)
            items = section.findItems(data)
            return list(items or [])
        except Exception as exc:  # noqa: BLE001
            if '404' not in str(exc):
                print(f"[Radio] Unable to load station directory for section {getattr(section, 'title', 'Music')}: {exc}")
            return []

    def _fetch_radio_hub_pairs(self, section: MusicSection) -> List[Tuple[Optional[PlexObject], PlexObject]]:
        raw_key = getattr(section, "key", None)
        key = str(raw_key or "").strip()
        if not key:
            return []
        try:
            server = self.ensure_server()
        except Exception:
            return []
        query_suffixes = [
            "",
            "&context=hub.music.stations",
            "&context=hub.music.radio",
            "&type=station",
            "&type=15",
        ]
        pairs: List[Tuple[Optional[PlexObject], PlexObject]] = []
        seen = set()
        for suffix in query_suffixes:
            path = f"/hubs/sections/{key}?includeStations=1&count=100{suffix}"
            try:
                data = server.query(path)
            except Exception as exc:  # noqa: BLE001
                if '404' not in str(exc):
                    print(f"[Radio] Unable to load station hubs ({suffix}) for section {getattr(section, 'title', 'Music')}: {exc}")
                continue
            hubs = section.findItems(data, cls=Hub) or []
            for hub in hubs:
                try:
                    hub_items = list(hub.items())
                except Exception as exc:  # noqa: BLE001
                    print(f"[Radio] Unable to load hub items for {getattr(hub, 'title', 'Hub')}: {exc}")
                    continue
                for item in hub_items:
                    identifier = (getattr(hub, 'hubIdentifier', None), getattr(item, 'ratingKey', None) or getattr(item, 'key', None))
                    if identifier in seen:
                        continue
                    seen.add(identifier)
                    pairs.append((hub, item))
        return pairs

    def _music_category_direct_items(self, section: MusicSection, category: str) -> List[object]:
        try:
            if category == "artists":
                return list(section.searchArtists(sort="titleSort:asc", maxresults=200))
            if category == "albums":
                return list(section.searchAlbums(sort="titleSort:asc", maxresults=200))
            if category == "tracks":
                return list(section.searchTracks(sort="titleSort:asc", maxresults=200))
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Direct lookup failed for '{category}': {exc}")
        return []

    def _music_recently_added(self, section: MusicSection) -> List[PlexObject]:
        items: List[PlexObject] = []
        try:
            items.extend(section.recentlyAddedAlbums(maxresults=60))
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Unable to load recently added albums: {exc}")
        try:
            items.extend(section.recentlyAddedTracks(maxresults=120))
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Unable to load recently added tracks: {exc}")
        return self._dedupe_media_items(items)

    def _music_audio_playlists(self, section: MusicSection) -> List[PlexObject]:
        try:
            server = self.ensure_server()
        except Exception:
            return []
        try:
            playlists = list(server.playlists(playlistType="audio"))
        except Exception as exc:  # noqa: BLE001
            print(f"[MusicCategory] Unable to load audio playlists: {exc}")
            return []
        target_id = self._normalize_section_id(
            getattr(section, "librarySectionID", None) or getattr(section, "key", None)
        )
        filtered: List[PlexObject] = []
        for playlist in playlists:
            playlist_section_id = self._normalize_section_id(getattr(playlist, "librarySectionID", None))
            if playlist_section_id and target_id and playlist_section_id != target_id:
                continue
            if getattr(playlist, "playlistType", None) not in {None, "audio"}:
                continue
            filtered.append(playlist)
        return filtered or playlists

    @staticmethod
    def _dedupe_media_items(items: Iterable[PlexObject]) -> List[PlexObject]:
        seen: Set[str] = set()
        result: List[PlexObject] = []
        for item in items:
            rating_key = getattr(item, "ratingKey", None)
            fallback_key = getattr(item, "key", None)
            identifier = str(rating_key or fallback_key or id(item))
            if identifier in seen:
                continue
            seen.add(identifier)
            result.append(item)
        return result

    def _classify_radio_station(self, hub: Optional[PlexObject], item: PlexObject) -> tuple[str, str]:
        texts: List[str] = []
        if hub is not None:
            for attr in ("title", "hubIdentifier", "context"):
                value = getattr(hub, attr, None)
                if value:
                    texts.append(str(value))
        for attr in ("title", "summary", "subtype", "hubIdentifier", "key", "playlistType"):
            value = getattr(item, attr, None)
            if value:
                texts.append(str(value))
        combined = " ".join(texts).lower()
        for key, keywords in _RADIO_KEYWORDS.items():
            if any(fragment in combined for fragment in keywords):
                display = _RADIO_DISPLAY_NAMES.get(key, key.replace("_", " ").title())
                return display, key
        fallback_candidates = [
            getattr(hub, "title", None) if hub is not None else None,
            getattr(item, "librarySectionTitle", None),
            getattr(item, "playlistType", None),
        ]
        fallback = next((candidate for candidate in fallback_candidates if candidate), "Stations")
        normalized = fallback.lower().replace(" ", "_")
        if not normalized:
            normalized = "station"
        return fallback, normalized

    def _radio_stations_for_section(self, section: MusicSection) -> List[MusicRadioStation]:
        cache_key = self._radio_cache_key(section)
        cached = self._radio_station_cache.get(cache_key)
        if cached is not None:
            return cached
        stations: List[MusicRadioStation] = []
        try:
            hubs = list(section.hubs() or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to load hubs for section {getattr(section, 'title', 'Music')}: {exc}")
            hubs = []
        station_candidates: List[Tuple[Optional[PlexObject], PlexObject]] = []
        for hub in hubs:
            try:
                hub_items = list(hub.items())
            except Exception as exc:  # noqa: BLE001
                print(f"[Radio] Unable to load hub items for {getattr(hub, 'title', 'Hub')}: {exc}")
                continue
            if not hub_items:
                continue
            for item in hub_items:
                item = self._ensure_item_loaded(item)
                key = getattr(item, "key", None) or getattr(item, "stationKey", None)
                if not key:
                    continue
                station_candidates.append((hub, item))
        try:
            fallback_playlists = list(section.stations() or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to load station listings for {getattr(section, 'title', 'Music')}: {exc}")
            fallback_playlists = []
        for playlist in fallback_playlists:
            playlist = self._ensure_item_loaded(playlist)
            key = getattr(playlist, "key", None)
            if not key:
                continue
            station_candidates.append((None, playlist))
        for item in self._fetch_section_station_directory(section):
            item = self._ensure_item_loaded(item)
            key = getattr(item, "key", None)
            if not key:
                continue
            station_candidates.append((None, item))

        if not station_candidates:
            for hub_ref, item in self._fetch_radio_hub_pairs(section):
                item = self._ensure_item_loaded(item)
                key = getattr(item, "key", None) or getattr(item, "stationKey", None)
                if not key:
                    continue
                station_candidates.append((hub_ref, item))

        if not station_candidates:
            station_candidates.extend(self._station_playlists_fallback(section))

        seen_keys: Set[str] = set()
        for hub_ref, item in station_candidates:
            key = getattr(item, "key", None)
            rating_key = getattr(item, "ratingKey", None)
            dedupe_key = str(rating_key or key or "")
            if not dedupe_key or dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            category, station_type = self._classify_radio_station(hub_ref, item)
            identifier_parts = [
                cache_key,
                dedupe_key,
                station_type,
            ]
            identifier = "::".join(part for part in identifier_parts if part)
            summary = getattr(item, "summary", "") or _RADIO_DISPLAY_NAMES.get(station_type, "")
            section_id = self._normalize_section_id(
                getattr(item, "librarySectionID", None)
                or getattr(section, "librarySectionID", None)
                or getattr(section, "key", None)
            )
            station = MusicRadioStation(
                identifier=identifier,
                title=getattr(item, "title", None) or category,
                summary=summary,
                key=key,
                station_type=station_type,
                category=category or "Stations",
                library_section_id=section_id,
                hub_title=getattr(hub_ref, "title", "") or category,
                hub_context=getattr(hub_ref, "context", "") or station_type,
                item=item,
            )
            stations.append(station)
        stations.sort(key=lambda s: (s.category.lower(), s.title.lower()))
        if stations:
            self._radio_station_cache[cache_key] = stations
        return stations

    def _station_playlists_fallback(self, section: MusicSection) -> List[Tuple[Optional[PlexObject], PlexObject]]:
        try:
            server = self.ensure_server()
        except Exception:
            return []
        try:
            playlists = list(server.playlists(playlistType="audio"))
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to enumerate playlists for fallback: {exc}")
            return []
        target_id = self._normalize_section_id(
            getattr(section, "librarySectionID", None) or getattr(section, "key", None)
        )
        results: List[Tuple[Optional[PlexObject], PlexObject]] = []
        for playlist in playlists:
            if not getattr(playlist, "radio", False):
                continue
            playlist_section_id = self._normalize_section_id(getattr(playlist, "librarySectionID", None))
            if playlist_section_id and target_id and playlist_section_id != target_id:
                continue
            results.append((None, self._ensure_item_loaded(playlist)))
        return results

    def _synthetic_radio_options(self, section: MusicSection) -> List[RadioOption]:
        options: List[RadioOption] = []
        section_id = self._normalize_section_id(
            getattr(section, "librarySectionID", None) or getattr(section, "key", None)
        ) or "music"
        descriptors = [
            ("library_radio", "Library Radio", "Shuffle your entire library with endless related tracks."),
            ("recent_radio", "Recently Added Radio", "Focus on the newest music while mixing in related songs."),
            ("shuffle_radio", "Deep Shuffle Radio", "Go deep into the catalogue with an always-changing mix."),
        ]
        for mode, label, description in descriptors:
            seed = self._pick_synthetic_seed_track(section, mode, sample_only=True)
            if seed is None:
                continue
            rating_key = getattr(seed, "ratingKey", None)
            options.append(
                RadioOption(
                    id=f"synthetic:{mode}:{section_id}",
                    label=label,
                    description=description,
                    category="Stations",
                    action=f"{mode}",
                    data={"section": section, "mode": mode, "seed_rating_key": rating_key},
                )
            )
        return options

    def _start_synthetic_radio(
        self,
        section: Optional[MusicSection],
        mode: str,
        description: str,
    ) -> tuple[PlayableMedia, RadioSession]:
        if section is None:
            raise RuntimeError("Music section is unavailable for radio playback.")
        seed: Optional[PlexObject] = None
        rating_key = option.data.get("seed_rating_key")
        if rating_key:
            try:
                seed = self.fetch_item(str(rating_key))
            except Exception:
                seed = None
        if seed is None:
            seed = self._pick_synthetic_seed_track(section, mode)
        if not seed:
            raise RuntimeError("Unable to find music to start this radio.")
        seed = self._ensure_item_loaded(seed)
        server = self.ensure_server()
        queue = PlayQueue.create(
            server,
            [seed],
            shuffle=1,
            includeRelated=1,
            continuous=1,
        )
        section_id = self._normalize_section_id(
            getattr(section, "librarySectionID", None) or getattr(section, "key", None)
        )
        friendly = description or mode.replace("_", " ").title()
        return self._initialize_radio_session(
            queue,
            kind=mode,
            description=friendly,
            station=None,
            library_section_id=section_id,
        )

    def _pick_synthetic_seed_track(
        self,
        section: MusicSection,
        mode: str,
        *,
        sample_only: bool = False,
    ) -> Optional[PlexObject]:
        candidates: List[PlexObject] = []
        try:
            if mode == "recent_radio":
                candidates.extend(section.recentlyAddedTracks(maxresults=200) or [])
            else:
                candidates.extend(section.searchTracks(sort="titleSort:asc", maxresults=200) or [])
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to gather seed tracks for {mode}: {exc}")
        if not candidates and mode != "recent_radio":
            try:
                candidates.extend(section.recentlyAddedTracks(maxresults=100) or [])
            except Exception:
                pass
        if sample_only:
            hydrated = []
            for track in candidates:
                if track is None:
                    continue
                hydrated.append(track)
                if len(hydrated) >= 50:
                    break
        else:
            hydrated = [self._ensure_item_loaded(track) for track in candidates if track is not None]
        playable_tracks = [track for track in hydrated if self.is_playable(track)]
        if not playable_tracks:
            return None
        return random.choice(playable_tracks)

    def _ensure_item_loaded(self, item: PlexObject) -> PlexObject:
        obj = item
        try:
            partial_flag = getattr(obj, "isPartialObject", None)
            if callable(partial_flag) and partial_flag():
                obj = obj.reload()
        except Exception:
            pass
        try:
            full_flag = getattr(obj, "isFullObject", None)
            if callable(full_flag) and full_flag():
                return obj
        except Exception:
            pass
        rating_key = getattr(obj, "ratingKey", None)
        if rating_key not in (None, ""):
            try:
                return self.fetch_item(str(rating_key))
            except Exception:
                pass
        key = getattr(obj, "key", None)
        if key:
            try:
                server = self.ensure_server()
                return server.fetchItem(key)
            except Exception:
                pass
        return obj

    def _ensure_queue_item_loaded(self, item: PlexObject) -> PlexObject:
        return self._ensure_item_loaded(item)

    def _initialize_radio_session(
        self,
        queue: PlayQueue,
        *,
        kind: str,
        description: str,
        station: Optional[MusicRadioStation] = None,
        library_section_id: Optional[str] = None,
    ) -> tuple[PlayableMedia, RadioSession]:
        items = list(queue.items)
        if not items:
            raise RuntimeError("The radio queue returned no playable items.")
        index = int(getattr(queue, "playQueueSelectedItemOffset", 0) or 0)
        if index >= len(items):
            index = 0
        first_item = self._ensure_queue_item_loaded(items[index])
        media = self.to_playable(first_item)
        if not media:
            raise RuntimeError("Unable to resolve the first radio track.")
        session = RadioSession(
            kind=kind,
            description=description,
            queue=queue,
            current_index=index,
            play_queue_id=int(getattr(queue, "playQueueID", 0) or 0),
            library_section_id=library_section_id,
            station=station,
            metadata={
                "source_uri": getattr(queue, "playQueueSourceURI", ""),
                "station_type": getattr(station, "station_type", kind) if station else kind,
            },
        )
        return media, session

    def _start_station_radio(self, station: MusicRadioStation) -> tuple[PlayableMedia, RadioSession]:
        server = self.ensure_server()
        queue = PlayQueue.fromStationKey(server, station.key)
        section_id = station.library_section_id or self._normalize_section_id(
            getattr(station.item, "librarySectionID", None)
        )
        return self._initialize_radio_session(
            queue,
            kind=station.station_type or "station",
            description=station.title,
            station=station,
            library_section_id=section_id,
        )

    def _start_continuous_radio(
        self,
        seed: PlexObject,
        *,
        kind: str,
        description: str,
        library_section_id: Optional[str] = None,
    ) -> tuple[PlayableMedia, RadioSession]:
        server = self.ensure_server()
        queue = PlayQueue.create(
            server,
            seed,
            shuffle=1,
            includeRelated=1,
            continuous=1,
        )
        section_id = library_section_id or self._normalize_section_id(getattr(seed, "librarySectionID", None))
        return self._initialize_radio_session(
            queue,
            kind=kind,
            description=description,
            station=None,
            library_section_id=section_id,
        )

    def _start_artist_radio(self, artist: PlexObject) -> tuple[PlayableMedia, RadioSession]:
        get_station = getattr(artist, "station", None)
        library_section_id = self._normalize_section_id(getattr(artist, "librarySectionID", None))
        if callable(get_station):
            try:
                playlist = get_station()
            except Exception as exc:  # noqa: BLE001
                print(f"[Radio] Artist station lookup failed: {exc}")
                playlist = None
            if playlist and getattr(playlist, "key", None):
                identifier = "::".join(
                    part
                    for part in (
                        "artist",
                        str(getattr(artist, "ratingKey", "")),
                        str(getattr(playlist, "ratingKey", "") or getattr(playlist, "key", "")),
                    )
                    if part
                )
                station = MusicRadioStation(
                    identifier=identifier,
                    title=getattr(playlist, "title", None) or f"{getattr(artist, 'title', 'Artist')} Radio",
                    summary=getattr(playlist, "summary", "") or _RADIO_DISPLAY_NAMES.get("artist_radio", ""),
                    key=getattr(playlist, "key", ""),
                    station_type="artist_radio",
                    category=_RADIO_DISPLAY_NAMES.get("artist_radio", "Artist Radio"),
                    library_section_id=library_section_id,
                    hub_title=_RADIO_DISPLAY_NAMES.get("artist_radio", "Artist Radio"),
                    hub_context="artist",
                    item=playlist,
                )
                return self._start_station_radio(station)
        description = _RADIO_DISPLAY_NAMES.get("artist_radio", "Artist Radio")
        title = getattr(artist, "title", None)
        if title:
            description = f"{title} Radio"
        return self._start_continuous_radio(
            artist,
            kind="artist_radio",
            description=description,
            library_section_id=library_section_id,
        )

    def _start_album_radio(self, album: PlexObject) -> tuple[PlayableMedia, RadioSession]:
        library_section_id = self._normalize_section_id(getattr(album, "librarySectionID", None))
        description = _RADIO_DISPLAY_NAMES.get("album_radio", "Album Radio")
        album_title = getattr(album, "title", None)
        if album_title:
            description = f"{album_title} Mix"
        return self._start_continuous_radio(
            album,
            kind="album_radio",
            description=description,
            library_section_id=library_section_id,
        )

    def _start_track_radio(self, track: PlexObject) -> tuple[PlayableMedia, RadioSession]:
        library_section_id = self._normalize_section_id(getattr(track, "librarySectionID", None))
        description = _RADIO_DISPLAY_NAMES.get("track_radio", "Track Radio")
        track_title = getattr(track, "title", None)
        if track_title:
            description = f"{track_title} Radio"
        return self._start_continuous_radio(
            track,
            kind="track_radio",
            description=description,
            library_section_id=library_section_id,
        )

    def radio_options_for(self, plex_object: Optional[PlexObject]) -> List[RadioOption]:
        section = self._music_section_for(plex_object)
        if not section:
            return []
        stations = self._radio_stations_for_section(section)
        seen_ids: Set[str] = set()
        station_options: List[RadioOption] = []
        for station in stations:
            if station.identifier in seen_ids:
                continue
            seen_ids.add(station.identifier)
            description = station.summary or _RADIO_DISPLAY_NAMES.get(station.station_type, station.category)
            station_options.append(
                RadioOption(
                    id=f"station:{station.identifier}",
                    label=station.title,
                    description=description,
                    category=station.category or "Stations",
                    action="station",
                    data={"station": station},
                )
            )
        station_options.sort(key=lambda opt: (opt.category.lower(), opt.label.lower()))

        synthetic = self._synthetic_radio_options(section)

        special_options: List[RadioOption] = []
        if plex_object and not isinstance(plex_object, LibrarySection):
            obj_type = getattr(plex_object, "type", "") or ""
            title = getattr(plex_object, "title", None)
            if obj_type == "artist":
                label = f"Artist Radio{f' - {title}' if title else ''}"
                description = "Start a station based on this artist."
                special_options.append(
                    RadioOption(
                        id=f"artist-radio:{getattr(plex_object, 'ratingKey', '')}",
                        label=label,
                        description=description,
                        category="Selection",
                        action="artist_radio",
                        data={"artist": plex_object},
                    )
                )
            elif obj_type == "album":
                label = f"Album Radio{f' - {title}' if title else ''}"
                description = "Play a mix inspired by this album."
                special_options.append(
                    RadioOption(
                        id=f"album-radio:{getattr(plex_object, 'ratingKey', '')}",
                        label=label,
                        description=description,
                        category="Selection",
                        action="album_radio",
                        data={"album": plex_object},
                    )
                )
            elif obj_type == "track":
                label = f"Track Radio{f' - {title}' if title else ''}"
                description = "Create a station seeded by this track."
                special_options.append(
                    RadioOption(
                        id=f"track-radio:{getattr(plex_object, 'ratingKey', '')}",
                        label=label,
                        description=description,
                        category="Selection",
                    action="track_radio",
                    data={"track": plex_object},
                )
            )
        return special_options + synthetic + station_options

    def start_radio_option(self, option: RadioOption) -> tuple[PlayableMedia, RadioSession]:
        action = option.action
        if action == "station":
            station = cast(MusicRadioStation, option.data["station"])
            return self._start_station_radio(station)
        if action == "artist_radio":
            artist = cast(PlexObject, option.data["artist"])
            return self._start_artist_radio(artist)
        if action == "album_radio":
            album = cast(PlexObject, option.data["album"])
            return self._start_album_radio(album)
        if action == "track_radio":
            track = cast(PlexObject, option.data["track"])
            return self._start_track_radio(track)
        if action in {"library_radio", "recent_radio", "shuffle_radio"}:
            section = cast(MusicSection, option.data.get("section"))
            mode = option.data.get("mode", action)
            return self._start_synthetic_radio(section, mode, option.label or option.id)
        raise RuntimeError(f"Unsupported radio option action '{action}'.")

    def start_playlist(self, playlist: PlexObject) -> tuple[PlayableMedia, RadioSession]:
        server = self.ensure_server()
        queue = PlayQueue.create(server, playlist, shuffle=0, continuous=0)
        section_id = self._normalize_section_id(getattr(playlist, "librarySectionID", None))
        description = getattr(playlist, "title", None) or "Playlist"
        return self._initialize_radio_session(
            queue,
            kind="playlist",
            description=description,
            station=None,
            library_section_id=section_id,
        )

    def next_radio_track(self, session: RadioSession) -> Optional[Tuple[PlayableMedia, int]]:
        queue = session.queue
        next_index = session.current_index + 1
        attempts = 0
        while attempts < 3:
            items = list(queue.items)
            if next_index < len(items):
                candidate = self._ensure_queue_item_loaded(items[next_index])
                media = self.to_playable(candidate)
                if media:
                    return media, next_index
                next_index += 1
                continue
            try:
                queue.refresh()
            except Exception as exc:  # noqa: BLE001
                print(f"[Radio] Unable to refresh radio queue {session.play_queue_id}: {exc}")
                return None
            attempts += 1
        return None

    def is_playable(self, node: PlexObject) -> bool:
        node_type = getattr(node, "type", "")
        if node_type in {"playlist", "radio_station"}:
            return False
        return hasattr(node, "getStreamURL") or node_type in {
            "movie",
            "episode",
            "track",
            "clip",
            "video",
            "photo",
        }

    def to_playable(self, node: PlexObject) -> Optional[PlayableMedia]:
        if not self.is_playable(node):
            return None
        candidate = node
        direct_url, fallback_url = self._derive_stream_urls(candidate)
        if not direct_url and not fallback_url:
            candidate = self._ensure_item_loaded(candidate)
            direct_url, fallback_url = self._derive_stream_urls(candidate)
            if not direct_url and not fallback_url:
                return None
        title = getattr(candidate, "title", str(candidate))
        media_type = getattr(candidate, "type", "unknown")
        stream_url = direct_url or fallback_url
        browser_url = fallback_url or direct_url
        if not stream_url:
            return None
        resume_offset = int(getattr(candidate, "viewOffset", 0) or 0)
        return PlayableMedia(
            title=title,
            media_type=media_type,
            key=candidate.key,
            stream_url=stream_url,
            browser_url=browser_url,
            resume_offset=resume_offset,
            item=candidate,
        )

    def resolve_playable(self, node: Optional[PlexObject]) -> Optional[PlayableMedia]:
        if node is None:
            return None
        playable = self.to_playable(node)
        if playable:
            return playable
        media_type = getattr(node, "type", "") or ""
        if media_type == "album":
            track = self._first_track_in_album(node)
            if track:
                return self.to_playable(track)
        if media_type == "artist":
            track = self._first_track_from_artist(node)
            if track:
                return self.to_playable(track)
        if media_type == "playlist":
            track = self._first_track_in_playlist(node)
            if track:
                return self.to_playable(track)
        if media_type == "season":
            episode = self._first_episode_in_season(node)
            if episode:
                playable = self.to_playable(episode)
                if playable:
                    playable.resume_offset = int(getattr(episode, "viewOffset", 0) or 0)
                    return playable
        return None

    def _derive_stream_urls(self, node: PlexObject) -> tuple[Optional[str], Optional[str]]:
        server = self.ensure_server()
        direct_url: Optional[str] = None
        fallback_url: Optional[str] = None
        resume_offset = int(getattr(node, "viewOffset", 0) or 0)

        media = getattr(node, "media", None)
        if media:
            first_media = media[0]
            parts = getattr(first_media, "parts", None)
            if parts:
                part: MediaPart = parts[0]
                direct_candidate = server.url(part.key)
                direct_url = self._ensure_plex_params(
                    direct_candidate,
                    token=server._token,  # noqa: SLF001
                    ensure_download=True,
                )

        if hasattr(node, "getStreamURL"):
            try:
                fallback_url = node.getStreamURL(offset=resume_offset)
            except Exception:  # noqa: BLE001 - best effort, continue to other fallbacks
                fallback_url = None

        if not fallback_url and getattr(node, "key", None):
            fallback_candidate = server.url(node.key)
            fallback_url = self._ensure_plex_params(
                fallback_candidate,
                token=server._token,  # noqa: SLF001
            )
        elif fallback_url:
            fallback_url = self._ensure_plex_params(
                fallback_url,
                token=server._token,  # noqa: SLF001
            )

        return direct_url, fallback_url

    @staticmethod
    def _ensure_plex_params(url: str, *, token: str, ensure_download: bool = False) -> str:
        parts = urlsplit(url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        if ensure_download and "download" not in query:
            query["download"] = "1"
        query["X-Plex-Token"] = token
        new_query = urlencode(query)
        return urlunsplit(parts._replace(query=new_query))

    def describe(self, node: PlexObject) -> str:
        parts = [getattr(node, "title", "")]
        media_type = getattr(node, "type", "")
        if media_type:
            parts.append(f"Type: {media_type}")
        summary = getattr(node, "summary", "")
        if summary:
            parts.append("")
            parts.append(summary)
        return "\n".join(part for part in parts if part)

    def search(self, query: str, limit: int = 50) -> List[PlexObject]:
        query = query.strip()
        if not query:
            return []
        server = self.ensure_server()
        return server.search(query, limit=limit)

    def fetch_item(self, rating_key: str) -> PlexObject:
        server = self.ensure_server()
        return server.fetchItem(f"/library/metadata/{rating_key}")

    def update_progress_by_key(self, rating_key: str, position: int, duration: int, state: str = "stopped") -> tuple[str, int]:
        item = self.fetch_item(rating_key)
        media = PlayableMedia(
            title=getattr(item, "title", str(item)),
            media_type=getattr(item, "type", "unknown"),
            key=item.key,
            stream_url="",
            browser_url=None,
            resume_offset=int(getattr(item, "viewOffset", 0) or 0),
            item=item,
        )
        return self.update_timeline(media, state, position, duration)

    @staticmethod
    def _resolve_related(item: PlexObject, attr_name: str) -> Optional[PlexObject]:
        """Safely resolve related Plex objects that may be attributes or callables."""
        related = getattr(item, attr_name, None)
        if callable(related):
            try:
                return related()
            except Exception:
                return None
        return related

    def _first_episode_in_season(self, season: Optional[PlexObject]) -> Optional[PlexObject]:
        if season is None:
            return None
        try:
            episodes = list(season.episodes())
        except Exception:
            return None
        if not episodes:
            return None
        try:
            episodes.sort(key=lambda ep: (getattr(ep, "index", 0) or 0, getattr(ep, "ratingKey", "")))
        except Exception:
            pass
        for episode in episodes:
            if getattr(episode, "ratingKey", None):
                return episode
        return None

    def _next_episode_in_season(self, episode: PlexObject, season: Optional[PlexObject]) -> Optional[PlexObject]:
        if season is None:
            return None
        current_key = getattr(episode, "ratingKey", None)
        current_index = getattr(episode, "index", None)
        try:
            episodes = list(season.episodes())
        except Exception:
            return None
        if not episodes:
            return None
        try:
            episodes.sort(key=lambda ep: (getattr(ep, "index", 0) or 0, getattr(ep, "ratingKey", "")))
        except Exception:
            pass
        seen_current = False
        for candidate in episodes:
            key = getattr(candidate, "ratingKey", None)
            if key == current_key:
                seen_current = True
                continue
            if not seen_current and current_index is not None:
                try:
                    candidate_index = getattr(candidate, "index", None)
                except Exception:
                    candidate_index = None
                if candidate_index is not None and current_index is not None and candidate_index > current_index:
                    seen_current = True
                else:
                    continue
            if seen_current and key and key != current_key:
                return candidate
        return None

    def _next_episode_after_season(self, season: Optional[PlexObject], show: Optional[PlexObject]) -> Optional[PlexObject]:
        if show is None:
            return None
        current_season_key = getattr(season, "ratingKey", None) if season else None
        current_index = getattr(season, "index", None) if season else None
        try:
            seasons = list(show.seasons())
        except Exception:
            return None
        if not seasons:
            return None
        try:
            seasons.sort(key=lambda s: (getattr(s, "index", 0) or 0, getattr(s, "ratingKey", "")))
        except Exception:
            pass
        seen_current = current_season_key is None
        for candidate in seasons:
            key = getattr(candidate, "ratingKey", None)
            index = getattr(candidate, "index", None)
            if current_season_key and key == current_season_key:
                seen_current = True
                continue
            if not seen_current and current_index is not None and index is not None and index > current_index:
                seen_current = True
            if not seen_current:
                continue
            next_episode = self._first_episode_in_season(candidate)
            if next_episode:
                return next_episode
        return None

    def _first_track_in_album(self, album: Optional[PlexObject]) -> Optional[PlexObject]:
        if album is None:
            return None
        try:
            tracks = list(album.tracks())
        except Exception:
            return None
        if not tracks:
            return None
        try:
            tracks.sort(
                key=lambda track: (
                    getattr(track, "parentIndex", 0) or 0,
                    getattr(track, "index", 0) or 0,
                    getattr(track, "ratingKey", ""),
                )
            )
        except Exception:
            pass
        for track in tracks:
            if getattr(track, "ratingKey", None):
                return track
        return None

    def _first_track_from_artist(self, artist: Optional[PlexObject]) -> Optional[PlexObject]:
        if artist is None:
            return None
        try:
            albums = list(artist.albums())
        except Exception:
            albums = []
        if albums:
            try:
                albums.sort(
                    key=lambda alb: (
                        getattr(alb, "year", 0) or 0,
                        str(getattr(alb, "titleSort", getattr(alb, "title", "") or "")).lower(),
                        getattr(alb, "ratingKey", ""),
                    )
                )
            except Exception:
                pass
            for album in albums:
                track = self._first_track_in_album(album)
                if track:
                    return track
        tracks_attr = getattr(artist, "tracks", None)
        if callable(tracks_attr):
            try:
                tracks = list(tracks_attr())
            except Exception:
                tracks = []
            if tracks:
                try:
                    tracks.sort(
                        key=lambda track: (
                            getattr(track, "parentIndex", 0) or 0,
                            getattr(track, "index", 0) or 0,
                            getattr(track, "ratingKey", ""),
                        )
                    )
                except Exception:
                    pass
                for track in tracks:
                    if getattr(track, "ratingKey", None):
                        return track
        return None

    def _first_track_in_playlist(self, playlist: Optional[PlexObject]) -> Optional[PlexObject]:
        if playlist is None:
            return None
        items_attr = getattr(playlist, "items", None)
        try:
            items = list(items_attr()) if callable(items_attr) else list(items_attr or [])
        except Exception:
            items = []
        if not items:
            key = getattr(playlist, "key", None)
            if key:
                try:
                    items = list(self.ensure_server().fetchItems(key))
                except Exception:
                    items = []
        for item in items:
            if getattr(item, "type", "") == "track" and getattr(item, "ratingKey", None):
                return item
        return None

    def find_next_episode(self, item: PlexObject) -> Optional[PlexObject]:
        if getattr(item, "type", "") != "episode":
            return None
        current_key = getattr(item, "ratingKey", None)
        show = self._resolve_related(item, "show")
        if show is not None:
            try:
                next_item = show.onDeck()
            except Exception:
                next_item = None
            if next_item and getattr(next_item, "ratingKey", None) not in {None, current_key}:
                return next_item
        season = self._resolve_related(item, "season")
        next_item = self._next_episode_in_season(item, season)
        if next_item:
            return next_item
        return self._next_episode_after_season(season, show)

    def next_in_series(self, item: PlexObject) -> Optional[PlayableMedia]:
        next_item = self.find_next_episode(item)
        if not next_item:
            return None
        playable = self.to_playable(next_item)
        if playable:
            playable.resume_offset = int(getattr(next_item, "viewOffset", 0) or 0)
        return playable

    def watch_queues(
        self,
        continue_limit: int = 25,
        up_next_limit: int = 25,
    ) -> Tuple[List[PlayableMedia], List[PlayableMedia]]:
        server = self.ensure_server()
        try:
            deck = list(server.library.onDeck())
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Unable to load Plex queues: {exc}") from exc
        continue_items: List[PlayableMedia] = []
        up_next_items: List[PlayableMedia] = []
        seen_continue: Set[str] = set()
        seen_upnext: Set[str] = set()
        for item in deck:
            rating_key = getattr(item, "ratingKey", None)
            if not rating_key:
                continue
            view_offset = int(getattr(item, "viewOffset", 0) or 0)
            duration = int(getattr(item, "duration", 0) or 0)
            playable = self.to_playable(item)
            if (
                view_offset > 0
                and duration > 0
                and len(continue_items) < continue_limit
                and rating_key not in seen_continue
                and playable
            ):
                continue_items.append(playable)
                seen_continue.add(rating_key)
            if view_offset > 0 and duration > 0 and len(up_next_items) < up_next_limit:
                next_item = self._determine_up_next(item)
                if next_item:
                    next_key = getattr(next_item, "ratingKey", None)
                    if (
                        next_key
                        and next_key not in seen_upnext
                    ):
                        next_playable = self.to_playable(next_item)
                        if next_playable:
                            up_next_items.append(next_playable)
                            seen_upnext.add(next_key)
                continue
            if playable and len(up_next_items) < up_next_limit and rating_key not in seen_upnext:
                up_next_items.append(playable)
                seen_upnext.add(rating_key)
            if len(continue_items) >= continue_limit and len(up_next_items) >= up_next_limit:
                break
        return continue_items, up_next_items

    def _determine_up_next(self, item: PlexObject) -> Optional[PlexObject]:
        if getattr(item, "type", "") == "episode":
            next_item = self.find_next_episode(item)
            if next_item:
                return next_item
        show = self._resolve_related(item, "show")
        if show is None:
            return None
        try:
            candidate = show.onDeck()
        except Exception:
            candidate = None
        if candidate and getattr(candidate, "ratingKey", None) not in {None, getattr(item, "ratingKey", None)}:
            return candidate
        return None

    def update_timeline(self, media: PlayableMedia, state: str, position: int, duration: int) -> tuple[str, int]:
        item = media.item
        bounded_duration = max(0, duration or int(getattr(item, "duration", 0) or 0))
        if bounded_duration == 0:
            try:
                item.reload()
                bounded_duration = max(0, int(getattr(item, "duration", 0) or 0))
            except Exception:
                bounded_duration = 0
        bounded_position = max(0, min(position, bounded_duration if bounded_duration else position))
        if bounded_duration and bounded_position > bounded_duration:
            bounded_position = bounded_duration
        if bounded_position == 0 and media.resume_offset:
            bounded_position = media.resume_offset
        near_completion = False
        send_state = state
        if state == "stopped" and bounded_duration:
            if bounded_position >= int(bounded_duration * 0.97):
                near_completion = True
            else:
                send_state = "paused"
        try:
            item.updateTimeline(bounded_position, state=send_state, duration=bounded_duration)
            if bounded_position > 0 and bounded_duration:
                progress_state = "stopped" if state == "stopped" else send_state
                try:
                    item.updateProgress(bounded_position, state=progress_state)
                except Exception as exc:
                    print(f"[Timeline] Failed to update progress: {exc}")
            media.resume_offset = bounded_position
        except Exception as exc:  # noqa: BLE001
            print(f"[Timeline] Failed to update timeline: {exc}")
        if near_completion:
            try:
                mark = getattr(item, "markWatched", None)
                if callable(mark):
                    mark()
            except Exception:
                pass
        tolerance = 1250
        confirm_deadline = time.time() + 8.0
        server_offset = 0
        while True:
            try:
                item.reload()
            except Exception:
                server_offset = int(getattr(item, "viewOffset", media.resume_offset) or media.resume_offset or 0)
                break
            server_offset = int(getattr(item, "viewOffset", media.resume_offset) or media.resume_offset or 0)
            target = max(0, bounded_position - tolerance)
            if (
                bounded_position <= 0
                or send_state == "playing"
                or server_offset >= target
                or time.time() >= confirm_deadline
            ):
                break
            remaining = max(0.0, confirm_deadline - time.time())
            wait_for = min(0.5, remaining) or 0.05
            if state == "stopped" and bounded_position > 0 and send_state != "stopped":
                try:
                    item.updateProgress(bounded_position, state="stopped")
                except Exception:
                    pass
            print(
                f"[Timeline] Awaiting server offset update: local={bounded_position} server={server_offset} "
                f"(target>={target})"
            )
            time.sleep(wait_for)
        if server_offset > 0:
            media.resume_offset = server_offset
        return send_state, server_offset

    def search_all_servers(
        self,
        query: str,
        limit_per_server: int = 50,
        on_hit: Optional[Callable[[SearchHit], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> List[SearchHit]:
        query = query.strip()
        if not query:
            return []
        hits: List[SearchHit] = []
        errors: List[str] = []
        servers = self.refresh_servers()
        if not servers:
            self._last_search_errors = ["No Plex servers are available for this account."]
            return hits
        original_server = None
        original_resource_id = self._current_resource_id
        try:
            original_server = self.ensure_server()
        except Exception as exc:
            self._last_search_errors = [f"Unable to connect to the current Plex server: {exc}"]
            return hits
        current_id = self._current_resource_id

        max_workers = min(30, len(servers))

        def search_resource(resource: MyPlexResource) -> tuple[List[SearchHit], List[str]]:
            local_hits: List[SearchHit] = []
            local_errors: List[str] = []
            name = resource.name or resource.clientIdentifier
            try:
                msg = f"Connecting to {name}..."
                print(f"[Search] {msg}")
                if on_status:
                    on_status(msg)
                server = self._connect_with_strategy(resource, reason=f"search:{name}")
            except Exception as exc:
                msg = f"{name}: connect failed ({exc})"
                print(f"[Search] {msg}")
                local_errors.append(msg)
                if on_status:
                    on_status(msg)
                return local_hits, local_errors
            try:
                results = server.search(query, limit=limit_per_server)
                msg = f"{name}: {len(results)} result(s) for '{query}'"
                print(f"[Search] {msg}")
                if on_status:
                    on_status(msg)
            except Exception as exc:
                msg = f"{name}: search failed ({exc})"
                print(f"[Search] {msg}")
                local_errors.append(msg)
                if on_status:
                    on_status(msg)
                return local_hits, local_errors
            for item in results:
                hit = SearchHit(resource=resource, server=server, item=item)
                local_hits.append(hit)
                if on_hit:
                    on_hit(hit)
            return local_hits, local_errors

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(search_resource, resource) for resource in servers]
            for future in as_completed(futures):
                local_hits, local_errors = future.result()
                hits.extend(local_hits)
                errors.extend(local_errors)

        self._server = original_server
        self._current_resource_id = original_resource_id
        self._last_search_errors = errors
        if not hits and errors:
            raise RuntimeError("; ".join(errors))
        return hits

    def last_search_errors(self) -> List[str]:
        return list(self._last_search_errors)

    def current_resource_id(self) -> Optional[str]:
        return self._current_resource_id


