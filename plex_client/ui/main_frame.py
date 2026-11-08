from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

import wx

from plexapi.base import PlexObject
from plexapi.library import LibrarySection
from plexapi.myplex import MyPlexAccount, MyPlexResource
from plexapi.server import PlexServer

from ..auth import AuthError, AuthManager
from ..config import ConfigStore
from .. import i18n
from ..i18n import N_, _, ngettext
from ..plex_service import (
    MusicAlphaBucket,
    MusicCategory,
    MusicRadioOption,
    MusicRadioStation,
    PlayableMedia,
    PlexService,
    RadioOption,
    RadioSession,
    SearchHit,
)
from .. import screen_reader
from ..updater import UpdateManager

# Plex type codes -> labels shown to the user (translated where displayed).
_TYPE_LABELS: Dict[str, str] = {
    "movie": N_("Movie"),
    "show": N_("Show"),
    "season": N_("Season"),
    "episode": N_("Episode"),
    "artist": N_("Artist"),
    "album": N_("Album"),
    "track": N_("Track"),
    "photo": N_("Photo"),
    "photoalbum": N_("Photo Album"),
    "playlist": N_("Playlist"),
    "collection": N_("Collection"),
    "clip": N_("Clip"),
    "tag": N_("Tag"),
    "genre": N_("Genre"),
    "director": N_("Director"),
    "actor": N_("Actor"),
    "unknown": N_("Unknown"),
}


# Lower-case fragments that pick the status bar tint. The status text is
# translated, so the French wording of the same messages is listed too.
# "connecté à"/"connecté en tant que" rather than "connecté", which would also
# match "Déconnecté.".
_STATUS_SUCCESS_CUES: Tuple[str, ...] = (
    "connected", "ready", "signed in", "streaming",
    "connecté à", "connecté en tant que", "prêt", "lecture de ",
)
_STATUS_PROGRESS_CUES: Tuple[str, ...] = (
    "connecting", "loading", "signing", "retrying", "searching",
    "connexion à", "connexion au", "chargement", "connexion en cours",
    "nouvelle tentative", "recherche en cours",
)
_STATUS_ERROR_CUES: Tuple[str, ...] = (
    "error", "failed", "unable", "cannot",
    "erreur", "échec", "impossible",
)


def _type_label(media_type: str) -> str:
    """Return the user-facing label for a Plex type code."""
    label = _TYPE_LABELS.get(media_type)
    if label:
        return _(label)
    return media_type.replace("_", " ").title()


def _localise_stock_buttons(dialog: wx.Dialog) -> None:
    """Give the OK/Cancel buttons wx creates for stock dialogs translated labels."""
    for button_id, label in ((wx.ID_OK, _("OK")), (wx.ID_CANCEL, _("Cancel"))):
        try:
            button = dialog.FindWindow(button_id)
            if button is not None:
                button.SetLabel(label)
        except Exception:
            pass


