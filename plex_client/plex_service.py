from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import time
from typing import Callable, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from plexapi.base import PlexObject
from plexapi.exceptions import NotFound
from plexapi.library import LibrarySection
from plexapi.media import MediaPart
from plexapi.myplex import MyPlexAccount, MyPlexResource
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


class PlexService:
    """Wraps common operations against the Plex API for the UI layer."""

    def __init__(self, account: MyPlexAccount, config: ConfigStore) -> None:
        self._account = account
        self._config = config
        self._resources: List[MyPlexResource] = []
        self._server: Optional[PlexServer] = None
        self._current_resource_id: Optional[str] = None
        self._last_search_errors: List[str] = []

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
        target = None
        if identifier:
            for resource in servers:
                if resource.clientIdentifier == identifier:
                    target = resource
                    break
        if target is None:
            if not servers:
                raise RuntimeError("No Plex servers are available for this account.")
            target = servers[0]
        return self.connect_resource(target)

    def connect_resource(self, resource: MyPlexResource) -> PlexServer:
        if resource not in self._resources:
            self._resources.append(resource)
        self._server = resource.connect(ssl=True)
        self._current_resource_id = resource.clientIdentifier
        self._config.set_selected_server(resource.clientIdentifier)
        return self._server

    def ensure_server(self) -> PlexServer:
        if self._server:
            return self._server
        stored_identifier = self._config.get_selected_server()
        return self.connect(identifier=stored_identifier)

    def libraries(self) -> Sequence[LibrarySection]:
        server = self.ensure_server()
        return server.library.sections()

    def list_children(self, node: PlexObject) -> Iterable[PlexObject]:
        if isinstance(node, LibrarySection):
            return node.all()
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
        if obj_type in {"photo", "clip"}:
            return []
        if obj_type == "photoalbum":
            return node.photos()
        if obj_type == "collection":
            return node.children()
        try:
            return node.children()
        except NotFound:
            return []

    def is_playable(self, node: PlexObject) -> bool:
        return hasattr(node, "getStreamURL") or getattr(node, "type", "") in {
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
        direct_url, fallback_url = self._derive_stream_urls(node)
        if not direct_url and not fallback_url:
            return None
        title = getattr(node, "title", str(node))
        media_type = getattr(node, "type", "unknown")
        stream_url = direct_url or fallback_url
        browser_url = fallback_url or direct_url
        if not stream_url:
            return None
        resume_offset = int(getattr(node, "viewOffset", 0) or 0)
        return PlayableMedia(
            title=title,
            media_type=media_type,
            key=node.key,
            stream_url=stream_url,
            browser_url=browser_url,
            resume_offset=resume_offset,
            item=node,
        )

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
                server = resource.connect(ssl=True)
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
