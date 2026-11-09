"""Tests for the Forgejo release helper (mocked HTTP, no network)."""
from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from tools import forgejo_release


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(url, code):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(b"{}"))


def test_split_repo_url_handles_common_remote_forms():
    from tools import release_tool

    assert release_tool._split_repo_url("https://git.serrebiradio.com/serrebi/Plexible.git") == (
        "git.serrebiradio.com", "serrebi", "Plexible")
    assert release_tool._split_repo_url("git@github.com:serrebidev/Plexible.git") == (
        "github.com", "serrebidev", "Plexible")
    assert release_tool._split_repo_url("not a url") is None


def test_repo_origin_prefers_forgejo_remote(monkeypatch, capsys):
    from tools import release_tool

    urls = {"forgejo": "https://git.serrebiradio.com/serrebi/Plexible.git",
            "origin": "https://github.com/serrebidev/Plexible.git"}
    monkeypatch.setattr(release_tool, "_run_git", lambda *args: urls[args[2]])
    assert release_tool._repo_origin(SimpleNamespace()) == 0
    out = capsys.readouterr().out
    assert "REPO_HOST=git.serrebiradio.com" in out
    assert "REPO_OWNER=serrebi" in out
    assert "REPO_NAME=Plexible" in out


def test_repo_origin_falls_back_to_origin(monkeypatch, capsys):
    from tools import release_tool

    def fake_run_git(*args):
        if args[2] == "forgejo":
            raise OSError("no such remote")
        return "https://github.com/serrebidev/Plexible.git"

    monkeypatch.setattr(release_tool, "_run_git", fake_run_git)
    assert release_tool._repo_origin(SimpleNamespace()) == 0
    out = capsys.readouterr().out
    assert "REPO_HOST=github.com" in out
    assert "REPO_OWNER=serrebidev" in out


def _patch_urlopen(monkeypatch, handler):
    calls = []

    def fake_urlopen(request, *args, **kwargs):
        calls.append(request)
        return handler(request)

    monkeypatch.setattr(forgejo_release.urllib.request, "urlopen", fake_urlopen)
    return calls


def _json_response(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def test_get_release_by_tag_returns_none_on_404(monkeypatch):
    def handler(request):
        raise _http_error(request.full_url, 404)

    _patch_urlopen(monkeypatch, handler)
    assert forgejo_release.get_release_by_tag("h", "o", "r", "v9.9.9", "tok") is None


def test_create_release_posts_expected_payload(monkeypatch):
    calls = _patch_urlopen(monkeypatch, lambda req: _json_response({"id": 1, "tag_name": "v2.0.0"}))
    release = forgejo_release.create_release("h", "o", "r", "v2.0.0", "tok", "v2.0.0", "notes")
    assert release["id"] == 1
    assert calls[0].get_method() == "POST"
    assert calls[0].full_url == "https://h/api/v1/repos/o/r/releases"
    assert calls[0].get_header("Authorization") == "token tok"
    payload = json.loads(calls[0].data.decode("utf-8"))
    assert payload == {"tag_name": "v2.0.0", "name": "v2.0.0", "body": "notes",
                       "draft": False, "prerelease": False}


def test_upload_assets_replaces_same_name_asset(monkeypatch, tmp_path):
    asset = tmp_path / "Plexible-v2.0.0.zip"
    asset.write_bytes(b"zip-bytes")
    release = {"id": 7, "tag_name": "v2.0.0",
               "assets": [{"id": 3, "name": "Plexible-v2.0.0.zip"}]}

    def handler(request):
        url = request.full_url
        if request.get_method() == "GET":
            return _json_response(release)
        if request.get_method() == "DELETE":
            assert url == "https://h/api/v1/repos/o/r/releases/7/assets/3"
            return FakeResponse(b"")
        assert request.get_method() == "POST"
        assert "releases/7/assets?name=" in url
        assert b"zip-bytes" in request.data
        return _json_response({"id": 4, "name": asset.name})

    calls = _patch_urlopen(monkeypatch, handler)
    out = forgejo_release.upload_assets("h", "o", "r", "v2.0.0", "tok", [asset])
    assert out["id"] == 7
    methods = [c.get_method() for c in calls]
    assert methods == ["GET", "DELETE", "POST", "GET"]


def test_upload_assets_missing_release_raises(monkeypatch, tmp_path):
    asset = tmp_path / "a.zip"
    asset.write_bytes(b"x")

    def handler(request):
        raise _http_error(request.full_url, 404)

    _patch_urlopen(monkeypatch, handler)
    with pytest.raises(forgejo_release.ForgejoError, match="No Forgejo release"):
        forgejo_release.upload_assets("h", "o", "r", "v0.0.0", "tok", [asset])


def test_create_command_requires_a_token(monkeypatch):
    monkeypatch.delenv("FORGEJO_TOKEN", raising=False)
    args = SimpleNamespace(tag="v2.0.0", assets=[], title="", notes_file="",
                           host="h", owner="o", repo="r", token="")
    with pytest.raises(forgejo_release.ForgejoError, match="token is required"):
        forgejo_release._cmd_create(args)
