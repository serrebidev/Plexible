"""First run without VLC: never download while loading, download in the background on first play."""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from plex_client.ui import playback


def _no_network(*_args, **_kwargs):
    raise AssertionError("no network access expected here")


@pytest.fixture
def portable_root(tmp_path, monkeypatch):
    monkeypatch.setattr(playback, "_portable_vlc_base_dir", lambda: tmp_path)
    return tmp_path


def _fake_vlc(root, version):
    folder = root / "win64" / f"vlc-{version}-win64" / f"vlc-{version}"
    folder.mkdir(parents=True)
    (folder / "libvlc.dll").write_bytes(b"")
    return folder


def test_loading_the_module_never_downloads_vlc(monkeypatch, portable_root):
    """This runs at import time, before any window: no download, no version lookup."""
    monkeypatch.setattr(playback, "_LIBVLC_BOOTSTRAPPED", False)
    monkeypatch.delenv("PYTHON_VLC_MODULE_PATH", raising=False)
    monkeypatch.delenv("VLC_PATH", raising=False)
    monkeypatch.setenv("ProgramFiles", str(portable_root / "none"))
    monkeypatch.setenv("ProgramFiles(x86)", str(portable_root / "none"))
    monkeypatch.setattr(playback.requests, "get", _no_network)
    monkeypatch.setattr(playback, "_ensure_portable_vlc", _no_network)
    monkeypatch.setattr(playback.os, "name", "nt")

    playback._bootstrap_libvlc_environment()

    assert "PYTHON_VLC_MODULE_PATH" not in playback.os.environ


def test_an_earlier_download_is_found_without_the_network(monkeypatch, portable_root):
    _fake_vlc(portable_root, "3.0.20")
    newest = _fake_vlc(portable_root, "3.0.24")
    monkeypatch.setattr(playback.requests, "get", _no_network)
    assert playback._find_portable_vlc("win64") == newest
    assert playback._ensure_portable_vlc("win64") == newest


def test_download_reports_its_progress(monkeypatch, portable_root):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("vlc-3.0.24/libvlc.dll", b"x" * 4000)
    data = archive.getvalue()
    chunks = [data[i : i + 1000] for i in range(0, len(data), 1000)]

    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {"Content-Length": str(len(data))}
    response.iter_content.return_value = chunks
    monkeypatch.setattr(playback.requests, "get", lambda *a, **k: response)
    monkeypatch.setattr(playback, "_portable_vlc_version", lambda arch: "3.0.24")

    seen = []
    path = playback._ensure_portable_vlc("win64", seen.append)

    assert path is not None and (path / "libvlc.dll").exists()
    assert seen == sorted(seen) and seen[-1] == 100


def test_progress_is_spoken_a_quarter_at_a_time(monkeypatch):
    spoken = []
    monkeypatch.setattr(playback.screen_reader, "speak", lambda text, interrupt=False: spoken.append((text, interrupt)))
    panel = SimpleNamespace(_header=MagicMock(), _is_destroying=lambda: False, _vlc_download_spoken=0)
    for percent in range(0, 101):
        playback.PlaybackPanel._on_vlc_download_progress(panel, percent)
    assert spoken == [("VLC 25%", False), ("VLC 50%", False), ("VLC 75%", False)]


def test_playback_starts_by_itself_once_vlc_is_ready(monkeypatch, portable_root):
    lib_dir = _fake_vlc(portable_root, "3.0.24")
    monkeypatch.delenv("PYTHON_VLC_MODULE_PATH", raising=False)
    media = object()
    panel = SimpleNamespace(
        _vlc_download_thread=object(),
        _vlc_download_media=media,
        _current=None,
        _libvlc_env_prepared=True,
        _is_destroying=lambda: False,
        _announce_accessible=MagicMock(),
        play=MagicMock(),
    )

    playback.PlaybackPanel._on_vlc_download_done(panel, lib_dir)

    assert playback.os.environ["PYTHON_VLC_MODULE_PATH"] == str(lib_dir)
    assert panel._libvlc_env_prepared is False
    panel._announce_accessible.assert_called_once_with("VLC is ready.")
    panel.play.assert_called_once_with(media)


def test_play_without_vlc_starts_the_download_instead_of_failing(monkeypatch):
    started = []
    panel = SimpleNamespace(
        _current=None,
        _vlc_download_needed=lambda: True,
        _start_vlc_download=started.append,
        _notify_timeline_state=MagicMock(),
        _halt_current_playback=MagicMock(),
        _start_offset=lambda media: 0,
        _play_with_libvlc=_no_network,
    )
    media = SimpleNamespace(stream_url="http://server/stream", browser_url=None, resume_offset=0)

    assert playback.PlaybackPanel.play(panel, media) == "downloading"
    assert started == [media]
    assert panel._current is None


def test_no_streaming_status_while_vlc_downloads():
    """The status said "Streaming ... via player" although nothing was playing yet."""
    from plex_client.ui import main_frame

    frame = SimpleNamespace(
        _active_queue_session=None,
        _nav_tree=MagicMock(),
        _queue_last_focus_index=0,
        _playlist_launching=False,
        _selected_playlist=None,
        _selected_object=None,
        _service=None,
        _schedule_progress_flush=MagicMock(),
        _playback_panel=SimpleNamespace(play=lambda media: "downloading"),
        _set_status=MagicMock(),
    )
    media = SimpleNamespace(item=SimpleNamespace(ratingKey=None), title="Song", media_type="track")

    main_frame.MainFrame._start_playback(frame, media)

    frame._set_status.assert_not_called()
