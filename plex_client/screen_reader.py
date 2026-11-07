"""Speak short messages through NVDA.

Adapted from BlindRSS (core/screen_reader_announce.py, MIT, serrebidev).

wx has no reliable way to make a screen reader read a status change: the
status bar has no accessible object and NVDA ignores the events wx can fire.
The NVDA controller client DLL talks to NVDA directly. It ships next to the
app (see tools/ensure_nvda_controller_client.py) and every call fails closed,
so the app behaves exactly as before when NVDA or the DLL is missing.

Windows only: elsewhere, and without NVDA, speak() does nothing.
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from pathlib import Path
from typing import List, Optional

LOG = logging.getLogger(__name__)

_DLL_NAMES = ("nvdaControllerClient.dll", "nvdaControllerClient64.dll")

_lock = threading.Lock()
_nvda_dll = None
_load_attempted = False


def speak(message: str, *, interrupt: bool = False) -> bool:
    """Speak ``message`` with NVDA. Returns True only if NVDA accepted it.

    ``interrupt`` cuts off whatever NVDA is saying first; use it for answers
    to something the user just did. Background status messages should not
    interrupt, so they never talk over what the user is reading.
    """
    text = str(message or "").strip()
    if not text or not sys.platform.startswith("win"):
        return False
    dll = _load_nvda_controller()
    if dll is None:
        return False
    try:
        if int(dll.nvdaController_testIfRunning()) != 0:
            return False
        if interrupt:
            try:
                dll.nvdaController_cancelSpeech()
            except Exception:
                pass
        return int(dll.nvdaController_speakText(text)) == 0
    except Exception as exc:
        LOG.debug("NVDA controller speech failed: %s", exc)
        return False


def _load_nvda_controller():
    global _nvda_dll, _load_attempted
    with _lock:
        if _load_attempted:
            return _nvda_dll
        _load_attempted = True
        for dll_path in _controller_candidates():
            try:
                dll = ctypes.WinDLL(str(dll_path))
                dll.nvdaController_testIfRunning.argtypes = []
                dll.nvdaController_testIfRunning.restype = ctypes.c_ulong
                dll.nvdaController_speakText.argtypes = [ctypes.c_wchar_p]
                dll.nvdaController_speakText.restype = ctypes.c_ulong
                dll.nvdaController_cancelSpeech.argtypes = []
                dll.nvdaController_cancelSpeech.restype = ctypes.c_ulong
            except Exception as exc:
                LOG.debug("Could not load NVDA controller client from %s: %s", dll_path, exc)
                continue
            _nvda_dll = dll
            break
        return _nvda_dll


def _controller_candidates() -> List[Path]:
    roots: List[Path] = []
    env_path = os.environ.get("PLEXIBLE_NVDA_CONTROLLER_DLL")
    if env_path:
        roots.append(Path(env_path))
    try:
        roots.append(Path(sys.executable).resolve().parent)
    except Exception:
        pass
    meipass: Optional[str] = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    # Running from source: the repository root.
    roots.append(Path(__file__).resolve().parents[1])

    found: List[Path] = []
    seen = set()
    for root in roots:
        if root.suffix.lower() == ".dll":
            paths = [root]
        else:
            folders = (root, root / "bin", root / "_internal", root / "_internal" / "bin")
            paths = [folder / name for folder in folders for name in _DLL_NAMES]
        for path in paths:
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            if path.is_file():
                found.append(path)
    return found


def _reset_for_tests() -> None:
    global _nvda_dll, _load_attempted
    with _lock:
        _nvda_dll = None
        _load_attempted = False
