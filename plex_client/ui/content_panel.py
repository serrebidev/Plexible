from __future__ import annotations

from typing import Callable, List, Optional

import wx

from plexapi.base import PlexObject

from ..plex_service import PlayableMedia


class NamedAccessible(wx.Accessible):
    """Simple accessible wrapper that exposes a constant name and role.

    Use this on wx.Panel and other containers so NVDA reads a meaningful
    name instead of the generic class name ("panel", "grouping", etc.).
    """

    _ROLE_MAP: dict[str, int] = {
        "list": wx.ROLE_SYSTEM_LIST,
        "tree": wx.ROLE_SYSTEM_OUTLINE,
        "table": wx.ROLE_SYSTEM_TABLE,
        "group": wx.ROLE_SYSTEM_GROUPING,
        "pane": wx.ROLE_SYSTEM_PANE,
        "text": wx.ROLE_SYSTEM_TEXT,
        "slider": wx.ROLE_SYSTEM_SLIDER,
    }

    def __init__(self, name: str, role: str = "list") -> None:
        super().__init__()
        self._name = name
        self._role = self._ROLE_MAP.get(role, wx.ROLE_SYSTEM_LIST)

    def set_name(self, name: str) -> None:
        """Update the announced name in place (the wxAccessible stays attached)."""
        self._name = name

    def GetName(self, childId: int) -> tuple[int, str]:
        if childId == 0:
            return wx.ACC_OK, self._name
        return wx.ACC_NOT_IMPLEMENTED, ""

    def GetRole(self, childId: int) -> tuple[int, int]:
        return wx.ACC_OK, self._role


class NonFocusablePanel(wx.Panel):
    """A wx.Panel that is a tab stop only when it has something to descend into.

    wxWidgets gives a TAB_TRAVERSAL container the focus itself when it has no
    focusable child, so decorative strips and empty panels become tab stops that
    NVDA announces as a bare "panel" — and Tab then gets stuck on them, because
    traversal from inside a childless container finds nowhere to go.

    Two hooks decide this, and only one of them actually governs traversal:

        AcceptsFocus()             -- may this panel hold focus itself?
        AcceptsFocusFromKeyboard() -- is this panel part of the Tab cycle?

    Overriding AcceptsFocus() alone does nothing: wxNavigationEnabled computes
    AcceptsFocusFromKeyboard() as ``HasAnyFocusableChildren() ||
    BaseWindowClass::AcceptsFocusFromKeyboard()``, and that second term is an
    explicitly scoped, NON-virtual call that never reaches a Python override.
    Verified with wx.UIActionSimulator: AcceptsFocus() False alongside
    AcceptsFocusFromKeyboard() True still takes and traps focus.

    Overriding AcceptsFocusFromKeyboard() to a flat False is equally wrong — it
    removes the whole subtree, so every control inside becomes unreachable.

    So answer it honestly: join the cycle only when a child can take the focus,
    in which case wx forwards to that child rather than stopping here.
    """

    def _has_focusable_child(self) -> bool:
        for child in self.GetChildren():
            if child.IsShown() and child.IsEnabled() and child.AcceptsFocusFromKeyboard():
                return True
        return False

    def AcceptsFocus(self) -> bool:
        return False

    def AcceptsFocusFromKeyboard(self) -> bool:
        return self._has_focusable_child()


class DecorativePanel(NonFocusablePanel):
    """Purely visual panel (accent bars, separators, the video surface).

    Has no children, so it is always out of the Tab cycle.
    """


class TransparentContainer(NonFocusablePanel):
    """Hosts real controls and forwards Tab to them, but is never a stop itself.

    Drops out of the cycle entirely when every child is hidden or disabled.
    """


def name_control(window: wx.Window, name: str, role: str = "list") -> NamedAccessible:
    """Attach a stable accessible name to a native control.

    wx.Window.SetName alone does not reach MSAA for native controls
    (tree views, edits, sliders), so NVDA announces only the control type.
    The returned accessible must be kept alive by the caller.
    """
    window.SetName(name)
    accessible = NamedAccessible(name, role)
    window.SetAccessible(accessible)
    return accessible


