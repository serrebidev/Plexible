from __future__ import annotations

import ctypes
import html
import importlib
import os
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Callable, Optional, Tuple

import requests
import wx
import wx.html2 as webview

from ..config import ConfigStore
from ..plex_service import PlayableMedia

_LIBVLC_BOOTSTRAPPED = False


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
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate.is_file():
                candidate = candidate.parent
            if candidate.is_dir() and (
                (candidate / "libvlc.dll").exists()
                or (candidate / "libvlccore.dll").exists()
            ):
                os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(candidate))
                _ensure_dll_directory(candidate)
                break
    _LIBVLC_BOOTSTRAPPED = True


requests.packages.urllib3.disable_warnings()

_bootstrap_libvlc_environment()
try:  # pragma: no cover - python-vlc is optional at import time
    import vlc  # type: ignore
except Exception:  # pragma: no cover - handled at runtime
    vlc = None


PlaybackState = dict[str, object]


class PlaybackPanel(wx.Panel):
    """Playback surface supporting embedded LibVLC with rich controls and fallbacks."""

    PLAYER_CHOICES = ["Auto", "LibVLC", "Browser", "VLC", "MPC"]

    def __init__(self, parent: wx.Window, config: ConfigStore) -> None:
        super().__init__(parent)
        self._config = config
        self._current: Optional[PlayableMedia] = None
        self._direct_url: Optional[str] = None
        self._browser_url: Optional[str] = None
        self._mode: str = "stopped"
        self._last_preference: str = "Auto"
        self._is_paused: bool = False
        self._browser_controlled: bool = False
        self._volume: int = 80
        self._muted: bool = False
        self._state_listener: Optional[Callable[[PlaybackState], None]] = None

        self._vlc_instance: Optional["vlc.Instance"] = None
        self._vlc_player: Optional["vlc.MediaPlayer"] = None
        self._vlc_check: Optional[wx.CallLater] = None
        self._vlc_notified_missing = False
        self._vlc_path_cache: Optional[str] = None
        self._mpc_path_cache: Optional[str] = None
        self._mpc_notified_missing = False
        self._libvlc_env_prepared = False
        self._libvlc_warning_shown = False
        self._libvlc_candidates: list[str] = []
        self._libvlc_candidate_index = 0
        self._libvlc_active_source: Optional[str] = None
        self._libvlc_check_attempts = 0
        self._libvlc_max_start_checks = 4

        self._header = wx.StaticText(self, label="Nothing is playing.")
        header_font = self._header.GetFont()
        header_font.SetPointSize(header_font.GetPointSize() + 1)
        self._header.SetFont(header_font)

        # Top row: player preference + open externally
        preference_bar = wx.BoxSizer(wx.HORIZONTAL)
        preference_bar.Add(wx.StaticText(self, label="Player:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        self._mode_selector = wx.Choice(self, choices=self.PLAYER_CHOICES)
        self._mode_selector.SetSelection(0)
        self._mode_selector.Bind(wx.EVT_CHOICE, self._handle_player_choice)
        preference_bar.Add(self._mode_selector, 0, wx.ALIGN_CENTER_VERTICAL)
        preference_bar.AddStretchSpacer()
        self._external_btn = wx.Button(self, label="Open Stream Externally")
        self._external_btn.Enable(False)
        self._external_btn.Bind(wx.EVT_BUTTON, self._open_stream_externally)
        preference_bar.Add(self._external_btn, 0, wx.ALIGN_CENTER_VERTICAL)

        # Second row: transport controls + volume
        controls_bar = wx.BoxSizer(wx.HORIZONTAL)
        self._play_btn = wx.Button(self, label="Play")
        self._pause_btn = wx.Button(self, label="Pause")
        self._stop_btn = wx.Button(self, label="Stop")
        self._mute_btn = wx.ToggleButton(self, label="Mute")
        self._play_btn.Bind(wx.EVT_BUTTON, self._on_play_clicked)
        self._pause_btn.Bind(wx.EVT_BUTTON, self._on_pause_clicked)
        self._stop_btn.Bind(wx.EVT_BUTTON, self._on_stop_clicked)
        self._mute_btn.Bind(wx.EVT_TOGGLEBUTTON, self._on_mute_toggled)
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
        controls_bar.AddStretchSpacer()

        self._video_panel = wx.Panel(self)
        self._video_panel.SetBackgroundColour(wx.BLACK)
        self._browser = webview.WebView.New(self)

        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(preference_bar, 0, wx.ALL | wx.EXPAND, 6)
        layout.Add(self._header, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 6)
        layout.Add(controls_bar, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 6)
        layout.Add(self._video_panel, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        layout.Add(self._browser, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        self.SetSizer(layout)

        self._show_libvlc(False)
        self._update_controls_enabled()
        self._update_volume_controls()
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
            "muted": self._muted,
            "volume": self._volume,
        }

    def play(self, media: PlayableMedia) -> str:
        """Play the provided media according to the active preference."""
        self._halt_current_playback()

        self._current = media
        self._direct_url = media.stream_url
        self._browser_url = media.browser_url or media.stream_url
        self._external_btn.Enable(True)
        self._is_paused = False

        preference = self._mode_selector.GetStringSelection() if self._mode_selector else "Auto"
        self._last_preference = preference

        print(
            "[Playback] Requested stream via "
            f"{preference} -> direct={self._direct_url} browser={self._browser_url}"
        )

        if preference == "LibVLC":
            mode = self._play_with_libvlc(force_message=True)
            if mode == "none":
                mode = self._play_with_browser()
            self._set_mode(mode)
            return mode

        if preference == "Browser":
            mode = self._play_with_browser()
            self._set_mode(mode)
            return mode

        if preference == "VLC":
            mode = self._launch_vlc_app(force_message=True)
            if mode == "none":
                mode = self._play_with_browser()
            self._set_mode(mode)
            return mode

        if preference == "MPC":
            mode = self._play_with_mpc(force_message=True)
            if mode == "none":
                mode = self._play_with_browser()
            self._set_mode(mode)
            return mode

        # Auto preference: LibVLC -> external VLC -> MPC -> Browser
        mode = self._play_with_libvlc()
        if mode != "none":
            self._set_mode(mode)
            return mode
        mode = self._launch_vlc_app()
        if mode != "none":
            self._set_mode(mode)
            return mode
        mode = self._play_with_mpc()
        if mode != "none":
            self._set_mode(mode)
            return mode
        mode = self._play_with_browser()
        self._set_mode(mode)
        return mode

    def stop(self) -> None:
        if self._mode == "stopped" and not self._current:
            return
        self._halt_current_playback()
        self._current = None
        self._direct_url = None
        self._browser_url = None
        self._browser_controlled = False
        self._is_paused = False
        self._header.SetLabel("Nothing is playing.")
        self._external_btn.Enable(False)
        self._set_mode("stopped")

    def resume(self) -> bool:
        if not self._current or not self._can_control_transport():
            return False
        if self._mode == "libvlc" and self._vlc_player:
            self._vlc_player.set_pause(False)
            self._is_paused = False
            self._header.SetLabel(f"Playing (LibVLC): {self._current.title}")
        elif self._mode == "browser" and self._browser_controlled:
            self._run_browser_script("var p=document.getElementById('player'); if(p){p.play();}")
            self._is_paused = False
            self._header.SetLabel(f"Playing (Browser): {self._current.title}")
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
        elif self._mode == "browser" and self._browser_controlled:
            self._run_browser_script("var p=document.getElementById('player'); if(p){p.pause();}")
            self._is_paused = True
            self._header.SetLabel(f"Paused (Browser): {self._current.title}")
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
        elif self._mode == "browser" and self._browser_controlled:
            self._run_browser_script(
                f"var p=document.getElementById('player'); if(p){{p.muted={'true' if self._muted else 'false'};}}"
            )
            applied = True
        self._update_volume_controls()
        self._notify_state()
        return applied

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
        elif self._mode == "browser" and self._browser_controlled:
            vol = value / 100
            self._run_browser_script(
                f"var p=document.getElementById('player'); if(p){{p.volume={vol}; p.muted={'true' if self._muted else 'false'};}}"
            )
            applied = True
        if update_slider:
            self._volume_slider.SetValue(self._volume)
        self._update_volume_controls()
        self._notify_state()
        return applied

    # ----------------------------------------------------------------- Event handlers

    def _handle_player_choice(self, _: wx.CommandEvent) -> None:
        self._last_preference = self._mode_selector.GetStringSelection() if self._mode_selector else "Auto"
        if self._current:
            self.play(self._current)

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

    def _on_volume_slider(self, _: wx.CommandEvent) -> None:
        self.set_volume(self._volume_slider.GetValue(), update_slider=False)

    def _on_destroy(self, event: wx.WindowDestroyEvent) -> None:
        self._halt_current_playback()
        event.Skip()

    # ------------------------------------------------------------- Playback helpers

    def _stop_libvlc_only(self) -> None:
        self._cancel_libvlc_timer()
        if self._vlc_player:
            try:
                self._vlc_player.stop()
            except Exception:
                pass
        self._libvlc_check_attempts = 0

    def _clear_libvlc_candidates(self) -> None:
        self._libvlc_candidates = []
        self._libvlc_candidate_index = 0
        self._libvlc_active_source = None

    def _halt_current_playback(self) -> None:
        self._stop_libvlc_only()
        self._clear_libvlc_candidates()
        self._browser.Stop()
        self._show_libvlc(False)

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

        if self._attempt_libvlc_fallback():
            return "libvlc"

        if force_message:
            wx.MessageBox(
                "LibVLC was unable to start playback for this item.",
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
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
        media.add_option(":http-user-agent=Plexible/1.0")
        self._vlc_player.set_media(media)  # type: ignore[union-attr]
        self._libvlc_active_source = stream_source
        self._vlc_player.audio_set_volume(self._volume)  # type: ignore[union-attr]
        self._vlc_player.audio_set_mute(self._muted)  # type: ignore[union-attr]
        label_suffix = " (HLS)" if descriptor == "HLS" else " (Direct)"
        self._header.SetLabel(
            f"Playing (LibVLC){label_suffix}: {self._current.title if self._current else 'Media'}"
        )
        self._browser_controlled = False
        self._show_libvlc(True)
        result = self._vlc_player.play()  # type: ignore[union-attr]
        if result == -1:
            print(f"[LibVLC] Failed to start {descriptor} stream (error code {result}).")
            self._stop_libvlc_only()
            return False
        self._libvlc_check_attempts = 0
        self._schedule_libvlc_check()
        return True

    def _attempt_libvlc_fallback(self) -> bool:
        self._stop_libvlc_only()
        self._libvlc_active_source = None
        while True:
            next_source = self._libvlc_next_source()
            if not next_source:
                return False
            descriptor = self._describe_stream_source(next_source)
            print(f"[LibVLC] Retrying with {descriptor} stream.")
            if self._start_libvlc(next_source):
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

    def _play_with_browser(self) -> str:
        self._show_libvlc(False)
        title = self._current.title if self._current else "Media"
        self._header.SetLabel(f"Playing (Browser): {title}")
        url = self._browser_url
        self._browser_controlled = False
        if not url:
            self._browser.SetPage(
                "<html><body style='background:#111;color:#eee;font-family:sans-serif;padding:12px;'>"
                "Unable to play this item."
                "</body></html>",
                "",
            )
        else:
            element, mime = self._element_for_url(url)
            if element in {"video", "audio"}:
                self._browser_controlled = True
                safe_url = html.escape(url, quote=True)
                muted_attr = " muted" if self._muted else ""
                volume_js = f"var p=document.getElementById('player'); if(p){{p.volume={self._volume/100};}}"
                mute_js = "p.muted=true;" if self._muted else "p.muted=false;"
                page = (
                    "<html><body style='margin:0;background:#000;color:#fff;'>"
                    f"<{element} id='player' src=\"{safe_url}\" type=\"{mime}\" controls autoplay{muted_attr} "
                    "style=\"width:100%;height:100%;background:#000;\">"
                    "Sorry, your system cannot play this stream."
                    f"</{element}>"
                    f"<script>{volume_js} var p=document.getElementById('player'); if(p){{{mute_js}}}</script>"
                    "</body></html>"
                )
                self._browser.SetPage(page, "")
            else:
                self._browser.LoadURL(url)
        if self._browser_controlled:
            wx.CallLater(250, self._apply_browser_volume_settings)
        return "browser"

    def _launch_vlc_app(self, force_message: bool = False) -> str:
        path = self._find_vlc()
        if not path:
            if force_message and not self._vlc_notified_missing:
                wx.MessageBox(
                    "VLC was not found. Install VLC or set the VLC_PATH environment variable.",
                    "Plexible",
                    wx.ICON_WARNING | wx.OK,
                    parent=self,
                )
                self._vlc_notified_missing = True
            return "none"
        url = self._direct_url or self._browser_url
        if not url:
            if force_message:
                wx.MessageBox(
                    "No usable stream URL is available for external playback.",
                    "Plexible",
                    wx.ICON_WARNING | wx.OK,
                    parent=self,
                )
            return "none"
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        try:
            subprocess.Popen(
                [path, url, "--play-and-exit"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as exc:
            if force_message:
                wx.MessageBox(
                    f"Failed to launch VLC.\n{exc}",
                    "Plexible",
                    wx.ICON_ERROR | wx.OK,
                    parent=self,
                )
            return "none"
        self._browser_controlled = False
        self._header.SetLabel(f"Playing in VLC: {self._current.title if self._current else 'Media'}")
        return "vlc"

    def _play_with_mpc(self, force_message: bool = False) -> str:
        path = self._find_mpc()
        if not path:
            if force_message and not self._mpc_notified_missing:
                wx.MessageBox(
                    "MPC-HC/BE was not found. Install MPC-HC (or set MPC_PATH) for this fallback.",
                    "Plexible",
                    wx.ICON_WARNING | wx.OK,
                    parent=self,
                )
                self._mpc_notified_missing = True
            return "none"
        url = self._direct_url or self._browser_url
        if not url:
            if force_message:
                wx.MessageBox(
                    "No usable stream URL is available for external playback.",
                    "Plexible",
                    wx.ICON_WARNING | wx.OK,
                    parent=self,
                )
            return "none"
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
        try:
            subprocess.Popen(
                [path, url],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except Exception as exc:
            if force_message:
                wx.MessageBox(
                    f"Failed to launch MPC.\n{exc}",
                    "Plexible",
                    wx.ICON_ERROR | wx.OK,
                    parent=self,
                )
            return "none"
        self._browser_controlled = False
        self._header.SetLabel(f"Playing in MPC: {self._current.title if self._current else 'Media'}")
        return "mpc"

    # -------------------------------------------------------------- LibVLC support

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
                os.environ["PYTHON_VLC_MODULE_PATH"] = str(directory)
                exe = directory / "vlc.exe"
                if exe.exists():
                    os.environ.setdefault("VLC_PATH", str(exe))
                _ensure_dll_directory(directory)
                break
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
                self._vlc_instance = vlc.Instance()
                self._vlc_player = self._vlc_instance.media_player_new()
            except Exception:
                self._libvlc_env_prepared = False
                self._prepare_libvlc_environment(force=True)
                try:
                    vlc = importlib.reload(vlc)  # type: ignore[arg-type]
                    self._vlc_instance = vlc.Instance()
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
        handle = self._video_panel.GetHandle()
        if sys.platform.startswith("win"):
            self._vlc_player.set_hwnd(int(handle))  # type: ignore[union-attr]
        elif sys.platform.startswith("linux"):
            self._vlc_player.set_xwindow(int(handle))  # type: ignore[union-attr]
        elif sys.platform == "darwin":
            self._vlc_player.set_nsobject(int(handle))  # type: ignore[union-attr]
        return True

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
            return
        if state in (vlc.State.Opening, vlc.State.Buffering, vlc.State.NothingSpecial):
            if self._libvlc_check_attempts < self._libvlc_max_start_checks:
                self._libvlc_check_attempts += 1
                self._schedule_libvlc_check(2000)
                return
        print(f"[LibVLC] Player state after launch: {state}")
        if self._attempt_libvlc_fallback():
            return
        self._halt_current_playback()
        if self._last_preference == "LibVLC":
            wx.MessageBox(
                "LibVLC could not play this item.",
                "Plexible",
                wx.ICON_WARNING | wx.OK,
                parent=self,
            )
            mode = self._play_with_browser()
            self._set_mode(mode)
            return
        # Auto fallback chain
        mode = self._play_with_mpc()
        if mode != "none":
            self._set_mode(mode)
            return
        mode = self._launch_vlc_app()
        if mode != "none":
            self._set_mode(mode)
            return
        mode = self._play_with_browser()
        self._set_mode(mode)

    # ----------------------------------------------------------------- UI helpers

    def _set_mode(self, mode: str) -> None:
        self._mode = mode
        if mode not in {"libvlc", "browser"}:
            self._is_paused = False
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

    def _update_volume_controls(self) -> None:
        self._mute_btn.SetValue(self._muted)
        label = "Muted" if self._muted or self._volume == 0 else f"{self._volume}%"
        self._volume_label.SetLabel(label)
        if not self._volume_control_available():
            self._volume_slider.SetValue(self._volume)

    def _notify_state(self) -> None:
        if not self._state_listener:
            return
        state = self.get_state()
        wx.CallAfter(self._state_listener, state)

    def _show_libvlc(self, visible: bool) -> None:
        self._video_panel.Show(visible)
        if visible:
            self._browser.Hide()
        else:
            self._browser.Show()
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
        candidates.extend(
            [
                r"C:\Program Files\VideoLAN\VLC\vlc.exe",
                r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
            ]
        )
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                self._vlc_path_cache = str(path)
                self._vlc_notified_missing = False
                return self._vlc_path_cache
        self._vlc_path_cache = None
        return None

    def _find_mpc(self) -> Optional[str]:
        if self._mpc_path_cache is not None:
            return self._mpc_path_cache
        candidates = []
        env_path = os.environ.get("MPC_PATH")
        if env_path:
            candidates.append(env_path)
        for candidate in ("mpc-hc64", "mpc-hc", "mpc-be64", "mpc-be"):
            which_path = which(candidate)
            if which_path:
                candidates.append(which_path)
        candidates.extend(
            [
                r"C:\Program Files\MPC-HC\mpc-hc64.exe",
                r"C:\Program Files (x86)\MPC-HC\mpc-hc.exe",
                r"C:\Program Files\MPC-BE x64\mpc-be64.exe",
                r"C:\Program Files (x86)\MPC-BE\mpc-be.exe",
            ]
        )
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate)
            if path.exists():
                self._mpc_path_cache = str(path)
                self._mpc_notified_missing = False
                return self._mpc_path_cache
        self._mpc_path_cache = None
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
        if python_32 and "Program Files (x86)" not in str(dir_path) and "Program Files" in str(dir_path):
            return (
                False,
                "This Python build is 32-bit. Please select the 32-bit VLC installation (Program Files (x86)\\VideoLAN\\VLC).",
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

    def _run_browser_script(self, script: str) -> None:
        try:
            self._browser.RunScript(script)
        except Exception:
            pass

    def _apply_browser_volume_settings(self) -> None:
        if not self._browser_controlled:
            return
        self._run_browser_script(
            f"var p=document.getElementById('player'); if(p){{p.volume={self._volume/100}; p.muted={'true' if self._muted else 'false'};}}"
        )

    def _can_control_transport(self) -> bool:
        return self._current is not None and (
            self._mode == "libvlc" or (self._mode == "browser" and self._browser_controlled)
        )

    def _volume_control_available(self) -> bool:
        return self._current is not None and (
            self._mode == "libvlc" or (self._mode == "browser" and self._browser_controlled)
        )

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

    def _element_for_url(self, url: str) -> Tuple[str, str]:
        lower = url.split("?", 1)[0].split("#", 1)[0].lower()
        if lower.endswith((".mp3", ".aac", ".m4a", ".flac")):
            return "audio", "audio/mpeg"
        if lower.endswith(".wav"):
            return "audio", "audio/wav"
        if lower.endswith(".ogg"):
            return "audio", "audio/ogg"
        if lower.endswith((".mp4", ".m4v", ".mov")):
            return "video", "video/mp4"
        if lower.endswith(".webm"):
            return "video", "video/webm"
        if lower.endswith(".ogv"):
            return "video", "video/ogg"
        if lower.endswith(".m3u8"):
            return "video", "application/vnd.apple.mpegurl"
        return "unknown", ""
