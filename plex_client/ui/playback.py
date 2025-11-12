from __future__ import annotations

import ctypes
import importlib
import os
import shutil
import zipfile
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Callable, Dict, List, Optional, Tuple

import requests
import wx

from ..config import ConfigStore
from ..plex_service import PlayableMedia

@dataclass
class QueueNodePayload:
    kind: str
    queue_index: Optional[int] = None


_LIBVLC_BOOTSTRAPPED = False
_PORTABLE_VLC_VERSION = "3.0.20"
_PORTABLE_VLC_URLS = {
    "win32": f"https://get.videolan.org/vlc/{_PORTABLE_VLC_VERSION}/win32/vlc-{_PORTABLE_VLC_VERSION}-win32.zip",
    "win64": f"https://get.videolan.org/vlc/{_PORTABLE_VLC_VERSION}/win64/vlc-{_PORTABLE_VLC_VERSION}-win64.zip",
}


def _portable_vlc_base_dir() -> Path:
    if not sys.platform.startswith("win"):
        return Path()
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Plexible" / "vlc"
    return Path.home() / ".plexible" / "vlc"


def _locate_extracted_libvlc(root: Path) -> Optional[Path]:
    for candidate in root.rglob("libvlc.dll"):
        return candidate.parent
    return None


def _ensure_portable_vlc(arch: str) -> Optional[Path]:
    if arch not in _PORTABLE_VLC_URLS:
        return None
    base_dir = _portable_vlc_base_dir()
    if not base_dir:
        return None
    target_dir = base_dir / arch / f"vlc-{_PORTABLE_VLC_VERSION}-{arch}"
    lib_dir = _locate_extracted_libvlc(target_dir) if target_dir.exists() else None
    if lib_dir and (lib_dir / "libvlc.dll").exists():
        return lib_dir
    url = _PORTABLE_VLC_URLS[arch]
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp_zip = target_dir / "vlc.zip"
    try:
        print(f"[LibVLC] Downloading portable VLC ({arch})...")
        with requests.get(url, stream=True, timeout=30) as resp:
            resp.raise_for_status()
            with tmp_zip.open("wb") as fp:
                shutil.copyfileobj(resp.raw, fp)
        with zipfile.ZipFile(tmp_zip) as archive:
            archive.extractall(target_dir)
        lib_dir = _locate_extracted_libvlc(target_dir)
        if lib_dir and (lib_dir / "libvlc.dll").exists():
            return lib_dir
    except Exception as exc:  # noqa: BLE001
        print(f"[LibVLC] Portable VLC download failed: {exc}")
    finally:
        if tmp_zip.exists():
            try:
                tmp_zip.unlink()
            except Exception:
                pass
    return None


def _ensure_dll_directory(path: Path) -> None:
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(path))
        except (FileNotFoundError, OSError):
            pass


def _bootstrap_libvlc_environment() -> None:
    global _LIBVLC_BOOTSTRAPPED
    if _LIBVLC_BOOTSTRAPPED:
        return
    existing = os.environ.get("PYTHON_VLC_MODULE_PATH")
    if existing:
        _ensure_dll_directory(Path(existing))
    else:
        candidates: list[Path] = []
        env_vlc = os.environ.get("VLC_PATH")
        if env_vlc:
            p = Path(env_vlc)
            candidates.append(p if p.is_dir() else p.parent)
        if os.name == "nt":
            for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
                base = os.environ.get(env_var)
                if base:
                    candidates.append(Path(base) / "VideoLAN" / "VLC")
        selected_dir: Optional[Path] = None
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.is_file():
                candidate = candidate.parent
            if candidate.is_dir() and (
                (candidate / "libvlc.dll").exists()
                or (candidate / "libvlccore.dll").exists()
            ):
                selected_dir = candidate
                break
        if selected_dir is None and os.name == "nt":
            arch = "win64" if struct.calcsize("P") == 8 else "win32"
            portable_dir = _ensure_portable_vlc(arch)
            if portable_dir and (portable_dir / "libvlc.dll").exists():
                selected_dir = portable_dir
        if selected_dir:
            os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(selected_dir))
            _ensure_dll_directory(selected_dir)
    _LIBVLC_BOOTSTRAPPED = True


requests.packages.urllib3.disable_warnings()
os.environ.setdefault("VLC_VERBOSE", "-1")

_bootstrap_libvlc_environment()
try:  # pragma: no cover - python-vlc is optional at import time
    import vlc  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    vlc = None


PlaybackState = dict[str, object]

SEEK_STEP_MS = 10000


