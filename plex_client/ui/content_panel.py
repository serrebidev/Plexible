from __future__ import annotations

from typing import Callable, List, Optional

import wx

from plexapi.base import PlexObject

from ..plex_service import PlayableMedia


class MetadataPanel(wx.Panel):
    """Shows metadata for the selected Plex object and exposes playback actions."""

    def __init__(
        self,
        parent: wx.Window,
        on_play: Callable[[PlayableMedia], None],
        on_radio: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._on_play = on_play
        self._on_radio = on_radio

        self._title = wx.StaticText(self, label="Select an item to see details.")
        bold_font = self._title.GetFont()
        bold_font.SetPointSize(bold_font.GetPointSize() + 2)
        bold_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._title.SetFont(bold_font)

        self._type_label = wx.StaticText(self, label="")
        self._queue_focus_handler: Optional[Callable[[], bool]] = None
        self._summary = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_NONE)
        self._summary.SetMinSize((200, 120))
        self._summary.SetName("Status")
        self._summary.Bind(wx.EVT_NAVIGATION_KEY, self._handle_summary_navigation)

        self._play_button = wx.Button(self, wx.ID_ANY, label="Play")
        self._play_button.Disable()
        self._play_button.Bind(wx.EVT_BUTTON, self._handle_play)
        self._play_button.Bind(wx.EVT_CHAR_HOOK, self._handle_play_char)
        self._play_button.Bind(wx.EVT_KEY_DOWN, self._handle_play_key)

        self._radio_button = wx.Button(self, wx.ID_ANY, label="Radio…")
        self._radio_button.Disable()
        self._radio_button.Hide()
        self._radio_button.Bind(wx.EVT_BUTTON, self._handle_radio)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        button_row.Add(self._play_button, 0, wx.RIGHT, 6)
        button_row.Add(self._radio_button, 0)

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(self._title, 0, wx.ALL | wx.EXPAND, 8)
        layout.Add(self._type_label, 0, wx.LEFT | wx.RIGHT, 8)
        layout.Add(self._summary, 1, wx.ALL | wx.EXPAND, 8)
        layout.Add(button_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(layout)

        self._current_media: Optional[PlayableMedia] = None
        self._status_text: str = ""
        self._radio_visible: bool = False
        self._radio_loading: bool = False

    def set_queue_focus_handler(self, handler: Optional[Callable[[], bool]]) -> None:
        """Register a callback to move focus to the playback queue."""
        self._queue_focus_handler = handler

    def update_content(self, obj: Optional[PlexObject], playable: Optional[PlayableMedia]) -> None:
        if obj is None:
            self._title.SetLabel("Select an item to see details.")
            self._type_label.SetLabel("")
            self._current_media = None
            self._apply_status_text()
            self.set_radio_state(visible=False)
            return

        self._title.SetLabel(getattr(obj, "title", "Untitled"))
        type_label = getattr(obj, "type", "")
        if type_label:
            self._type_label.SetLabel(f"Type: {type_label}")
        else:
            self._type_label.SetLabel("")

        summary = getattr(obj, "summary", "")
        self._summary.SetValue(summary or "")
        self._summary.SetName("Description" if playable else "Status")

        self._current_media = playable
        if playable:
            self._play_button.Enable()
        else:
            self._play_button.Disable()

    def set_status_message(self, message: str) -> None:
        self._status_text = message or ""
        if self._current_media is None:
            self._apply_status_text()

    def set_radio_state(
        self,
        *,
        visible: bool,
        enabled: bool = False,
        label: str = "Radio…",
        loading: bool = False,
        tooltip: Optional[str] = None,
    ) -> None:
        self._radio_loading = loading
        self._radio_button.SetLabel(label)
        self._radio_button.SetToolTip(tooltip or "")
        if visible:
            if not self._radio_visible:
                self._radio_button.Show()
                self._radio_visible = True
                self.Layout()
        else:
            if self._radio_visible:
                self._radio_button.Hide()
                self._radio_visible = False
                self.Layout()
        if not visible:
            return
        if loading:
            self._radio_button.Disable()
        elif enabled and self._on_radio:
            self._radio_button.Enable()
        else:
            self._radio_button.Disable()

    def _apply_status_text(self) -> None:
        self._summary.SetValue(self._status_text or "")
        self._summary.SetName("Status")
        self._play_button.Disable()

    def _handle_play(self, _: wx.CommandEvent) -> None:
        if self._current_media:
            self._on_play(self._current_media)

    def _handle_play_char(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self._current_media:
                self._on_play(self._current_media)
                return
        event.Skip()

    def _handle_play_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_SPACE:
            if self._current_media:
                self._on_play(self._current_media)
                return
            event.Skip()
            return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self._current_media:
                self._on_play(self._current_media)
                return
        event.Skip()

    def _handle_radio(self, _: wx.CommandEvent) -> None:
        if self._radio_loading:
            wx.Bell()
            return
        if self._on_radio:
            self._on_radio()
        else:
            wx.Bell()

    def _handle_summary_navigation(self, event: wx.NavigationKeyEvent) -> None:
        if not event.IsFromTab() or event.GetEventObject() is not self._summary:
            event.Skip()
            return
        if event.GetDirection() and self._queue_focus_handler:
            handled = self._queue_focus_handler()
            if handled:
                return
        event.Skip()


class _NamedAccessible(wx.Accessible):
    """Simple accessible wrapper that exposes a constant name."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name

    def GetName(self, childId: int) -> tuple[int, str]:
        if childId == 0:
            return wx.ACC_OK, self._name
        return wx.ACC_NOT_IMPLEMENTED, ""

    def GetRole(self, childId: int) -> tuple[int, int]:
        return wx.ACC_OK, wx.ROLE_SYSTEM_LIST


class QueuesPanel(wx.Panel):
    """Displays Continue Watching and Up Next queues."""

    _MIN_LIST_HEIGHT = 140

    def __init__(
        self,
        parent: wx.Window,
        on_play: Callable[[PlayableMedia], None],
        on_select: Callable[[Optional[PlayableMedia]], None],
        on_refresh: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_play = on_play
        self._on_select = on_select
        self._on_refresh = on_refresh

        self._continue_items: List[PlayableMedia] = []
        self._upnext_items: List[PlayableMedia] = []
        self._suppress_events = False
        self._accessible_refs: List[_NamedAccessible] = []
        self._continue_label = "Continue Watching"
        self._upnext_label = "Up Next"
        self._continue_last_key: Optional[str] = None
        self._continue_last_index: int = -1
        self._upnext_last_key: Optional[str] = None
        self._upnext_last_index: int = -1
        self._last_focus_list: Optional[str] = None

        self._continue_list = self._create_list()
        self._continue_list.InsertColumn(0, "Title")
        self._continue_list.InsertColumn(1, "Progress")
        self._set_accessibility(self._continue_list, self._continue_label)
        self._continue_placeholder = wx.StaticText(self, label="")
        self._continue_placeholder.Hide()

        self._upnext_list = self._create_list()
        self._upnext_list.InsertColumn(0, "Title")
        self._upnext_list.InsertColumn(1, "Type")
        self._set_accessibility(self._upnext_list, self._upnext_label)
        self._upnext_placeholder = wx.StaticText(self, label="")
        self._upnext_placeholder.Hide()

        self._bind_events()

        continue_box = wx.StaticBoxSizer(wx.StaticBox(self, label=self._continue_label), wx.VERTICAL)
        continue_box.Add(self._continue_list, 1, wx.EXPAND)
        continue_box.Add(self._continue_placeholder, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 12)

        upnext_box = wx.StaticBoxSizer(wx.StaticBox(self, label=self._upnext_label), wx.VERTICAL)
        upnext_box.Add(self._upnext_list, 1, wx.EXPAND)
        upnext_box.Add(self._upnext_placeholder, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 12)

        root = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(continue_box, 1, wx.EXPAND | wx.ALL, 6)
        root.Add(upnext_box, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(root)

    def show_placeholders(self, continue_message: str, up_next_message: str) -> None:
        self._continue_items.clear()
        self._upnext_items.clear()
        self._set_placeholder(self._continue_list, self._continue_placeholder, continue_message)
        self._set_placeholder(self._upnext_list, self._upnext_placeholder, up_next_message)
        self._on_select(None)
        self.Layout()

    def update_lists(self, continue_items: List[PlayableMedia], up_next_items: List[PlayableMedia]) -> None:
        self._continue_items = list(continue_items)
        self._upnext_items = list(up_next_items)
        selection_restored = False

        if self._continue_items:
            self._populate_list(
                self._continue_list,
                self._continue_items,
                lambda media: self._format_progress(media.item),
            )
            self._show_list(self._continue_list, self._continue_placeholder)
        else:
            self._continue_last_key = None
            self._continue_last_index = -1
            if self._last_focus_list == "continue":
                self._last_focus_list = None
            self._set_placeholder(
                self._continue_list,
                self._continue_placeholder,
                "Nothing in progress yet.",
            )

        if self._upnext_items:
            self._populate_list(
                self._upnext_list,
                self._upnext_items,
                lambda media: self._format_media_type(media.item),
            )
            self._show_list(self._upnext_list, self._upnext_placeholder)
        else:
            self._upnext_last_key = None
            self._upnext_last_index = -1
            if self._last_focus_list == "upnext":
                self._last_focus_list = None
            self._set_placeholder(
                self._upnext_list,
                self._upnext_placeholder,
                "No upcoming episodes right now.",
            )

        restored = self._restore_last_selection()
        if restored is not None:
            selection_restored = True
        if not selection_restored:
            self._on_select(None)
        self.Layout()

    def _create_list(self) -> wx.ListCtrl:
        list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_NONE)
        list_ctrl.SetMinSize((-1, self._MIN_LIST_HEIGHT))
        return list_ctrl

    def _bind_events(self) -> None:
        self._continue_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_continue_selected)
        self._continue_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_list_deselected)
        self._continue_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_continue_activated)
        self._continue_list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)

        self._upnext_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_upnext_selected)
        self._upnext_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_list_deselected)
        self._upnext_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_upnext_activated)
        self._upnext_list.Bind(wx.EVT_KEY_DOWN, self._on_list_key)

    def _populate_list(
        self,
        list_ctrl: wx.ListCtrl,
        items: List[PlayableMedia],
        secondary_formatter: Callable[[PlayableMedia], str],
    ) -> None:
        self._suppress_events = True
        try:
            list_ctrl.Freeze()
            list_ctrl.DeleteAllItems()
            for idx, media in enumerate(items):
                list_ctrl.InsertItem(idx, self._format_title(media))
                list_ctrl.SetItem(idx, 1, secondary_formatter(media))
            self._autosize_columns(list_ctrl)
            self._clear_selection(list_ctrl)
        finally:
            list_ctrl.Thaw()
            self._suppress_events = False

    def _autosize_columns(self, list_ctrl: wx.ListCtrl) -> None:
        column_count = list_ctrl.GetColumnCount()
        if column_count == 0:
            return
        width = list_ctrl.GetClientSize().width
        if width <= 0:
            width = 400
        primary_width = max(int(width * 0.7), 240)
        secondary_width = max(width - primary_width - 12, 120)
        list_ctrl.SetColumnWidth(0, primary_width)
        list_ctrl.SetColumnWidth(1, secondary_width)

    def _clear_selection(self, list_ctrl: wx.ListCtrl) -> None:
        previous = self._suppress_events
        self._suppress_events = True
        try:
            index = list_ctrl.GetFirstSelected()
            while index != -1:
                list_ctrl.SetItemState(index, 0, wx.LIST_STATE_SELECTED)
                index = list_ctrl.GetNextItem(index, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
        finally:
            self._suppress_events = previous

    def _set_accessibility(self, window: wx.Window, name: str) -> None:
        window.SetName(name)
        accessible = _NamedAccessible(name)
        window.SetAccessible(accessible)
        self._accessible_refs.append(accessible)

    def _set_placeholder(
        self,
        list_ctrl: wx.ListCtrl,
        placeholder: wx.StaticText,
        message: str,
    ) -> None:
        self._suppress_events = True
        try:
            list_ctrl.Hide()
            placeholder.SetLabel(message)
            placeholder.Show()
            self._clear_selection(list_ctrl)
            list_ctrl.DeleteAllItems()
        finally:
            self._suppress_events = False

    def _show_list(self, list_ctrl: wx.ListCtrl, placeholder: wx.StaticText) -> None:
        placeholder.Hide()
        list_ctrl.Show()
        placeholder.SetLabel("")

    def _format_title(self, media: PlayableMedia) -> str:
        item = media.item
        media_type = getattr(item, "type", media.media_type)
        if media_type == "episode":
            show = getattr(item, "grandparentTitle", "") or ""
            season = getattr(item, "parentIndex", None)
            episode = getattr(item, "index", None)
            if show and season is not None and episode is not None:
                try:
                    season_str = f"S{int(season):02d}"
                except Exception:
                    season_str = f"S{season}"
                try:
                    episode_str = f"E{int(episode):02d}"
                except Exception:
                    episode_str = f"E{episode}"
                return f"{show} · {season_str}{episode_str} – {media.title}"
            if show:
                return f"{show} – {media.title}"
        return media.title

    def _format_progress(self, item: PlexObject) -> str:
        offset = int(getattr(item, "viewOffset", 0) or 0)
        duration = int(getattr(item, "duration", 0) or 0)
        if duration <= 0 or offset <= 0:
            return ""
        percent = min(99, int(offset * 100 / duration))
        remaining = max(0, duration - offset)
        remaining_minutes = remaining // 60000
        if remaining_minutes >= 1:
            return f"{percent}% · {remaining_minutes} min left"
        return f"{percent}% watched"

    def _format_media_type(self, item: PlexObject) -> str:
        media_type = getattr(item, "type", "") or ""
        return media_type.capitalize()

    def _on_continue_selected(self, event: wx.ListEvent) -> None:
        if self._suppress_events:
            return
        index = event.GetIndex()
        self._clear_selection(self._upnext_list)
        media = self._continue_items[index] if 0 <= index < len(self._continue_items) else None
        if media:
            self._continue_last_key = media.key
            self._continue_last_index = index
            self._last_focus_list = "continue"
        self._on_select(media)
        event.Skip()

    def _on_upnext_selected(self, event: wx.ListEvent) -> None:
        if self._suppress_events:
            return
        index = event.GetIndex()
        self._clear_selection(self._continue_list)
        media = self._upnext_items[index] if 0 <= index < len(self._upnext_items) else None
        if media:
            self._upnext_last_key = media.key
            self._upnext_last_index = index
            self._last_focus_list = "upnext"
        self._on_select(media)
        event.Skip()

    def _on_list_deselected(self, _: wx.ListEvent) -> None:
        if self._suppress_events:
            return
        if (
            self._continue_list.GetSelectedItemCount() == 0
            and self._upnext_list.GetSelectedItemCount() == 0
        ):
            self._last_focus_list = None
            self._on_select(None)

    def _on_continue_activated(self, event: wx.ListEvent) -> None:
        index = event.GetIndex()
        if 0 <= index < len(self._continue_items):
            self._on_play(self._continue_items[index])

    def _on_upnext_activated(self, event: wx.ListEvent) -> None:
        index = event.GetIndex()
        if 0 <= index < len(self._upnext_items):
            self._on_play(self._upnext_items[index])

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_F5:
            if self._on_refresh:
                self._on_refresh()
            return
        event.Skip()

    def _restore_last_selection(self) -> Optional[PlayableMedia]:
        if self._last_focus_list == "continue":
            return self._restore_continue_selection()
        if self._last_focus_list == "upnext":
            return self._restore_upnext_selection()
        return None

    def _restore_continue_selection(self) -> Optional[PlayableMedia]:
        index = self._resolve_restore_index(self._continue_items, self._continue_last_key, self._continue_last_index)
        if index is None:
            return None
        self._clear_selection(self._upnext_list)
        if not self._select_list_index(self._continue_list, index):
            return None
        media = self._continue_items[index]
        self._continue_last_index = index
        self._continue_last_key = media.key
        self._last_focus_list = "continue"
        self._on_select(media)
        return media

    def _restore_upnext_selection(self) -> Optional[PlayableMedia]:
        index = self._resolve_restore_index(self._upnext_items, self._upnext_last_key, self._upnext_last_index)
        if index is None:
            return None
        self._clear_selection(self._continue_list)
        if not self._select_list_index(self._upnext_list, index):
            return None
        media = self._upnext_items[index]
        self._upnext_last_index = index
        self._upnext_last_key = media.key
        self._last_focus_list = "upnext"
        self._on_select(media)
        return media

    def _resolve_restore_index(
        self,
        items: List[PlayableMedia],
        last_key: Optional[str],
        last_index: int,
    ) -> Optional[int]:
        if not items:
            return None
        if last_key:
            for idx, media in enumerate(items):
                if media.key == last_key:
                    return idx
        if last_index >= 0:
            bounded = min(last_index, len(items) - 1)
            if bounded >= 0:
                return bounded
        return None

    def _select_list_index(self, list_ctrl: wx.ListCtrl, index: int) -> bool:
        if index < 0 or index >= list_ctrl.GetItemCount():
            return False
        previous = self._suppress_events
        self._suppress_events = True
        try:
            list_ctrl.SetItemState(
                index,
                wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
                wx.LIST_STATE_SELECTED | wx.LIST_STATE_FOCUSED,
            )
            list_ctrl.EnsureVisible(index)
        finally:
            self._suppress_events = previous
        return True
