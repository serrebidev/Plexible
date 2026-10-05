"""Tests for Plexible updater release targeting."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from plex_client import updater


@pytest.mark.parametrize("status", ["HashMismatch", "UnknownError", "NotSigned", "Incompatible"])
def test_pinned_certificate_does_not_override_invalid_signature(status, monkeypatch):
    result = SimpleNamespace(returncode=0, stdout=json.dumps({"Status": status, "Thumbprint": "ABCD"}), stderr="")
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: result)
    monkeypatch.setattr(updater, "_win_verify_trust", lambda path: 0x80096010, raising=False)
    with pytest.raises(updater.UpdateError):
        updater._verify_authenticode(Path("Plexible.exe"), ["ABCD"])


def test_valid_signature_requires_pinned_publisher(monkeypatch):
    result = SimpleNamespace(returncode=0, stdout=json.dumps({"Status": "Valid", "Thumbprint": "OTHER"}), stderr="")
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: result)
    with pytest.raises(updater.UpdateError):
        updater._verify_authenticode(Path("Plexible.exe"), ["ABCD"])


@pytest.mark.parametrize("status", ["Valid", "NotTrusted"])
def test_pinned_signature_accepts_valid_or_untrusted_chain(status, monkeypatch):
    result = SimpleNamespace(returncode=0, stdout=json.dumps({"Status": status, "Thumbprint": "ab cd"}), stderr="")
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: result)
    updater._verify_authenticode(Path("Plexible.exe"), ["ABCD"])


@pytest.mark.parametrize("native_status, accepted", [(0x800B0109, True), (0x80096010, False), (0x800B0101, False)])
def test_unknown_signature_error_requires_verified_untrusted_root(native_status, accepted, monkeypatch):
    result = SimpleNamespace(returncode=0, stdout='{"Status":"UnknownError","Thumbprint":"ABCD"}', stderr="")
    monkeypatch.setattr(updater.subprocess, "run", lambda *args, **kwargs: result)
    monkeypatch.setattr(updater, "_win_verify_trust", lambda path: native_status, raising=False)
    if accepted:
        updater._verify_authenticode(Path("Plexible.exe"), ["ABCD"])
    else:
        with pytest.raises(updater.UpdateError):
            updater._verify_authenticode(Path("Plexible.exe"), ["ABCD"])


def test_signature_path_with_apostrophe_is_escaped(monkeypatch):
    captured = []

    def run(args, **kwargs):
        captured.extend(args)
        return SimpleNamespace(returncode=0, stdout='{"Status":"Valid","Thumbprint":"ABCD"}', stderr="")

    monkeypatch.setattr(updater.subprocess, "run", run)
    updater._verify_authenticode(Path("O'Brien/Plexible.exe"), ["ABCD"])
    assert "'O''Brien/Plexible.exe'" in captured[-1].replace("\\", "/")


def test_downloaded_manifest_cannot_add_a_trusted_publisher(monkeypatch):
    release = {"tag_name": "v2.0.0", "assets": [{"name": "Plexible-update.json", "browser_download_url": "https://example.com/manifest"}]}
    manifest = {"version": "2.0.0", "asset": "Plexible-v2.0.0.zip", "download_url": "https://example.com/app.zip", "sha256": "a" * 64, "signing_thumbprint": "UNTRUSTED"}
    responses = iter([SimpleNamespace(status_code=200, headers={}, raise_for_status=lambda: None, json=lambda: release),
                      SimpleNamespace(raise_for_status=lambda: None, json=lambda: manifest)])
    monkeypatch.setattr(updater.requests, "get", lambda *args, **kwargs: next(responses))
    monkeypatch.delenv("PLEXIBLE_TRUSTED_SIGNING_THUMBPRINTS", raising=False)
    manager = updater.UpdateManager(None, Mock())
    info = manager._fetch_latest_update()
    assert "UNTRUSTED" not in info.signing_thumbprints
    assert "FB99DDCECA07B170E0A950F0C780AD899D28D770" in info.signing_thumbprints


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_unix_packaged_app_offers_manual_download(platform, monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", platform)
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    manager = updater.UpdateManager(None, Mock())
    messages = []
    monkeypatch.setattr(manager, "_show_message", messages.append)
    prompt = Mock(return_value=updater.wx.NO)
    monkeypatch.setattr(updater.wx, "MessageBox", prompt)
    manager._prompt_for_update(updater.UpdateInfo("2.0.0", "windows.zip", "https://example.com/windows.zip", "a" * 64, ""))
    assert len(messages) == 1
    assert "https://github.com/serrebidev/Plexible/releases/latest" in messages[0]
    prompt.assert_not_called()


def test_updater_targets_serrebidev_repo():
    from plex_client import updater

    assert updater.GITHUB_OWNER == "serrebidev"
    assert updater.GITHUB_REPO == "Plexible"
