from __future__ import annotations

import threading
import time
from typing import Dict, Iterable, List, Optional, Set, Tuple, cast

import wx

from plexapi.base import PlexObject
from plexapi.library import LibrarySection
from plexapi.myplex import MyPlexAccount, MyPlexResource
from plexapi.server import PlexServer

from ..auth import AuthError, AuthManager
from ..config import ConfigStore
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


class SearchResultsDialog(wx.Dialog):
    """Dialog that streams search results as they arrive."""

    def __init__(self, parent: wx.Window, query: str) -> None:
        self._status_message = ""
        self._status_bar: Optional[wx.StatusBar] = None
        super().__init__(parent, title=f"Search: {query}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._hits: List[SearchHit] = []
        self._errors: List[str] = []
        self._finished = False
        self._closed = False

        heading = wx.StaticText(self, label=f"Results for '{query}':")
        self._list = wx.ListBox(self)
        self._status = wx.StaticText(self, label="Searching remote Plex servers…")

        self._open_button = wx.Button(self, wx.ID_OK, "Open")
        self._open_button.Enable(False)
        cancel_button = wx.Button(self, wx.ID_CANCEL, "Close")

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
        self._closed = True
        super().EndModal(retCode)

    def add_hit(self, hit: SearchHit, label: str) -> None:
        if self._closed:
            return
        self._hits.append(hit)
        self._list.Append(label)
        self._open_button.Enable(True)
        self._status.SetLabel(f"{len(self._hits)} result(s) so far…")

    def update_status(self, message: str) -> None:
        if self._closed:
            return
        self._status.SetLabel(message)

    def finish(self, errors: List[str]) -> None:
        if self._closed:
            return
        self._finished = True
        self._errors = errors
        if self._hits:
            self._status.SetLabel(f"Finished. {len(self._hits)} result(s).")
        else:
            self._status.SetLabel("Finished. No results found.")
            self._open_button.Enable(False)

    def finish_with_error(self, message: str) -> None:
        if self._closed:
            return
        self._finished = True
        self._errors = [message]
        self._status.SetLabel(f"Error: {message}")
        self._open_button.Enable(False)

    def _on_open(self, _: wx.CommandEvent) -> None:
        if self.selected_hit is not None:
            self.EndModal(wx.ID_OK)
        else:
            wx.Bell()

    def _on_cancel(self, _: wx.CommandEvent) -> None:
        self.EndModal(wx.ID_CANCEL)

    def _on_window_close(self, event: wx.CloseEvent) -> None:
        self.EndModal(wx.ID_CANCEL)

    def _on_activate(self, _: wx.CommandEvent) -> None:
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


class RadioChooserDialog(wx.Dialog):
    """Dialog for selecting a radio station option."""

    def __init__(self, parent: wx.Window, options: Iterable[RadioOption]) -> None:
        super().__init__(parent, title="Choose Radio Station", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._options: List[RadioOption] = list(options)

        heading = wx.StaticText(self, label="Select a radio station:")

        self._list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self._list.InsertColumn(0, "Station")
        self._list.InsertColumn(1, "Category")
        for index, option in enumerate(self._options):
            index_item = self._list.InsertItem(index, option.label)
            self._list.SetItem(index_item, 1, option.category)
        self._list.SetColumnWidth(0, 220)
        self._list.SetColumnWidth(1, 140)
        self._list.SetName("Radio Stations")

        desc_label = wx.StaticText(self, label="Description:")
        self._description = wx.TextCtrl(
            self,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_NO_VSCROLL | wx.BORDER_NONE,
        )
        self._description.SetMinSize((260, 110))
        self._description.SetName("Station Description")

        self._start_button = wx.Button(self, wx.ID_OK, "Start")
        self._start_button.Enable(False)
        cancel_button = wx.Button(self, wx.ID_CANCEL, "Cancel")

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

        self._list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self._list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_deselect)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        self._list.Bind(wx.EVT_CHAR_HOOK, self._on_list_char)
        self._start_button.Bind(wx.EVT_BUTTON, self._on_start)
        cancel_button.Bind(wx.EVT_BUTTON, lambda _: self.EndModal(wx.ID_CANCEL))

    @property
    def selected_option(self) -> Optional[RadioOption]:
        index = self._list.GetFirstSelected()
        if index == wx.NOT_FOUND:
            return None
        return self._options[index]

    def _update_description(self) -> None:
        option = self.selected_option
        if option:
            self._description.SetValue(option.description or "")
        else:
            self._description.SetValue("")

    def _on_select(self, _: wx.ListEvent) -> None:
        self._start_button.Enable(True)
        self._update_description()

    def _on_deselect(self, _: wx.ListEvent) -> None:
        if self._list.GetSelectedItemCount() == 0:
            self._start_button.Enable(False)
            self._update_description()

    def _on_activate(self, _: wx.ListEvent) -> None:
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

    def _on_start(self, _: wx.CommandEvent) -> None:
        if self.selected_option is not None:
            self.EndModal(wx.ID_OK)
        else:
            wx.Bell()
from .content_panel import MetadataPanel, QueuesPanel
from .navigation import NavigationTree
from .playback import PlaybackPanel, SEEK_STEP_MS


class MainFrame(wx.Frame):
    """Primary application window that orchestrates Plex authentication and playback."""

    _account: Optional[MyPlexAccount] = None
    _service: Optional[PlexService] = None

    def __init__(self, config: ConfigStore, auth_manager: AuthManager) -> None:
        super().__init__(None, title="Plexible", size=(1200, 800))
        self._config = config
        self._auth = auth_manager
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
        self._active_queue_session: Optional[RadioSession] = None
        self._queue_last_focus_index: int = -1
        self._reset_autoplay_state()

        self._build_menu()

        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        left_panel = wx.Panel(splitter)
        right_panel = wx.Panel(splitter)

        self._nav_tree = NavigationTree(
            left_panel,
            loader=self._load_children,
            on_selection=self._handle_selection,
        )
        self._nav_tree.Bind(wx.EVT_KEY_DOWN, self._on_navigation_key)
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(self._nav_tree, 1, wx.EXPAND)
        left_panel.SetSizer(left_sizer)

        right_splitter = wx.SplitterWindow(right_panel, style=wx.SP_LIVE_UPDATE)
        top_splitter = wx.SplitterWindow(right_splitter, style=wx.SP_LIVE_UPDATE)
        self._metadata_panel = MetadataPanel(
            top_splitter,
            on_play=self._start_playback,
            on_radio=self._handle_radio_action,
        )
        self._metadata_panel.set_status_message("Connecting...")
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
        )
        self._playback_panel.set_state_listener(self._on_playback_state_change)
        self._playback_panel.set_timeline_callback(self._handle_timeline_update)
        self._metadata_panel.set_queue_focus_handler(self._focus_queue_from_metadata)
        right_splitter.SplitHorizontally(top_splitter, self._playback_panel, sashPosition=320)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer.Add(right_splitter, 1, wx.EXPAND)
        right_panel.SetSizer(right_sizer)
        self._queues_panel.show_placeholders("Sign in to see your queue.", "Sign in to see your queue.")

        splitter.SplitVertically(left_panel, right_panel, sashPosition=320)
        splitter.SetMinimumPaneSize(180)
        right_splitter.SetMinimumPaneSize(220)

        self.CreateStatusBar()
        self._status_bar = self.GetStatusBar()
        self.CentreOnScreen()

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self._initialise_account()
        self._refresh_player_menu()

    def _build_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        self._signin_item = file_menu.Append(wx.ID_ANY, "Sign In...\tCtrl+I")
        self._signout_item = file_menu.Append(wx.ID_ANY, "Sign Out")
        file_menu.AppendSeparator()
        self._refresh_item = file_menu.Append(wx.ID_REFRESH, "Refresh Libraries\tF5")
        self._search_item = file_menu.Append(wx.ID_FIND, "Global Search...\tCtrl+F")
        self._change_server_item = file_menu.Append(wx.ID_ANY, "Change Server...")
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, "Exit\tCtrl+Q")
        menu_bar.Append(file_menu, "&File")

        player_menu = wx.Menu()
        self._player_play_item = player_menu.Append(wx.ID_ANY, "Play\tSpace")
        self._player_pause_item = player_menu.Append(wx.ID_ANY, "Pause\tShift+Space")
        self._player_stop_item = player_menu.Append(wx.ID_STOP, "Stop\tCtrl+S")
        self._player_rewind_item = player_menu.Append(wx.ID_ANY, "Rewind 10s\tCtrl+Left")
        self._player_fast_forward_item = player_menu.Append(wx.ID_ANY, "Fast Forward 10s\tCtrl+Right")
        player_menu.AppendSeparator()
        self._player_volume_up_item = player_menu.Append(wx.ID_ANY, "Volume Up\tCtrl+Up")
        self._player_volume_down_item = player_menu.Append(wx.ID_ANY, "Volume Down\tCtrl+Down")
        self._player_fullscreen_item = player_menu.AppendCheckItem(wx.ID_ANY, "Fullscreen\tF11")
        self._player_mute_item = player_menu.AppendCheckItem(wx.ID_ANY, "Mute\tCtrl+0")
        menu_bar.Append(player_menu, "&Player")
        self._player_menu = player_menu

        self.SetMenuBar(menu_bar)

        self.Bind(wx.EVT_MENU, self._handle_sign_in, self._signin_item)
        self.Bind(wx.EVT_MENU, self._handle_sign_out, self._signout_item)
        self.Bind(wx.EVT_MENU, self._handle_refresh, self._refresh_item)
        self.Bind(wx.EVT_MENU, self._handle_search, self._search_item)
        self.Bind(wx.EVT_MENU, self._handle_change_server, self._change_server_item)
        self.Bind(wx.EVT_MENU, lambda _: self.Close(True), exit_item)
        self.Bind(wx.EVT_MENU, self._handle_player_play, self._player_play_item)
        self.Bind(wx.EVT_MENU, self._handle_player_pause, self._player_pause_item)
        self.Bind(wx.EVT_MENU, self._handle_player_stop, self._player_stop_item)
        self.Bind(wx.EVT_MENU, self._handle_player_rewind, self._player_rewind_item)
        self.Bind(wx.EVT_MENU, self._handle_player_fast_forward, self._player_fast_forward_item)
        self.Bind(wx.EVT_MENU, self._handle_player_volume_up, self._player_volume_up_item)
        self.Bind(wx.EVT_MENU, self._handle_player_volume_down, self._player_volume_down_item)
        self.Bind(wx.EVT_MENU, self._handle_player_mute, self._player_mute_item)
        self.Bind(wx.EVT_MENU, self._handle_player_fullscreen, self._player_fullscreen_item)

        self._install_accelerators()
        self._update_menu_state()
        self._refresh_player_menu()

    def _install_accelerators(self) -> None:
        entries = [
            (wx.ACCEL_CTRL, ord("S"), self._player_stop_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_LEFT, self._player_rewind_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_RIGHT, self._player_fast_forward_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_UP, self._player_volume_up_item.GetId()),
            (wx.ACCEL_CTRL, wx.WXK_DOWN, self._player_volume_down_item.GetId()),
            (wx.ACCEL_CTRL, ord("0"), self._player_mute_item.GetId()),
        ]
        try:
            self.SetAcceleratorTable(wx.AcceleratorTable(entries))
        except Exception:
            pass

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
            self._set_status("Sign in to begin.")
            self._update_menu_state()

    def _set_account(self, account: MyPlexAccount) -> None:
        self._account = account
        self._service = PlexService(account, self._config)
        self._set_status(f"Signed in as {account.username}. Loading servers…")
        self._update_menu_state()
        self._load_libraries_async()

    def _load_libraries_async(self) -> None:
        if not self._service:
            return

        def worker() -> None:
            try:
                server = self._service.ensure_server()
                libraries = list(self._service.libraries())
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._handle_library_error, exc)
                return
            wx.CallAfter(self._handle_libraries_loaded, server, libraries)

        threading.Thread(target=worker, name="PlexLibraryLoader", daemon=True).start()
        self._set_status("Connecting to Plex server…")

    def _handle_library_error(self, exc: Exception) -> None:
        self._nav_tree.clear()
        self._set_status(f"Failed to load libraries: {exc}")
        wx.MessageBox(f"Unable to load Plex libraries:\n{exc}", "Plexible", wx.ICON_ERROR | wx.OK, parent=self)
        self._queues_panel.show_placeholders("Unable to load queues.", "Unable to load queues.")

    def _handle_libraries_loaded(self, server: PlexServer, libraries: Iterable) -> None:
        try:
            self._nav_tree.populate(libraries)
        except RuntimeError:
            return
        self._status_message = f"Connected to {server.friendlyName}"
        self._set_status(self._status_message)

        self._refresh_watch_queues()
        self._flush_pending_progress()

    def _load_children(self, plex_object: object):
        if not self._service:
            return []
        return self._service.list_children(plex_object)

    def _refresh_watch_queues(self) -> None:
        if not hasattr(self, "_queues_panel"):
            return
        self._cancel_queue_refresh_timer()
        if not self._service:
            self._queues_panel.show_placeholders("Sign in to see your queue.", "Sign in to see your queue.")
            return

        self._queues_panel.show_placeholders("Loading...", "Loading...")

        def worker() -> None:
            try:
                continue_items, up_next_items = self._service.watch_queues()  # type: ignore[union-attr]
                continue_items = self._merge_pending_progress(continue_items)
            except Exception as exc:  # noqa: BLE001
                print(f"[Queues] Unable to load queues: {exc}")
                wx.CallAfter(
                    self._queues_panel.show_placeholders,
                    "Unable to load queues. Try again shortly.",
                    "Unable to load queues. Try again shortly.",
                )
                return
            wx.CallAfter(self._queues_panel.update_lists, continue_items, up_next_items)

        threading.Thread(target=worker, name="PlexQueueLoader", daemon=True).start()

    def _handle_selection(self, plex_object: Optional[object]) -> None:
        self._selected_object = plex_object
        self._selected_playable = None
        self._selected_playlist = None
        self._active_playlist_key = None
        self._radio_options = []
        self._radio_pending_sessions.clear()
        self._radio_loading = False
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
        if isinstance(plex_object, MusicCategory):
            self._metadata_panel.update_content(plex_object, None)
            self._metadata_panel.set_radio_state(visible=False)
            return
        if isinstance(plex_object, MusicAlphaBucket):
            self._metadata_panel.update_content(plex_object, None)
            self._metadata_panel.set_radio_state(visible=False)
            return
        if isinstance(plex_object, MusicRadioStation):
            station_option = self._radio_option_from_station(plex_object)
            self._radio_options = [station_option]
            self._metadata_panel.update_content(plex_object, None)
            self._metadata_panel.set_radio_state(
                visible=True,
                enabled=True,
                label="Play Radio.",
                loading=False,
                tooltip="Start this radio station.",
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
                label=option.label or "Play Radio.",
                loading=False,
                tooltip=description,
            )
            return
        playable: Optional[PlayableMedia] = None
        if plex_object and self._service:
            if not isinstance(plex_object, LibrarySection):
                try:
                    playable = self._service.resolve_playable(plex_object)
                except Exception as exc:  # noqa: BLE001
                    print(f"[Selection] Unable to resolve playable media: {exc}")
                    playable = None
        self._selected_playable = playable
        self._metadata_panel.update_content(plex_object, playable)
        if playlist_candidate is None and plex_object is not None:
            self._load_radio_options_async(plex_object)
        else:
            self._metadata_panel.set_radio_state(visible=False)

    @staticmethod
    def _radio_option_from_station(station: MusicRadioStation) -> RadioOption:
        description = station.summary or f"{station.title} radio"
        return RadioOption(
            id=f"station:{station.identifier}",
            label=station.title,
            description=description,
            category=station.category or "Stations",
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
            label="Radio…",
            loading=True,
            tooltip="Loading radio stations…",
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

    def _apply_radio_options(
        self,
        token: int,
        options: List[RadioOption],
        error: Optional[str],
    ) -> None:
        if token != self._radio_request_token:
            return
        self._radio_loading = False
        self._radio_options = options
        if error:
            tooltip = f"Radio unavailable: {error}"
            self._metadata_panel.set_radio_state(
                visible=True,
                enabled=False,
                label="Radio…",
                loading=False,
                tooltip=tooltip,
            )
            return
        if options:
            self._metadata_panel.set_radio_state(
                visible=True,
                enabled=True,
                label="Radio…",
                loading=False,
                tooltip="Open the radio menu.",
            )
        else:
            self._metadata_panel.set_radio_state(visible=False)

    def _handle_radio_action(self) -> None:
        if self._radio_loading:
            wx.Bell()
            return
        if not self._radio_options:
            wx.MessageBox("No radio stations are available for this selection.", "Plexible", wx.ICON_INFORMATION | wx.OK, parent=self)
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
        self._set_status(f"Starting {option.label}…")
        self._metadata_panel.set_radio_state(
            visible=True,
            enabled=False,
            label="Radio…",
            loading=True,
            tooltip="Starting radio…",
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
        if token != self._radio_request_token:
            return
        self._metadata_panel.set_radio_state(
            visible=bool(self._radio_options),
            enabled=bool(self._radio_options),
            label="Radio…",
            loading=False,
            tooltip="Open the radio menu." if self._radio_options else None,
        )
        if error or not media or not session:
            message = error or "Unknown error."
            wx.MessageBox(
                f"Unable to start {option.label}:\n{message}",
                "Plexible",
                wx.ICON_ERROR | wx.OK,
                parent=self,
            )
            return
        self._start_playback(media, preserve_queue=True)
        self._register_radio_session(media, session)
        self._update_queue_display(session, media, focus=False, highlight_index=session.current_index)
        self._queue_manual_play(media)
        self._set_status(f"Streaming {media.title} ({session.description})")

    def _start_playlist_session(self, playlist: PlexObject) -> bool:
        if not self._service:
            wx.Bell()
            return False
        try:
            media, session = self._service.start_playlist(playlist)
        except Exception as exc:  # noqa: BLE001
            wx.MessageBox(
                f"Unable to start playlist '{getattr(playlist, 'title', 'Playlist')}':\n{exc}",
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
        self._set_status(f"Streaming {media.title} (Playlist)")
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
            self._queue_last_focus_index = -1
            return
        try:
            queue_items = list(session.queue.items)
        except Exception as exc:  # noqa: BLE001
            print(f"[Radio] Unable to read queue items: {exc}")
            self._active_queue_session = None
            self._nav_tree.set_queue_items([])
            self._queue_last_focus_index = -1
            return
        self._nav_tree.set_queue_items(queue_items)
        if not queue_items:
            self._active_queue_session = session
            self._queue_last_focus_index = -1
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
        queue_item = self._service._ensure_queue_item_loaded(queue_items[index])
        playable = self._service.to_playable(queue_item)
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
        for pending_key, (pending_session, _) in list(self._radio_pending_sessions.items()):
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
                        if server_offset > 0:
                            self._config.remove_pending_progress(str(rating_key))
                            self._last_positions[str(rating_key)] = server_offset
                except Exception as exc:  # noqa: BLE001
                    print(f"[Progress] Unable to pre-flush {rating_key}: {exc}")
        self._schedule_progress_flush(5000)
        mode = self._playback_panel.play(media)
        if mode == "libvlc":
            player_desc = "built-in LibVLC"
        elif mode == "vlc":
            player_desc = "VLC"
        elif mode == "mpc":
            player_desc = "MPC"
        elif mode == "none":
            player_desc = "player (failed)"
        else:
            player_desc = "player"
        self._set_status(f"Streaming {media.title} ({media.media_type}) via {player_desc}")

    def _handle_queue_selection(self, media: Optional[PlayableMedia]) -> None:
        if media:
            self._metadata_panel.update_content(media.item, media)
            self._load_radio_options_async(media.item)
        else:
            self._metadata_panel.update_content(None, None)
            self._metadata_panel.set_radio_state(visible=False)

    def _handle_sign_in(self, _: wx.CommandEvent) -> None:
        if self._account:
            wx.MessageBox("You are already signed in.", "Plexible", wx.ICON_INFORMATION | wx.OK, parent=self)
            return
        self._show_busy("A browser window was opened for Plex authentication.\nApprove the request to continue.")

        def callback(success: bool, account: Optional[MyPlexAccount], error: Optional[Exception]) -> None:
            wx.CallAfter(self._on_auth_result, success, account, error)

        self._auth.authenticate_with_browser(callback)

    def _on_auth_result(self, success: bool, account: Optional[MyPlexAccount], error: Optional[Exception]) -> None:
        self._cancel_progress_flush_timer()
        self._flush_pending_progress_sync()
        self._clear_busy()
        if success and account:
            self._set_account(account)
        else:
            message = str(error) if error else "Authentication was cancelled."
            wx.MessageBox(f"Unable to authenticate with Plex:\n{message}", "Plexible", wx.ICON_ERROR | wx.OK, parent=self)
            self._set_status("Sign in to begin.")
            self._update_menu_state()

    def _handle_sign_out(self, _: wx.CommandEvent) -> None:
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
        self._last_queue_play_key = None
        self._queues_panel.show_placeholders("Sign in to see your queue.", "Sign in to see your queue.")
        self._set_status("Signed out.")
        self._update_menu_state()
        self._refresh_player_menu()

    def _handle_refresh(self, _: wx.CommandEvent) -> None:
        if not self._service:
            self._set_status("Sign in to refresh libraries.")
            return
        self._load_libraries_async()

    def _handle_search(self, _: wx.CommandEvent) -> None:
        if not self._service:
            wx.MessageBox("Sign in to search your Plex libraries.", "Plexible", wx.ICON_INFORMATION | wx.OK, parent=self)
            return
        entry = wx.TextEntryDialog(self, "Enter a keyword to search across all libraries:", "Global Search")
        if entry.ShowModal() != wx.ID_OK:
            entry.Destroy()
            return
        query = entry.GetValue().strip()
        entry.Destroy()
        if not query:
            return

        results_dialog = SearchResultsDialog(self, query)

        def on_hit(hit: SearchHit) -> None:
            label = self._format_search_result(hit)
            results_dialog.add_hit(hit, label)

        def on_status(message: str) -> None:
            results_dialog.update_status(message)

        def worker() -> None:
            try:
                self._service.search_all_servers(
                    query,
                    limit_per_server=50,
                    on_hit=lambda hit: wx.CallAfter(on_hit, hit),
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
            wx.MessageBox(
                "Some servers could not be searched:\n- " + "\n- ".join(errors),
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
        elif not results_dialog.has_hits:
            self._set_status(f"No results for '{query}'.")
        else:
            self._set_status(f"Search cancelled for '{query}'.")

    def _handle_search_hit(self, hit: SearchHit) -> None:
        if not self._service:
            return
        current_id = self._service.current_resource_id()  # type: ignore[union-attr]
        if current_id and hit.resource.clientIdentifier != current_id:
            self._connect_to_server(hit.resource, None, post_selection=hit)
            return
        self._display_search_result(hit.item)
        self._set_status(f"Showing result '{getattr(hit.item, 'title', str(hit.item))}'.")

    def _handle_change_server(self, _: wx.CommandEvent) -> None:
        if not self._service:
            wx.MessageBox("Sign in to select a Plex server.", "Plexible", wx.ICON_INFORMATION | wx.OK, parent=self)
            return
        self._show_busy("Loading available servers...")

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
        if not self._service:
            return
        server = self._service.ensure_server()  # type: ignore[union-attr]

        def worker() -> None:
            resolved = self._resolve_item_for_navigation(server, item)
            if not resolved:
                return
            lineage = self._build_navigation_lineage(server, resolved)
            if not lineage:
                return
            wx.CallAfter(self._nav_tree.focus_path, lineage)

        threading.Thread(target=worker, name="PlexNavFocus", daemon=True).start()

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

    def _format_search_result(self, hit: SearchHit) -> str:
        item = hit.item
        title = getattr(item, "title", str(item))
        media_type = getattr(item, "type", "")
        extras = []
        for attr in ("grandparentTitle", "parentTitle", "artist", "show"):
            value = getattr(item, attr, None)
            if isinstance(value, str) and value:
                extras.append(value)
        section_title = getattr(item, "librarySectionTitle", "")
        server_label = self._format_server_label(hit.resource, None)
        parts = [title]
        if media_type:
            parts.append(f"[{media_type}]")
        if extras:
            parts.append(f"({' • '.join(extras)})")
        if section_title:
            parts.append(f"- {section_title}")
        if server_label:
            parts.append(f"@ {server_label}")
        return " ".join(part for part in parts if part)

    def _handle_server_change_error(self, exc: Exception) -> None:
        self._clear_busy()
        wx.MessageBox(f"Unable to retrieve Plex servers:\n{exc}", "Plexible", wx.ICON_ERROR | wx.OK, parent=self)

    def _prompt_server_selection(self, servers: List[MyPlexResource]) -> None:
        self._clear_busy()
        if not servers:
            wx.MessageBox("No Plex servers were returned for this account.", "Plexible", wx.ICON_WARNING | wx.OK, parent=self)
            return
        current_id = self._service.current_resource_id() if self._service else None  # type: ignore[union-attr]
        labels = [self._format_server_label(resource, current_id) for resource in servers]
        dialog = wx.SingleChoiceDialog(self, "Select the Plex server to connect to:", "Change Server", labels)
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
            self._set_status(f"Already connected to {label}.")
            return
        self._pending_selection = post_selection
        self._show_busy(f"Connecting to {label}...")

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
        self._set_status(f"Connected to {server.friendlyName}.")
        self._refresh_player_menu()
        if self._pending_selection:
            hit = self._pending_selection
            self._pending_selection = None
            try:
                refreshed = server.fetchItem(hit.item.key)
            except Exception:
                refreshed = hit.item
            try:
                self._display_search_result(refreshed)
                self._set_status(f"Showing result '{getattr(refreshed, 'title', str(refreshed))}'.")
            except Exception as exc:  # noqa: BLE001
                wx.MessageBox(
                    f"Unable to load the selected item after switching servers:\n{exc}",
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
                    if sync:
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

        if sync or self._closing:
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
            wx.CallAfter(self._refresh_watch_queues)
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
        if source_key in self._radio_sessions:
            next_key = self._prime_radio_autoplay(media, source_key)
            if next_key:
                self._autoplay_flagged.add(source_key)
                return next_key
        existing = self._autoplay_sources.get(source_key)
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
        self._set_status(f"Auto-playing next episode: {media.title}")

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

    def _handle_player_play(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.resume():
            wx.Bell()
            self._refresh_player_menu()

    def _handle_player_pause(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.pause():
            wx.Bell()
            self._refresh_player_menu()

    def _handle_player_stop(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.stop_playback():
            wx.Bell()
        self._active_playlist_key = None
        self._refresh_player_menu()

    def _handle_player_rewind(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.seek_by(-SEEK_STEP_MS):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_fast_forward(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.seek_by(SEEK_STEP_MS):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_volume_up(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.adjust_volume(5):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_volume_down(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.adjust_volume(-5):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_fullscreen(self, _: wx.CommandEvent) -> None:
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
        name = resource.name or resource.product or "Plex Server"
        suffix = ""
        if resource.clientIdentifier == current_id:
            suffix = " (current)"
        return f"{name}{suffix}"

    def _set_status(self, message: str) -> None:
        self._status_message = message
        if hasattr(self, "_metadata_panel") and self._metadata_panel:
            self._metadata_panel.set_status_message(message)
        if self._status_bar is None:
            self._status_bar = self.GetStatusBar()
        if self._status_bar:
            self._status_bar.SetStatusText(message or "")

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
        server_position = server_offset if server_offset and server_offset > 0 else None
        effective = max(0, position, server_position or 0)
        if effective <= 0:
            if state == "stopped":
                self._config.remove_pending_progress(rating_key)
                self._last_positions.pop(rating_key, None)
            return
        if effective >= int(duration * 0.97):
            self._config.remove_pending_progress(rating_key)
            self._last_positions.pop(rating_key, None)
            if not self._closing:
                wx.CallAfter(self._schedule_queue_refresh, 600)
            return
        if server_position is not None and server_position >= max(0, effective - 2000):
            self._config.remove_pending_progress(rating_key)
            self._last_positions[rating_key] = server_position
            return
        existing = self._config.get_pending_progress().get(rating_key)
        prior = max(
            self._last_positions.get(rating_key, 0),
            (existing or {}).get("position", 0),
            server_position or 0,
        )
        if prior and effective + 2000 < prior:
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

        def worker() -> None:
            self._progress_flush_active = True
            changed = self._process_pending_progress(work_items)
            if changed:
                wx.CallAfter(self._schedule_queue_refresh, 2000)
            if not self._config.get_pending_progress():
                wx.CallAfter(self._cancel_progress_flush_timer)
            self._progress_flush_active = False

        threading.Thread(target=worker, name="PlexProgressFlusher", daemon=True).start()
        self._schedule_progress_flush()

    def _flush_pending_progress_sync(self) -> None:
        while self._progress_flush_active:
            time.sleep(0.05)
        if not self._service:
            return
        pending = self._config.get_pending_progress()
        if not pending:
            return
        work_items = list(pending.items())
        self._progress_flush_active = True
        changed = self._process_pending_progress(work_items)
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
                self._config.remove_pending_progress(rating_key)
                continue
            try:
                applied_state, server_offset = self._service.update_progress_by_key(  # type: ignore[arg-type]
                    rating_key,
                    position,
                    duration,
                    state,
                )
                print(f"[Progress] server accepted {rating_key} new state={applied_state} offset={server_offset}")
                if server_offset > 0:
                    self._config.remove_pending_progress(rating_key)
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
