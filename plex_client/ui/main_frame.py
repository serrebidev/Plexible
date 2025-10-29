from __future__ import annotations

import threading
from typing import Iterable, List, Optional

import wx

from plexapi.base import PlexObject
from plexapi.myplex import MyPlexAccount, MyPlexResource
from plexapi.server import PlexServer

from ..auth import AuthError, AuthManager
from ..config import ConfigStore
from ..plex_service import PlayableMedia, PlexService, SearchHit


class SearchResultsDialog(wx.Dialog):
    """Dialog that streams search results as they arrive."""

    def __init__(self, parent: wx.Window, query: str) -> None:
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
from .content_panel import MetadataPanel
from .navigation import NavigationTree
from .playback import PlaybackPanel


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

        self._build_menu()

        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        left_panel = wx.Panel(splitter)
        right_panel = wx.Panel(splitter)

        self._nav_tree = NavigationTree(
            left_panel,
            loader=self._load_children,
            on_selection=self._handle_selection,
        )
        left_sizer = wx.BoxSizer(wx.VERTICAL)
        left_sizer.Add(self._nav_tree, 1, wx.EXPAND)
        left_panel.SetSizer(left_sizer)

        right_splitter = wx.SplitterWindow(right_panel, style=wx.SP_LIVE_UPDATE)
        self._metadata_panel = MetadataPanel(right_splitter, on_play=self._start_playback)
        self._playback_panel = PlaybackPanel(right_splitter, config)
        self._playback_panel.set_state_listener(self._on_playback_state_change)
        right_splitter.SplitHorizontally(self._metadata_panel, self._playback_panel, sashPosition=280)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        right_sizer.Add(right_splitter, 1, wx.EXPAND)
        right_panel.SetSizer(right_sizer)

        splitter.SplitVertically(left_panel, right_panel, sashPosition=320)
        splitter.SetMinimumPaneSize(180)
        right_splitter.SetMinimumPaneSize(180)

        self.CreateStatusBar()
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
        self._player_stop_item = player_menu.Append(wx.ID_STOP, "Stop\tCtrl+.")
        player_menu.AppendSeparator()
        self._player_volume_up_item = player_menu.Append(wx.ID_ANY, "Volume Up\tCtrl++")
        self._player_volume_down_item = player_menu.Append(wx.ID_ANY, "Volume Down\tCtrl+-")
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
        self.Bind(wx.EVT_MENU, self._handle_player_volume_up, self._player_volume_up_item)
        self.Bind(wx.EVT_MENU, self._handle_player_volume_down, self._player_volume_down_item)
        self.Bind(wx.EVT_MENU, self._handle_player_mute, self._player_mute_item)

        self._update_menu_state()
        self._refresh_player_menu()

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

    def _handle_libraries_loaded(self, server: PlexServer, libraries: Iterable) -> None:
        try:
            self._nav_tree.populate(libraries)
        except RuntimeError:
            return
        self._set_status(f"Connected to {server.friendlyName}.")

    def _load_children(self, plex_object: PlexObject):
        if not self._service:
            return []
        return self._service.list_children(plex_object)

    def _handle_selection(self, plex_object: Optional[PlexObject]) -> None:
        if not self._service:
            self._metadata_panel.update_content(None, None)
            return
        playable = self._service.to_playable(plex_object) if plex_object else None
        self._metadata_panel.update_content(plex_object, playable)

    def _start_playback(self, media: PlayableMedia) -> None:
        mode = self._playback_panel.play(media)
        if mode == "libvlc":
            player_desc = "built-in LibVLC"
        elif mode == "browser":
            player_desc = "embedded browser"
        elif mode == "vlc":
            player_desc = "VLC"
        elif mode == "mpc":
            player_desc = "MPC"
        else:
            player_desc = "player"
        self._set_status(f"Streaming {media.title} ({media.media_type}) via {player_desc}")

    def _handle_sign_in(self, _: wx.CommandEvent) -> None:
        if self._account:
            wx.MessageBox("You are already signed in.", "Plexible", wx.ICON_INFORMATION | wx.OK, parent=self)
            return
        self._show_busy("A browser window was opened for Plex authentication.\nApprove the request to continue.")

        def callback(success: bool, account: Optional[MyPlexAccount], error: Optional[Exception]) -> None:
            wx.CallAfter(self._on_auth_result, success, account, error)

        self._auth.authenticate_with_browser(callback)

    def _on_auth_result(self, success: bool, account: Optional[MyPlexAccount], error: Optional[Exception]) -> None:
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
        playable = self._service.to_playable(item) if self._service else None  # type: ignore[union-attr]
        self._metadata_panel.update_content(item, playable)
        if playable:
            self._playback_panel.stop()
        self._refresh_player_menu()

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
        self._pending_selection = post_selection
        self._show_busy(f"Connecting to {label}...")

        def worker() -> None:
            try:
                server = self._service.connect(identifier=resource.clientIdentifier)  # type: ignore[union-attr]
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
        muted = bool(state.get("muted", False))
        self._player_play_item.Enable(can_play)
        self._player_pause_item.Enable(can_pause)
        self._player_stop_item.Enable(can_stop)
        self._player_volume_up_item.Enable(can_volume)
        self._player_volume_down_item.Enable(can_volume)
        self._player_mute_item.Enable(can_volume)
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
        self._refresh_player_menu()

    def _handle_player_volume_up(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.adjust_volume(5):
            wx.Bell()
        self._refresh_player_menu()

    def _handle_player_volume_down(self, _: wx.CommandEvent) -> None:
        if not self._playback_panel.adjust_volume(-5):
            wx.Bell()
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
        status_bar = self.GetStatusBar()
        if status_bar:
            status_bar.SetStatusText(message)

    def _show_busy(self, message: str) -> None:
        self._clear_busy()
        self._busy_info = wx.BusyInfo(message, parent=self)

    def _clear_busy(self) -> None:
        if self._busy_info:
            self._busy_info = None

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._clear_busy()
        event.Skip()
