from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Sequence
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
        self._server = target.connect(ssl=True)
        self._current_resource_id = target.clientIdentifier
        self._config.set_selected_server(target.clientIdentifier)
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
        return PlayableMedia(
            title=title,
            media_type=media_type,
            key=node.key,
            stream_url=stream_url,
            browser_url=browser_url,
            item=node,
        )

    def _derive_stream_urls(self, node: PlexObject) -> tuple[Optional[str], Optional[str]]:
        server = self.ensure_server()
        direct_url: Optional[str] = None
        fallback_url: Optional[str] = None

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
                fallback_url = node.getStreamURL()
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
