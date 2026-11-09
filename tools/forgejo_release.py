"""Forgejo release helper for Plexible.

Creates Forgejo releases and uploads assets with clobber semantics. This
replaces `gh release create` / `gh release upload` now that releases live on
https://git.serrebiradio.com/serrebi/Plexible. Stdlib only.

Token from --token or the FORGEJO_TOKEN environment variable.

    python tools/forgejo_release.py create vX.Y.Z a.zip b.json --title vX.Y.Z --notes-file notes.md
    python tools/forgejo_release.py upload vX.Y.Z file.tar.gz
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_HOST = "git.serrebiradio.com"
DEFAULT_OWNER = "serrebi"
DEFAULT_REPO = "Plexible"


class ForgejoError(RuntimeError):
    pass


def _api_url(host: str, path: str) -> str:
    return f"https://{host}/api/v1{path}"


def _request(
    method: str,
    url: str,
    token: str,
    data: bytes | None = None,
    content_type: str | None = None,
) -> Any:
    headers = {"Authorization": f"token {token}", "Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        with contextlib.suppress(OSError):
            detail = exc.read().decode("utf-8", "replace")
        raise ForgejoError(f"{method} {url} failed: HTTP {exc.code} {detail}".strip()) from exc
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return body


def get_release_by_tag(host: str, owner: str, repo: str, tag: str, token: str) -> dict[str, Any] | None:
    quoted = urllib.parse.quote(tag, safe="")
    url = _api_url(host, f"/repos/{owner}/{repo}/releases/tags/{quoted}")
    try:
        result = _request("GET", url, token)
    except ForgejoError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    return result


def create_release(
    host: str,
    owner: str,
    repo: str,
    tag: str,
    token: str,
    title: str,
    notes: str,
) -> dict[str, Any]:
    url = _api_url(host, f"/repos/{owner}/{repo}/releases")
    payload = json.dumps(
        {
            "tag_name": tag,
            "name": title or tag,
            "body": notes,
            "draft": False,
            "prerelease": False,
        }
    ).encode("utf-8")
    return _request("POST", url, token, data=payload, content_type="application/json")


def delete_asset(host: str, owner: str, repo: str, release_id: int, asset_id: int, token: str) -> None:
    url = _api_url(host, f"/repos/{owner}/{repo}/releases/{release_id}/assets/{asset_id}")
    try:
        _request("DELETE", url, token)
    except ForgejoError as exc:
        if "HTTP 404" in str(exc):
            return
        raise


def upload_asset(
    host: str,
    owner: str,
    repo: str,
    release_id: int,
    asset_path: Path,
    token: str,
) -> dict[str, Any]:
    boundary = "----plexible-forgejo-upload"
    filename = asset_path.name
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="attachment"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    footer = f"\r\n--{boundary}--\r\n".encode()
    body = header + asset_path.read_bytes() + footer
    query = urllib.parse.urlencode({"name": filename})
    url = _api_url(host, f"/repos/{owner}/{repo}/releases/{release_id}/assets?{query}")
    return _request("POST", url, token, data=body, content_type=f"multipart/form-data; boundary={boundary}")


def upload_assets(
    host: str,
    owner: str,
    repo: str,
    tag: str,
    token: str,
    assets: list[Path],
) -> dict[str, Any]:
    release = get_release_by_tag(host, owner, repo, tag, token)
    if release is None:
        raise ForgejoError(f"No Forgejo release found for tag {tag}.")
    release_id = int(release["id"])
    existing = {asset.get("name"): asset.get("id") for asset in release.get("assets") or []}
    for asset_path in assets:
        if not asset_path.is_file():
            raise ForgejoError(f"Asset not found: {asset_path}")
        old_id = existing.get(asset_path.name)
        if old_id is not None:
            delete_asset(host, owner, repo, release_id, int(old_id), token)
        uploaded = upload_asset(host, owner, repo, release_id, asset_path, token)
        existing[asset_path.name] = uploaded.get("id")
    release = get_release_by_tag(host, owner, repo, tag, token)
    if release is None:  # pragma: no cover - release vanished mid-upload
        raise ForgejoError(f"Forgejo release for tag {tag} disappeared during upload.")
    return release


def _resolve_token(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get("FORGEJO_TOKEN", "")
    if not token:
        raise ForgejoError("A Forgejo API token is required (--token or FORGEJO_TOKEN).")
    return token


def _cmd_create(args: argparse.Namespace) -> int:
    token = _resolve_token(args)
    notes = Path(args.notes_file).read_text(encoding="utf-8") if args.notes_file else ""
    release = get_release_by_tag(args.host, args.owner, args.repo, args.tag, token)
    if release is None:
        release = create_release(args.host, args.owner, args.repo, args.tag, token, args.title or args.tag, notes)
        print(f"Created Forgejo release {args.tag} (id {release.get('id')}).")
    else:
        print(f"Forgejo release {args.tag} already exists (id {release.get('id')}); uploading assets.")
    assets = [Path(path) for path in args.assets]
    if assets:
        upload_assets(args.host, args.owner, args.repo, args.tag, token, assets)
        for asset in assets:
            print(f"Uploaded {asset.name} to {args.tag}.")
    return 0


def _cmd_upload(args: argparse.Namespace) -> int:
    token = _resolve_token(args)
    assets = [Path(path) for path in args.assets]
    upload_assets(args.host, args.owner, args.repo, args.tag, token, assets)
    for asset in assets:
        print(f"Uploaded {asset.name} to {args.tag}.")
    return 0


def _add_repo_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--owner", default=DEFAULT_OWNER)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--token", default="")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create Forgejo releases and upload assets.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="Create a release (or reuse it) and upload assets.")
    create_parser.add_argument("tag")
    create_parser.add_argument("assets", nargs="*")
    create_parser.add_argument("--title", default="")
    create_parser.add_argument("--notes-file", default="")
    _add_repo_args(create_parser)
    create_parser.set_defaults(func=_cmd_create)

    upload_parser = subparsers.add_parser("upload", help="Upload assets to an existing release.")
    upload_parser.add_argument("tag")
    upload_parser.add_argument("assets", nargs="+")
    _add_repo_args(upload_parser)
    upload_parser.set_defaults(func=_cmd_upload)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ForgejoError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