class SearchResultsDialog(wx.Dialog):
    """Dialog that streams search results as they arrive."""

    def __init__(self, parent: wx.Window, query: str) -> None:
        self._status_message = ""
        self._status_bar: Optional[wx.StatusBar] = None
        super().__init__(parent, title=_("Search: {query}", query=query), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._hits: List[SearchHit] = []
        self._errors: List[str] = []
        self._finished = False
        self._closed = False
        self._pending_hits: List[SearchHit] = []
        self._pending_labels: List[str] = []
        self._flush_timer: Optional[wx.CallLater] = None
        self._flush_interval_ms = 120
        self._last_running_status_count = 0
        self._last_running_status_time = 0.0

        heading = wx.StaticText(self, label=_("Results for '{query}':", query=query))
        heading.SetName(_("Search Results Heading"))
        self._list = wx.ListBox(self)
        self._list.SetName(_("Search Results"))
        self._status = wx.StaticText(self, label=_("Searching remote Plex servers…"))
        self._status.SetName(_("Search Status"))
        self._status_message = self._status.GetLabel()

        self._open_button = wx.Button(self, wx.ID_OK, _("Open"))
        self._open_button.Enable(False)
        cancel_button = wx.Button(self, wx.ID_CANCEL, _("Close"))

        button_sizer = wx.StdDialogButtonSizer()
        button_sizer.AddButton(self._open_button)
        button_sizer.AddButton(cancel_button)
        button_sizer.Realize()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 6)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        sizer.Add(self._status, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 6)
        self.SetSizerAndFit(sizer)
        self.SetSize((520, 420))

        self._open_button.Bind(wx.EVT_BUTTON, self._on_open)
        cancel_button.Bind(wx.EVT_BUTTON, self._on_cancel)
        self.Bind(wx.EVT_CLOSE, self._on_window_close)
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_activate)
        self._list.Bind(wx.EVT_CHAR_HOOK, self._on_list_char)

    def EndModal(self, retCode: int) -> None:  # type: ignore[override]
        if self._closed:
            return
        self._cancel_flush_timer()
        self._flush_pending_hits()
        self._closed = True
        super().EndModal(retCode)

    def add_hit(self, hit: SearchHit, label: str) -> None:
        self.add_hits([(hit, label)])

    def add_hits(self, entries: Iterable[Tuple[SearchHit, str]]) -> None:
        if self._closed:
            return
        local_hits: List[SearchHit] = []
        local_labels: List[str] = []
        for hit, label in entries:
            local_hits.append(hit)
            local_labels.append(label)
        if not local_hits:
            return
        self._pending_hits.extend(local_hits)
        self._pending_labels.extend(local_labels)
        self._schedule_flush()

    def update_status(self, message: str) -> None:
        self._set_status_label(message)

    def _set_status_label(self, message: str) -> None:
        if self._closed:
            return
        if message == self._status_message:
            return
        self._status_message = message
        self._status.SetLabel(message)

    def _set_running_result_status(self) -> None:
        if self._closed:
            return
        count = len(self._hits)
        now = time.monotonic()
        should_update = False
        if self._last_running_status_count == 0 and count > 0:
            should_update = True
        elif count - self._last_running_status_count >= 5:
            should_update = True
        elif now - self._last_running_status_time >= 0.75:
            should_update = True
        if not should_update and count != self._last_running_status_count:
            return
        self._last_running_status_count = count
        self._last_running_status_time = now
        self._set_status_label(ngettext("{count} result so far.", "{count} results so far.", count))

    def _schedule_flush(self) -> None:
        if self._closed:
            return
        if self._flush_timer is not None:
            is_running = getattr(self._flush_timer, "IsRunning", None)
            if callable(is_running) and is_running():
                return
        self._flush_timer = wx.CallLater(self._flush_interval_ms, self._flush_pending_hits)

    def _cancel_flush_timer(self) -> None:
        if self._flush_timer is None:
            return
        try:
            self._flush_timer.Stop()
        except Exception:
            pass
        self._flush_timer = None

    def _flush_pending_hits(self) -> None:
        timer = self._flush_timer
        self._flush_timer = None
        if timer is not None:
            try:
                timer.Stop()
            except Exception:
                pass
        if not self._pending_hits:
            return
        if self._closed:
            self._pending_hits.clear()
            self._pending_labels.clear()
            return
        pending_hits = self._pending_hits
        pending_labels = self._pending_labels
        self._pending_hits = []
        self._pending_labels = []
        self._list.Freeze()
        try:
            append_items = getattr(self._list, "AppendItems", None)
            if append_items:
                append_items(pending_labels)
            else:
                for label in pending_labels:
                    self._list.Append(label)
        finally:
            self._list.Thaw()
        self._hits.extend(pending_hits)
        if self._hits:
            self._open_button.Enable(True)
            self._set_running_result_status()

    def finish(self, errors: List[str]) -> None:
        if self._closed:
            return
        self._cancel_flush_timer()
        self._flush_pending_hits()
        self._finished = True
        self._errors = errors
        if self._hits:
            message = ngettext("Finished. {count} result.", "Finished. {count} results.", len(self._hits))
        else:
            message = _("Finished. No results found.")
            self._open_button.Enable(False)
        if errors:
            message = ngettext(
                "{message} {count} server issue.",
                "{message} {count} server issues.",
                len(errors),
                message=message,
            )
        self._set_status_label(message)

    def finish_with_error(self, message: str) -> None:
        if self._closed:
            return
        self._cancel_flush_timer()
        self._flush_pending_hits()
        self._finished = True
        self._errors = [message]
        self._set_status_label(_("Error: {message}", message=message))
        self._open_button.Enable(False)

    def _on_open(self, _event: wx.CommandEvent) -> None:
        if self.selected_hit is not None:
            self.EndModal(wx.ID_OK)
        else:
            wx.Bell()

    def _on_cancel(self, _event: wx.CommandEvent) -> None:
        self.EndModal(wx.ID_CANCEL)

    def _on_window_close(self, event: wx.CloseEvent) -> None:
        self.EndModal(wx.ID_CANCEL)

    def _on_activate(self, _event: wx.CommandEvent) -> None:
        if self.selected_hit is not None:
            self.EndModal(wx.ID_OK)

    def _on_list_char(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self.selected_hit is not None:
                self.EndModal(wx.ID_OK)
            else:
                wx.Bell()
            return
        event.Skip()

    @property
    def selected_hit(self) -> Optional[SearchHit]:
        index = self._list.GetSelection()
        if index == wx.NOT_FOUND:
            return None
        return self._hits[index]

    @property
    def errors(self) -> List[str]:
        return list(self._errors)

    @property
    def has_hits(self) -> bool:
        return bool(self._hits)


class CollectionItemsDialog(wx.Dialog):
    """Non-modal window that lists the items inside a Plex collection."""

    def __init__(
        self,
        parent: wx.Window,
        on_play: Callable[[PlexObject], None],
        on_focus_request: Callable[[PlexObject], None],
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            title=_("Collection"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.MAXIMIZE_BOX,
        )
        self._on_play = on_play
        self._on_focus_request = on_focus_request
        self._on_close = on_close
        self._items: List[PlexObject] = []

        heading = wx.StaticText(self, label=_("Collection Items"))
        heading.SetName(_("Collection Heading"))
        heading_font = heading.GetFont()
        heading_font.SetPointSize(heading_font.GetPointSize() + 2)
        heading_font.SetWeight(wx.FONTWEIGHT_BOLD)
        heading.SetFont(heading_font)

        self._status = wx.StaticText(self, label=_("Loading collection..."))
        self._status.SetName(_("Collection Status"))
        self._status.Wrap(520)

        self._list = wx.ListBox(
            self,
            style=wx.LB_SINGLE | wx.BORDER_THEME,
        )
        self._list.SetName(_("Collection Items"))

        self._focus_button = wx.Button(self, wx.ID_ANY, label=_("Focus in Navigation"))
        self._focus_button.SetName(_("Focus in Navigation"))
        self._focus_button.Disable()
        play_button = wx.Button(self, wx.ID_ANY, label=_("Play"))
        play_button.SetName(_("Play Collection Item"))
        play_button.Disable()
        close_button = wx.Button(self, wx.ID_CLOSE, label=_("Close"))

        self._focus_button.Bind(wx.EVT_BUTTON, self._handle_focus)
        play_button.Bind(wx.EVT_BUTTON, self._handle_play_click)
        close_button.Bind(wx.EVT_BUTTON, self._handle_close_button)
        self._list.Bind(wx.EVT_LISTBOX, self._handle_selection_changed)
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, self._handle_item_activated)
        self._list.Bind(wx.EVT_KEY_DOWN, self._handle_list_key)

        button_row = wx.BoxSizer(wx.HORIZONTAL)
        button_row.AddStretchSpacer()
        button_row.Add(self._focus_button, 0, wx.RIGHT, 6)
        button_row.Add(play_button, 0, wx.RIGHT, 6)
        button_row.Add(close_button, 0)

        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(heading, 0, wx.ALL, 8)
        root.Add(self._status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        root.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)
        root.Add(button_row, 0, wx.EXPAND | wx.ALL, 8)
        self.SetSizer(root)
        self.SetSize((760, 520))

        self.Bind(wx.EVT_CLOSE, self._handle_close_window)
        self._play_button = play_button
        self._update_button_state()

    def set_collection_title(self, collection: PlexObject) -> None:
        title = getattr(collection, "title", None)
        heading = title.strip() if isinstance(title, str) else _("Collection")
        self.SetTitle(_("Collection: {title}", title=heading))

    def show_loading(self, message: str) -> None:
        self._status.SetLabel(message)
        self._list.Clear()
        self._items.clear()
        self._update_button_state()

    def show_error(self, message: str) -> None:
        self._status.SetLabel(message)
        self._list.Clear()
        self._items.clear()
        self._update_button_state()

    def show_items(
        self,
        items: Sequence[PlexObject],
        formatter: Callable[[PlexObject], tuple[str, str, str]],
    ) -> None:
        self._items = list(items)
        labels = []
        for item in self._items:
            title, item_type, details = formatter(item)
            parts = [title]
            if item_type:
                parts.append(item_type)
            if details:
                parts.append(details)
            labels.append("  ·  ".join(parts))
        self._list.Set(labels)
        count = len(self._items)
        summary = ngettext("{count} item.", "{count} items.", count)
        self._status.SetLabel(summary)
        if self._items:
            self._list.SetSelection(0)
        self._update_button_state()

    def _handle_selection_changed(self, _event: wx.CommandEvent) -> None:
        self._update_button_state()

    def _handle_item_activated(self, event: wx.CommandEvent) -> None:
        item = self._item_for_index(event.GetSelection())
        if item:
            self._on_play(item)

    def _handle_list_key(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            item = self._item_for_index(self._list.GetSelection())
            if item:
                self._on_play(item)
                return
        event.Skip()

    def _handle_play_click(self, _event: wx.CommandEvent) -> None:
        item = self._item_for_index(self._list.GetSelection())
        if item:
            self._on_play(item)

    def _handle_focus(self, _event: wx.CommandEvent) -> None:
        item = self._item_for_index(self._list.GetSelection())
        if item:
            self._on_focus_request(item)

    def _handle_close_button(self, _event: wx.CommandEvent) -> None:
        self.Close()

    def _handle_close_window(self, event: wx.CloseEvent) -> None:
        self._on_close()
        event.Skip()

    def _item_for_index(self, index: int) -> Optional[PlexObject]:
        if index < 0 or index >= len(self._items):
            return None
        return self._items[index]

    def _update_button_state(self) -> None:
        # wx.ListBox has no GetSelectedItemCount(); that is a wx.ListCtrl API.
        has_selection = self._list.GetSelection() != wx.NOT_FOUND
        self._focus_button.Enable(has_selection)
        self._play_button.Enable(has_selection)


class RadioChooserDialog(wx.Dialog):
    """Dialog for selecting a radio station option."""

    def __init__(self, parent: wx.Window, options: Iterable[RadioOption]) -> None:
        super().__init__(parent, title=_("Choose Radio Station"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._options: List[RadioOption] = list(options)

        heading = wx.StaticText(self, label=_("Select a radio station:"))
        heading.SetName(_("Radio Station Heading"))

        self._list = wx.ListBox(self, style=wx.LB_SINGLE | wx.BORDER_THEME)
        labels = []
        for option in self._options:
            if option.category:
                labels.append(f"{option.label}  ·  {option.category}")
            else:
                labels.append(option.label)
        self._list.Set(labels)
        self._list.SetName(_("Radio Stations"))

        desc_label = wx.StaticText(self, label=_("Description:"))
        self._description = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NO_VSCROLL | wx.BORDER_NONE,
        )
        self._description.SetMinSize((260, 110))
        self._description.SetName(_("Station Description"))

        self._start_button = wx.Button(self, wx.ID_OK, _("Start"))
        self._start_button.Enable(False)
        cancel_button = wx.Button(self, wx.ID_CANCEL, _("Cancel"))

        button_sizer = wx.StdDialogButtonSizer()
        button_sizer.AddButton(self._start_button)
        button_sizer.AddButton(cancel_button)
        button_sizer.Realize()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(heading, 0, wx.ALL, 6)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        sizer.Add(desc_label, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
        sizer.Add(self._description, 0, wx.EXPAND | wx.ALL, 6)
        sizer.Add(button_sizer, 0, wx.EXPAND | wx.ALL, 6)

        self.SetSizerAndFit(sizer)
        self.SetSize((480, 420))
        self._list.SetFocus()

        self._list.Bind(wx.EVT_LISTBOX, self._on_select)
        self._list.Bind(wx.EVT_LISTBOX_DCLICK, self._on_activate)
        self._list.Bind(wx.EVT_CHAR_HOOK, self._on_list_char)
        self._start_button.Bind(wx.EVT_BUTTON, self._on_start)
        cancel_button.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CANCEL))

    @property
    def selected_option(self) -> Optional[RadioOption]:
        index = self._list.GetSelection()
        if index == wx.NOT_FOUND:
            return None
        return self._options[index]

    def _update_description(self) -> None:
        option = self.selected_option
        if option:
            self._description.SetValue(option.description or "")
        else:
            self._description.SetValue("")

    def _on_select(self, _event: wx.CommandEvent) -> None:
        self._start_button.Enable(True)
        self._update_description()

    def _on_activate(self, _event: wx.CommandEvent) -> None:
        if self.selected_option is not None:
            self.EndModal(wx.ID_OK)
        else:
            wx.Bell()

    def _on_list_char(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self.selected_option is not None:
                self.EndModal(wx.ID_OK)
            else:
                wx.Bell()
            return
        event.Skip()

    def _on_start(self, _event: wx.CommandEvent) -> None:
        if self.selected_option is not None:
            self.EndModal(wx.ID_OK)
        else:
            wx.Bell()
from .content_panel import (
    MetadataPanel,
    NamedAccessible,
    QueuesPanel,
    TransparentContainer,
)
from .navigation import NavigationTree
from .playback import PlaybackPanel, SEEK_STEP_MS
from .wx_language import menu_shortcut


class MainFrame(wx.Frame):
    """Primary application window that orchestrates Plex authentication and playback."""

    _account: Optional[MyPlexAccount] = None
    _service: Optional[PlexService] = None

    def __init__(
        self,
        config: ConfigStore,
        auth_manager: AuthManager,
        on_restart_requested: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(None, title="Plexible", size=(1200, 800))
        self._config = config
        self._auth = auth_manager
        # Called when the user asks for a restart (language change). The caller
        # relaunches Plexible once this window has fully closed.
        self._on_restart_requested = on_restart_requested
        self._update_manager = UpdateManager(self, config, status_callback=self._set_status)
        self._service: Optional[PlexService] = None
        self._account: Optional[MyPlexAccount] = None
        self._busy_info: Optional[wx.BusyInfo] = None
        self._pending_selection: Optional[SearchHit] = None
        self._queue_refresh_timer: Optional[wx.CallLater] = None
        self._last_queue_play_key: Optional[str] = None
        self._timeline_threads: list[threading.Thread] = []
        self._status_message: str = ""
        self._status_bar: Optional[wx.StatusBar] = None
        self._selected_object: Optional[object] = None
        self._selected_playable: Optional[PlayableMedia] = None
        self._closing: bool = False
        self._progress_flush_active: bool = False
        self._progress_flush_timer: Optional[wx.CallLater] = None
        self._last_positions: Dict[str, int] = {}
        self._selected_playlist: Optional[PlexObject] = None
        self._playlist_launching: bool = False
        self._active_playlist_key: Optional[str] = None
        self._autoplay_sources: Dict[str, str] = {}
        self._autoplay_candidates: Dict[str, PlayableMedia] = {}
        self._autoplay_flagged: Set[str] = set()
        self._autoplay_pending_source: Optional[str] = None
        self._autoplay_timer: Optional[wx.CallLater] = None
        self._radio_options: List[RadioOption] = []
        self._radio_loading: bool = False
        self._radio_request_token: int = 0
        self._radio_sessions: Dict[str, RadioSession] = {}
        self._radio_pending_sessions: Dict[str, Tuple[RadioSession, int]] = {}
        self._collection_request_token: int = 0
        self._collection_dialog: Optional[CollectionItemsDialog] = None
        self._collection_dialog_identifier: Optional[str] = None
        self._active_queue_session: Optional[RadioSession] = None
        self._queue_last_focus_index: int = -1
        self._playable_request_token: int = 0
        self._reset_autoplay_state()

        self._build_menu()

        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        splitter.SetAccessible(NamedAccessible(_("Main Splitter"), "pane"))
        # TransparentContainer, not wx.Panel: a plain panel keeps the focus itself
        # whenever every child is hidden or disabled, which puts an unlabelled
        # "pane" in the Tab cycle. These only ever host other controls.
        left_panel = TransparentContainer(splitter)
        left_panel.SetAccessible(NamedAccessible(_("Navigation Panel"), "pane"))
        right_panel = TransparentContainer(splitter)
        right_panel.SetAccessible(NamedAccessible(_("Content Panel"), "pane"))

        self._nav_tree = NavigationTree(
            left_panel,
            loader=self._load_children,
            on_selection=self._handle_selection,
        )
        self._nav_tree.set_music_label_style(config.get_music_label_style())
        self._nav_tree.Bind(wx.EVT_KEY_DOWN, self._on_navigation_key)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(self._nav_tree, 1, wx.EXPAND)
        left_panel.SetSizer(left_sizer)

        right_splitter = wx.SplitterWindow(right_panel, style=wx.SP_LIVE_UPDATE)
        right_splitter.SetAccessible(NamedAccessible(_("Content Splitter"), "pane"))
        top_splitter = wx.SplitterWindow(right_splitter, style=wx.SP_LIVE_UPDATE)
        top_splitter.SetAccessible(NamedAccessible(_("Metadata Splitter"), "pane"))
        self._metadata_panel = MetadataPanel(
            top_splitter,
            on_play=self._start_playback,
            on_radio=self._handle_radio_action,
        )
        self._metadata_panel.set_status_message(_("Connecting..."))
        self._queues_panel = QueuesPanel(
            top_splitter,
            on_play=self._start_playback,
            on_select=self._handle_queue_selection,
            on_refresh=self._refresh_watch_queues,
        )
        top_splitter.SplitHorizontally(self._metadata_panel, self._queues_panel, sashPosition=190)
        top_splitter.SetMinimumPaneSize(150)

        self._playback_panel = PlaybackPanel(
            right_splitter,
            config,
            on_queue_activate=self._handle_queue_activate,
            on_skip=self._handle_skip,
        )
        self._playback_panel.set_state_listener(self._on_playback_state_change)
        self._playback_panel.set_timeline_callback(self._handle_timeline_update)
        self._metadata_panel.set_queue_focus_handler(self._focus_queue_from_metadata)
        right_splitter.SplitHorizontally(top_splitter, self._playback_panel, sashPosition=320)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer.Add(right_splitter, 1, wx.EXPAND)
        right_panel.SetSizer(right_sizer)
        self._queues_panel.show_placeholders(_("Sign in to see your queue."), _("Sign in to see your queue."))

        splitter.SplitVertically(left_panel, right_panel, sashPosition=320)
        splitter.SetMinimumPaneSize(180)
        right_splitter.SetMinimumPaneSize(220)

        self.CreateStatusBar()
        self._status_bar = self.GetStatusBar()
        self.CentreOnScreen()

        # Apply saved theme on startup
        if self._config.get_ui_theme() == "dark":
            self._apply_theme(dark=True)

        self._apply_tab_order()

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._initialise_account()
        self._refresh_player_menu()
        self._update_manager.schedule_auto_check()

    def _build_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        self._signin_item = file_menu.Append(wx.ID_ANY, _("Sign In...") + menu_shortcut("Ctrl+I"))
        self._signout_item = file_menu.Append(wx.ID_ANY, _("Sign Out"))
        file_menu.AppendSeparator()
        self._refresh_item = file_menu.Append(wx.ID_REFRESH, _("Refresh Libraries") + menu_shortcut("F5"))
        self._search_item = file_menu.Append(wx.ID_FIND, _("Global Search...") + menu_shortcut("Ctrl+F"))
        self._change_server_item = file_menu.Append(wx.ID_ANY, _("Change Server..."))
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, _("Exit") + menu_shortcut("Ctrl+Q"))
        menu_bar.Append(file_menu, _("&File"))

        player_menu = wx.Menu()
        self._player_play_item = player_menu.Append(wx.ID_ANY, _("Play") + menu_shortcut("Space"))
        self._player_pause_item = player_menu.Append(wx.ID_ANY, _("Pause") + menu_shortcut("Shift+Space"))
        self._player_stop_item = player_menu.Append(wx.ID_STOP, _("Stop") + menu_shortcut("Ctrl+S"))
        self._player_prev_track_item = player_menu.Append(wx.ID_ANY, _("Previous Track") + menu_shortcut("Ctrl+["))
        self._player_next_track_item = player_menu.Append(wx.ID_ANY, _("Next Track") + menu_shortcut("Ctrl+]"))
        player_menu.AppendSeparator()
        self._player_rewind_item = player_menu.Append(wx.ID_ANY, _("Rewind 10s") + menu_shortcut("Ctrl+Left"))
        self._player_fast_forward_item = player_menu.Append(wx.ID_ANY, _("Fast Forward 10s") + menu_shortcut("Ctrl+Right"))
        player_menu.AppendSeparator()
        self._player_volume_up_item = player_menu.Append(wx.ID_ANY, _("Volume Up") + menu_shortcut("Ctrl+Up"))
        self._player_volume_down_item = player_menu.Append(wx.ID_ANY, _("Volume Down") + menu_shortcut("Ctrl+Down"))
        self._player_fullscreen_item = player_menu.AppendCheckItem(wx.ID_ANY, _("Fullscreen") + menu_shortcut("F11"))
        self._player_mute_item = player_menu.AppendCheckItem(wx.ID_ANY, _("Mute") + menu_shortcut("Ctrl+0"))
        player_menu.AppendSeparator()
        self._player_announce_item = player_menu.Append(wx.ID_ANY, _("Announce Playback State") + menu_shortcut("Ctrl+Shift+A"))
        menu_bar.Append(player_menu, _("&Player"))
        self._player_menu = player_menu

        help_menu = wx.Menu()
        self._dark_mode_item = help_menu.AppendCheckItem(wx.ID_ANY, _("Dark Mode") + menu_shortcut("Ctrl+Shift+D"))
        self._dark_mode_item.Check(self._config.get_ui_theme() == "dark")
        help_menu.AppendSubMenu(self._build_language_menu(), _("La&nguage"))
        help_menu.AppendSeparator()
        self._check_updates_item = help_menu.Append(wx.ID_ANY, _("Check for Updates..."))
        self._auto_update_item = help_menu.AppendCheckItem(wx.ID_ANY, _("Automatically Check for Updates"))
        self._auto_update_item.Check(self._update_manager.is_auto_check_enabled())
        menu_bar.Append(help_menu, _("&Help"))

        self.SetMenuBar(menu_bar)

        self.Bind(wx.EVT_MENU, self._handle_sign_in, self._signin_item)
        self.Bind(wx.EVT_MENU, self._handle_sign_out, self._signout_item)
        self.Bind(wx.EVT_MENU, self._handle_refresh, self._refresh_item)
        self.Bind(wx.EVT_MENU, self._handle_search, self._search_item)
        self.Bind(wx.EVT_MENU, self._handle_change_server, self._change_server_item)
        self.Bind(wx.EVT_MENU, lambda _event: self.Close(True), exit_item)
        self.Bind(wx.EVT_MENU, self._handle_player_play, self._player_play_item)
        self.Bind(wx.EVT_MENU, self._handle_player_pause, self._player_pause_item)
        self.Bind(wx.EVT_MENU, self._handle_player_stop, self._player_stop_item)
        self.Bind(wx.EVT_MENU, self._handle_player_prev_track, self._player_prev_track_item)
        self.Bind(wx.EVT_MENU, self._handle_player_next_track, self._player_next_track_item)
        self.Bind(wx.EVT_MENU, self._handle_player_rewind, self._player_rewind_item)
        self.Bind(wx.EVT_MENU, self._handle_player_fast_forward, self._player_fast_forward_item)
        self.Bind(wx.EVT_MENU, self._handle_player_volume_up, self._player_volume_up_item)
        self.Bind(wx.EVT_MENU, self._handle_player_volume_down, self._player_volume_down_item)
        self.Bind(wx.EVT_MENU, self._handle_player_mute, self._player_mute_item)
        self.Bind(wx.EVT_MENU, self._handle_player_announce, self._player_announce_item)
        self.Bind(wx.EVT_MENU, self._handle_player_fullscreen, self._player_fullscreen_item)
        self.Bind(wx.EVT_MENU, self._handle_toggle_dark_mode, self._dark_mode_item)
        self.Bind(wx.EVT_MENU, self._handle_check_updates, self._check_updates_item)
        self.Bind(wx.EVT_MENU, self._handle_toggle_auto_updates, self._auto_update_item)

        self._install_accelerators()
        self._update_menu_state()
        self._refresh_player_menu()

    def _install_accelerators(self) -> None:
        entries = [
            (wx.ACCEL_CTRL, ord("S"), self._player_stop_item.GetId()),
            (wx.ACCEL_CTRL, ord("["), self._player_prev_track_item.GetId()),
            (wx.ACCEL_CTRL, ord("]"), self._player_next_track_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_LEFT, self._player_rewind_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_RIGHT, self._player_fast_forward_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_UP, self._player_volume_up_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_DOWN, self._player_volume_down_item.GetId()),
            (wx.ACCEL_CTRL, ord("0"), self._player_mute_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("A"), self._player_announce_item.GetId()),
            (wx.ACCEL_CTRL | wx.ACCEL_SHIFT, ord("D"), self._dark_mode_item.GetId()),
        ]
        try:
            self.SetAcceleratorTable(wx.AcceleratorTable(entries))
        except Exception:
            pass

    def _handle_check_updates(self, _event: wx.CommandEvent) -> None:
        self._update_manager.check_for_updates(interactive=True)

    def _build_language_menu(self) -> wx.Menu:
        menu = wx.Menu()
        current = self._config.get_language()
        if current not in i18n.SUPPORTED_LANGUAGES:
            current = i18n.SYSTEM_LANGUAGE
        choices = [(i18n.SYSTEM_LANGUAGE, _("System Default"))]
        # Language names stay in their own language so anyone can find theirs.
        choices += list(i18n.SUPPORTED_LANGUAGES.items())
        for code, label in choices:
            item = menu.AppendRadioItem(wx.ID_ANY, label)
            item.Check(code == current)
            self.Bind(wx.EVT_MENU, lambda _event, code=code: self._handle_language_choice(code), item)
        return menu

    def _handle_language_choice(self, code: str) -> None:
        if code == self._config.get_language():
            return
        self._config.set_language(code)
        if i18n.resolve_language(code) == i18n.get_language():
            return
        # Menus and panels are built once, so the new language applies on restart.
        # Ask in the chosen language: that is the one the user reads.
        catalog = i18n.load_catalog(i18n.resolve_language(code))

        def in_new_language(message: str) -> str:
            return catalog.get(message, message)

        if self._on_restart_requested is None:
            message = N_("The new language will apply the next time Plexible starts.")
            wx.MessageBox(in_new_language(message), "Plexible", wx.ICON_INFORMATION | wx.OK, parent=self)
            return
        question = N_("Plexible needs to restart to use the new language. Restart now?")
        answer = wx.MessageBox(in_new_language(question), "Plexible", wx.ICON_QUESTION | wx.YES_NO, parent=self)
        if answer == wx.YES:
            self._on_restart_requested()
            self.Close()
        else:
            self._set_status(in_new_language(N_("The new language will apply the next time Plexible starts.")))

    def _handle_toggle_dark_mode(self, event: wx.CommandEvent) -> None:
        """Toggle between light and dark UI themes without affecting NVDA accessibility."""
        dark = bool(event.IsChecked())
        self._config.set_ui_theme("dark" if dark else "light")
        self._apply_theme(dark)
        self._set_status(_("Dark mode enabled.") if dark else _("Dark mode disabled."))

    def _handle_toggle_auto_updates(self, event: wx.CommandEvent) -> None:
        enabled = bool(event.IsChecked())
        self._update_manager.set_auto_check_enabled(enabled)
        status = _("Automatic update checks enabled.") if enabled else _("Automatic update checks disabled.")
        self._set_status(status)

    def _initialise_account(self) -> None:
        try:
            account = self._auth.load_saved_account()
        except AuthError as exc:
            self._set_status(str(exc))
            self._auth.sign_out()
            self._update_menu_state()
            return

        if account:
            self._set_account(account)
        else:
            self._set_status(_("Sign in to begin."))
            self._update_menu_state()

    def _set_account(self, account: MyPlexAccount) -> None:
        self._account = account
        self._service = PlexService(account, self._config)
        self._set_status(_("Signed in as {username}. Loading servers…", username=account.username))
        self._update_menu_state()
        self._load_libraries_async()

    def _load_libraries_async(self, retry_count: int = 0) -> None:
        if not self._service or self._closing:
            return
        max_retries = 2

        def worker() -> None:
            try:
                server = self._service.ensure_server()
                libraries = list(self._service.libraries())
            except Exception as exc:  # noqa: BLE001
                if retry_count < max_retries and not self._closing:
                    print(f"[MainFrame] Library load failed (attempt {retry_count + 1}), retrying...: {exc}")
                    wx.CallAfter(lambda: self._set_status(
                        _(
                            "Connection failed — retrying ({attempt}/{total})…",
                            attempt=retry_count + 1,
                            total=max_retries,
                        )
                    ))
                    time.sleep(2)
                    wx.CallAfter(lambda: self._load_libraries_async(retry_count + 1))
                    return
                wx.CallAfter(self._handle_library_error, exc)
                return
            wx.CallAfter(self._handle_libraries_loaded, server, libraries,
                         self._service._last_connect_fallback if self._service else False)

        threading.Thread(target=worker, name="PlexLibraryLoader", daemon=True).start()
        if retry_count == 0:
            self._set_status(_("Connecting to Plex server…"))

    def _handle_library_error(self, exc: Exception) -> None:
        if self._closing:
            return
        self._nav_tree.clear()
        self._set_status(_("Failed to load libraries: {error}", error=exc))
        wx.MessageBox(
            _("Unable to load Plex libraries:\n{error}", error=exc),
            "Plexible",
            wx.ICON_ERROR | wx.OK,
            parent=self,
        )
        self._queues_panel.show_placeholders(_("Unable to load queues."), _("Unable to load queues."))

    def _handle_libraries_loaded(self, server: PlexServer, libraries: Iterable, fallback: bool = False) -> None:
        if self._closing:
            return
        try:
            self._nav_tree.populate(libraries)
        except RuntimeError:
            return
        library_count = sum(1 for _library in libraries)
        self._status_message = _("Connected to {server}", server=server.friendlyName)
        # Update status bar silently first, then announce with full message
        if hasattr(self, "_metadata_panel") and self._metadata_panel:
            self._metadata_panel.set_status_message(self._status_message)
        if self._status_bar is None:
            self._status_bar = self.GetStatusBar()
        if self._status_bar:
            self._status_bar.SetStatusText(self._status_message or "")

        self._refresh_watch_queues()
        self._flush_pending_progress()
        # Single delayed announcement so NVDA reads the ready message once
        if fallback:
            preferred = self._config.get_selected_server_name() or _("your preferred server")
            announce_msg = ngettext(
                "Could not reach {preferred}. Connected to {server} instead. {count} library loaded.",
                "Could not reach {preferred}. Connected to {server} instead. {count} libraries loaded.",
                library_count,
                preferred=preferred,
                server=server.friendlyName,
            )
        else:
            announce_msg = ngettext(
                "Ready. Connected to {server}. {count} library loaded.",
                "Ready. Connected to {server}. {count} libraries loaded.",
                library_count,
                server=server.friendlyName,
            )
        wx.CallLater(500, lambda: self._announce_screen_reader(announce_msg))

    def _load_children(self, plex_object: object):
        if not self._service:
            return []
        return self._service.list_children(plex_object)

    def _refresh_watch_queues(self) -> None:
        if not hasattr(self, "_queues_panel") or self._closing:
            return
        self._cancel_queue_refresh_timer()
        if not self._service:
            self._queues_panel.show_placeholders(_("Sign in to see your queue."), _("Sign in to see your queue."))
            return

        self._queues_panel.show_placeholders(_("Loading..."), _("Loading..."))

        def worker() -> None:
            try:
                continue_items, up_next_items = self._service.watch_queues()  # type: ignore[union-attr]
                continue_items = self._merge_pending_progress(continue_items)
            except Exception as exc:  # noqa: BLE001
                print(f"[Queues] Unable to load queues: {exc}")
                wx.CallAfter(self._apply_watch_queues, None, None)
                return
            wx.CallAfter(self._apply_watch_queues, continue_items, up_next_items)

        threading.Thread(target=worker, name="PlexQueueLoader", daemon=True).start()

    def _apply_watch_queues(
        self,
        continue_items: Optional[List[PlayableMedia]],
        up_next_items: Optional[List[PlayableMedia]],
    ) -> None:
        # Runs on the UI thread after the loader finishes; the frame may already be
        # gone by then, and touching the panel would hit a deleted C++ object.
        if self._closing or not hasattr(self, "_queues_panel"):
            return
        if continue_items is None or up_next_items is None:
            self._queues_panel.show_placeholders(
                _("Unable to load queues. Try again shortly."),
                _("Unable to load queues. Try again shortly."),
            )
            return
        self._queues_panel.update_lists(continue_items, up_next_items)

    def _handle_selection(self, plex_object: Optional[object]) -> None:
        self._selected_object = plex_object
        self._selected_playable = None
        self._selected_playlist = None
        self._active_playlist_key = None
        self._radio_options = []
        self._radio_pending_sessions.clear()
        self._radio_loading = False
        # Invalidate any radio lookup still in flight for the previous selection;
        # otherwise its result lands on this selection and offers the wrong station.
        self._radio_request_token += 1
        self._collection_request_token += 1
        collection_token = self._collection_request_token
        if isinstance(plex_object, PlexObject):
            queue_index = self._queue_index_for_object(plex_object)
            if queue_index is not None:
                self._queue_last_focus_index = queue_index
        if not self._service:
            self._metadata_panel.update_content(None, None)
            self._metadata_panel.set_radio_state(visible=False)
            return
        playlist_candidate: Optional[PlexObject] = None
        if isinstance(plex_object, PlexObject) and getattr(plex_object, "type", "") == "playlist":
            playlist_candidate = plex_object
        self._selected_playlist = playlist_candidate
        collection_candidate: Optional[PlexObject] = None
        collection_identifier: Optional[str] = None
        if isinstance(plex_object, PlexObject) and getattr(plex_object, "type", "") == "collection":
            collection_candidate = plex_object
            collection_identifier = self._navigation_identifier(collection_candidate)
        else:
            if hasattr(self, "_dismiss_collection_dialog"):
                self._dismiss_collection_dialog()
            else:
                # failsafe for older builds where the dialog helpers might not exist yet
                self._collection_dialog = None
                self._collection_dialog_identifier = None

        if isinstance(plex_object, MusicCategory):
            self._metadata_panel.update_content(plex_object, None)
            self._metadata_panel.set_radio_state(visible=False)
            self._metadata_panel.set_status_message(
                plex_object.summary or _("Expand this category to browse items.")
            )
            return
        if isinstance(plex_object, MusicAlphaBucket):
            self._metadata_panel.update_content(plex_object, None)
            self._metadata_panel.set_radio_state(visible=False)
            self._metadata_panel.set_status_message(
                plex_object.summary or _("Expand to see items.")
            )
            return
        if isinstance(plex_object, MusicRadioStation):
            station_option = self._radio_option_from_station(plex_object)
            self._radio_options = [station_option]
            self._metadata_panel.update_content(plex_object, None)
            self._metadata_panel.set_radio_state(
                visible=True,
                enabled=True,
                label=_("Play Radio."),
                loading=False,
                tooltip=_("Start this radio station."),
            )
            return
        if isinstance(plex_object, MusicRadioOption):
            option = plex_object.option
            description = option.description or option.label
            self._radio_options = [option]
            self._metadata_panel.set_status_message(description)
            self._metadata_panel.update_content(None, None)
            self._metadata_panel.set_radio_state(
                visible=True,
                enabled=True,
                label=option.label or _("Play Radio."),
                loading=False,
                tooltip=description,
            )
            return
        self._selected_playable = None
        self._metadata_panel.update_content(plex_object, None)
        # Load radio options, resolve playable, and load collection items
        # after the early-return checks above.
        should_load_radio = (
            playlist_candidate is None
            and isinstance(plex_object, PlexObject)
            and getattr(plex_object, "type", "") not in {"collection"}
            and self._service.is_music_context(plex_object)
        )
        if should_load_radio:
            self._load_radio_options_async(plex_object)
        else:
            self._metadata_panel.set_radio_state(visible=False)
        if plex_object and self._service and not isinstance(plex_object, LibrarySection):
            self._resolve_playable_async(cast(PlexObject, plex_object))
        if collection_candidate is not None and collection_identifier:
            dialog = self._ensure_collection_dialog(collection_candidate, collection_identifier)
            dialog.show_loading(_("Loading collection items..."))
            self._metadata_panel.set_status_message(_("Collection items appear in the collection window."))
            self._load_collection_items_async(collection_candidate, collection_token, collection_identifier)

    @staticmethod
    def _radio_option_from_station(station: MusicRadioStation) -> RadioOption:
        description = station.summary or _("{title} radio", title=station.title)
        return RadioOption(
            id=f"station:{station.identifier}",
            label=station.title,
            description=description,
            category=station.category or _("Stations"),
            action="station",
            data={"station": station},
        )

    def _load_radio_options_async(self, plex_object: Optional[object]) -> None:
        if not self._service:
            self._metadata_panel.set_radio_state(visible=False)
            return
        target_object = plex_object if isinstance(plex_object, PlexObject) else None
        if target_object is None:
            self._metadata_panel.set_radio_state(visible=False)
            return
        self._radio_loading = True
        self._radio_request_token += 1
        request_token = self._radio_request_token
        self._metadata_panel.set_radio_state(
            visible=True,
            enabled=False,
            label=_("Radio…"),
            loading=True,
            tooltip=_("Loading radio stations…"),
        )

        def worker(target: Optional[PlexObject], token: int) -> None:
            try:
                options = self._service.radio_options_for(target)
                error: Optional[str] = None
            except Exception as exc:  # noqa: BLE001
                print(f"[Radio] Unable to enumerate radio options: {exc}")
                options = []
                error = str(exc)
            wx.CallAfter(self._apply_radio_options, token, options, error)

        threading.Thread(
            target=worker,
            args=(target_object, request_token),
            name="PlexRadioOptions",
            daemon=True,
        ).start()

    def _resolve_playable_async(self, plex_object: PlexObject) -> None:
        self._playable_request_token += 1
        request_token = self._playable_request_token
        self._metadata_panel.set_status_message(_("Loading playback details..."))

        def worker(target: PlexObject, token: int) -> None:
            try:
                playable = self._service.resolve_playable(target)
                error: Optional[str] = None
            except Exception as exc:  # noqa: BLE001
                print(f"[Selection] Unable to resolve playable media: {exc}")
                playable = None
                error = str(exc)
            wx.CallAfter(self._apply_resolved_playable, target, playable, token, error)

        threading.Thread(
            target=worker,
            args=(plex_object, request_token),
            name="PlexPlayableResolver",
            daemon=True,
        ).start()

    def _apply_resolved_playable(
        self,
        plex_object: PlexObject,
        playable: Optional[PlayableMedia],
        token: int,
        error: Optional[str],
    ) -> None:
        if self._closing:
            return
        if token != self._playable_request_token:
            return
        if plex_object is not self._selected_object:
            return
        self._selected_playable = playable
        self._metadata_panel.update_content(plex_object, playable)
        if playable:
            return
        if error:
            self._metadata_panel.set_status_message(_("Unable to resolve playback: {error}", error=error))
        else:
            self._metadata_panel.set_status_message(_("Nothing available to play."))

    def _apply_radio_options(
        self,
        token: int,
        options: List[RadioOption],
        error: Optional[str],
    ) -> None:
        if self._closing:
            return
        if token != self._radio_request_token:
            return
        self._radio_loading = False
        self._radio_options = options
        if error:
            tooltip = _("Radio unavailable: {error}", error=error)
            self._metadata_panel.set_radio_state(
                visible=True,
                enabled=False,
                label=_("Radio…"),
                loading=False,
                tooltip=tooltip,
            )
            return
        if options:
            self._metadata_panel.set_radio_state(
                visible=True,
                enabled=True,
                label=_("Radio…"),
                loading=False,
                tooltip=_("Open the radio menu."),
            )
        else:
            self._metadata_panel.set_radio_state(visible=False)

    def _load_collection_items_async(self, collection: PlexObject, token: int, identifier: str) -> None:
        if not self._service:
            dialog = self._collection_dialog
            if dialog and identifier == self._collection_dialog_identifier:
                dialog.show_error(_("Sign in to view this collection."))
            self._metadata_panel.set_status_message(_("Sign in to view this collection."))
            return

        def worker(target: PlexObject, request_token: int, target_id: str) -> None:
            try:
                items = self._service.collection_items(target)
                error: Optional[str] = None
            except Exception as exc:  # noqa: BLE001
                print(f"[Collection] Unable to enumerate items for '{getattr(target, 'title', target)}': {exc}")
                items = []
                error = str(exc)
            wx.CallAfter(self._apply_collection_items, request_token, target_id, target, items, error)

        threading.Thread(
            target=worker,
            args=(collection, token, identifier),
            name="PlexCollectionItems",
            daemon=True,
        ).start()

    def _apply_collection_items(
        self,
        token: int,
        identifier: str,
        collection: PlexObject,
        items: List[PlexObject],
        error: Optional[str],
    ) -> None:
        if self._closing:
            return
        if token != self._collection_request_token:
            return
        if identifier != self._collection_dialog_identifier:
            return
        dialog = self._collection_dialog
        if not dialog:
            return
        dialog.set_collection_title(collection)
        title = getattr(collection, "title", None) or _("collection")
        if error:
            message = _("Unable to load '{title}': {error}", title=title, error=error)
            dialog.show_error(message)
            self._metadata_panel.set_status_message(message)
            return
        if not items:
            message = _("This collection does not contain any items.")
            dialog.show_error(message)
            self._metadata_panel.set_status_message(message)
            return
        dialog.show_items(items, self._collection_item_fields)
        summary = ngettext(
            "{count} item loaded in the collection window.",
            "{count} items loaded in the collection window.",
            len(items),
        )
        self._metadata_panel.set_status_message(summary)

    def _collection_item_fields(self, item: PlexObject) -> tuple[str, str, str]:
        media_type = getattr(item, "type", "") or ""
        title = getattr(item, "title", None)
        if not isinstance(title, str) or not title.strip():
            title = getattr(item, "name", None)
        if not isinstance(title, str) or not title.strip():
            title = str(item)
        clean_title = title.strip()

        type_label = _type_label(media_type) if media_type else _("Item")
        details_parts: List[str] = []

        if media_type == "episode":
            show = getattr(item, "grandparentTitle", None) or getattr(item, "show", None)
            season_raw = getattr(item, "parentIndex", None)
            episode_raw = getattr(item, "index", None)
            if isinstance(show, str) and show.strip():
                details_parts.append(show.strip())
            try:
                season_num = int(season_raw) if season_raw is not None else None
            except (TypeError, ValueError):
                season_num = None
            try:
                episode_num = int(episode_raw) if episode_raw is not None else None
            except (TypeError, ValueError):
                episode_num = None
            if season_num is not None and episode_num is not None:
                details_parts.append(f"S{season_num:02d}E{episode_num:02d}")
            elif episode_num is not None:
                details_parts.append(f"E{episode_num}")
        elif media_type == "movie":
            year = getattr(item, "year", None)
            try:
                year_int = int(year) if year else None
            except (TypeError, ValueError):
                year_int = None
            if year_int:
                details_parts.append(str(year_int))
        elif media_type == "season":
            series = getattr(item, "parentTitle", None) or getattr(item, "show", None)
            if isinstance(series, str) and series.strip():
                details_parts.append(series.strip())
            index_raw = getattr(item, "index", None)
            if isinstance(index_raw, int):
                details_parts.append(_("Season {number}", number=index_raw))
        elif media_type == "artist":
            genre = getattr(item, "genre", None)
            if isinstance(genre, str) and genre.strip():
                details_parts.append(genre.strip())
        elif media_type == "album":
            artist = getattr(item, "parentTitle", None) or getattr(item, "grandparentTitle", None)
            if isinstance(artist, str) and artist.strip():
                details_parts.append(artist.strip())
        elif media_type == "track":
            album = getattr(item, "parentTitle", None)
            artist = getattr(item, "grandparentTitle", None) or getattr(item, "parentTitle", None)
            if isinstance(album, str) and album.strip():
                details_parts.append(album.strip())
            if isinstance(artist, str) and artist.strip():
                details_parts.append(artist.strip())
        elif media_type == "collection":
            section = getattr(item, "librarySectionTitle", None)
            if isinstance(section, str) and section.strip():
                details_parts.append(section.strip())

        summary = getattr(item, "summary", None)
        if (not details_parts) and isinstance(summary, str) and summary.strip():
            trimmed = summary.strip()
            details_parts.append(trimmed if len(trimmed) <= 120 else f"{trimmed[:117]}...")

        details = " - ".join(details_parts)
        return clean_title, type_label or _("Item"), details

    def _ensure_collection_dialog(self, collection: PlexObject, identifier: str) -> CollectionItemsDialog:
        dialog = self._collection_dialog
        if dialog is None or not dialog:
            dialog = CollectionItemsDialog(
                self,
                on_play=self._play_collection_item,
                on_focus_request=self._focus_navigation_on_item,
                on_close=self._on_collection_dialog_closed,
            )
            self._collection_dialog = dialog
        self._collection_dialog_identifier = identifier
        dialog.set_collection_title(collection)
        if not dialog.IsShown():
            dialog.Show()
        try:
            dialog.Raise()
        except Exception:
            pass
        return dialog

    def _dismiss_collection_dialog(self) -> None:
        dialog = self._collection_dialog
        if not dialog:
            return
        self._collection_dialog = None
        self._collection_dialog_identifier = None
        try:
            dialog.Destroy()
        except Exception:
            try:
                dialog.Hide()
            except Exception:
                pass

    def _on_collection_dialog_closed(self) -> None:
        self._collection_dialog = None
        self._collection_dialog_identifier = None

    def _play_collection_item(self, item: PlexObject) -> None:
        if not self._service:
            wx.Bell()
            return
        try:
            playable = self._service.resolve_playable(item)
        except Exception as exc:  # noqa: BLE001
            print(f"[Collection] Unable to resolve playable item: {exc}")
            playable = None
        if not playable:
            wx.Bell()
            self._metadata_panel.set_status_message(_("Unable to play the selected collection item."))
            return
        self._selected_object = item
        self._selected_playable = playable
        self._metadata_panel.update_content(item, playable)
        self._metadata_panel.set_radio_state(visible=False)
        self._focus_navigation_on_item(item)
        self._start_playback(playable)


    def _handle_radio_action(self) -> None:
        if self._radio_loading:
            wx.Bell()
            return
        if not self._radio_options:
            wx.MessageBox(
                _("No radio stations are available for this selection."),
                "Plexible",
                wx.ICON_INFORMATION | wx.OK,
                parent=self,
            )
            return
        if len(self._radio_options) == 1:
            self._start_radio_option(self._radio_options[0])
            return
        dialog = RadioChooserDialog(self, self._radio_options)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                option = dialog.selected_option
                if option:
                    self._start_radio_option(option)
                else:
                    wx.Bell()
        finally:
            dialog.Destroy()

    def _start_radio_option(self, option: RadioOption) -> None:
        if not self._service:
            wx.Bell()
            return
        self._set_status(_("Starting {name}…", name=option.label))
        self._metadata_panel.set_radio_state(
            visible=True,
            enabled=False,
            label=_("Radio…"),
            loading=True,
            tooltip=_("Starting radio…"),
        )

        def worker(selected: RadioOption, token: int) -> None:
            try:
                media, session = self._service.start_radio_option(selected)
                error: Optional[str] = None
            except Exception as exc:  # noqa: BLE001
                print(f"[Radio] Unable to start {selected.label}: {exc}")
                media = None
                session = None
                error = str(exc)
            wx.CallAfter(self._finish_radio_start, token, selected, media, session, error)

        threading.Thread(
            target=worker,
            args=(option, self._radio_request_token),
            name="PlexRadioStart",
            daemon=True,
        ).start()

    def _finish_radio_start(
        self,
        token: int,
        option: RadioOption,
        media: Optional[PlayableMedia],
        session: Optional[RadioSession],
        error: Optional[str],
    ) -> None:
        if self._closing:
            return
        if token != self._radio_request_token:
            return
        self._metadata_panel.set_radio_state(
            visible=bool(self._radio_options),
            enabled=bool(self._radio_options),
            label=_("Radio…"),
            loading=False,
            tooltip=_("Open the radio menu.") if self._radio_options else None,
        )
        if error or not media or not session:
            message = error or _("Unknown error.")
            wx.MessageBox(
                _("Unable to start {name}:\n{error}", name=option.label, error=message),
                "Plexible",
                wx.ICON_ERROR | wx.OK,
                parent=self,
            )
            return
        self._start_playback(media, preserve_queue=True)
        self._register_radio_session(media, session)
        self._update_queue_display(session, media, focus=False, highlight_index=session.current_index)
        self._queue_manual_play(media)
        self._set_status(_("Streaming {title} ({description})", title=media.title, description=session.description))

    def _start_playlist_session(self, playlist: PlexObject) -> bool:
        if not self._service:
            wx.Bell()
            return False
        try:
            media, session = self._service.start_playlist(playlist)
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(
                _(
                    "Unable to start playlist '{title}':\n{error}",
                    title=getattr(playlist, "title", None) or _("Playlist"),
                    error=exc,
                ),
                "Plexible",
                wx.ICON_ERROR | wx.OK,
                parent=self,
            )
            return False
        self._playlist_launching = True
        try:
            self._start_playback(media, preserve_queue=True)
        finally:
            self._playlist_launching = False
        self._metadata_panel.update_content(media.item, media)
        self._metadata_panel.set_radio_state(visible=False)
        self._radio_options = []
        self._register_radio_session(media, session)
        self._update_queue_display(session, media, focus=False, highlight_index=session.current_index)
        self._queue_manual_play(media)
        self._selected_playable = media
        playlist_key = getattr(playlist, "ratingKey", None)
        self._active_playlist_key = str(playlist_key) if playlist_key is not None else None
        self._set_status(_("Streaming {title} (Playlist)", title=media.title))
        return True

    def _register_radio_session(
        self,
        media: PlayableMedia,
        session: RadioSession,
        *,
        pending_index: Optional[int] = None,
    ) -> None:
        rating_key = getattr(media.item, "ratingKey", None)
        if rating_key is None:
            return
        key = str(rating_key)
        if session.metadata is None:
            session.metadata = {}
        previous_key = session.metadata.get("current_rating_key")
        if previous_key and previous_key != key:
            self._radio_sessions.pop(str(previous_key), None)
        if pending_index is not None:
            session.current_index = pending_index
        session.metadata["current_rating_key"] = key
        self._radio_sessions[key] = session
        self._radio_pending_sessions.pop(key, None)

    def _update_queue_display(
        self,
        session: Optional[RadioSession],
        media: Optional[PlayableMedia],
        *,
        focus: bool = False,
        highlight_index: Optional[int] = None,
    ) -> None:
        if not hasattr(self, "_playback_panel"):
            return
        if session is None:
            self._active_queue_session = None
            self._nav_tree.set_queue_items([])
            self._playback_panel.clear_queue()
            self._queue_last_focus_index = -1
            return
        try:
            session.queue.refresh()
        except Exception:
            pass
        try:
            queue_items = list(session.queue.items)
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to read queue items: {exc}")
            self._active_queue_session = None
            self._nav_tree.set_queue_items([])
            self._playback_panel.clear_queue()
            self._queue_last_focus_index = -1
            return
        self._nav_tree.set_queue_items(queue_items)
        if not queue_items:
            self._active_queue_session = session
            self._queue_last_focus_index = -1
            self._playback_panel.clear_queue()
            return
        previous = self._active_queue_session is session
        if highlight_index is not None:
            highlight = highlight_index
        else:
            highlight = session.current_index
        if highlight < 0 or highlight >= len(queue_items):
            highlight = 0
        self._active_queue_session = session
        should_focus = focus or not previous
        if should_focus or self._nav_tree.selection_is_queue():
            self._nav_tree.highlight_queue_index(highlight, focus=should_focus)
        else:
            self._nav_tree.remember_queue_index(highlight)
        self._queue_last_focus_index = highlight
        self._playback_panel.set_queue_items(
            queue_items,
            current_index=highlight,
            focus=should_focus,
        )

    def _focus_queue_from_metadata(self) -> bool:
        index = self._queue_last_focus_index
        if index < 0:
            index = self._nav_tree.last_queue_index()
        return self._nav_tree.highlight_queue_index(index, focus=True)

    def _handle_queue_activate(self, index: int) -> None:
        session = self._active_queue_session
        if not session or not self._service:
            wx.Bell()
            return
        try:
            queue_items = list(session.queue.items)
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to load queue during activation: {exc}")
            wx.Bell()
            return
        if index < 0 or index >= len(queue_items):
            wx.Bell()
            return
        try:
            queue_item = self._service._ensure_queue_item_loaded(queue_items[index])
            playable = self._service.to_playable(queue_item)
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to resolve queue item {index}: {exc}")
            wx.Bell()
            return
        if not playable:
            wx.Bell()
            return
        session.current_index = index
        was_launching = self._playlist_launching
        self._playlist_launching = True
        try:
            self._start_playback(playable, preserve_queue=True)
        finally:
            self._playlist_launching = was_launching
        self._register_radio_session(playable, session, pending_index=index)
        self._metadata_panel.update_content(playable.item, playable)
        self._metadata_panel.set_radio_state(visible=False)
        self._queue_manual_play(playable)
        self._selected_playable = playable
        self._update_queue_display(session, playable, focus=True, highlight_index=index)

    def _handle_skip(self, direction: int) -> None:
        """Skip to the next or previous track in the active queue/radio session."""
        session = self._active_queue_session
        if not session or not self._service:
            wx.Bell()
            return
        try:
            queue_items = list(session.queue.items)
        except Exception:
            wx.Bell()
            return
        if not queue_items:
            wx.Bell()
            return
        if direction > 0:
            # Next: try next_radio_track first, then advance index
            try:
                result = self._service.next_radio_track(session)
            except Exception as exc:  # noqa: BLE001
                print(f"[Radio] Unable to advance to the next track: {exc}")
                result = None
            if result:
                next_media, next_index = result
                session.current_index = next_index
                was_launching = self._playlist_launching
                self._playlist_launching = True
                try:
                    self._start_playback(next_media, preserve_queue=True)
                finally:
                    self._playlist_launching = was_launching
                self._register_radio_session(next_media, session, pending_index=next_index)
                self._metadata_panel.update_content(next_media.item, next_media)
                self._queue_manual_play(next_media)
                self._selected_playable = next_media
                self._update_queue_display(session, next_media, focus=True, highlight_index=next_index)
                self._set_status(_("Streaming {title} ({description})", title=next_media.title, description=session.description))
                return
        elif direction < 0:
            # Previous: go back one index in the queue
            prev_index = max(0, session.current_index - 1)
            if prev_index != session.current_index and prev_index < len(queue_items):
                self._handle_queue_activate(prev_index)
                return
        wx.Bell()

    def _clear_radio_session_for_key(self, key: str) -> None:
        session = self._radio_sessions.pop(key, None)
        if not session:
            return
        if getattr(session, "kind", "") == "playlist":
            self._active_playlist_key = None
        if session.metadata:
            session.metadata.pop("current_rating_key", None)
        if session is self._active_queue_session:
            self._update_queue_display(None, None)
        for pending_key, (pending_session, _pending_index) in list(self._radio_pending_sessions.items()):
            if pending_session is session or pending_key == key:
                self._radio_pending_sessions.pop(pending_key, None)

    def _prime_radio_autoplay(self, media: PlayableMedia, source_key: str) -> Optional[str]:
        if not self._service:
            return None
        session = self._radio_sessions.get(source_key)
        if not session:
            return None
        try:
            result = self._service.next_radio_track(session)
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to fetch next radio track: {exc}")
            self._clear_radio_session_for_key(source_key)
            return None
        if not result:
            self._clear_radio_session_for_key(source_key)
            return None
        next_media, next_index = result
        next_key_raw = getattr(next_media.item, "ratingKey", None)
        if next_key_raw is None:
            return None
        next_key = str(next_key_raw)
        self._radio_pending_sessions[next_key] = (session, next_index)
        self._autoplay_sources[source_key] = next_key
        self._autoplay_candidates[next_key] = next_media
        self._config.remove_pending_progress(next_key)
        self._last_positions.pop(next_key, None)
        return next_key

    def _on_navigation_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code == wx.WXK_RIGHT:
            item = self._nav_tree.GetSelection()
            if item and item.IsOk():
                if not self._nav_tree.IsExpanded(item):
                    self._nav_tree.expand_with_focus(item)
                else:
                    child = self._nav_tree.first_real_child(item)
                    if child and child.IsOk():
                        self._nav_tree.SelectItem(child)
                        self._nav_tree.EnsureVisible(child)
                return
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            if self._nav_tree.selection_is_queue():
                index = self._nav_tree.selected_queue_index()
                if index is not None:
                    self._handle_queue_activate(index)
                    return
            if self._service and self._selected_object:
                if self._play_selected_object(self._selected_object):
                    return
        event.Skip()

    def _play_selected_object(self, plex_object: object) -> bool:
        if not self._service:
            return False
        if isinstance(plex_object, MusicCategory) or isinstance(plex_object, MusicAlphaBucket):
            item = self._nav_tree.GetSelection()
            if item and item.IsOk() and not self._nav_tree.IsExpanded(item):
                self._nav_tree.expand_with_focus(item)
            return False
        if isinstance(plex_object, MusicRadioStation):
            station_option = self._radio_option_from_station(plex_object)
            self._radio_options = [station_option]
            self._radio_loading = False
            self._start_radio_option(station_option)
            return True
        if isinstance(plex_object, MusicRadioOption):
            option = plex_object.option
            self._radio_options = [option]
            self._radio_loading = False
            self._start_radio_option(option)
            return True
        if isinstance(plex_object, PlexObject) and getattr(plex_object, "type", "") == "playlist":
            return self._start_playlist_session(cast(PlexObject, plex_object))
        playable: Optional[PlayableMedia] = None
        if plex_object is self._selected_object and self._selected_playable:
            playable = self._selected_playable
        if not playable and not isinstance(plex_object, LibrarySection):
            try:
                playable = self._service.resolve_playable(cast(PlexObject, plex_object))
            except Exception as exc:  # noqa: BLE001
                print(f"[Playback] Unable to resolve selected media: {exc}")
                playable = None
        if not playable:
            playable = self._first_playable_descendant(cast(PlexObject, plex_object))
        if not playable:
            return False
        self._start_playback(playable)
        self._queue_manual_play(playable)
        if plex_object is self._selected_object:
            self._selected_playable = playable
        return True

    def _start_playback(self, media: PlayableMedia, *, preserve_queue: bool = False) -> None:
        if not preserve_queue:
            self._active_queue_session = None
            self._nav_tree.set_queue_items([])
            self._queue_last_focus_index = -1
        if (
            not self._playlist_launching
            and self._selected_playlist is not None
            and self._selected_object is self._selected_playlist
        ):
            playlist_obj = self._selected_playlist
            if isinstance(playlist_obj, PlexObject):
                playlist_key = getattr(playlist_obj, "ratingKey", None)
                key_str = str(playlist_key) if playlist_key is not None else ""
                if not key_str or key_str != (self._active_playlist_key or ""):
                    if self._start_playlist_session(playlist_obj):
                        return
        rating_key = getattr(media.item, "ratingKey", None)
        if self._service and rating_key:
            pending = self._config.get_pending_entry(str(rating_key))
            if pending:
                try:
                    position = int(pending.get("position", 0))
                    duration = int(pending.get("duration", 0))
                    state = str(pending.get("state", "playing") or "playing")
                    if position > 0 and duration > 0:
                        print(f"[Progress] flushing before playback {rating_key} pos={position}")
                        applied_state, server_offset = self._service.update_progress_by_key(  # type: ignore[arg-type]
                            str(rating_key),
                            position,
                            duration,
                            state,
                        )
                        print(f"[Progress] pre-play flush applied state={applied_state} offset={server_offset}")
                        if abs(server_offset - position) <= 2000 and self._config.remove_pending_progress(
                            str(rating_key), expected=pending
                        ):
                            self._last_positions[str(rating_key)] = server_offset
                except Exception as exc:  # noqa: BLE001
                    print(f"[Progress] Unable to pre-flush {rating_key}: {exc}")
        self._schedule_progress_flush(5000)
        mode = self._playback_panel.play(media)
        if mode == "libvlc":
            player_desc = _("built-in LibVLC")
        elif mode == "vlc":
            player_desc = "VLC"
        elif mode == "mpc":
            player_desc = "MPC"
        elif mode == "none":
            player_desc = _("player (failed)")
        else:
            player_desc = _("player")
        self._set_status(
            _(
                "Streaming {title} ({media_type}) via {player}",
                title=media.title,
                media_type=_type_label(media.media_type),
                player=player_desc,
            )
        )

    def _handle_queue_selection(self, media: Optional[PlayableMedia]) -> None:
        if media:
            self._metadata_panel.update_content(media.item, media)
            self._load_radio_options_async(media.item)
        else:
            self._metadata_panel.update_content(None, None)
            self._metadata_panel.set_radio_state(visible=False)

    def _handle_sign_in(self, _event: wx.CommandEvent) -> None:
        if self._account:
            wx.MessageBox(_("You are already signed in."), "Plexible", wx.ICON_INFORMATION | wx.OK, parent=self)
            return
        def pin_ready(pin_code: str, oauth_url: str) -> None:
            wx.CallAfter(lambda: self._set_status(
                _("Plex PIN: {pin} — visit {url} to approve", pin=pin_code, url=oauth_url)
            ))

        def callback(success: bool, account: Optional[MyPlexAccount], error: Optional[Exception]) -> None:
            wx.CallAfter(self._on_auth_result, success, account, error)

        self._show_busy(
            _(
                "A browser window was opened for Plex authentication."
                "\nIf the browser did not open, check the status bar for a PIN code."
                "\nVisit https://plex.tv/link and enter the PIN to approve."
            )
        )
        self._auth.authenticate_with_browser(callback, on_pin_ready=pin_ready)

    def _on_auth_result(self, success: bool, account: Optional[MyPlexAccount], error: Optional[Exception]) -> None:
        if self._closing:
            return
        self._cancel_progress_flush_timer()
        self._flush_pending_progress_sync()
        self._clear_busy()
        if success and account:
            self._set_account(account)
        else:
            message = str(error) if error else _("Authentication was cancelled.")
            wx.MessageBox(
                _("Unable to authenticate with Plex:\n{error}", error=message),
                "Plexible",
                wx.ICON_ERROR | wx.OK,
                parent=self,
            )
            self._set_status(_("Sign in to begin."))
            self._update_menu_state()

    def _handle_sign_out(self, _event: wx.CommandEvent) -> None:
        if not self._account:
            return
        self._auth.sign_out()
        self._account = None
        self._service = None
        self._nav_tree.clear()
        self._metadata_panel.update_content(None, None)
        self._playback_panel.stop()
        self._cancel_queue_refresh_timer()
        self._reset_autoplay_state()
        # The collection window still lists items belonging to the account we just
        # left; acting on them would target the next account's server.
        self._dismiss_collection_dialog()
        self._last_queue_play_key = None
        self._queues_panel.show_placeholders(_("Sign in to see your queue."), _("Sign in to see your queue."))
        self._set_status(_("Signed out."))
        self._update_menu_state()
        self._refresh_player_menu()

    def _handle_refresh(self, _event: wx.CommandEvent) -> None:
        if not self._service:
            self._set_status(_("Sign in to refresh libraries."))
            return
        self._load_libraries_async()

    def _handle_search(self, _event: wx.CommandEvent) -> None:
        if not self._service:
            wx.MessageBox(
                _("Sign in to search your Plex libraries."),
                "Plexible",
                wx.ICON_INFORMATION | wx.OK,
                parent=self,
            )
            return
        entry = wx.TextEntryDialog(
            self,
            _("Enter a keyword to search across all libraries:"),
            _("Global Search"),
        )
        _localise_stock_buttons(entry)
        if entry.ShowModal() != wx.ID_OK:
            entry.Destroy()
            return
        query = entry.GetValue().strip()
        entry.Destroy()
        if not query:
            return

        results_dialog = SearchResultsDialog(self, query)

        def on_hit(received: Iterable[SearchHit]) -> None:
            entries: List[Tuple[SearchHit, str]] = []
            for hit in received:
                label = self._format_search_result(hit)
                entries.append((hit, label))
            if entries:
                results_dialog.add_hits(entries)

        def on_status(message: str) -> None:
            results_dialog.update_status(message)

        def worker() -> None:
            try:
                self._service.search_all_servers(
                    query,
                    limit_per_server=50,
                    on_hit=lambda hits: wx.CallAfter(on_hit, list(hits)),
                    on_status=lambda msg: wx.CallAfter(on_status, msg),
                )  # type: ignore[union-attr]
                errors = self._service.last_search_errors() if self._service else []
                wx.CallAfter(results_dialog.finish, errors)
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(results_dialog.finish_with_error, str(exc))

        threading.Thread(target=worker, name="PlexSearchWorker", daemon=True).start()
        result = results_dialog.ShowModal()
        selected_hit = results_dialog.selected_hit
        errors = results_dialog.errors
        results_dialog.Destroy()

        if result == wx.ID_OK and selected_hit:
            self._handle_search_hit(selected_hit)
        elif errors:
            self._set_status(
                ngettext(
                    "Search finished with {count} server issue.",
                    "Search finished with {count} server issues.",
                    len(errors),
                )
            )
        elif not results_dialog.has_hits:
            self._set_status(_("No results for '{query}'.", query=query))
        else:
            self._set_status(_("Search cancelled for '{query}'.", query=query))

    def _handle_search_hit(self, hit: SearchHit) -> None:
        if not self._service:
            return
        current_id = self._service.current_resource_id()  # type: ignore[union-attr]
        if current_id and hit.resource.clientIdentifier != current_id:
            self._connect_to_server(hit.resource, None, post_selection=hit)
            return
        self._open_search_hit(hit)

    def _handle_change_server(self, _event: wx.CommandEvent) -> None:
        if not self._service:
            wx.MessageBox(
                _("Sign in to select a Plex server."),
                "Plexible",
                wx.ICON_INFORMATION | wx.OK,
                parent=self,
            )
            return
        self._show_busy(_("Loading available servers..."))

        def worker() -> None:
            try:
                servers = self._service.refresh_servers()  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._handle_server_change_error, exc)
                return
            wx.CallAfter(self._prompt_server_selection, servers)

        threading.Thread(target=worker, name="PlexServerListWorker", daemon=True).start()

    def _display_search_result(self, item: PlexObject) -> None:
        self._handle_selection(item)
        if self._selected_playable:
            self._playback_panel.stop()
        self._refresh_player_menu()
        self._focus_navigation_on_item(item)

    def _focus_navigation_on_item(self, item: PlexObject) -> None:
        if not self._service or self._closing:
            return
        try:
            server = self._service.ensure_server()  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            print(f"[Navigation] Unable to reach the server to focus '{getattr(item, 'title', item)}': {exc}")
            return

        def worker() -> None:
            resolved = self._resolve_item_for_navigation(server, item)
            if not resolved:
                return
            lineage = self._build_navigation_lineage(server, resolved)
            if not lineage:
                return
            wx.CallAfter(self._apply_navigation_focus, lineage)

        threading.Thread(target=worker, name="PlexNavFocus", daemon=True).start()

    def _apply_navigation_focus(self, lineage: List[PlexObject]) -> None:
        if self._closing:
            return
        self._nav_tree.focus_path(lineage)

    def _resolve_item_for_navigation(self, server: PlexServer, item: PlexObject) -> Optional[PlexObject]:
        for attr in ("key", "ratingKey"):
            value = getattr(item, attr, None)
            if not value:
                continue
            try:
                return server.fetchItem(str(value))
            except Exception:
                continue
        return item

    def _build_navigation_lineage(self, server: PlexServer, item: PlexObject) -> List[PlexObject]:
        lineage: List[PlexObject] = []
        try:
            section = item.section()
        except Exception:
            section = None
        if isinstance(section, PlexObject):
            lineage.append(section)
        current = item
        ancestors: List[PlexObject] = []
        seen: Set[str] = set()
        while isinstance(current, PlexObject):
            identifier = self._navigation_identifier(current)
            if identifier in seen:
                break
            seen.add(identifier)
            ancestors.append(current)
            parent = self._resolve_parent_object(server, current)
            if not parent:
                break
            current = parent
        ancestors.reverse()
        for obj in ancestors:
            if not lineage or self._navigation_identifier(lineage[-1]) != self._navigation_identifier(obj):
                lineage.append(obj)
        return lineage

    def _resolve_parent_object(self, server: PlexServer, obj: PlexObject) -> Optional[PlexObject]:
        obj_type = getattr(obj, "type", "")
        attr_map = {
            "episode": ("season", "show"),
            "season": ("show",),
            "track": ("album", "artist"),
            "album": ("artist",),
            "clip": ("parent",),
            "photo": ("parent",),
            "collection": ("parent",),
        }
        for attr in attr_map.get(obj_type, ("parent",)):
            candidate = self._safe_lookup(obj, attr)
            resolved = self._ensure_object(server, candidate)
            if resolved:
                return resolved
        for attr in ("parentRatingKey", "grandparentRatingKey", "parentKey", "grandparentKey"):
            key = getattr(obj, attr, None)
            resolved = self._ensure_object(server, key)
            if resolved:
                return resolved
        return None

    def _safe_lookup(self, obj: PlexObject, attr: str) -> Optional[object]:
        try:
            value = getattr(obj, attr, None)
        except Exception:
            return None
        if callable(value):
            try:
                return value()
            except Exception:
                return None
        return value

    def _ensure_object(self, server: PlexServer, value: Optional[object]) -> Optional[PlexObject]:
        if isinstance(value, PlexObject):
            return value
        if value is None:
            return None
        try:
            return server.fetchItem(str(value))
        except Exception:
            return None

    def _queue_index_for_object(self, obj: PlexObject) -> Optional[int]:
        session = self._active_queue_session
        if not session:
            return None
        try:
            queue_items = list(session.queue.items)
        except Exception:
            return None
        target = self._navigation_identifier(obj)
        if not target:
            return None
        for idx, candidate in enumerate(queue_items):
            if self._navigation_identifier(candidate) == target:
                return idx
        return None

    def _navigation_identifier(self, obj: PlexObject) -> str:
        for attr in ("ratingKey", "key", "uuid", "guid"):
            try:
                value = getattr(obj, attr, None)
            except Exception:
                value = None
            if value:
                return str(value)
        return str(id(obj))

    def _tag_title_and_category(self, tag_obj: PlexObject) -> tuple[str, Optional[str]]:
        raw = getattr(tag_obj, "title", None)
        if not isinstance(raw, str) or not raw.strip():
            raw = getattr(tag_obj, "tag", None)
        if not isinstance(raw, str) or not raw.strip():
            raw = str(tag_obj)
        trimmed = raw.strip()
        if trimmed.startswith("<") and trimmed.endswith(">"):
            inner = trimmed[1:-1]
            parts = [segment for segment in inner.split(":") if segment]
            if len(parts) >= 2:
                category = parts[0]
                name = parts[-1]
                friendly_name = name.replace("-", " ").strip() or name
                friendly_category = category.replace("-", " ").strip()
                category_label = friendly_category.title() if friendly_category else None
                return friendly_name, category_label
        humanized = trimmed.replace("-", " ").strip()
        return humanized or raw, None

    def _format_search_result(self, hit: SearchHit) -> str:
        item = hit.item
        raw_title = getattr(item, "title", str(item))
        media_type = getattr(item, "type", "")
        if media_type == "tag":
            title, tag_category = self._tag_title_and_category(item)
        else:
            title = raw_title.replace("-", " ").strip() if isinstance(raw_title, str) else raw_title
            if isinstance(title, str) and not title:
                title = raw_title
            tag_category = None

        extras: List[str] = []
        for attr in ("grandparentTitle", "parentTitle", "artist", "show"):
            value = getattr(item, attr, None)
            if isinstance(value, str) and value:
                extras.append(value)
        if tag_category:
            extras.append(tag_category)
        section_title = getattr(item, "librarySectionTitle", "")
        server_label = self._format_server_label(hit.resource, None)
        parts = [str(title)]
        if media_type:
            parts.append(f"[{_type_label(media_type)}]")
        if extras:
            parts.append(f"({' / '.join(extras)})")
        if section_title:
            parts.append(f"- {section_title}")
        if server_label:
            parts.append(f"@ {server_label}")
        return " ".join(part for part in parts if part)

    def _open_search_hit(self, hit: SearchHit) -> None:
        item = hit.item
        item_type = getattr(item, "type", "")
        if item_type == "tag":
            self._show_tag_dialog(hit, item)
            return
        self._display_search_result(item)
        self._set_status(_("Showing result '{title}'.", title=getattr(item, "title", str(item))))

    def _show_tag_dialog(self, hit: Optional[SearchHit], tag: PlexObject) -> None:
        if not self._service:
            return
        resource = hit.resource if hit else self._service.current_resource()  # type: ignore[union-attr]
        try:
            server = hit.server if hit else self._service.ensure_server()
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(
                _("Unable to connect to the Plex server for this tag:\n{error}", error=exc),
                "Plexible",
                wx.ICON_ERROR | wx.OK,
                parent=self,
            )
            return
        if resource is None or server is None:
            wx.MessageBox(
                _("Tag items are unavailable because no Plex server is connected."),
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
            return
        title, category = self._tag_title_and_category(tag)
        heading = title if not category else f"{title} ({category})"
        self._metadata_panel.update_content(tag, None)
        self._metadata_panel.set_radio_state(visible=False)
        self._set_status(_("Loading tag '{name}'…", name=heading))
        dialog = SearchResultsDialog(self, _("Tag: {name}", name=heading))
        dialog.update_status(_("Loading tag items…"))

        def worker() -> None:
            batch: List[Tuple[SearchHit, str]] = []
            count = 0
            try:
                for child in self._service.iter_tag_items(tag, server=server, limit=None):  # type: ignore[union-attr]
                    sub_hit = SearchHit(resource=resource, server=server, item=child)
                    label = self._format_search_result(sub_hit)
                    batch.append((sub_hit, label))
                    count += 1
                    if len(batch) >= 25:
                        wx.CallAfter(dialog.add_hits, list(batch))
                        batch.clear()
                if batch:
                    wx.CallAfter(dialog.add_hits, list(batch))
                wx.CallAfter(dialog.finish, [])
                wx.CallAfter(
                    dialog.update_status,
                    ngettext(
                        "Loaded {count} item for tag '{name}'.",
                        "Loaded {count} items for tag '{name}'.",
                        count,
                        name=heading,
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(dialog.finish_with_error, _("Unable to load tag items: {error}", error=exc))

        threading.Thread(target=worker, name="PlexTagLoader", daemon=True).start()
        result = dialog.ShowModal()
        selected_hit = dialog.selected_hit
        errors = dialog.errors
        has_hits = dialog.has_hits
        dialog.Destroy()
        if result == wx.ID_OK and selected_hit:
            self._handle_search_hit(selected_hit)
            return
        if errors:
            self._set_status(
                ngettext(
                    "Tag '{name}' finished with {count} issue.",
                    "Tag '{name}' finished with {count} issues.",
                    len(errors),
                    name=heading,
                )
            )
        elif not has_hits:
            self._set_status(_("No videos found for tag '{name}'.", name=heading))
        else:
            self._set_status(_("Tag browsing cancelled for '{name}'.", name=heading))

    def _handle_server_change_error(self, exc: Exception) -> None:
        if self._closing:
            return
        self._clear_busy()
        wx.MessageBox(
            _("Unable to retrieve Plex servers:\n{error}", error=exc),
            "Plexible",
            wx.ICON_ERROR | wx.OK,
            parent=self,
        )

    def _prompt_server_selection(self, servers: List[MyPlexResource]) -> None:
        if self._closing:
            return
        self._clear_busy()
        if not servers:
            wx.MessageBox(
                _("No Plex servers were returned for this account."),
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
            return
        current_id = self._service.current_resource_id() if self._service else None  # type: ignore[union-attr]
        labels = [self._format_server_label(resource, current_id) for resource in servers]
        dialog = wx.SingleChoiceDialog(
            self,
            _("Select the Plex server to connect to:"),
            _("Change Server"),
            labels,
        )
        _localise_stock_buttons(dialog)
        if current_id:
            for index, resource in enumerate(servers):
                if resource.clientIdentifier == current_id:
                    dialog.SetSelection(index)
                    break
        if dialog.ShowModal() == wx.ID_OK:
            index = dialog.GetSelection()
            dialog.Destroy()
            self._connect_to_server(servers[index], labels[index])
        else:
            dialog.Destroy()

    def _connect_to_server(self, resource: MyPlexResource, label: Optional[str] = None, post_selection: Optional[SearchHit] = None) -> None:
        current_id = self._service.current_resource_id() if self._service else None  # type: ignore[union-attr]
        if label is None:
            label = self._format_server_label(resource, current_id)
        if current_id and resource.clientIdentifier == current_id:
            self._set_status(_("Already connected to {name}.", name=label))
            return
        self._pending_selection = post_selection
        self._show_busy(_("Connecting to {name}...", name=label))

        def worker() -> None:
            try:
                server = self._service.connect_resource(resource)  # type: ignore[union-attr]
                libraries = list(self._service.libraries())  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._handle_server_change_error, exc)
                return
            wx.CallAfter(self._apply_server_change, server, libraries)

        threading.Thread(target=worker, name="PlexServerConnectWorker", daemon=True).start()

    def _apply_server_change(self, server: PlexServer, libraries: Iterable[PlexObject]) -> None:
        if self._closing:
            return
        self._clear_busy()
        self._playback_panel.stop()
        self._nav_tree.clear()
        try:
            self._nav_tree.populate(libraries)
        except RuntimeError:
            pass
        self._metadata_panel.update_content(None, None)
        self._cancel_queue_refresh_timer()
        self._reset_autoplay_state()
        self._last_queue_play_key = None
        self._refresh_watch_queues()
        self._flush_pending_progress()
        self._set_status(_("Connected to {server}.", server=server.friendlyName))
        self._refresh_player_menu()
        if self._pending_selection:
            hit = self._pending_selection
            self._pending_selection = None
            try:
                refreshed = server.fetchItem(hit.item.key)
            except Exception:
                refreshed = hit.item
            try:
                refreshed_hit = SearchHit(resource=hit.resource, server=server, item=refreshed)
                self._open_search_hit(refreshed_hit)
            except Exception as exc:  # noqa: BLE001
                wx.MessageBox(
                    _("Unable to load the selected item after switching servers:\n{error}", error=exc),
                    "Plexible",
                    wx.ICON_ERROR | wx.OK,
                    parent=self,
                )

    def _update_menu_state(self) -> None:
        signed_in = getattr(self, "_account", None) is not None
        self._signin_item.Enable(not signed_in)
        self._signout_item.Enable(signed_in)
        self._refresh_item.Enable(signed_in)
        self._search_item.Enable(signed_in)
        self._change_server_item.Enable(signed_in)
        self._refresh_player_menu()

    def _handle_timeline_update(self, media: PlayableMedia, state: str, position: int, duration: int, sync: bool = False) -> None:
        if not self._service:
            return
        raw_rating_key = getattr(media.item, "ratingKey", None)
        rating_key = str(raw_rating_key) if raw_rating_key is not None else None
        bounded_duration = max(0, duration)
        if not bounded_duration:
            try:
                bounded_duration = int(getattr(media.item, "duration", 0) or 0)
            except Exception:
                bounded_duration = 0
        bounded_position = max(0, position)
        if bounded_duration and bounded_position > bounded_duration:
            bounded_position = bounded_duration
        if rating_key:
            last_known = self._last_positions.get(rating_key, 0)
            if bounded_position <= 0 and last_known > 0:
                bounded_position = last_known

        if state == "stopped" and bounded_position <= 0 and rating_key:
            pending_entry = self._config.get_pending_entry(rating_key)
            prior_known = max(
                self._last_positions.get(rating_key, 0),
                pending_entry.get("position", 0),
            )
            if prior_known > 0:
                bounded_position = prior_known
            else:
                self._last_positions.pop(rating_key, None)
                return

        progress_ratio = 0.0
        near_completion = False
        if bounded_duration > 0:
            progress_ratio = bounded_position / bounded_duration
            near_completion = progress_ratio >= 0.97

        if rating_key and near_completion:
            next_key = self._prime_autoplay_candidate(media)
            if state == "stopped" and next_key and not self._closing:
                self._schedule_autoplay(rating_key)
        elif state == "stopped" and rating_key and self._autoplay_pending_source == rating_key:
            self._cancel_autoplay_timer()
            self._autoplay_pending_source = None
        if state == "stopped" and rating_key and not near_completion:
            self._clear_radio_session_for_key(rating_key)

        # Only closing waits for the server here: the window must not go away
        # before the position is saved. Stop and seek used to wait as well, on
        # the GUI thread, which froze the window and silenced the screen reader
        # for up to ~8 s whenever the server was slow or unreachable.
        inline = self._closing
        if state == "stopped" and bounded_position > 0:
            # Playing the same item again right away must resume from here,
            # even before the server has answered.
            media.resume_offset = bounded_position

        def update() -> None:
            local_offset: Optional[int] = None
            applied_state = state
            try:
                print(
                    f"[Timeline] push state={state} key={rating_key} pos={bounded_position} "
                    f"dur={bounded_duration} closing={self._closing} sync={sync}"
                )
                applied_state, local_offset = self._service.update_timeline(
                    media,
                    state,
                    bounded_position,
                    bounded_duration,
                )  # type: ignore[union-attr]
                if (sync or self._closing) and rating_key is not None:
                    print(f"[Timeline] server viewOffset={local_offset} for key={rating_key}")
            except Exception as exc:  # noqa: BLE001
                print(f"[Timeline] Unable to update playback status: {exc}")
            finally:
                if rating_key:
                    if inline:
                        self._ingest_progress(rating_key, bounded_position, bounded_duration, applied_state, local_offset)
                    else:
                        wx.CallAfter(
                            self._ingest_progress,
                            rating_key,
                            bounded_position,
                            bounded_duration,
                            applied_state,
                            local_offset,
                        )
                if state == "stopped" and not inline:
                    # Refresh "Continue Watching" once the server has the new
                    # position, not before.
                    wx.CallAfter(self._refresh_watch_queues)

        if inline:
            update()
        else:
            def worker() -> None:
                try:
                    update()
                finally:
                    try:
                        self._timeline_threads.remove(threading.current_thread())
                    except ValueError:
                        pass

            thread = threading.Thread(target=worker, name="PlexTimelineUpdate", daemon=True)
            self._timeline_threads.append(thread)
            thread.start()

        if self._closing:
            if rating_key:
                if bounded_position > 0:
                    self._last_positions[rating_key] = bounded_position
                elif state == "stopped":
                    self._last_positions.pop(rating_key, None)
            return
        if state == "playing":
            if rating_key and rating_key != self._last_queue_play_key:
                self._last_queue_play_key = rating_key
                wx.CallAfter(self._schedule_queue_refresh, 750)
        elif state == "stopped":
            self._last_queue_play_key = None
            wx.CallAfter(self._schedule_queue_refresh, 2000)
        if rating_key:
            self._schedule_progress_flush(5000)
        if rating_key:
            if bounded_position > 0:
                self._last_positions[rating_key] = bounded_position
            elif state == "stopped":
                self._last_positions.pop(rating_key, None)

    def _prime_autoplay_candidate(self, media: PlayableMedia) -> Optional[str]:
        if not self._service:
            return None
        raw_key = getattr(media.item, "ratingKey", None)
        if raw_key is None:
            return None
        source_key = str(raw_key)
        existing = self._autoplay_sources.get(source_key)
        if source_key in self._radio_sessions:
            # Already primed: re-priming re-runs the queue lookup on every timeline
            # tick near the end of a track and orphans the previous candidate in
            # _autoplay_candidates / _radio_pending_sessions.
            if existing and existing in self._autoplay_candidates:
                return existing
            next_key = self._prime_radio_autoplay(media, source_key)
            if next_key:
                self._autoplay_flagged.add(source_key)
                return next_key
        if existing and existing in self._autoplay_candidates:
            return existing
        if source_key in self._autoplay_flagged and not existing:
            return None
        try:
            next_media = self._service.next_in_series(media.item)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            print(f"[Autoplay] Unable to evaluate next episode for {source_key}: {exc}")
            self._autoplay_flagged.add(source_key)
            return existing
        self._autoplay_flagged.add(source_key)
        if not next_media:
            return existing
        next_key_raw = getattr(next_media.item, "ratingKey", None)
        if next_key_raw is None:
            return existing
        next_key = str(next_key_raw)
        self._autoplay_sources[source_key] = next_key
        self._autoplay_candidates[next_key] = next_media
        self._config.remove_pending_progress(next_key)
        self._last_positions.pop(next_key, None)
        print(f"[Autoplay] Prepared next episode {next_key} from source {source_key}")
        return next_key

    def _cancel_autoplay_timer(self) -> None:
        if self._autoplay_timer:
            try:
                self._autoplay_timer.Stop()
            except Exception:
                pass
        self._autoplay_timer = None

    def _schedule_autoplay(self, source_key: str) -> None:
        if not source_key:
            return
        if self._autoplay_pending_source == source_key and self._autoplay_timer:
            return
        self._cancel_autoplay_timer()
        self._autoplay_pending_source = source_key
        self._autoplay_timer = wx.CallLater(900, self._autoplay_next, source_key)

    def _autoplay_next(self, source_key: str) -> None:
        self._autoplay_timer = None
        if self._closing or not self._service:
            return
        source_key_str = str(source_key)
        next_key = self._autoplay_sources.get(source_key_str)
        if not next_key:
            return
        media = self._autoplay_candidates.get(next_key)
        pending_entry = self._radio_pending_sessions.pop(next_key, None)
        pending_session: Optional[RadioSession] = None
        pending_index: Optional[int] = None
        if pending_entry:
            pending_session, pending_index = pending_entry
        if not media:
            try:
                item = self._service.fetch_item(next_key)  # type: ignore[arg-type]
            except Exception as exc:  # noqa: BLE001
                print(f"[Autoplay] Unable to fetch next episode {next_key}: {exc}")
                self._remove_autoplay_candidate(source_key=source_key_str, clear_flag=True)
                return
            media = self._service.to_playable(item)
            if not media:
                self._remove_autoplay_candidate(source_key=source_key_str, clear_flag=True)
                return
        state = self._playback_panel.get_state() if hasattr(self, "_playback_panel") else {}
        if state.get("has_media", False):
            print("[Autoplay] Player busy, skipping automatic play.")
            return
        print(f"[Autoplay] Starting next episode {next_key} (source {source_key_str})")
        self._autoplay_pending_source = None
        self._remove_autoplay_candidate(source_key=source_key_str, clear_flag=True)
        self._start_playback(media, preserve_queue=True)
        if pending_session:
            self._register_radio_session(media, pending_session, pending_index=pending_index)
            self._update_queue_display(
                pending_session,
                media,
                focus=False,
                highlight_index=pending_index if pending_index is not None else pending_session.current_index,
            )
        self._queue_manual_play(media)
        self._set_status(_("Auto-playing next episode: {title}", title=media.title))

    def _remove_autoplay_candidate(
        self,
        *,
        next_key: Optional[str] = None,
        source_key: Optional[str] = None,
        clear_flag: bool = False,
    ) -> None:
        if next_key is not None:
            key = str(next_key)
            self._autoplay_candidates.pop(key, None)
            self._radio_pending_sessions.pop(key, None)
            for src, mapped in list(self._autoplay_sources.items()):
                if mapped == key:
                    self._autoplay_sources.pop(src, None)
                    if clear_flag:
                        self._autoplay_flagged.discard(src)
        if source_key is not None:
            src_key = str(source_key)
            mapped = self._autoplay_sources.pop(src_key, None)
            if mapped:
                self._autoplay_candidates.pop(mapped, None)
                self._radio_pending_sessions.pop(mapped, None)
            if clear_flag:
                self._autoplay_flagged.discard(src_key)
            self._clear_radio_session_for_key(src_key)

    def _reset_autoplay_state(self) -> None:
        self._cancel_autoplay_timer()
        self._autoplay_sources.clear()
        self._autoplay_candidates.clear()
        self._autoplay_flagged.clear()
        self._autoplay_pending_source = None
        self._radio_sessions.clear()
        self._radio_pending_sessions.clear()
        self._active_playlist_key = None
        self._selected_playlist = None
        self._update_queue_display(None, None)

    def _queue_manual_play(self, media: PlayableMedia) -> None:
        if not self._service:
            return
        self._cancel_autoplay_timer()
        self._autoplay_pending_source = None
        raw_key = getattr(media.item, "ratingKey", None)
        rating_key = str(raw_key) if raw_key is not None else None
        if rating_key:
            self._remove_autoplay_candidate(next_key=rating_key, clear_flag=True)
            self._autoplay_flagged.discard(rating_key)
            self._last_queue_play_key = rating_key
            resume = int(getattr(media, "resume_offset", 0) or getattr(media.item, "viewOffset", 0) or 0)
            if resume > 0:
                self._last_positions[rating_key] = resume
                self._config.upsert_pending_progress(
                    rating_key,
                    resume,
                    int(getattr(media.item, "duration", 0) or 0),
                    "playing",
                )
            else:
                self._last_positions.pop(rating_key, None)
        wx.CallAfter(self._schedule_queue_refresh, 3000)
        self._schedule_progress_flush(5000)

    def _first_playable_descendant(self, plex_object: PlexObject, depth: int = 0, max_depth: int = 3) -> Optional[PlayableMedia]:
        if depth >= max_depth:
            return None
        try:
            children = list(self._service.list_children(plex_object)) if self._service else []
        except Exception:
            children = []
        for child in children:
            playable = self._service.to_playable(child) if self._service else None
            if playable:
                return playable
        for child in children:
            descendant = self._first_playable_descendant(child, depth + 1, max_depth)
            if descendant:
                return descendant
        return None

    def _on_playback_state_change(self, state: dict[str, object]) -> None:
        self._refresh_player_menu(state)

    def _refresh_player_menu(self, state: Optional[dict[str, object]] = None) -> None:
        if not hasattr(self, "_player_play_item"):
            return
        if state is None and hasattr(self, "_playback_panel"):
            state = self._playback_panel.get_state()
        state = state or {}
        can_play = bool(state.get("can_play", False))
        can_pause = bool(state.get("can_pause", False))
        can_stop = bool(state.get("can_stop", False))
        can_volume = bool(state.get("can_volume", False))
        can_seek = bool(state.get("can_seek", False))
        muted = bool(state.get("muted", False))
        self._player_play_item.Enable(can_play)
        self._player_pause_item.Enable(can_pause)
        self._player_stop_item.Enable(can_stop)
        self._player_rewind_item.Enable(can_seek)
        self._player_fast_forward_item.Enable(can_seek)
        self._player_volume_up_item.Enable(can_volume)
        self._player_volume_down_item.Enable(can_volume)
        self._player_mute_item.Enable(can_volume)
        self._player_fullscreen_item.Enable(can_volume)
        self._player_fullscreen_item.Check(bool(state.get("fullscreen", False)))
        self._player_mute_item.Check(muted)

    def _handle_player_play(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.resume():
            wx.Bell()
            self._refresh_player_menu()

    def _handle_player_pause(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.pause():
            wx.Bell()
            self._refresh_player_menu()

    def _handle_player_stop(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.stop_playback():
            wx.Bell()
        self._active_playlist_key = None
        self._refresh_player_menu()

    def _handle_player_prev_track(self, _event: wx.CommandEvent) -> None:
        self._handle_skip(-1)
        self._refresh_player_menu()

    def _handle_player_next_track(self, _event: wx.CommandEvent) -> None:
        self._handle_skip(1)
        self._refresh_player_menu()

    def _handle_player_rewind(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.seek_by(-SEEK_STEP_MS):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_fast_forward(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.seek_by(SEEK_STEP_MS):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_announce(self, _event: wx.CommandEvent) -> None:
        """Speak the current playback state via the status bar for screen readers."""
        state = self._playback_panel.get_state()
        if not state.get("has_media"):
            self._announce_screen_reader(_("Nothing is playing."), interrupt=True)
            return
        parts = []
        # What's playing
        media = self._playback_panel._current
        if media:
            parts.append(_("Playing: {title}", title=media.title))
        # Mode
        mode = state.get("mode", "")
        if mode == "libvlc" and not state.get("can_pause", False):
            parts.append(_("Paused"))
        elif mode == "libvlc":
            parts.append(_("Playing"))
        elif mode == "stopped":
            parts.append(_("Stopped"))
        # Volume
        parts.append(_("Volume {volume}%", volume=state.get("volume", 0)))
        if state.get("muted"):
            parts.append(_("Muted"))
        # Fullscreen
        if state.get("fullscreen"):
            parts.append(_("Fullscreen"))
        self._announce_screen_reader(". ".join(parts), interrupt=True)

    def _handle_player_volume_up(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.adjust_volume(5):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_volume_down(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.adjust_volume(-5):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_fullscreen(self, _event: wx.CommandEvent) -> None:
        if not self._playback_panel.set_fullscreen(self._player_fullscreen_item.IsChecked()):
            wx.Bell()
            self._player_fullscreen_item.Check(self._playback_panel.is_fullscreen())
        self._refresh_player_menu()

    def _handle_player_mute(self, event: wx.CommandEvent) -> None:
        desired = event.IsChecked()
        current_state = self._playback_panel.get_state()
        if desired != current_state.get("muted", False):
            if not self._playback_panel.toggle_mute():
                wx.Bell()
        self._refresh_player_menu()

    def _format_server_label(self, resource: MyPlexResource, current_id: Optional[str]) -> str:
        name = resource.name or resource.product or _("Plex Server")
        if resource.clientIdentifier == current_id:
            return _("{name} (current)", name=name)
        return name

    # ------------------------------------------------------------------ Accessibility

    def _apply_tab_order(self) -> None:
        """Pin Tab to a predictable left-to-right, top-to-bottom order.

        Without this, traversal follows child-creation order across three
        nested splitters, which does not match how the window reads.  Only
        real controls are listed — decorative and container panels are kept
        out of the cycle by DecorativePanel / TransparentContainer.
        """
        order = [
            self._nav_tree,
            self._metadata_panel.description_control(),
            self._metadata_panel.play_control(),
            self._metadata_panel.radio_control(),
            self._queues_panel.continue_control(),
            self._queues_panel.upnext_control(),
            *self._playback_panel.transport_controls(),
        ]
        previous: Optional[wx.Window] = None
        for control in order:
            if control is None:
                continue
            if previous is not None:
                try:
                    control.MoveAfterInTabOrder(previous)
                except Exception:
                    # Siblings only; a control in another parent keeps its own slot.
                    pass
            previous = control

    # ------------------------------------------------------------------ Theme

    _DARK_PANEL = wx.Colour(30, 30, 30)
    _DARK_TEXT = wx.Colour(212, 212, 212)
    _DARK_LIST = wx.Colour(37, 37, 38)
    _DARK_TREE = wx.Colour(37, 37, 38)

    def _apply_theme(self, dark: bool) -> None:
        """Recursively apply light or dark theme colours to all child widgets.

        Only sets background/text colours that are safe for screen readers:
        never touches SetName, focus order, or accessible roles.
        """
        bg = self._DARK_PANEL if dark else wx.NullColour
        fg = self._DARK_TEXT if dark else wx.NullColour
        list_bg = self._DARK_LIST if dark else wx.NullColour
        tree_bg = self._DARK_TREE if dark else wx.NullColour
        self._apply_theme_recurse(self, bg, fg, list_bg, tree_bg, dark)
        self.Refresh()

    @classmethod
    def _apply_theme_recurse(
        cls,
        win: wx.Window,
        bg: wx.Colour,
        fg: wx.Colour,
        list_bg: wx.Colour,
        tree_bg: wx.Colour,
        dark: bool,
    ) -> None:
        """Walk the widget tree and apply theme colours based on widget type."""
        if isinstance(win, (wx.Button, wx.ToggleButton)):
            pass  # Buttons keep their semantic colours (play/pause/stop)
        elif isinstance(win, wx.ListBox):
            win.SetBackgroundColour(list_bg)
            if fg.IsOk():
                win.SetForegroundColour(fg)
        elif isinstance(win, wx.TreeCtrl):
            win.SetBackgroundColour(tree_bg)
            if fg.IsOk():
                win.SetForegroundColour(fg)
        elif isinstance(win, (wx.TextCtrl, wx.StaticText)):
            if fg.IsOk():
                win.SetForegroundColour(fg)
        elif isinstance(win, (wx.Panel, wx.SplitterWindow, wx.Frame)):
            win.SetBackgroundColour(bg)
        # Recurse into children
        for child in win.GetChildren():
            cls._apply_theme_recurse(child, bg, fg, list_bg, tree_bg, dark)

    # ------------------------------------------------------------------ Status

    def _set_status(self, message: str) -> None:
        self._status_message = message
        # Worker threads post status updates through CallAfter; after the frame has
        # gone the panel and status bar are deleted C++ objects.
        if self._closing:
            return
        if hasattr(self, "_metadata_panel") and self._metadata_panel:
            self._metadata_panel.set_status_message(message)
        if self._status_bar is None:
            self._status_bar = self.GetStatusBar()
        if self._status_bar:
            self._status_bar.SetStatusText(message or "")
            # Color-code status bar background for quick visual state recognition.
            # Never change text color — only background tint, so NVDA/high-contrast is unaffected.
            dark = self._config.get_ui_theme() == "dark"
            # Messages are translated, so each tone lists its English and French cues.
            lower = (message or "").lower()
            if any(w in lower for w in _STATUS_SUCCESS_CUES):
                bg = wx.Colour(30, 60, 30) if dark else wx.Colour(232, 245, 233)
                self._status_bar.SetBackgroundColour(bg)
            elif any(w in lower for w in _STATUS_PROGRESS_CUES):
                bg = wx.Colour(60, 50, 20) if dark else wx.Colour(255, 248, 225)
                self._status_bar.SetBackgroundColour(bg)
            elif any(w in lower for w in _STATUS_ERROR_CUES):
                bg = wx.Colour(60, 25, 25) if dark else wx.Colour(255, 235, 238)
                self._status_bar.SetBackgroundColour(bg)
            else:
                self._status_bar.SetBackgroundColour(wx.NullColour)
            self._announce_screen_reader(message)

    def _announce_screen_reader(self, message: str, *, interrupt: bool = False) -> None:
        """Speak ``message`` with the screen reader.

        Status messages do not interrupt; answers to a key the user pressed do.
        """
        # Announcements are posted with CallLater and can outlive the frame.
        if self._closing or not message:
            return
        screen_reader.speak(message, interrupt=interrupt)

    def _show_busy(self, message: str) -> None:
        self._clear_busy()
        self._busy_info = wx.BusyInfo(message, parent=self)

    def _clear_busy(self) -> None:
        if self._busy_info:
            self._busy_info = None

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._closing = True
        if hasattr(self, "_playback_panel"):
            try:
                self._playback_panel.set_fullscreen(False)
            except Exception:
                pass
            try:
                self._playback_panel.force_timeline_snapshot()
            except Exception:
                pass
            try:
                self._playback_panel.stop()
            except Exception:
                pass
        self._clear_busy()
        self._cancel_queue_refresh_timer()
        self._cancel_autoplay_timer()
        self._cancel_progress_flush_timer()
        self._flush_pending_progress_sync()
        for thread in list(self._timeline_threads):
            try:
                thread.join(timeout=2.5)
            except Exception:
                pass
        self._timeline_threads.clear()
        event.Skip()

    def _schedule_queue_refresh(self, delay_ms: int = 2000) -> None:
        self._cancel_queue_refresh_timer()
        # Background flushes post this via CallAfter, which can land after the close
        # handler already cancelled the timers; re-arming here would fire the refresh
        # against destroyed panels.
        if self._closing:
            return
        self._queue_refresh_timer = wx.CallLater(delay_ms, self._refresh_watch_queues)

    def _cancel_queue_refresh_timer(self) -> None:
        if self._queue_refresh_timer:
            try:
                self._queue_refresh_timer.Stop()
            except Exception:
                pass
        self._queue_refresh_timer = None
        # Clean up finished timeline workers
        alive_threads: list[threading.Thread] = []
        for thread in self._timeline_threads:
            if thread.is_alive():
                alive_threads.append(thread)
        self._timeline_threads = alive_threads

    def _merge_pending_progress(self, continue_items: List[PlayableMedia]) -> List[PlayableMedia]:
        overrides: Dict[str, tuple[int, Optional[int]]] = {}
        pending = self._config.get_pending_progress()
        for rating_key, payload in pending.items():
            try:
                position = int(payload.get("position", 0))
                duration = int(payload.get("duration", 0))
            except Exception:
                continue
            if position > 0:
                overrides[rating_key] = (position, duration if duration > 0 else None)
        for rating_key, position in self._last_positions.items():
            if position <= 0:
                continue
            existing = overrides.get(rating_key)
            if existing is None or position > existing[0]:
                overrides[rating_key] = (position, existing[1] if existing else None)
        if not overrides or not self._service:
            return continue_items

        merged = list(continue_items)
        seen: Dict[str, int] = {}
        for index, media in enumerate(continue_items):
            key = str(getattr(media.item, "ratingKey", ""))
            if key:
                seen[key] = index
                override = overrides.get(key)
                if override and override[0] > 0:
                    media.resume_offset = override[0]
                    try:
                        setattr(media.item, "viewOffset", override[0])
                    except Exception:
                        pass
                    overrides.pop(key, None)

        for rating_key, (position, duration) in list(overrides.items()):
            if position <= 0:
                continue
            try:
                item = self._service.fetch_item(rating_key)  # type: ignore[arg-type]
            except Exception:
                continue
            playable = self._service.to_playable(item)
            if not playable:
                continue
            playable.resume_offset = position
            try:
                setattr(playable.item, "viewOffset", position)
            except Exception:
                pass
            key = str(getattr(playable.item, "ratingKey", ""))
            if key in seen:
                merged[seen[key]] = playable
            else:
                merged.insert(0, playable)
                seen[key] = 0
        for next_key, autoplay_media in list(self._autoplay_candidates.items()):
            key = str(next_key)
            if key in seen:
                self._remove_autoplay_candidate(next_key=key)
                continue
            merged.insert(0, autoplay_media)
            seen[key] = 0
        return merged

    def _ingest_progress(
        self,
        rating_key: Optional[str],
        position: int,
        duration: int,
        state: str,
        server_offset: Optional[int],
    ) -> None:
        if not rating_key or duration <= 0:
            return
        rating_key = str(rating_key)
        existing = self._config.get_pending_entry(rating_key)
        server_position = server_offset if server_offset and server_offset > 0 else None
        effective = max(0, position, server_position or 0)
        prior = max(self._last_positions.get(rating_key, 0), existing.get("position", 0))
        if prior and effective + 2000 < prior:
            return
        if effective <= 0:
            if state == "stopped":
                self._config.remove_pending_progress(rating_key, expected=existing)
                self._last_positions.pop(rating_key, None)
            return
        if effective >= int(duration * 0.97):
            self._config.remove_pending_progress(rating_key, expected=existing)
            self._last_positions.pop(rating_key, None)
            if not self._closing:
                wx.CallAfter(self._schedule_queue_refresh, 600)
            return
        if server_position is not None and server_position >= max(0, effective - 2000):
            self._config.remove_pending_progress(rating_key, expected=existing)
            self._last_positions[rating_key] = server_position
            return
        if prior and effective < 1000:
            return
        if effective < 1000:
            return
        if existing and abs(existing.get("position", 0) - effective) < 750:
            return
        self._config.upsert_pending_progress(rating_key, effective, duration, state)
        self._last_positions[rating_key] = effective
        print(f"[Progress] cached {rating_key} pos={effective} dur={duration} state={state} server={server_offset}")
        if not self._closing:
            wx.CallAfter(self._schedule_queue_refresh, 750)
            self._flush_pending_progress()
            self._schedule_progress_flush(5000)

    def _flush_pending_progress(self) -> None:
        if not self._service:
            return
        if self._progress_flush_active:
            return
        pending = self._config.get_pending_progress()
        if not pending:
            self._cancel_progress_flush_timer()
            return

        work_items = list(pending.items())
        # Claim the flush slot here rather than inside the worker: otherwise a second
        # scheduled flush — or the synchronous close-time flush, which spins on this
        # flag — starts before the thread has had a chance to set it.
        self._progress_flush_active = True

        def worker() -> None:
            try:
                changed = self._process_pending_progress(work_items)
                if changed:
                    wx.CallAfter(self._schedule_queue_refresh, 2000)
                if not self._config.get_pending_progress():
                    wx.CallAfter(self._cancel_progress_flush_timer)
            finally:
                # Never leave the flag set; _flush_pending_progress_sync would
                # otherwise block the close handler forever.
                self._progress_flush_active = False

        threading.Thread(target=worker, name="PlexProgressFlusher", daemon=True).start()
        self._schedule_progress_flush()

    def _flush_pending_progress_sync(self) -> None:
        # Bounded wait: this runs on the close path, so a wedged background flush
        # must not hang the shutdown indefinitely.
        deadline = time.monotonic() + 2.5
        while self._progress_flush_active and time.monotonic() < deadline:
            time.sleep(0.05)
        if self._progress_flush_active:
            # Leave the in-flight snapshot on disk instead of racing another flush.
            return
        if not self._service:
            return
        pending = self._config.get_pending_progress()
        if not pending:
            return
        work_items = list(pending.items())
        self._progress_flush_active = True
        try:
            changed = self._process_pending_progress(work_items)
        finally:
            self._progress_flush_active = False
        if changed:
            self._schedule_queue_refresh(2000)
        if not self._config.get_pending_progress():
            self._cancel_progress_flush_timer()

    def _process_pending_progress(self, items: list[tuple[str, dict[str, int]]]) -> bool:
        changed = False
        for rating_key, payload in items:
            try:
                position = int(payload.get("position", 0))
                duration = int(payload.get("duration", 0))
                state = str(payload.get("state", "stopped") or "stopped")
            except Exception:
                continue
            print(f"[Progress] flushing {rating_key} pos={position} dur={duration} state={state}")
            if position <= 0 or duration <= 0:
                self._config.remove_pending_progress(rating_key, expected=payload)
                continue
            try:
                applied_state, server_offset = self._service.update_progress_by_key(  # type: ignore[arg-type]
                    rating_key,
                    position,
                    duration,
                    state,
                )
                print(f"[Progress] server accepted {rating_key} new state={applied_state} offset={server_offset}")
                if server_offset > 0 and abs(server_offset - position) <= 2000 and self._config.remove_pending_progress(
                    rating_key, expected=payload
                ):
                    self._last_positions[str(rating_key)] = server_offset
                    changed = True
            except Exception as exc:  # noqa: BLE001
                print(f"[Timeline] Unable to flush cached progress for {rating_key}: {exc}")
        return changed

    def _schedule_progress_flush(self, delay_ms: int = 10000) -> None:
        self._cancel_progress_flush_timer()
        if self._closing:
            return
        self._progress_flush_timer = wx.CallLater(delay_ms, self._flush_pending_progress)

    def _cancel_progress_flush_timer(self) -> None:
        if self._progress_flush_timer:
            try:
                self._progress_flush_timer.Stop()
            except Exception:
                pass
        self._progress_flush_timer = None
