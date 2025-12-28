from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

import requests
import wx

from .config import ConfigStore
from .version import APP_NAME, APP_USER_AGENT, APP_VERSION


GITHUB_OWNER = "serrebi"
GITHUB_REPO = "Plexible"
APP_EXE_NAME = "Plexible.exe"
UPDATE_MANIFEST_NAME = "Plexible-update.json"
TRUSTED_SIGNING_THUMBPRINTS = {
    "9E12A2ECCBE8731BD034EC88761C766C4089EC0D",
}

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    asset_name: str
    download_url: str
    sha256: str
    published_at: str
    notes: str = ""
    signing_thumbprints: Tuple[str, ...] = ()


def _parse_version(version: str) -> Tuple[int, int, int]:
    match = _VERSION_RE.match(version.strip())
    if not match:
        raise ValueError(f"Unsupported version format: {version}")
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def _normalize_version(version: str) -> str:
    major, minor, patch = _parse_version(version)
    return f"{major}.{minor}.{patch}"


def _is_newer(candidate: str, current: str) -> bool:
    return _parse_version(candidate) > _parse_version(current)


def _get_update_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / APP_NAME / "updates"


def _safe_extract(archive: zipfile.ZipFile, target_dir: Path) -> None:
    target_dir = target_dir.resolve()
    for member in archive.infolist():
        member_path = (target_dir / member.filename).resolve()
        if member_path != target_dir and target_dir not in member_path.parents:
            raise UpdateError("Update archive contains an unsafe path.")
    archive.extractall(target_dir)


def _find_app_dir(staging_dir: Path) -> Path:
    if (staging_dir / APP_EXE_NAME).exists():
        return staging_dir
    subdirs = [p for p in staging_dir.iterdir() if p.is_dir()]
    for candidate in subdirs:
        if (candidate / APP_EXE_NAME).exists():
            return candidate
    raise UpdateError(f"Updated {APP_EXE_NAME} not found in extracted files.")


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _normalize_thumbprint(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace(" ", "").strip().upper()


def _normalize_thumbprints(values: Iterable[str]) -> Tuple[str, ...]:
    normalized = {_normalize_thumbprint(value) for value in values if value}
    normalized.discard("")
    return tuple(sorted(normalized))


def _env_thumbprints() -> Tuple[str, ...]:
    raw = os.environ.get("PLEXIBLE_TRUSTED_SIGNING_THUMBPRINTS", "")
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _extract_manifest_thumbprints(manifest: dict) -> Tuple[str, ...]:
    raw = manifest.get("signing_thumbprints") or manifest.get("signing_thumbprint")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if item)
    return ()


