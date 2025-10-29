from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

import wx

from plexapi.base import PlexObject
from plexapi.library import LibrarySection


@dataclass
class NodePayload:
    kind: str
    plex_object: Optional[PlexObject]


TreeLoader = Callable[[PlexObject], Iterable[PlexObject]]
SelectionHandler = Callable[[Optional[PlexObject]], None]


class NavigationTree(wx.TreeCtrl):
    """Tree view that lazily expands Plex libraries and their children."""

    def __init__(
        self,
        parent: wx.Window,
        loader: TreeLoader,
        on_selection: SelectionHandler,
        *args,
        **kwargs,
    ) -> None:
        super().__init__(parent, style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT, *args, **kwargs)
        self._loader = loader
        self._on_selection = on_selection
        self._root = self.AddRoot("root")
        self._destroyed = False
        self.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._handle_expanding)
        self.Bind(wx.EVT_TREE_SEL_CHANGED, self._handle_selection)
        self.Bind(wx.EVT_WINDOW_DESTROY, self._handle_destroy)

    def populate(self, libraries: Iterable[LibrarySection]) -> None:
        if self._destroyed:
            return
        try:
            self.DeleteChildren(self._root)
        except RuntimeError:
            return
        for section in libraries:
            try:
                node = self.AppendItem(self._root, section.title, data=self._wrap("library", section))
            except RuntimeError:
                continue
            self._add_placeholder(node)

    def clear(self) -> None:
        if self._destroyed:
            return
        try:
            self.DeleteChildren(self._root)
        except RuntimeError:
            return

    def _wrap(self, kind: str, plex_object: Optional[PlexObject]) -> NodePayload:
        return NodePayload(kind=kind, plex_object=plex_object)

    def _payload(self, item: wx.TreeItemId) -> Optional[NodePayload]:
        if self._destroyed:
            return None
        try:
            data = self.GetItemData(item)
        except RuntimeError:
            return None
        return data if isinstance(data, NodePayload) else None

    def _handle_expanding(self, event: wx.TreeEvent) -> None:
        item = event.GetItem()
        if self._destroyed:
            return
        payload = self._payload(item)
        if not payload or not payload.plex_object:
            return
        if payload.kind == "placeholder":
            return
        if not self._has_placeholder(item):
            return
        self._populate_children(item, payload.plex_object)

    def _populate_children(self, item: wx.TreeItemId, plex_object: PlexObject) -> None:
        if self._destroyed:
            return
        try:
            self.DeleteChildren(item)
        except RuntimeError:
            return

        def work() -> None:
            try:
                children = list(self._loader(plex_object))
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._show_error, item, exc)
                return
            wx.CallAfter(self._apply_children, item, children)

        threading.Thread(target=work, name="PlexTreeLoader", daemon=True).start()

    def _apply_children(self, item: wx.TreeItemId, children: Iterable[PlexObject]) -> None:
        if self._destroyed or not item or not item.IsOk():
            return
        try:
            self.DeleteChildren(item)
        except RuntimeError:
            return
        for child in children:
            child_type = getattr(child, "type", "item")
            label = getattr(child, "title", str(child))
            try:
                child_item = self.AppendItem(item, label, data=self._wrap(child_type, child))
            except RuntimeError:
                continue
            if self._is_expandable(child):
                self._add_placeholder(child_item)

    def _show_error(self, item: wx.TreeItemId, exc: Exception) -> None:
        if self._destroyed or not item or not item.IsOk():
            return
        try:
            error_item = self.AppendItem(item, f"Error: {exc}", data=self._wrap("error", None))
        except RuntimeError:
            return
        self.SetItemTextColour(error_item, wx.RED)

    def _handle_selection(self, event: wx.TreeEvent) -> None:
        item = event.GetItem()
        if self._destroyed or not item or not item.IsOk():
            return
        payload = self._payload(item)
        plex_object = payload.plex_object if payload else None
        self._on_selection(plex_object)

    def _add_placeholder(self, item: wx.TreeItemId) -> None:
        if self._destroyed or not item or not item.IsOk():
            return
        try:
            placeholder = self.AppendItem(item, "Loading...", data=self._wrap("placeholder", None))
        except RuntimeError:
            return
        self.SetItemTextColour(placeholder, wx.Colour(120, 120, 120))

    def _has_placeholder(self, item: wx.TreeItemId) -> bool:
        child, cookie = self.GetFirstChild(item)
        while child and child.IsOk():
            payload = self._payload(child)
            if payload and payload.kind == "placeholder":
                return True
            child, cookie = self.GetNextChild(item, cookie)
        return False

    def _is_expandable(self, plex_object: PlexObject) -> bool:
        media_type = getattr(plex_object, "type", "")
        return media_type in {
            "show",
            "season",
            "artist",
            "album",
            "photoalbum",
            "collection",
        } or isinstance(plex_object, LibrarySection)

    def _handle_destroy(self, event: wx.WindowDestroyEvent) -> None:
        self._destroyed = True
        event.Skip()