class MetadataPanel(TransparentContainer):
    """Shows metadata for the selected Plex object and exposes playback actions."""

    def __init__(
        self,
        parent: wx.Window,
        on_play: Callable[[PlayableMedia], None],
        on_radio: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(parent)
        self.SetAccessible(NamedAccessible("Metadata Panel", "pane"))
        self._on_play = on_play
        self._on_radio = on_radio

        # Title with visual accent bar
        self._title = wx.StaticText(self, label="Select an item to see details.")
        self._title.SetName("Selected Item Title")
        bold_font = self._title.GetFont()
        bold_font.SetPointSize(bold_font.GetPointSize() + 2)
        bold_font.SetWeight(wx.FONTWEIGHT_BOLD)
        self._title.SetFont(bold_font)
        self._title.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_CAPTIONTEXT))

        # Thin accent bar under the title (decorative only, never focusable)
        self._title_accent = DecorativePanel(self, size=(-1, 2))
        self._title_accent.SetName("Title Accent")
        self._title_accent.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT))

        self._type_label = wx.StaticText(self, label="")
        self._type_label.SetName("Media Type")
        self._type_label.SetForegroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT))
        self._queue_focus_handler: Optional[Callable[[], bool]] = None
        self._summary = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_THEME)
        self._summary.SetMinSize((200, 120))
        # SetName does not reach MSAA for a native edit, so NVDA used to announce
        # only "edit read only multi line". Attach a real accessible instead.
        self._summary_accessible = name_control(self._summary, "Item Description", "text")
        self._summary.Bind(wx.EVT_NAVIGATION_KEY, self._handle_summary_navigation)

        self._play_button = wx.Button(self, wx.ID_ANY, label="Play")
        self._play_button.SetName("Play Selected Item")
        self._play_button.SetBackgroundColour(wx.Colour(46, 125, 50))
        self._play_button.SetForegroundColour(wx.WHITE)
        self._play_button.Disable()
        self._play_button.Bind(wx.EVT_BUTTON, self._handle_play)
        self._play_button.Bind(wx.EVT_CHAR_HOOK, self._handle_play_char)
        self._play_button.Bind(wx.EVT_KEY_DOWN, self._handle_play_key)

        self._radio_button = wx.Button(self, wx.ID_ANY, label="Radio…")
        self._radio_button.SetName("Start Radio")
        self._radio_button.Disable()
        self._radio_button.Hide()
        self._radio_button.Bind(wx.EVT_BUTTON, self._handle_radio)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        button_row.Add(self._play_button, 0, wx.RIGHT, 6)
        button_row.Add(self._radio_button, 0)

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(self._title, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        layout.Add(self._title_accent, 0, wx.LEFT | wx.RIGHT | wx.TOP | wx.EXPAND, 8)
        layout.Add(self._type_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 8)
        layout.Add(self._summary, 1, wx.ALL | wx.EXPAND, 8)
        layout.Add(button_row, 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(layout)

        self._current_media: Optional[PlayableMedia] = None
        self._status_text: str = ""
        self._radio_visible: bool = False
        self._radio_loading: bool = False

    def description_control(self) -> wx.Window:
        """The description edit — first Tab stop inside this panel."""
        return self._summary

    def play_control(self) -> wx.Window:
        return self._play_button

    def radio_control(self) -> wx.Window:
        return self._radio_button

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


class QueuesPanel(TransparentContainer):
    """Displays Continue Watching and Up Next queues using accessible wx.ListBox controls."""

    _MIN_LIST_HEIGHT = 140

    def __init__(
        self,
        parent: wx.Window,
        on_play: Callable[[PlayableMedia], None],
        on_select: Callable[[Optional[PlayableMedia]], None],
        on_refresh: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.SetAccessible(NamedAccessible("Queue Panels", "pane"))
        self._on_play = on_play
        self._on_select = on_select
        self._on_refresh = on_refresh

        self._continue_items: List[PlayableMedia] = []
        self._upnext_items: List[PlayableMedia] = []
        self._suppress_events = False
        self._accessible_refs: List[NamedAccessible] = []
        self._continue_label = "Continue Watching"
        self._upnext_label = "Up Next"
        self._continue_last_key: Optional[str] = None
        self._continue_last_index: int = -1
        self._upnext_last_key: Optional[str] = None
        self._upnext_last_index: int = -1
        self._last_focus_list: Optional[str] = None

        continue_box_widget = wx.StaticBox(self, label=self._continue_label)
        continue_box = wx.StaticBoxSizer(continue_box_widget, wx.VERTICAL)
        self._continue_list = self._create_list(continue_box_widget)
        self._set_accessibility(self._continue_list, self._continue_label)
        self._continue_placeholder = wx.StaticText(continue_box_widget, label="")
        self._continue_placeholder.Hide()

        upnext_box_widget = wx.StaticBox(self, label=self._upnext_label)
        upnext_box = wx.StaticBoxSizer(upnext_box_widget, wx.VERTICAL)
        self._upnext_list = self._create_list(upnext_box_widget)
        self._set_accessibility(self._upnext_list, self._upnext_label)
        self._upnext_placeholder = wx.StaticText(upnext_box_widget, label="")
        self._upnext_placeholder.Hide()

        self._bind_events()

        continue_box.Add(self._continue_list, 1, wx.EXPAND)
        continue_box.Add(self._continue_placeholder, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 12)

        upnext_box.Add(self._upnext_list, 1, wx.EXPAND)
        upnext_box.Add(self._upnext_placeholder, 0, wx.ALIGN_CENTER | wx.TOP | wx.BOTTOM, 12)

        root = wx.BoxSizer(wx.HORIZONTAL)
        root.Add(continue_box, 1, wx.EXPAND | wx.ALL, 6)
        root.Add(upnext_box, 1, wx.EXPAND | wx.ALL, 6)
        self.SetSizer(root)

    def continue_control(self) -> wx.Window:
        return self._continue_list

    def upnext_control(self) -> wx.Window:
        return self._upnext_list

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
            # No previous selection to restore — default to first available item
            # so the user can press Enter immediately without arrowing first.
            if self._continue_items and self._continue_list.GetSelection() == wx.NOT_FOUND:
                self._select_list_index(self._continue_list, 0)
                self._on_select(self._continue_items[0])
                self._last_focus_list = "continue"
                self._continue_last_index = 0
                self._continue_last_key = self._continue_items[0].key
                selection_restored = True
            elif self._upnext_items and self._upnext_list.GetSelection() == wx.NOT_FOUND:
                self._select_list_index(self._upnext_list, 0)
                self._on_select(self._upnext_items[0])
                self._last_focus_list = "upnext"
                self._upnext_last_index = 0
                self._upnext_last_key = self._upnext_items[0].key
                selection_restored = True
            else:
                self._on_select(None)
        self.Layout()

    def _create_list(self, parent: Optional[wx.Window] = None) -> wx.ListBox:
        list_box = wx.ListBox(parent or self, style=wx.LB_SINGLE | wx.BORDER_THEME)
        list_box.SetMinSize((-1, self._MIN_LIST_HEIGHT))
        return list_box

    def _bind_events(self) -> None:
        self._continue_list.Bind(wx.EVT_LISTBOX, self._on_continue_selected)
        self._continue_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_continue_activated)
        # Use EVT_CHAR_HOOK instead of EVT_KEY_DOWN because the native
        # Windows ListBox consumes VK_RETURN at WM_KEYDOWN before wx sees it.
        # CHAR_HOOK fires at WM_CHAR level and catches Enter reliably.
        self._continue_list.Bind(wx.EVT_CHAR_HOOK, self._on_list_key)

        self._upnext_list.Bind(wx.EVT_LISTBOX, self._on_upnext_selected)
        self._upnext_list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_upnext_activated)
        self._upnext_list.Bind(wx.EVT_CHAR_HOOK, self._on_list_key)

    def _populate_list(
        self,
        list_box: wx.ListBox,
        items: List[PlayableMedia],
        secondary_formatter: Callable[[PlayableMedia], str],
    ) -> None:
        self._suppress_events = True
        try:
            list_box.Freeze()
            list_box.Clear()
            labels = []
            for media in items:
                title = self._format_title(media)
                secondary = secondary_formatter(media)
                if secondary:
                    label = f"{title}  ·  {secondary}"
                else:
                    label = title
                labels.append(label)
            list_box.Set(labels)
            self._clear_selection(list_box)
        finally:
            list_box.Thaw()
            self._suppress_events = False

    def _clear_selection(self, list_box: wx.ListBox) -> None:
        previous = self._suppress_events
        self._suppress_events = True
        try:
            list_box.SetSelection(wx.NOT_FOUND)
        finally:
            self._suppress_events = previous

    def _set_accessibility(self, window: wx.Window, name: str, role: str = "list") -> None:
        self._accessible_refs.append(name_control(window, name, role))

    def _set_placeholder(
        self,
        list_box: wx.ListBox,
        placeholder: wx.StaticText,
        message: str,
    ) -> None:
        self._suppress_events = True
        try:
            list_box.Hide()
            placeholder.SetLabel(message)
            placeholder.Show()
            self._clear_selection(list_box)
            list_box.Clear()
        finally:
            self._suppress_events = False

    def _show_list(self, list_box: wx.ListBox, placeholder: wx.StaticText) -> None:
        placeholder.Hide()
        list_box.Show()
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

    def _on_continue_selected(self, event: wx.CommandEvent) -> None:
        if self._suppress_events:
            return
        index = event.GetSelection()
        self._clear_selection(self._upnext_list)
        media = self._continue_items[index] if 0 <= index < len(self._continue_items) else None
        if media:
            self._continue_last_key = media.key
            self._continue_last_index = index
            self._last_focus_list = "continue"
        self._on_select(media)
        event.Skip()

    def _on_upnext_selected(self, event: wx.CommandEvent) -> None:
        if self._suppress_events:
            return
        index = event.GetSelection()
        self._clear_selection(self._continue_list)
        media = self._upnext_items[index] if 0 <= index < len(self._upnext_items) else None
        if media:
            self._upnext_last_key = media.key
            self._upnext_last_index = index
            self._last_focus_list = "upnext"
        self._on_select(media)
        event.Skip()

    def _on_continue_activated(self, event: wx.CommandEvent) -> None:
        index = event.GetSelection()
        if 0 <= index < len(self._continue_items):
            self._on_play(self._continue_items[index])

    def _on_upnext_activated(self, event: wx.CommandEvent) -> None:
        index = event.GetSelection()
        if 0 <= index < len(self._upnext_items):
            self._on_play(self._upnext_items[index])

    def _on_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_F5:
            if self._on_refresh:
                self._on_refresh()
            return
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            focus = wx.Window.FindFocus()
            if focus is self._continue_list:
                idx = self._continue_list.GetSelection()
                if 0 <= idx < len(self._continue_items):
                    self._on_play(self._continue_items[idx])
                    return
            elif focus is self._upnext_list:
                idx = self._upnext_list.GetSelection()
                if 0 <= idx < len(self._upnext_items):
                    self._on_play(self._upnext_items[idx])
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

    def _select_list_index(self, list_box: wx.ListBox, index: int) -> bool:
        if index < 0 or index >= list_box.GetCount():
            return False
        previous = self._suppress_events
        self._suppress_events = True
        try:
            list_box.SetSelection(index)
        finally:
            self._suppress_events = previous
        return True