class PlaybackPanel(wx.Panel):
    """Playback surface using LibVLC with automatic native fallbacks."""

    def __init__(
        self,
        parent: wx.Window,
        config: ConfigStore,
        *,
        on_queue_activate: Optional[Callable[[int], None]] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._current: Optional[PlayableMedia] = None
        self._direct_url: Optional[str] = None
        self._browser_url: Optional[str] = None
        self._mode: str = "stopped"
        self._is_paused: bool = False
        self._volume: int = 80
        self._muted: bool = False
        self._state_listener: Optional[Callable[[PlaybackState], None]] = None
        self._timeline_callback: Optional[Callable[[PlayableMedia, str, int, int, bool], None]] = None
        self._timeline_timer: Optional[wx.CallLater] = None
        self._last_timeline_state: Optional[str] = None
        self._last_timeline_position: int = 0
        self._resume_offset: int = 0
        self._resume_applied: bool = False
        self._seek_slider_duration: int = 0
        self._updating_seek_slider: bool = False
        self._seek_dragging: bool = False
        self._fullscreen: bool = False
        self._fullscreen_frame: Optional[wx.Frame] = None
        self._fullscreen_video_panel: Optional[wx.Panel] = None
        self._active_video_window: wx.Window

        self._vlc_instance: Optional["vlc.Instance"] = None
        self._vlc_player: Optional["vlc.MediaPlayer"] = None
        self._vlc_check: Optional[wx.CallLater] = None
        self._vlc_notified_missing = False
        self._vlc_path_cache: Optional[str] = None
        self._libvlc_env_prepared = False
        self._libvlc_warning_shown = False
        self._libvlc_candidates: list[str] = []
        self._libvlc_candidate_index = 0
        self._libvlc_active_source: Optional[str] = None
        self._libvlc_check_attempts = 0
        self._libvlc_max_start_checks = 4
        self._vlc_event_manager: Optional["vlc.EventManager"] = None
        self._vlc_error_callback: Optional[Callable[[object], None]] = None
        self._queue_activate_callback = on_queue_activate

        self._header = wx.StaticText(self, label="Nothing is playing.")
        header_font = self._header.GetFont()
        header_font.SetPointSize(header_font.GetPointSize() + 1)
        self._header.SetFont(header_font)

        header_row = wx.BoxSizer(wx.HORIZONTAL)
        header_row.Add(self._header, 1, wx.ALIGN_CENTER_VERTICAL)

        # Transport controls + volume
        controls_bar = wx.BoxSizer(wx.HORIZONTAL)
        self._play_btn = wx.Button(self, wx.ID_APPLY, label="Play")
        self._pause_btn = wx.Button(self, wx.ID_ANY, label="Pause")
        self._stop_btn = wx.Button(self, wx.ID_STOP, label="Stop")
        self._mute_btn = wx.ToggleButton(self, wx.ID_ANY, label="Mute")
        self._play_btn.Bind(wx.EVT_BUTTON, self._on_play_clicked)
        self._play_btn.Bind(wx.EVT_CHAR_HOOK, self._handle_play_char)
        self._pause_btn.Bind(wx.EVT_BUTTON, self._on_pause_clicked)
        self._pause_btn.Bind(wx.EVT_CHAR_HOOK, self._handle_pause_char)
        self._stop_btn.Bind(wx.EVT_BUTTON, self._on_stop_clicked)
        self._stop_btn.Bind(wx.EVT_CHAR_HOOK, self._handle_stop_char)
        self._mute_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_mute_toggled)
        self._mute_btn.Bind(wx.EVT_CHAR_HOOK, self._handle_mute_char)
        controls_bar.Add(self._play_btn, 0, wx.RIGHT, 4)
        controls_bar.Add(self._pause_btn, 0, wx.RIGHT, 4)
        controls_bar.Add(self._stop_btn, 0, wx.RIGHT, 12)
        controls_bar.Add(self._mute_btn, 0, wx.RIGHT, 6)
        controls_bar.Add(wx.StaticText(self, label="Volume:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._volume_slider = wx.Slider(self, value=self._volume, minValue=0, maxValue=100, size=(160, -1))
        self._volume_slider.Bind(wx.EVT_SLIDER, self._on_volume_slider)
        controls_bar.Add(self._volume_slider, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self._volume_label = wx.StaticText(self, label="")
        controls_bar.Add(self._volume_label, 0, wx.ALIGN_CENTER_VERTICAL)
        self._fullscreen_btn = wx.ToggleButton(self, wx.ID_ANY, label="Fullscreen")
        self._fullscreen_btn.Enable(False)
        self._fullscreen_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_fullscreen_toggled)
        self._fullscreen_btn.Bind(wx.EVT_CHAR_HOOK, self._handle_fullscreen_char)
        controls_bar.Add(self._fullscreen_btn, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        controls_bar.AddStretchSpacer()

        self._seek_slider = wx.Slider(self, value=0, minValue=0, maxValue=1, style=wx.SL_HORIZONTAL)
        self._seek_slider.SetToolTip("Playback position")
        self._seek_slider.Disable()
        self._seek_slider.Bind(wx.EVT_SCROLL_THUMBTRACK, self._on_seek_slider_track)
        self._seek_slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, self._on_seek_slider_release)
        self._seek_slider.Bind(wx.EVT_SCROLL_CHANGED, self._on_seek_slider_changed)
        self._seek_slider.Bind(wx.EVT_CHAR_HOOK, self._handle_panel_char)

        self._video_panel = wx.Panel(self)
        self._video_panel.SetBackgroundColour(wx.BLACK)
        self._active_video_window = self._video_panel

        self._queue_panel = wx.Panel(self)
        self._queue_panel.SetName("Queue Panel")
        queue_box = wx.StaticBoxSizer(wx.StaticBox(self._queue_panel, label="Current Queue"), wx.VERTICAL)
        self._queue_tree = wx.TreeCtrl(
            self._queue_panel,
            style=wx.TR_HAS_BUTTONS | wx.TR_HIDE_ROOT | wx.TR_SINGLE,
        )
        self._queue_tree.SetName("Current Queue")
        self._queue_tree.SetMinSize((0, 150))
        self._queue_root = self._queue_tree.AddRoot("Queue Root")
        self._queue_tree.Bind(wx.EVT_TREE_ITEM_ACTIVATED, self._on_queue_item_activated)
        self._queue_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_queue_item_selected)
        self._queue_tree.Bind(wx.EVT_CHAR_HOOK, self._handle_queue_char)
        queue_box.Add(self._queue_tree, 1, wx.EXPAND)
        self._queue_panel.SetSizer(queue_box)
        self._queue_panel.Hide()
        self._queue_items: list[object] = []
        self._queue_index_map: Dict[int, wx.TreeItemId] = {}
        self._queue_selected_index = -1
        self._queue_last_focus_index = 0
        self._queue_suppress_events = False

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(header_row, 0, wx.ALL | wx.EXPAND, 6)
        layout.Add(controls_bar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 6)
        layout.Add(self._seek_slider, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 6)
        layout.Add(self._video_panel, 1, wx.EXPAND | wx.ALL, 6)
        layout.Add(self._queue_panel, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.SetSizer(layout)

        self.Bind(wx.EVT_CHAR_HOOK, self._handle_panel_char)
        self._video_panel.Bind(wx.EVT_CHAR_HOOK, self._handle_panel_char)

        self._update_controls_enabled()
        self._update_volume_controls()
        self._reset_seek_slider()
        self.Bind(wx.EVT_WINDOW_DESTROY, self._on_destroy)
        self._notify_state()

    # ------------------------------------------------------------------ Public API

    def set_state_listener(self, listener: Optional[Callable[[PlaybackState], None]]) -> None:
        self._state_listener = listener
        self._notify_state()

    def get_state(self) -> PlaybackState:
        return {
            "mode": self._mode,
            "has_media": self._current is not None,
            "can_play": self._can_control_transport() and self._is_paused,
            "can_pause": self._can_control_transport() and not self._is_paused,
            "can_stop": self._mode != "stopped" or self._current is not None,
            "can_volume": self._volume_control_available(),
            "can_seek": self._can_control_transport(),
            "muted": self._muted,
            "volume": self._volume,
            "fullscreen": self._fullscreen,
        }

    def play(self, media: PlayableMedia) -> str:
        """Play the provided media using LibVLC with automatic fallbacks."""
        if self._current:
            snapshot_pos = self._current_position()
            snapshot_dur = self._current_duration()
            if snapshot_dur > 0:
                self._notify_timeline_state("stopped", snapshot_pos, snapshot_dur, sync=True)
        self._halt_current_playback()

        self._current = media
        self._direct_url = media.stream_url
        self._browser_url = media.browser_url or media.stream_url
        self._is_paused = False
        self._resume_offset = max(0, int(getattr(media, "resume_offset", 0) or 0))
        self._resume_applied = self._resume_offset == 0

        print(
            "[Playback] Requested stream -> "
            f"direct={self._direct_url} fallback={self._browser_url}"
        )

        mode = self._play_with_libvlc()
        if mode == "libvlc":
            self._set_mode(mode)
            self._handle_playback_start(mode)
            return mode

        self._header.SetLabel("Unable to start playback for this item.")
        wx.MessageBox(
            "Plexible could not start LibVLC playback for this item.",
            "Plexible",
            wx.ICON_WARNING | wx.OK,
            parent=self,
        )
        self._set_mode("stopped")
        self._notify_timeline_reset()
        self._current = None
        self._direct_url = None
        self._browser_url = None
        return "none"

    def set_queue_items(
        self,
        items: list[object],
        current_index: int = 0,
        *,
        focus: bool = False,
    ) -> None:
        """Populate the queue tree with grouped entries."""
        self._queue_items = list(items)
        self._queue_index_map.clear()
        if not self._queue_items:
            self.clear_queue()
            return

        self._queue_suppress_events = True
        self._queue_tree.Freeze()
        try:
            self._queue_tree.DeleteChildren(self._queue_root)
            parent_cache: Dict[Tuple[str, ...], wx.TreeItemId] = {}
            for idx, plex_item in enumerate(self._queue_items):
                path = self._queue_path_for_item(plex_item, idx)
                if not path:
                    path = [f"{idx + 1:02d}. Item"]
                parent = self._queue_root
                prefix: list[str] = []
                for depth, segment in enumerate(path):
                    prefix.append(segment)
                    key = tuple(prefix)
                    node = parent_cache.get(key)
                    is_leaf = depth == len(path) - 1
                    if node is None:
                        payload = QueueNodePayload("item" if is_leaf else "group", idx if is_leaf else None)
                        node = self._queue_tree.AppendItem(parent, segment, data=payload)
                        parent_cache[key] = node
                        if not is_leaf:
                            self._queue_tree.SetItemBold(node, True)
                    elif is_leaf:
                        payload = self._queue_payload(node)
                        if payload:
                            payload.queue_index = idx
                    parent = node
                leaf_key = tuple(path)
                leaf = parent_cache.get(leaf_key)
                if leaf:
                    self._queue_index_map[idx] = leaf
        finally:
            self._queue_tree.Thaw()
            self._queue_suppress_events = False

        if not self._queue_panel.IsShown():
            self._queue_panel.Show()
            sizer = self.GetSizer()
            if sizer:
                sizer.Layout()

        highlight = current_index if 0 <= current_index < len(self._queue_items) else -1
        if (
            not focus
            and 0 <= self._queue_selected_index < len(self._queue_items)
        ):
            highlight = self._queue_selected_index
        elif not focus and self._queue_last_focus_index >= 0:
            highlight = min(self._queue_last_focus_index, len(self._queue_items) - 1)
        if highlight < 0:
            highlight = 0

        if focus:
            self.focus_queue(highlight)
        else:
            self._highlight_queue_index(highlight)

    def clear_queue(self) -> None:
        """Hide and clear the queue tree."""
        self._queue_items.clear()
        self._queue_index_map.clear()
        if hasattr(self, "_queue_tree"):
            self._queue_tree.DeleteChildren(self._queue_root)
        self._queue_selected_index = -1
        self._queue_last_focus_index = 0
        if self._queue_panel.IsShown():
            self._queue_panel.Hide()
            sizer = self.GetSizer()
            if sizer:
                sizer.Layout()

    def highlight_queue_index(self, index: int) -> None:
        """Update the selected item without rebuilding the tree."""
        if not self._queue_items or not self._queue_panel.IsShown():
            return
        self._highlight_queue_index(index)

    def focus_queue(self, index: Optional[int] = None) -> bool:
        """Move focus to the queue tree for keyboard navigation."""
        if not self._queue_items or not self._queue_panel.IsShown():
            return False
        target = index if index is not None else self._queue_selected_index
        if target is None or target < 0 or target >= len(self._queue_items):
            fallback = self._queue_last_focus_index
            if 0 <= fallback < len(self._queue_items):
                target = fallback
            else:
                target = 0
        if self._highlight_queue_index(target):
            self._queue_tree.SetFocus()
            return True
        return False

    def focus_queue_from_metadata(self) -> bool:
        """Handle metadata panel requests to move straight into the queue tree."""
        if not self._queue_items or not self._queue_panel.IsShown():
            return False
        return self.focus_queue(self._queue_last_focus_index)

    def _on_queue_item_activated(self, event: wx.TreeEvent) -> None:
        item = event.GetItem()
        payload = self._queue_payload(item)
        if payload and payload.queue_index is not None and self._queue_activate_callback:
            self._queue_activate_callback(payload.queue_index)
            return
        event.Skip()

    def _handle_queue_char(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            item = self._queue_tree.GetSelection()
            payload = self._queue_payload(item)
            if payload and payload.queue_index is not None and self._queue_activate_callback:
                self._queue_activate_callback(payload.queue_index)
                return
        event.Skip()

    def _on_queue_item_selected(self, event: wx.TreeEvent) -> None:
        if self._queue_suppress_events:
            event.Skip()
            return
        item = event.GetItem()
        payload = self._queue_payload(item)
        if payload and payload.queue_index is not None:
            self._queue_selected_index = payload.queue_index
            self._queue_last_focus_index = payload.queue_index
        else:
            self._queue_selected_index = -1
        event.Skip()

    def _highlight_queue_index(self, index: int) -> bool:
        if not self._queue_items or not self._queue_panel.IsShown():
            return False
        item = self._queue_index_map.get(index)
        if not item or not item.IsOk():
            return False
        self._queue_suppress_events = True
        try:
            self._queue_tree.UnselectAll()
            self._expand_to_item(item)
            self._queue_tree.SelectItem(item)
            self._queue_tree.EnsureVisible(item)
        finally:
            self._queue_suppress_events = False
        self._queue_selected_index = index
        self._queue_last_focus_index = index
        return True

    def _queue_payload(self, item: wx.TreeItemId) -> Optional[QueueNodePayload]:
        if not item or not item.IsOk():
            return None
        data = self._queue_tree.GetItemData(item)
        return data if isinstance(data, QueueNodePayload) else None

    def _expand_to_item(self, item: wx.TreeItemId) -> None:
        parent = self._queue_tree.GetItemParent(item)
        while parent and parent.IsOk() and parent != self._queue_root:
            self._queue_tree.Expand(parent)
            parent = self._queue_tree.GetItemParent(parent)

    def _queue_path_for_item(self, plex_item: object, queue_index: int) -> List[str]:
        media_type = self._coerce_label(getattr(plex_item, "type", "")).lower()
        title = self._coerce_label(getattr(plex_item, "title", "")) or f"Item {queue_index + 1}"
        path: List[str] = []
        if media_type == "episode":
            show = self._coerce_label(getattr(plex_item, "grandparentTitle", ""))
            if show:
                path.append(show)
            season_value = getattr(plex_item, "parentIndex", None)
            if season_value not in (None, "", "-1"):
                path.append(self._format_number_label("Season ", season_value))
            episode_value = getattr(plex_item, "index", None)
            code_parts: List[str] = []
            if season_value not in (None, "", "-1"):
                code_parts.append(self._format_number_label("S", season_value, width=2))
            if episode_value not in (None, "", "-1"):
                code_parts.append(self._format_number_label("E", episode_value, width=2))
            leaf = f"{queue_index + 1:02d}. "
            if code_parts:
                leaf += f"{''.join(code_parts)} - "
            leaf += title
            return path + [leaf]
        if media_type == "track":
            artist = (
                self._coerce_label(getattr(plex_item, "grandparentTitle", ""))
                or self._coerce_label(getattr(plex_item, "parentTitle", ""))
            )
            album = self._coerce_label(getattr(plex_item, "parentTitle", ""))
            if artist:
                path.append(artist)
            if album and album != artist:
                path.append(album)
            path.append(f"{queue_index + 1:02d}. {title}")
            return path
        if media_type == "movie":
            year = getattr(plex_item, "year", None)
            if year not in (None, "", "-1"):
                try:
                    year_text = f"{int(year)}"
                except Exception:
                    year_text = self._coerce_label(year)
                leaf = f"{queue_index + 1:02d}. {title} ({year_text})"
            else:
                leaf = f"{queue_index + 1:02d}. {title}"
            return [leaf]
        if media_type == "clip":
            series = (
                self._coerce_label(getattr(plex_item, "grandparentTitle", ""))
                or self._coerce_label(getattr(plex_item, "parentTitle", ""))
            )
            if series:
                path.append(series)
            path.append(f"{queue_index + 1:02d}. {title}")
            return path
        container = (
            self._coerce_label(getattr(plex_item, "grandparentTitle", ""))
            or self._coerce_label(getattr(plex_item, "parentTitle", ""))
        )
        if container:
            path.append(container)
        path.append(f"{queue_index + 1:02d}. {title}")
        return path

    def _coerce_label(self, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    def _format_number_label(self, prefix: str, value: object, width: Optional[int] = None) -> str:
        try:
            number = int(value)
            if width is not None and number >= 0:
                return f"{prefix}{number:0{width}d}"
            return f"{prefix}{number}"
        except Exception:
            return f"{prefix}{value}"

    def stop(self) -> None:
        if self._mode == "stopped" and not self._current:
            return
        final_position = self._current_position()
        duration = self._current_duration()
        self._notify_timeline_state("stopped", final_position, duration, sync=True)
        self._halt_current_playback()
        self._current = None
        self._direct_url = None
        self._browser_url = None
        self._is_paused = False
        self._resume_offset = 0
        self._resume_applied = False
        self._pre_fullscreen_focus: Optional[wx.Window] = None
        self._header.SetLabel("Nothing is playing.")
        self._set_mode("stopped")

    def resume(self) -> bool:
        if not self._current or not self._can_control_transport():
            return False
        if self._mode == "libvlc" and self._vlc_player:
            self._vlc_player.set_pause(False)
            self._is_paused = False
            self._header.SetLabel(f"Playing (LibVLC): {self._current.title}")
            self._start_timeline_poll()
            try:
                position = int(self._vlc_player.get_time())
            except Exception:
                position = 0
            self._notify_timeline_state("playing", position, self._current_duration())
        else:
            return False
        self._notify_state()
        return True

    def pause(self) -> bool:
        if not self._current or not self._can_control_transport():
            return False
        if self._mode == "libvlc" and self._vlc_player:
            self._vlc_player.set_pause(True)
            self._is_paused = True
            self._header.SetLabel(f"Paused (LibVLC): {self._current.title}")
            try:
                position = int(self._vlc_player.get_time())
            except Exception:
                position = 0
            self._cancel_timeline_poll()
            self._notify_timeline_state("paused", position, self._current_duration())
        else:
            return False
        self._notify_state()
        return True

    def stop_playback(self) -> bool:
        if self._current or self._mode != "stopped":
            self.stop()
            return True
        return False

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        applied = False
        if self._mode == "libvlc" and self._vlc_player:
            self._vlc_player.audio_set_mute(self._muted)
            applied = True
        self._update_volume_controls()
        self._notify_state()
        return applied

    def is_fullscreen(self) -> bool:
        return self._fullscreen

    def set_fullscreen(self, desired: bool) -> bool:
        if desired:
            return self._enter_fullscreen()
        return self._exit_fullscreen()

    def toggle_fullscreen(self) -> bool:
        return self.set_fullscreen(not self._fullscreen)

    def adjust_volume(self, delta: int) -> bool:
        return self.set_volume(self._volume + delta)

    def set_volume(self, value: int, update_slider: bool = True) -> bool:
        value = max(0, min(100, value))
        self._volume = value
        if value > 0 and self._muted:
            self._muted = False
        applied = False
        if self._mode == "libvlc" and self._vlc_player:
            self._vlc_player.audio_set_volume(value)
            self._vlc_player.audio_set_mute(self._muted)
            applied = True
        if update_slider:
            self._volume_slider.SetValue(self._volume)
        self._update_volume_controls()
        self._notify_state()
        return applied

    def seek_by(self, delta_ms: int) -> bool:
        if self._mode != "libvlc" or not self._vlc_player or not self._current:
            return False
        current = self._current_position()
        return self.seek_to(current + delta_ms)

    def seek_to(self, position: int) -> bool:
        if self._mode != "libvlc" or not self._vlc_player or not self._current:
            return False
        duration = self._current_duration()
        target = max(0, int(position))
        if duration:
            target = min(target, duration)
        try:
            self._vlc_player.set_time(target)
        except Exception as exc:
            print(f"[LibVLC] seek_to failed: {exc}")
            return False
        self._resume_offset = target
        self._resume_applied = True
        self.force_timeline_snapshot(sync=True, position=target)
        return True

    # ----------------------------------------------------------------- Event handlers

    def _open_stream_externally(self, _: wx.CommandEvent) -> None:
        url = self._direct_url or self._browser_url
        if not url:
            wx.MessageBox(
                "No stream URL is available for this item.",
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
            return
        wx.LaunchDefaultBrowser(url)

    def _handle_play_char(self, event: wx.KeyEvent) -> None:
        self._handle_button_char(event, self._on_play_clicked, self._play_btn)

    def _handle_pause_char(self, event: wx.KeyEvent) -> None:
        self._handle_button_char(event, self._on_pause_clicked, self._pause_btn)

    def _handle_stop_char(self, event: wx.KeyEvent) -> None:
        self._handle_button_char(event, self._on_stop_clicked, self._stop_btn)

    def _handle_mute_char(self, event: wx.KeyEvent) -> None:
        self._handle_toggle_char(event, self._mute_btn, self._on_mute_toggled)

    def _handle_fullscreen_char(self, event: wx.KeyEvent) -> None:
        self._handle_toggle_char(event, self._fullscreen_btn, self._on_fullscreen_toggled)

    def _on_seek_slider_track(self, event: wx.ScrollEvent) -> None:
        if self._seek_slider.IsEnabled():
            self._seek_dragging = True
        event.Skip()

    def _on_seek_slider_release(self, event: wx.ScrollEvent) -> None:
        self._seek_dragging = False
        self._apply_seek_from_slider()
        event.Skip()

    def _on_seek_slider_changed(self, event: wx.ScrollEvent) -> None:
        if self._seek_dragging:
            event.Skip()
            return
        self._apply_seek_from_slider()
        event.Skip()

    def _apply_seek_from_slider(self) -> None:
        if self._updating_seek_slider or not self._seek_slider.IsEnabled():
            return
        if self._mode != "libvlc":
            return
        target = self._seek_slider.GetValue()
        if not self.seek_to(target):
            wx.Bell()

    def _handle_button_char(self, event: wx.KeyEvent, handler: Callable[[wx.CommandEvent], None], control: wx.Control) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            evt = wx.CommandEvent(wx.EVT_BUTTON.typeId, control.GetId())
            evt.SetEventObject(control)
            handler(evt)
            return
        event.Skip()

    def _handle_toggle_char(self, event: wx.KeyEvent, control: wx.ToggleButton, handler: Callable[[wx.CommandEvent], None]) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            control.SetValue(not control.GetValue())
            evt = wx.CommandEvent(wx.EVT_TOGGLEBUTTON.typeId, control.GetId())
            evt.SetInt(1 if control.GetValue() else 0)
            evt.SetEventObject(control)
            handler(evt)
            return
        event.Skip()

    def _handle_panel_char(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        ctrl = event.CmdDown() or event.ControlDown()
        if ctrl:
            if code in (ord("S"), ord("s")):
                if not self.stop_playback():
                    wx.Bell()
                return
            if code == wx.WXK_RIGHT:
                if not self.seek_by(SEEK_STEP_MS):
                    wx.Bell()
                return
            if code == wx.WXK_LEFT:
                if not self.seek_by(-SEEK_STEP_MS):
                    wx.Bell()
                return
        event.Skip()

    def _on_play_clicked(self, _: wx.CommandEvent) -> None:
        if not self.resume():
            wx.Bell()

    def _on_pause_clicked(self, _: wx.CommandEvent) -> None:
        if not self.pause():
            wx.Bell()

    def _on_stop_clicked(self, _: wx.CommandEvent) -> None:
        if not self.stop_playback():
            wx.Bell()

    def _on_mute_toggled(self, event: wx.CommandEvent) -> None:
        desired = bool(event.IsChecked())
        if desired != self._muted:
            if not self.toggle_mute():
                wx.Bell()
        else:
            self._update_volume_controls()

    def _on_fullscreen_toggled(self, event: wx.CommandEvent) -> None:
        desired = bool(event.IsChecked())
        if not self.set_fullscreen(desired):
            self._fullscreen_btn.SetValue(self._fullscreen)
            wx.Bell()

    def _on_volume_slider(self, _: wx.CommandEvent) -> None:
        self.set_volume(self._volume_slider.GetValue(), update_slider=False)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        self._halt_current_playback()
        event.Skip()

    # ------------------------------------------------------------- Playback helpers

    def _stop_libvlc_only(self) -> None:
        self._cancel_libvlc_timer()
        self._detach_libvlc_events()
        if self._vlc_player:
            try:
                self._vlc_player.stop()
            except Exception:
                pass
        self._libvlc_check_attempts = 0

    def _attach_libvlc_events(self) -> None:
        if self._vlc_player is None or vlc is None:
            return
        try:
            manager = self._vlc_player.event_manager()
        except Exception:
            return
        self._detach_libvlc_events()
        self._vlc_event_manager = manager
        if self._vlc_error_callback is None:
            def _callback(event: object) -> None:
                self._on_libvlc_error(event)
            self._vlc_error_callback = _callback
        try:
            manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._vlc_error_callback)
        except Exception:
            pass

    def _detach_libvlc_events(self) -> None:
        if self._vlc_event_manager and self._vlc_error_callback and vlc is not None:
            try:
                self._vlc_event_manager.event_detach(vlc.EventType.MediaPlayerEncounteredError, self._vlc_error_callback)
            except Exception:
                pass
        self._vlc_event_manager = None

    def _on_libvlc_error(self, _event: object = None) -> None:
        print("[LibVLC] Encountered playback error; stopping playback.")
        wx.CallAfter(self._handle_libvlc_failure, "LibVLC reported an error while streaming.", False, True)

    def _clear_libvlc_candidates(self) -> None:
        self._libvlc_candidates = []
        self._libvlc_candidate_index = 0
        self._libvlc_active_source = None

    def _halt_current_playback(self) -> None:
        self._stop_libvlc_only()
        self._cancel_timeline_poll()
        self._exit_fullscreen()
        self._notify_timeline_reset()
        self._clear_libvlc_candidates()

    def _play_with_libvlc(self, force_message: bool = False) -> str:
        if not (self._direct_url or self._browser_url):
            if force_message:
                wx.MessageBox(
                    "No stream URL is available for LibVLC playback.",
                    "Plexible",
                    wx.ICON_WARNING | wx.OK,
                    parent=self,
                )
            return "none"
        if not self._ensure_libvlc():
            if force_message and not self._libvlc_warning_shown:
                wx.MessageBox(
                    "LibVLC is not available. Install VLC and ensure python-vlc can locate it.",
                    "Plexible",
                    wx.ICON_WARNING | wx.OK,
                    parent=self,
                )
                self._libvlc_warning_shown = True
            return "none"

        self._libvlc_reset_candidates()
        stream_source = self._libvlc_next_source()
        if not stream_source:
            if force_message:
                wx.MessageBox(
                    "LibVLC could not find a playable stream for this item.",
                    "Plexible",
                    wx.ICON_WARNING | wx.OK,
                    parent=self,
                )
            return "none"

        if self._start_libvlc(stream_source):
            return "libvlc"

        if force_message:
            wx.MessageBox(
                "LibVLC was unable to start playback for this item.",
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
        return "none"
        return "none"

    def _libvlc_reset_candidates(self) -> None:
        self._clear_libvlc_candidates()
        seen = set()
        if self._direct_url:
            seen.add(self._direct_url)
            self._libvlc_candidates.append(self._direct_url)
        if self._browser_url and self._browser_url not in seen:
            self._libvlc_candidates.append(self._browser_url)

    def _libvlc_next_source(self) -> Optional[str]:
        while self._libvlc_candidate_index < len(self._libvlc_candidates):
            candidate = self._libvlc_candidates[self._libvlc_candidate_index]
            self._libvlc_candidate_index += 1
            if not self._probe_stream(candidate):
                print(f"[LibVLC] Probe failed for {self._describe_stream_source(candidate)} stream.")
                continue
            self._libvlc_active_source = candidate
            return candidate
        self._libvlc_active_source = None
        return None

    def _describe_stream_source(self, url: str) -> str:
        return "HLS" if "m3u8" in url.lower() else "Direct"

    def _start_libvlc(self, stream_source: str) -> bool:
        if self._vlc_instance is None or self._vlc_player is None:
            return False
        descriptor = self._describe_stream_source(stream_source)
        print(f"[LibVLC] Starting {descriptor} stream: {stream_source}")
        media = self._vlc_instance.media_new(stream_source)  # type: ignore[union-attr]
        if "m3u8" in stream_source.lower():
            media.add_option(":network-caching=2000")
        if sys.platform.startswith("win"):
            media.add_option(":audio-output=directsound")
        media.add_option(":http-user-agent=Plexible/1.0")
        media.add_option(":no-video-title-show")
        media.add_option(":no-osd")
        if self._resume_offset:
            resume_seconds = max(0.0, self._resume_offset / 1000.0)
            media.add_option(f":start-time={resume_seconds:.3f}")
        self._vlc_player.set_media(media)  # type: ignore[union-attr]
        self._libvlc_active_source = stream_source
        self._vlc_player.audio_set_volume(self._volume)  # type: ignore[union-attr]
        self._vlc_player.audio_set_mute(self._muted)  # type: ignore[union-attr]
        label_suffix = " (HLS)" if descriptor == "HLS" else " (Direct)"
        self._header.SetLabel(
            f"Playing (LibVLC){label_suffix}: {self._current.title if self._current else 'Media'}"
        )
        self._show_libvlc(True)
        self._resume_applied = self._resume_offset == 0
        self._attach_libvlc_events()
        result = self._vlc_player.play()  # type: ignore[union-attr]
        if result == -1:
            print(f"[LibVLC] Failed to start {descriptor} stream (error code {result}).")
            self._stop_libvlc_only()
            return False
        self._libvlc_check_attempts = 0
        self._schedule_libvlc_check()
        return True

    def _probe_stream(self, url: str) -> bool:
        try:
            resp = requests.get(
                url,
                stream=True,
                timeout=3,
                verify=False,
                headers={"User-Agent": "Plexible/1.0"},
            )
            resp.close()
            return resp.ok
        except requests.RequestException as exc:
            print(f"[LibVLC] Probe error for {self._describe_stream_source(url)} stream: {exc}")
            return False

    def _prepare_libvlc_environment(self, force: bool = False) -> None:
        if self._libvlc_env_prepared and not force:
            return
        _bootstrap_libvlc_environment()
        configured_dir: Optional[Path] = None
        if getattr(self, "_config", None):
            configured_value = self._config.get_vlc_path()
            if configured_value:
                configured_dir = Path(configured_value)
                if configured_dir.is_file():
                    configured_dir = configured_dir.parent
        candidates: list[Path] = []
        if configured_dir:
            candidates.append(configured_dir)
        env_module = os.environ.get("PYTHON_VLC_MODULE_PATH")
        if env_module:
            candidates.append(Path(env_module))
        exe_path = self._find_vlc()
        if exe_path:
            candidates.append(Path(exe_path).parent)
        if sys.platform.startswith("win"):
            is_64bit = struct.calcsize("P") == 8
            program_files = os.environ.get("ProgramFiles")
            program_files_x86 = os.environ.get("ProgramFiles(x86)")
            default_dirs: list[Path] = []
            if is_64bit:
                if program_files:
                    default_dirs.append(Path(program_files) / "VideoLAN" / "VLC")
                if program_files_x86:
                    default_dirs.append(Path(program_files_x86) / "VideoLAN" / "VLC")
            else:
                if program_files_x86:
                    default_dirs.append(Path(program_files_x86) / "VideoLAN" / "VLC")
                if program_files:
                    default_dirs.append(Path(program_files) / "VideoLAN" / "VLC")
            for directory in default_dirs:
                if directory and all(directory.resolve() != existing.resolve() for existing in candidates if existing):
                    candidates.append(directory)
        selected_dir: Optional[Path] = None
        for directory in candidates:
            if not directory:
                continue
            directory = directory.resolve()
            if directory.is_file():
                directory = directory.parent
            if not directory.is_dir():
                continue
            dll = directory / "libvlc.dll"
            core = directory / "libvlccore.dll"
            if dll.exists() and core.exists():
                compatible, message = self._is_libvlc_compatible(directory)
                if not compatible:
                    print(f"[LibVLC] Skipping {directory}: {message}")
                    continue
                selected_dir = directory
                break
        if selected_dir is None and sys.platform.startswith("win"):
            arch = "win64" if struct.calcsize("P") == 8 else "win32"
            portable_dir = _ensure_portable_vlc(arch)
            if portable_dir and (portable_dir / "libvlc.dll").exists():
                selected_dir = portable_dir
        if selected_dir:
            os.environ["PYTHON_VLC_MODULE_PATH"] = str(selected_dir)
            exe = selected_dir / "vlc.exe"
            if exe.exists():
                os.environ.setdefault("VLC_PATH", str(exe))
            _ensure_dll_directory(selected_dir)
        self._libvlc_env_prepared = True

    def _ensure_libvlc(self) -> bool:
        global vlc
        self._prepare_libvlc_environment()
        if vlc is None:
            try:
                vlc = importlib.import_module("vlc")
            except Exception:
                return False
        if self._vlc_instance is None or self._vlc_player is None:
            try:
                instance_args = ["--no-video-title-show", "--quiet"]
                if sys.platform.startswith("win"):
                    instance_args.append("--aout=directsound")
                self._vlc_instance = vlc.Instance(*instance_args)
                self._vlc_player = self._vlc_instance.media_player_new()
            except Exception:
                self._libvlc_env_prepared = False
                self._prepare_libvlc_environment(force=True)
                try:
                    vlc = importlib.reload(vlc)  # type: ignore[arg-type]
                    instance_args = ["--no-video-title-show", "--quiet"]
                    if sys.platform.startswith("win"):
                        instance_args.append("--aout=directsound")
                    self._vlc_instance = vlc.Instance(*instance_args)
                    self._vlc_player = self._vlc_instance.media_player_new()
                except Exception:
                    if self._prompt_for_vlc_path():
                        return self._ensure_libvlc()
                    if not self._libvlc_warning_shown:
                        wx.MessageBox(
                            "LibVLC could not be initialised. Install the VLC version matching this Python build (32-bit vs 64-bit) or select the correct VLC folder when prompted.",
                            "Plexible",
                            wx.ICON_WARNING | wx.OK,
                            parent=self,
                        )
                    self._libvlc_warning_shown = True
                    self._vlc_instance = None
                    self._vlc_player = None
                    return False
        if self._vlc_player and sys.platform.startswith("win"):
            try:
                self._vlc_player.audio_output_set("directsound")
            except Exception:
                pass
        self._update_vlc_drawable(self._active_video_window)
        return True

    def _update_vlc_drawable(self, window: Optional[wx.Window]) -> None:
        if self._vlc_player is None or vlc is None or window is None:
            return
        try:
            handle = window.GetHandle()
        except Exception:
            return
        if sys.platform.startswith("win"):
            self._vlc_player.set_hwnd(int(handle))  # type: ignore[union-attr]
        elif sys.platform.startswith("linux"):
            self._vlc_player.set_xwindow(int(handle))  # type: ignore[union-attr]
        elif sys.platform == "darwin":
            self._vlc_player.set_nsobject(int(handle))  # type: ignore[union-attr]

    def _schedule_libvlc_check(self, delay: int = 3000) -> None:
        self._cancel_libvlc_timer()
        self._vlc_check = wx.CallLater(delay, self._verify_libvlc_start)

    def _cancel_libvlc_timer(self) -> None:
        if self._vlc_check:
            try:
                self._vlc_check.Stop()
            except Exception:
                pass
        self._vlc_check = None

    def _verify_libvlc_start(self) -> None:
        self._vlc_check = None
        if self._vlc_player is None or vlc is None:
            return
        state = self._vlc_player.get_state()
        if state in (vlc.State.Playing, vlc.State.Paused):
            self._libvlc_check_attempts = 0
            self._handle_playback_start("libvlc")
            return
        if state in (vlc.State.Opening, vlc.State.Buffering, vlc.State.NothingSpecial):
            if self._libvlc_check_attempts < self._libvlc_max_start_checks:
                self._libvlc_check_attempts += 1
                self._schedule_libvlc_check(2000)
                return
        print(f"[LibVLC] Player state after launch: {state}")
        self._handle_libvlc_failure("LibVLC could not start playback.", False, True)

    # ----------------------------------------------------------------- UI helpers

    def _handle_libvlc_failure(self, reason: str, _allow_external: bool, alert_user: bool) -> None:
        if not self._current:
            return
        print(f"[LibVLC] {reason}")
        self._stop_libvlc_only()
        self._exit_fullscreen()
        self._libvlc_active_source = None
        if alert_user:
            wx.MessageBox(
                "LibVLC could not play this item.",
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
        self._header.SetLabel("Unable to start playback.")
        self._set_mode("stopped")
        self._notify_timeline_reset()

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode != "libvlc" and self._fullscreen:
            self._exit_fullscreen()
        if mode != "libvlc":
            self._is_paused = False
            self._reset_seek_slider()
        self._update_controls_enabled()
        self._update_volume_controls()
        self._notify_state()

    def _update_controls_enabled(self) -> None:
        can_control = self._can_control_transport()
        can_volume = self._volume_control_available()
        has_media = self._current is not None
        self._play_btn.Enable(can_control)
        self._pause_btn.Enable(can_control and not self._is_paused)
        self._stop_btn.Enable(has_media or self._mode != "stopped")
        self._mute_btn.Enable(can_volume)
        self._volume_slider.Enable(can_volume)
        self._fullscreen_btn.Enable(self._mode == "libvlc")
        self._fullscreen_btn.SetValue(self._fullscreen)

    def _update_volume_controls(self) -> None:
        self._mute_btn.SetValue(self._muted)
        label = "Muted" if self._muted or self._volume == 0 else f"{self._volume}%"
        self._volume_label.SetLabel(label)
        if not self._volume_control_available():
            self._volume_slider.SetValue(self._volume)

    def _reset_seek_slider(self) -> None:
        if not hasattr(self, "_seek_slider"):
            return
        self._seek_slider_duration = 0
        self._seek_dragging = False
        self._updating_seek_slider = True
        try:
            self._seek_slider.Enable(False)
            self._seek_slider.SetRange(0, 1)
            self._seek_slider.SetValue(0)
        finally:
            self._updating_seek_slider = False

    def _set_seek_slider(self, position: int, duration: int) -> None:
        if not hasattr(self, "_seek_slider"):
            return
        if self._mode != "libvlc" or duration <= 0 or not self._current:
            self._reset_seek_slider()
            return
        clamped_duration = max(1, duration)
        clamped_position = max(0, min(position, clamped_duration))
        self._seek_slider_duration = clamped_duration
        self._updating_seek_slider = True
        try:
            if self._seek_slider.GetMax() != clamped_duration or self._seek_slider.GetMin() != 0:
                self._seek_slider.SetRange(0, clamped_duration)
            if not self._seek_dragging:
                self._seek_slider.SetValue(clamped_position)
            self._seek_slider.Enable(True)
        finally:
            self._updating_seek_slider = False

    def _notify_state(self) -> None:
        if not self._state_listener:
            return
        state = self.get_state()
        wx.CallAfter(self._state_listener, state)

    def set_timeline_callback(
        self,
        callback: Optional[Callable[[PlayableMedia, str, int, int, bool], None]],
    ) -> None:
        self._timeline_callback = callback

    def _current_duration(self) -> int:
        if not self._current:
            return 0
        duration = 0
        if self._mode == "libvlc" and self._vlc_player:
            try:
                duration = int(self._vlc_player.get_length())
            except Exception:
                duration = 0
        if not duration and getattr(self._current.item, "duration", None):
            try:
                duration = int(getattr(self._current.item, "duration", 0) or 0)
            except Exception:
                duration = 0
        return max(0, duration)

    def _current_position(self) -> int:
        fallback = max(0, self._last_timeline_position)
        if self._mode == "libvlc" and self._vlc_player:
            try:
                vlc_time = int(self._vlc_player.get_time())
            except Exception:
                vlc_time = -1
            if vlc_time >= 0:
                return max(0, vlc_time)
        return fallback

    def force_timeline_snapshot(self, sync: bool = True, position: Optional[int] = None) -> None:
        if not self._current:
            return
        if position is None:
            position = self._current_position()
        duration = self._current_duration()
        self._notify_timeline_state("playing", max(0, int(position)), duration, sync=sync)

    def _handle_playback_start(self, mode: str) -> None:
        if not self._current:
            return
        duration = self._current_duration()
        if mode == "libvlc":
            position = self._resume_offset or 0
            if not position and self._vlc_player:
                try:
                    position = max(0, int(self._vlc_player.get_time()))
                except Exception:
                    position = 0
            self._start_timeline_poll()
            self._notify_timeline_state("playing", position, duration)
            self._maybe_seek_to_resume(initial=True)
        else:
            self._cancel_timeline_poll()
            position = 1000 if duration else 0
            self._notify_timeline_state("playing", position, duration)

    def _start_timeline_poll(self, delay_ms: int = 5000) -> None:
        self._cancel_timeline_poll()
        if self._mode != "libvlc":
            return
        self._timeline_timer = wx.CallLater(delay_ms, self._poll_timeline)

    def _maybe_seek_to_resume(self, initial: bool = False) -> None:
        if (
            self._resume_applied
            or not self._resume_offset
            or self._mode != "libvlc"
            or self._vlc_player is None
            or vlc is None
        ):
            return
        try:
            state = self._vlc_player.get_state()
        except Exception:
            state = None
        if state not in (vlc.State.Playing, vlc.State.Paused):
            if initial:
                wx.CallLater(100, self._maybe_seek_to_resume)
            return
        try:
            current_time = int(self._vlc_player.get_time())
        except Exception:
            current_time = None
        else:
            if current_time is not None and current_time >= 0:
                tolerance = 500
                if current_time + tolerance >= self._resume_offset:
                    self._resume_applied = True
                    return
        try:
            self._vlc_player.set_time(self._resume_offset)
            self._resume_applied = True
            print(f"[LibVLC] Resume offset applied at {self._resume_offset} ms.")
        except Exception as exc:
            print(f"[LibVLC] Failed to apply resume offset: {exc}")
        else:
            self._resume_applied = True

    def _enter_fullscreen(self) -> bool:
        if self._fullscreen:
            return True
        if self._mode != "libvlc" or self._vlc_player is None or vlc is None or not self._current:
            return False
        if not self._ensure_libvlc():
            return False
        self._pre_fullscreen_focus = wx.Window.FindFocus()
        frame = wx.Frame(
            self.GetTopLevelParent(),
            title=self._current.title if self._current else "Plexible",
            style=wx.DEFAULT_FRAME_STYLE,
        )
        frame.SetBackgroundColour(wx.BLACK)
        video_panel = wx.Panel(frame)
        video_panel.SetBackgroundColour(wx.BLACK)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(video_panel, 1, wx.EXPAND)
        frame.SetSizer(frame_sizer)
        frame.Bind(wx.EVT_CLOSE, self._on_fullscreen_close)
        frame.Bind(wx.EVT_CHAR_HOOK, self._on_fullscreen_key)
        frame.ShowFullScreen(True)
        frame.Show()
        frame.Raise()
        frame.SetFocus()
        video_panel.SetFocus()
        self._pre_fullscreen_focus = wx.Window.FindFocus()
        self._video_panel.Hide()
        self.Layout()
        self._fullscreen_frame = frame
        self._fullscreen_video_panel = video_panel
        self._fullscreen = True
        self._active_video_window = video_panel
        self._update_vlc_drawable(video_panel)
        self._fullscreen_btn.SetValue(True)
        self._update_controls_enabled()
        self._notify_state()
        self._maybe_seek_to_resume()
        return True

    def _exit_fullscreen(self) -> bool:
        if not self._fullscreen:
            return True
        frame = self._fullscreen_frame
        panel = self._fullscreen_video_panel
        self._fullscreen_frame = None
        self._fullscreen_video_panel = None
        self._fullscreen = False
        self._active_video_window = self._video_panel
        self._update_vlc_drawable(self._video_panel)
        self._video_panel.Show()
        if self._pre_fullscreen_focus and self._pre_fullscreen_focus.IsOk():
            wx.CallAfter(self._pre_fullscreen_focus.SetFocus)
        self.SetFocus()
        self.Layout()
        if panel:
            panel.Destroy()
        if frame:
            try:
                frame.ShowFullScreen(False)
            except Exception:
                pass
            frame.Destroy()
        self._fullscreen_btn.SetValue(False)
        self._update_controls_enabled()
        self._notify_state()
        return True

    def _on_fullscreen_close(self, event: wx.CloseEvent) -> None:
        self._exit_fullscreen()
        event.Skip(False)

    def _on_fullscreen_key(self, event: wx.KeyEvent) -> None:
        code = event.GetKeyCode()
        if code in (wx.WXK_ESCAPE, wx.WXK_F11):
            self._exit_fullscreen()
        else:
            event.Skip()

    def _cancel_timeline_poll(self) -> None:
        if self._timeline_timer:
            try:
                self._timeline_timer.Stop()
            except Exception:
                pass
        self._timeline_timer = None

    def _poll_timeline(self) -> None:
        self._timeline_timer = None
        if not self._current or self._mode != "libvlc" or self._vlc_player is None or vlc is None:
            return
        try:
            state = self._vlc_player.get_state()
        except Exception:
            state = None
        try:
            position = max(0, int(self._vlc_player.get_time()))
        except Exception:
            position = 0
        duration = self._current_duration()
        if state == vlc.State.Playing:
            self._maybe_seek_to_resume()
            self._notify_timeline_state("playing", position, duration)
            self._start_timeline_poll()
        elif state == vlc.State.Paused:
            self._maybe_seek_to_resume()
            self._notify_timeline_state("paused", position, duration)
            self._start_timeline_poll()
        elif state in (vlc.State.Ended, vlc.State.Stopped):
            self._notify_timeline_state("stopped", duration or position, duration)
            wx.CallAfter(self.stop)
        elif state == vlc.State.Error:
            self._notify_timeline_state("stopped", position, duration)
            wx.CallAfter(self._handle_libvlc_failure, "LibVLC reported an error while streaming.", False, True)
        else:
            self._start_timeline_poll()

    def _notify_timeline_state(self, state: str, position: int, duration: int, *, sync: bool = False) -> None:
        duration = max(0, duration or self._current_duration())
        position = max(0, position)
        self._set_seek_slider(position, duration)
        if not self._timeline_callback or not self._current:
            return
        if (
            self._last_timeline_state == state
            and abs(position - self._last_timeline_position) < 1500
            and not sync
        ):
            return
        self._last_timeline_state = state
        self._last_timeline_position = position
        try:
            callback = self._timeline_callback
            if sync:
                callback(self._current, state, position, duration, True)
            else:
                wx.CallAfter(callback, self._current, state, position, duration, False)
        except Exception:
            pass

    def _notify_timeline_reset(self) -> None:
        self._last_timeline_state = None
        self._last_timeline_position = 0
        self._reset_seek_slider()

    def _show_libvlc(self, visible: bool) -> None:
        self._video_panel.Show(visible)
        self.Layout()

    # -------------------------------------------------------------- Player discovery

    def _find_vlc(self) -> Optional[str]:
        if self._vlc_path_cache is not None:
            return self._vlc_path_cache
        candidates: list[str] = []
        configured = self._config.get_vlc_path() if getattr(self, "_config", None) else None
        if configured:
            path = Path(configured)
            exe = path if path.suffix.lower() == ".exe" else path / "vlc.exe"
            candidates.append(str(exe))
        env_path = os.environ.get("VLC_PATH")
        if env_path:
            candidates.append(env_path)
        which_path = which("vlc")
        if which_path:
            candidates.append(which_path)
        if sys.platform.startswith("win"):
            is_64bit = struct.calcsize("P") == 8
            program_files = os.environ.get("ProgramFiles")
            program_files_x86 = os.environ.get("ProgramFiles(x86)")
            default_paths: list[str] = []
            if is_64bit:
                if program_files:
                    default_paths.append(str(Path(program_files) / "VideoLAN" / "VLC" / "vlc.exe"))
                if program_files_x86:
                    default_paths.append(str(Path(program_files_x86) / "VideoLAN" / "VLC" / "vlc.exe"))
            else:
                if program_files_x86:
                    default_paths.append(str(Path(program_files_x86) / "VideoLAN" / "VLC" / "vlc.exe"))
                if program_files:
                    default_paths.append(str(Path(program_files) / "VideoLAN" / "VLC" / "vlc.exe"))
            for path in default_paths:
                if path not in candidates:
                    candidates.append(path)
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if not path.exists():
                continue
            valid = True
            message: Optional[str] = None
            try:
                valid, message = self._validate_vlc_directory(path.parent)
            except Exception:
                valid = False
            if not valid:
                if message:
                    print(f"[LibVLC] Skipping {path.parent}: {message}")
                continue
            self._vlc_path_cache = str(path)
            self._vlc_notified_missing = False
            return self._vlc_path_cache
        self._vlc_path_cache = None
        return None

    # ------------------------------------------------------------------ Utility

    def _validate_vlc_directory(self, directory: Path) -> tuple[bool, Optional[str]]:
        dir_path = directory.resolve()
        if dir_path.is_file():
            dir_path = dir_path.parent
        dll = dir_path / "libvlc.dll"
        core = dir_path / "libvlccore.dll"
        if not dll.exists() or not core.exists():
            return False, "Selected folder does not contain libvlc.dll and libvlccore.dll."
        python_32 = sys.maxsize <= 2**32
        python_64 = not python_32
        if python_32 and "Program Files (x86)" not in str(dir_path) and "Program Files" in str(dir_path):
            return (
                False,
                "This Python build is 32-bit. Please select the 32-bit VLC installation (Program Files (x86)\\VideoLAN\\VLC).",
            )
        if python_64 and "Program Files (x86)" in str(dir_path):
            return (
                False,
                "This Python build is 64-bit. Please select the 64-bit VLC installation (Program Files\\VideoLAN\\VLC).",
            )
        return True, None

    def _prompt_for_vlc_path(self) -> bool:
        if self._vlc_notified_missing:
            return False
        dlg = wx.DirDialog(self, "Select the VLC installation directory", style=wx.DD_DEFAULT_STYLE)
        try:
            if dlg.ShowModal() == wx.ID_OK:
                path = Path(dlg.GetPath())
                valid, message = self._validate_vlc_directory(path)
                if not valid:
                    wx.MessageBox(message or "Invalid VLC installation directory.", "Plexible", wx.ICON_WARNING | wx.OK, parent=self)
                    return False
                self._config.set_vlc_path(str(path))
                self._vlc_path_cache = None
                self._libvlc_env_prepared = False
                self._vlc_notified_missing = False
                return True
        finally:
            dlg.Destroy()
        self._vlc_notified_missing = True
        return False

    def _can_control_transport(self) -> bool:
        return self._current is not None and self._mode == "libvlc"

    def _volume_control_available(self) -> bool:
        return self._current is not None and self._mode == "libvlc"

    def _is_libvlc_compatible(self, directory: Path) -> Tuple[bool, Optional[str]]:
        directory = directory.resolve()
        dll = directory / "libvlc.dll"
        core = directory / "libvlccore.dll"
        if not dll.exists() or not core.exists():
            return False, "libvlc.dll/libvlccore.dll not found"
        try:
            ctypes.WinDLL(str(dll))
        except OSError as exc:
            return False, str(exc)
        return True, None
