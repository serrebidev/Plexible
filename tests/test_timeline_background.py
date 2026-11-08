"""Stop and seek send the position without blocking the window; closing still waits."""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from plex_client.plex_service import PlayableMedia
from plex_client.ui import main_frame


@pytest.fixture
def call_after(monkeypatch):
    calls = []
    monkeypatch.setattr(main_frame.wx, "CallAfter", lambda fn, *args, **kwargs: calls.append((fn, args)))
    return calls


def _frame(update_timeline, *, closing=False):
    frame = SimpleNamespace(
        _service=SimpleNamespace(update_timeline=update_timeline),
        _closing=closing,
        _last_positions={},
        _config=MagicMock(),
        _autoplay_pending_source=None,
        _last_queue_play_key="old",
        _timeline_threads=[],
        _prime_autoplay_candidate=lambda media: None,
        _cancel_autoplay_timer=lambda: None,
        _clear_radio_session_for_key=lambda key: None,
        _ingest_progress=MagicMock(name="ingest"),
        _refresh_watch_queues=MagicMock(name="refresh"),
        _schedule_queue_refresh=MagicMock(),
        _schedule_progress_flush=MagicMock(),
    )
    frame._config.get_pending_entry.return_value = {}
    return frame


def _movie():
    item = SimpleNamespace(ratingKey=93090, duration=6_632_256, type="movie")
    return PlayableMedia("Movie", "movie", "/library/metadata/93090", "", None, 0, item)


@pytest.mark.parametrize("state", ["stopped", "playing"])  # Stop, and the snapshot sent on a seek
def test_stop_and_seek_return_while_the_server_is_still_answering(call_after, state):
    release = threading.Event()
    called_on = []

    def slow_update(media, sent_state, position, duration):
        called_on.append(threading.current_thread())
        release.wait(5)
        return ("paused", position)

    frame = _frame(slow_update)
    media = _movie()
    main_frame.MainFrame._handle_timeline_update(frame, media, state, 3_748_885, 6_632_256, sync=True)

    # Back on the GUI thread although the server has not answered yet.
    assert frame._timeline_threads, "the update runs on a worker thread"
    worker = frame._timeline_threads[0]
    assert worker.is_alive()
    frame._ingest_progress.assert_not_called()
    if state == "stopped":
        assert media.resume_offset == 3_748_885, "playing it again right away resumes here"

    release.set()
    worker.join(5)
    assert called_on and called_on[0] is not threading.current_thread()
    posted = [fn for fn, _args in call_after]
    assert frame._ingest_progress in posted, "progress is recorded back on the GUI thread"
    assert (frame._refresh_watch_queues in posted) == (state == "stopped")


def test_continue_watching_is_refreshed_only_after_the_server_has_the_position(call_after):
    release = threading.Event()
    frame = _frame(lambda *args: (release.wait(5), ("paused", args[2]))[1])
    main_frame.MainFrame._handle_timeline_update(frame, _movie(), "stopped", 3_748_885, 6_632_256, sync=True)
    assert frame._refresh_watch_queues not in [fn for fn, _ in call_after]
    release.set()
    frame._timeline_threads[0].join(5)
    assert frame._refresh_watch_queues in [fn for fn, _ in call_after]


def test_closing_still_saves_before_the_window_goes_away(call_after):
    called_on = []

    def update(media, sent_state, position, duration):
        called_on.append(threading.current_thread())
        return ("paused", position)

    frame = _frame(update, closing=True)
    main_frame.MainFrame._handle_timeline_update(frame, _movie(), "stopped", 3_748_885, 6_632_256, sync=True)

    assert called_on == [threading.current_thread()], "closing waits for the server on the spot"
    assert frame._timeline_threads == []
    frame._ingest_progress.assert_called_once()