def _verify_authenticode(exe_path: Path, allowed_thumbprints: Iterable[str]) -> None:
    allowed = set(_normalize_thumbprints(allowed_thumbprints))
    command = (
        "$sig = Get-AuthenticodeSignature -LiteralPath "
        f"'{exe_path}'; "
        "$thumb = $null; "
        "if ($sig.SignerCertificate) { $thumb = $sig.SignerCertificate.Thumbprint }; "
        "$obj = [pscustomobject]@{ Status = $sig.Status.ToString(); StatusMessage = $sig.StatusMessage; Thumbprint = $thumb }; "
        "$obj | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise UpdateError(f"Authenticode verification failed: {result.stderr.strip() or result.stdout.strip()}")
    payload = (result.stdout or "").strip()
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        raise UpdateError(f"Authenticode verification failed: {payload or 'Invalid signature output.'}")
    status = str(data.get("Status") or "").strip()
    status_message = str(data.get("StatusMessage") or "").strip()
    thumbprint = _normalize_thumbprint(data.get("Thumbprint"))
    if status.lower() == "valid":
        return
    if thumbprint and thumbprint in allowed:
        return
    message = f"Authenticode status was {status or 'Unknown'}."
    if status_message:
        message = f"{message} {status_message}"
    if thumbprint:
        message = f"{message} (thumbprint {thumbprint})"
    raise UpdateError(message)


class UpdateManager:
    def __init__(
        self,
        parent: wx.Window,
        config: ConfigStore,
        *,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._parent = parent
        self._config = config
        self._status_callback = status_callback
        self._check_thread: Optional[threading.Thread] = None
        self._update_thread: Optional[threading.Thread] = None
        self._busy_info: Optional[wx.BusyInfo] = None
        self._auto_check_scheduled = False

    def is_auto_check_enabled(self) -> bool:
        return self._config.get_auto_check_updates()

    def set_auto_check_enabled(self, enabled: bool) -> None:
        self._config.set_auto_check_updates(enabled)

    def schedule_auto_check(self, delay_ms: int = 2500) -> None:
        if self._auto_check_scheduled or not self.is_auto_check_enabled():
            return
        self._auto_check_scheduled = True
        wx.CallLater(delay_ms, self.check_for_updates, False)

    def check_for_updates(self, interactive: bool = True) -> None:
        if self._check_thread and self._check_thread.is_alive():
            if interactive:
                self._show_message("An update check is already running.")
            return

        def worker() -> None:
            try:
                info = self._fetch_latest_update()
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._handle_check_error, exc, interactive)
                return
            wx.CallAfter(self._handle_check_result, info, interactive)

        self._check_thread = threading.Thread(target=worker, name="PlexibleUpdateCheck", daemon=True)
        self._check_thread.start()
        if interactive:
            self._set_status("Checking for updates...")

    def _handle_check_error(self, exc: Exception, interactive: bool) -> None:
        self._set_status("")
        if interactive:
            self._show_message(f"Unable to check for updates:\n{exc}", icon=wx.ICON_ERROR)

    def _handle_check_result(self, info: UpdateInfo, interactive: bool) -> None:
        self._set_status("")
        current_version = _normalize_version(APP_VERSION)
        if _is_newer(info.version, current_version):
            self._prompt_for_update(info)
            return
        if interactive:
            self._show_message(f"Plexible is up to date (v{current_version}).")

    def _prompt_for_update(self, info: UpdateInfo) -> None:
        current_version = _normalize_version(APP_VERSION)
        notes = (info.notes or "").strip()
        if notes and len(notes) > 500:
            notes = notes[:497] + "..."
        detail = f"Update available: v{info.version} (current v{current_version})."
        if notes:
            detail = f"{detail}\n\nRelease notes:\n{notes}"
        if not self._is_frozen():
            detail = (
                f"{detail}\n\nAutomatic updates are available only in the packaged app."
                f"\nDownload: {info.download_url}"
            )
            self._show_message(detail)
            return
        detail = f"{detail}\n\nDownload and install now? Plexible will restart."
        result = wx.MessageBox(
            detail,
            "Plexible Update Available",
            wx.YES_NO | wx.ICON_INFORMATION,
            parent=self._parent,
        )
        if result == wx.YES:
            self._start_update(info)

    def _start_update(self, info: UpdateInfo) -> None:
        if self._update_thread and self._update_thread.is_alive():
            self._show_message("An update is already in progress.")
            return

        self._busy_info = wx.BusyInfo("Downloading update...", parent=self._parent)

        def worker() -> None:
            try:
                staging_dir, backup_dir = self._download_and_stage(info)
            except Exception as exc:  # noqa: BLE001
                wx.CallAfter(self._handle_update_error, exc)
                return
            wx.CallAfter(self._finalize_update, staging_dir, backup_dir)

        self._update_thread = threading.Thread(target=worker, name="PlexibleUpdateApply", daemon=True)
        self._update_thread.start()

    def _handle_update_error(self, exc: Exception) -> None:
        self._clear_busy()
        self._show_message(f"Update failed:\n{exc}", icon=wx.ICON_ERROR)

    def _finalize_update(self, staging_dir: Path, backup_dir: Path) -> None:
        self._clear_busy()
        try:
            helper_path = self._prepare_helper()
            install_dir = Path(sys.executable).resolve().parent
            args = [
                "cmd",
                "/c",
                str(helper_path),
                str(install_dir),
                str(staging_dir),
                str(backup_dir),
                APP_EXE_NAME,
                str(os.getpid()),
            ]
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen(args, creationflags=creation_flags)
        except Exception as exc:  # noqa: BLE001
            self._show_message(f"Failed to launch updater:\n{exc}")
            return
        self._show_message("Update prepared. Plexible will close and restart.")
        self._parent.Close(True)

    def _download_and_stage(self, info: UpdateInfo) -> tuple[Path, Path]:
        if not self._is_frozen():
            raise UpdateError("Updates can only be installed from the packaged app.")

        update_root = _get_update_root()
        download_dir = update_root / "downloads"
        staging_root = update_root / "staging" / info.version
        backup_root = update_root / "backup" / info.version
        download_dir.mkdir(parents=True, exist_ok=True)
        if staging_root.exists():
            shutil.rmtree(staging_root, ignore_errors=True)
        staging_root.mkdir(parents=True, exist_ok=True)
        backup_root.mkdir(parents=True, exist_ok=True)

        archive_path = download_dir / info.asset_name
        self._set_status("Downloading update package...")
        with requests.get(info.download_url, stream=True, timeout=60, headers={"User-Agent": APP_USER_AGENT}) as resp:
            resp.raise_for_status()
            with archive_path.open("wb") as handle:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)

        self._set_status("Verifying update package...")
        actual_hash = _sha256_file(archive_path)
        if actual_hash.lower() != info.sha256.lower():
            raise UpdateError("Downloaded update failed SHA-256 verification.")

        self._set_status("Extracting update package...")
        with zipfile.ZipFile(archive_path) as archive:
            _safe_extract(archive, staging_root)

        app_dir = _find_app_dir(staging_root)
        exe_path = app_dir / APP_EXE_NAME
        self._set_status("Verifying update signature...")
        _verify_authenticode(exe_path, info.signing_thumbprints)

        return app_dir, backup_root

    def _fetch_latest_update(self) -> UpdateInfo:
        api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
        headers = {"Accept": "application/vnd.github+json", "User-Agent": APP_USER_AGENT}
        response = requests.get(api_url, headers=headers, timeout=15)
        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset")
            when = ""
            if reset and reset.isdigit():
                when = datetime.fromtimestamp(int(reset)).strftime("%Y-%m-%d %H:%M")
                when = f" (resets {when})"
            raise UpdateError(f"GitHub API rate limit exceeded{when}.")
        response.raise_for_status()
        release = response.json()
        tag_name = str(release.get("tag_name") or "").strip()
        if not tag_name:
            raise UpdateError("Latest release does not include a tag name.")
        assets = release.get("assets") or []
        manifest_asset = None
        for asset in assets:
            if asset.get("name") == UPDATE_MANIFEST_NAME:
                manifest_asset = asset
                break
        if not manifest_asset:
            raise UpdateError(f"{UPDATE_MANIFEST_NAME} not found in the latest release assets.")
        manifest_url = manifest_asset.get("browser_download_url")
        if not manifest_url:
            raise UpdateError("Update manifest download URL missing from release assets.")
        manifest_resp = requests.get(manifest_url, headers=headers, timeout=15)
        manifest_resp.raise_for_status()
        manifest = manifest_resp.json()

        version = str(manifest.get("version") or "").strip()
        asset_name = str(manifest.get("asset") or manifest.get("asset_name") or "").strip()
        download_url = str(manifest.get("download_url") or "").strip()
        sha256 = str(manifest.get("sha256") or "").strip()
        published_at = str(manifest.get("published_at") or release.get("published_at") or "").strip()
        notes = str(manifest.get("notes") or "").strip()
        manifest_thumbprints = _extract_manifest_thumbprints(manifest)
        allowed_thumbprints = _normalize_thumbprints(
            list(TRUSTED_SIGNING_THUMBPRINTS) + list(_env_thumbprints()) + list(manifest_thumbprints)
        )

        tag_version = _normalize_version(tag_name)
        if version and _normalize_version(version) != tag_version:
            raise UpdateError("Update manifest version does not match the release tag.")
        version = version or tag_version

        if not download_url and asset_name:
            for asset in assets:
                if asset.get("name") == asset_name:
                    download_url = str(asset.get("browser_download_url") or "").strip()
                    break

        if not asset_name or not download_url or not sha256:
            raise UpdateError("Update manifest is missing required fields.")

        return UpdateInfo(
            version=_normalize_version(version),
            asset_name=asset_name,
            download_url=download_url,
            sha256=sha256,
            published_at=published_at,
            notes=notes,
            signing_thumbprints=allowed_thumbprints,
        )

    def _prepare_helper(self) -> Path:
        update_root = _get_update_root()
        update_root.mkdir(parents=True, exist_ok=True)
        helper_target = update_root / "update_helper.bat"
        helper_source = self._helper_template_path()
        helper_target.write_text(helper_source.read_text(encoding="utf-8"), encoding="utf-8")
        return helper_target

    def _helper_template_path(self) -> Path:
        if self._is_frozen():
            return Path(sys.executable).resolve().parent / "update_helper.bat"
        return Path(__file__).resolve().with_name("update_helper.bat")

    def _set_status(self, message: str) -> None:
        if self._status_callback:
            wx.CallAfter(self._status_callback, message)

    def _clear_busy(self) -> None:
        self._busy_info = None

    def _show_message(self, message: str, *, icon: int = wx.ICON_INFORMATION, title: str = "Plexible") -> None:
        wx.MessageBox(message, title, wx.OK | icon, parent=self._parent)

    @staticmethod
    def _is_frozen() -> bool:
        return bool(getattr(sys, "frozen", False))
