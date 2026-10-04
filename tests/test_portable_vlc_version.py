from unittest.mock import Mock

import pytest
import requests

from plex_client.ui import playback


def test_portable_vlc_discovers_current_stable(monkeypatch):
    monkeypatch.delenv("PLEXIBLE_VLC_VERSION", raising=False)
    response = Mock(text="3.0.25\nhttps://get.videolan.org/vlc/3.0.25/\n")
    get = Mock(return_value=response)
    monkeypatch.setattr(playback.requests, "get", get)
    assert playback._portable_vlc_version("win64") == "3.0.25"
    assert get.call_args.args == ("https://update.videolan.org/vlc/status-win-x64",)


@pytest.mark.parametrize("failure", [requests.ConnectionError(), None])
def test_portable_vlc_uses_verified_fallback(monkeypatch, failure):
    monkeypatch.delenv("PLEXIBLE_VLC_VERSION", raising=False)
    monkeypatch.setattr(playback.requests, "get", Mock(
        side_effect=failure, return_value=Mock(text="../../unsafe")))
    assert playback._portable_vlc_version("win64") == "3.0.24"


def test_portable_vlc_explicit_override_avoids_network(monkeypatch):
    monkeypatch.setenv("PLEXIBLE_VLC_VERSION", "3.0.25")
    get = Mock()
    monkeypatch.setattr(playback.requests, "get", get)
    assert playback._portable_vlc_version("win32") == "3.0.25"
    get.assert_not_called()
    monkeypatch.setenv("PLEXIBLE_VLC_VERSION", "../../unsafe")
    with pytest.raises(ValueError):
        playback._portable_vlc_version("win32")
