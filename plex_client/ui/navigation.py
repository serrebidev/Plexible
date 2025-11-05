from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set

import wx

from plexapi.base import PlexObject
from plexapi.library import Folder, LibrarySection

from ..plex_service import MusicAlphaBucket, MusicCategory, MusicRadioOption


@dataclass
class NodePayload:
    kind: str
    plex_object: Optional[object]
    identifier: str
    queue_index: Optional[int] = None


TreeLoader = Callable[[object], Iterable[object]]
SelectionHandler = Callable[[Optional[object]], None]


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
        self._queue_root: Optional[wx.TreeItemId] = None
        self._queue_items: List[PlexObject] = []
        self._queue_index_map: Dict[int, wx.TreeItemId] = {}
        self._queue_selected_index: int = -1
        self._queue_saved_index: int = -1
        self._loading_nodes: Set[str] = set()
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
        self._queue_root = None
        self._queue_items.clear()
        self._queue_index_map.clear()
        self._queue_selected_index = -1
        self._queue_saved_index = -1

    def set_queue_items(self, items: Sequence[PlexObject]) -> None:
        if self._destroyed:
            return
        items = list(items)
        if not items:
            self._queue_items.clear()
            self._queue_index_map.clear()
            if self._queue_root and self._queue_root.IsOk():
                try:
                    self.Delete(self._queue_root)
                except RuntimeError:
                    pass
            self._queue_root = None
            self._queue_selected_index = -1
            self._queue_saved_index = -1
            return

        root = self._ensure_queue_root()
        if not root or not root.IsOk():
            return
        selected_item = self.GetSelection()
        selected_payload = self._payload(selected_item)
        selected_is_queue = bool(
            selected_payload and selected_payload.kind in {"queue_root", "queue_item"}
        )
        selected_index = (
            selected_payload.queue_index
            if selected_payload and selected_payload.queue_index is not None
            else self._queue_saved_index
        )

        self._queue_items = list(items)
        self._queue_index_map.clear()
        try:
            self.DeleteChildren(root)
        except RuntimeError:
            return
        for idx, plex_object in enumerate(self._queue_items):
            label = self._format_queue_label(plex_object, idx)
            identifier = f"queue-{idx}-{self._identify(plex_object)}"
            payload = NodePayload(
                kind="queue_item",
                plex_object=plex_object,
                identifier=identifier,
                queue_index=idx,
            )
            try:
                item = self.AppendItem(root, label, data=payload)
            except RuntimeError:
                continue
            self._queue_index_map[idx] = item
        try:
            self.Expand(root)
        except RuntimeError:
            pass
        previous_saved = self._queue_saved_index
        if selected_index >= 0:
            self._queue_saved_index = min(selected_index, len(self._queue_items) - 1)
        elif previous_saved >= 0:
            self._queue_saved_index = min(previous_saved, len(self._queue_items) - 1)
        else:
            self._queue_saved_index = -1
        if selected_is_queue and self._queue_saved_index >= 0:
            self.highlight_queue_index(self._queue_saved_index, focus=False)
        else:
            self._queue_selected_index = -1

    def highlight_queue_index(self, index: int, *, focus: bool = False) -> bool:
        if (
            self._destroyed
            or not self._queue_root
            or not self._queue_root.IsOk()
            or index < 0
            or index >= len(self._queue_items)
        ):
            return False
        item = self._queue_index_map.get(index)
        if not item or not item.IsOk():
            return False
        try:
            self.SelectItem(item)
        except RuntimeError:
            return False
        try:
            self.EnsureVisible(item)
        except RuntimeError:
            pass
        if focus:
            try:
                self.SetFocus()
            except RuntimeError:
                pass
        self._queue_selected_index = index
        self._queue_saved_index = index
        return True

    def _wrap(self, kind: str, plex_object: Optional[PlexObject]) -> NodePayload:
        return NodePayload(
            kind=kind,
            plex_object=plex_object,
            identifier=self._identify(plex_object),
            queue_index=None,
        )

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

    def _populate_children(self, item: wx.TreeItemId, plex_object: object) -> None:
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

    def _apply_children(self, item: wx.TreeItemId, children: Iterable[object]) -> None:
        self._replace_children(item, list(children))

    def _ensure_queue_root(self) -> Optional[wx.TreeItemId]:
        if self._destroyed:
            return None
        if self._queue_root and self._queue_root.IsOk():
            return self._queue_root
        payload = NodePayload(kind="queue_root", plex_object=None, identifier="queue-root")
        try:
            self._queue_root = self.PrependItem(self._root, "Now Playing", data=payload)
        except RuntimeError:
            try:
                self._queue_root = self.AppendItem(self._root, "Now Playing", data=payload)
            except RuntimeError:
                self._queue_root = None
        if self._queue_root and self._queue_root.IsOk():
            try:
                self.SetItemBold(self._queue_root, True)
            except RuntimeError:
                pass
        return self._queue_root

    def _format_queue_label(self, plex_object: PlexObject, index: int) -> str:
        title = getattr(plex_object, "title", None) or getattr(plex_object, "name", None) or "Untitled"
        return f"{index + 1:02d}. {title}"

    def selection_is_queue(self) -> bool:
        payload = self._payload(self.GetSelection())
        return bool(payload and payload.kind in {"queue_root", "queue_item"})

    def last_queue_index(self) -> int:
        return self._queue_saved_index

    def remember_queue_index(self, index: int) -> None:
        if not self._queue_items:
            self._queue_saved_index = -1
            return
        if index < 0:
            self._queue_saved_index = -1
            return
        self._queue_saved_index = min(index, len(self._queue_items) - 1)

    def selected_queue_index(self) -> Optional[int]:
        return self._queue_selected_index if self._queue_selected_index >= 0 else None


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
        if payload and payload.kind == "queue_item" and payload.queue_index is not None:
            self._queue_selected_index = payload.queue_index
            self._queue_saved_index = payload.queue_index
        elif payload and payload.kind == "queue_root":
            self._queue_selected_index = -1
        else:
            self._queue_selected_index = -1
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

    def _is_expandable(self, plex_object: object) -> bool:
        if isinstance(plex_object, (MusicCategory, MusicAlphaBucket)):
            return True
        media_type = getattr(plex_object, "type", "")
        return media_type in {
            "show",
            "season",
            "artist",
            "album",
            "photoalbum",
            "collection",
        } or isinstance(plex_object, (LibrarySection, Folder))

    def expand_with_focus(self, item: wx.TreeItemId) -> None:
        if self._destroyed or not item or not item.IsOk():
            return
        try:
            self.Expand(item)
            self.EnsureVisible(item)
        except RuntimeError:
            return
        self._schedule_focus_first_child(item)

    def first_real_child(self, item: wx.TreeItemId) -> Optional[wx.TreeItemId]:
        child, cookie = self.GetFirstChild(item)
        while child and child.IsOk():
            payload = self._payload(child)
            if payload and payload.kind != "placeholder":
                return child
            child, cookie = self.GetNextChild(item, cookie)
        return None

    def _schedule_focus_first_child(self, item: wx.TreeItemId, attempts: int = 8, delay_ms: int = 90) -> None:
        if attempts <= 0 or self._destroyed or not item or not item.IsOk():
            return
        child = self.first_real_child(item)
        if child and child.IsOk():
            try:
                self.SelectItem(child)
                self.EnsureVisible(child)
            except RuntimeError:
                pass
            return
        wx.CallLater(delay_ms, self._schedule_focus_first_child, item, attempts - 1, delay_ms)

    def _handle_destroy(self, event: wx.WindowDestroyEvent) -> None:
        self._destroyed = True
        event.Skip()

    def focus_path(self, lineage: Sequence[PlexObject]) -> None:
        if self._destroyed or not lineage:
            return
        wx.CallAfter(self._focus_path_step, list(lineage), 0, self._root)

    def _focus_path_step(self, lineage: List[PlexObject], index: int, parent_item: wx.TreeItemId) -> None:
        if self._destroyed or index >= len(lineage):
            return
        if not parent_item or not parent_item.IsOk():
            return
        target = lineage[index]
        target_id = self._identify(target)
        if not target_id:
            return
        child_item = self._find_child_by_identifier(parent_item, target_id)
        if not child_item:
            parent_payload = self._payload(parent_item)
            parent_obj = parent_payload.plex_object if parent_payload else None
            if not parent_obj:
                return
            loading_key = parent_payload.identifier or self._identify(parent_obj)
            if loading_key and loading_key in self._loading_nodes:
                return
            if loading_key:
                self._loading_nodes.add(loading_key)

            def load_children() -> None:
                try:
                    children = list(self._loader(parent_obj))
                    error: Optional[Exception] = None
                except Exception as exc:  # noqa: BLE001
                    children = None
                    error = exc
                def apply(children_list: Optional[List[object]], err: Optional[Exception]) -> None:
                    if loading_key:
                        self._loading_nodes.discard(loading_key)
                    if err:
                        print(f"[NavigationTree] Unable to load children during focus: {err}")
                        return
                    if children_list is None:
                        return
                    def done() -> None:
                        self._focus_path_step(lineage, index, parent_item)
                    self._replace_children(parent_item, children_list, completion=done)
                wx.CallAfter(apply, children, error)

            threading.Thread(target=load_children, name="PlexNavNodeLoader", daemon=True).start()
            return
        should_expand = parent_item != self._root or not self.HasFlag(wx.TR_HIDE_ROOT)
        if should_expand:
            try:
                self.Expand(parent_item)
            except RuntimeError:
                return
        if index == len(lineage) - 1:
            try:
                self.SelectItem(child_item)
                self.EnsureVisible(child_item)
            except RuntimeError:
                pass
            return
        wx.CallAfter(self._focus_path_step, lineage, index + 1, child_item)

    def _identify(self, plex_object: Optional[object]) -> str:
        if not plex_object:
            return ""
        for attr in ("identifier", "ratingKey", "key", "uuid", "guid"):
            try:
                value = getattr(plex_object, attr, None)
            except Exception:
                value = None
            if value:
                return str(value)
        return str(id(plex_object))

    def _find_child_by_identifier(self, parent: wx.TreeItemId, identifier: str) -> Optional[wx.TreeItemId]:
        if not identifier or not parent or not parent.IsOk():
            return None
        child, cookie = self.GetFirstChild(parent)
        while child and child.IsOk():
            payload = self._payload(child)
            if payload and payload.identifier == identifier:
                return child
            child, cookie = self.GetNextChild(parent, cookie)
        return None

    def _apply_children_from_list(self, item: wx.TreeItemId, children: Iterable[object]) -> None:
        self._replace_children(item, list(children))

    def _replace_children(
        self,
        item: wx.TreeItemId,
        children: List[object],
        completion: Optional[Callable[[], None]] = None,
    ) -> None:
        print(f"[NavigationTree] replacing children count={len(children)} for {self.GetItemText(item) if item and item.IsOk() else '<invalid>'}")
        if self._destroyed or not item or not item.IsOk():
            return
        try:
            self.DeleteChildren(item)
        except RuntimeError:
            return
        if not children:
            if completion:
                completion()
            return
        self._append_children_batch(item, children, 0, completion=completion)

    def _append_children_batch(
        self,
        item: wx.TreeItemId,
        children: List[object],
        start: int,
        batch_size: int = 80,
        completion: Optional[Callable[[], None]] = None,
    ) -> None:
        if self._destroyed or not item or not item.IsOk():
            return
        end = min(len(children), start + batch_size)
        print(f"[NavigationTree] append batch start={start} end={end} total={len(children)}")
        for index in range(start, end):
            child = children[index]
            child_type = getattr(child, "type", "") or ("folder" if isinstance(child, Folder) else "item")
            label = getattr(child, "title", None) or getattr(child, "label", None) or str(child)
            try:
                child_item = self.AppendItem(item, label, data=self._wrap(child_type, child))
            except RuntimeError:
                continue
            if self._is_expandable(child):
                self._add_placeholder(child_item)
        if end < len(children):
            wx.CallAfter(self._append_children_batch, item, children, end, batch_size, completion)
        elif completion:
            completion()

