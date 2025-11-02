import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class ConfigStore:
    """Handles reading and writing lightweight configuration for the client."""

    CONFIG_FILENAME = "config.json"
    LEGACY_DIR = Path.home() / "AppData" / "Roaming" / "PlexWxClient"

    def __init__(self) -> None:
        self._config_dir = self._resolve_config_dir()
        self._config_path = self._config_dir / self.CONFIG_FILENAME
        self._data: Dict[str, Any] = {}
        self._loaded = False
        self._migrate_legacy_config()

    def _resolve_config_dir(self) -> Path:
        candidates = list(self._iter_candidate_dirs())
        for candidate in candidates:
            config_path = candidate / self.CONFIG_FILENAME
            if config_path.exists():
                return candidate
        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                return candidate
            except OSError:
                continue
        fallback = Path.cwd()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _iter_candidate_dirs(self) -> Iterable[Path]:
        override = os.environ.get("PLEXIBLE_CONFIG_DIR")
        if override:
            yield Path(override).resolve()
        script_path = self._script_directory()
        if script_path:
            yield script_path
        package_dir = Path(__file__).resolve().parent.parent
        yield package_dir

    def _script_directory(self) -> Optional[Path]:
        try:
            if getattr(sys, "frozen", False):  # support PyInstaller-style bundles
                return Path(sys.executable).resolve().parent
            if sys.argv:
                return Path(sys.argv[0]).resolve().parent
        except Exception:
            return None
        return None

    def _migrate_legacy_config(self) -> None:
        legacy_path = self.LEGACY_DIR / self.CONFIG_FILENAME
        if not legacy_path.exists():
            return
        if self._config_path.exists():
            return
        try:
            legacy_data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        self._config_dir.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(legacy_data, indent=2), encoding="utf-8")

    @property
    def data(self) -> Dict[str, Any]:
        if not self._loaded:
            self._data = self._load_from_disk()
            self._loaded = True
        return self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self._save_to_disk()

    def clear(self, key: str) -> None:
        if key in self.data:
            del self.data[key]
            self._save_to_disk()

    def _default_config(self) -> Dict[str, Any]:
        return {
            "client_id": uuid.uuid4().hex,
            "auth_token": None,
            "selected_server": None,
            "vlc_path": None,
            "pending_progress": {},
        }

    def _load_from_disk(self) -> Dict[str, Any]:
        if not self._config_path.exists():
            return self._default_config()
        try:
            with self._config_path.open("r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (json.JSONDecodeError, OSError):
            data = self._default_config()
        if "client_id" not in data or not data["client_id"]:
            data["client_id"] = uuid.uuid4().hex
        return data

    def _save_to_disk(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self._config_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fp:
            json.dump(self.data, fp, indent=2)
        tmp_path.replace(self._config_path)

    def get_client_id(self) -> str:
        client_id = self.get("client_id")
        if not client_id:
            client_id = uuid.uuid4().hex
            self.set("client_id", client_id)
        return client_id

    def get_auth_token(self) -> Optional[str]:
        return self.get("auth_token")

    def set_auth_token(self, token: Optional[str]) -> None:
        if token:
            self.set("auth_token", token)
        else:
            self.clear("auth_token")

    def get_selected_server(self) -> Optional[str]:
        return self.get("selected_server")

    def set_selected_server(self, identifier: Optional[str]) -> None:
        if identifier:
            self.set("selected_server", identifier)
        else:
            self.clear("selected_server")

    def get_vlc_path(self) -> Optional[str]:
        return self.get("vlc_path")

    def set_vlc_path(self, path: Optional[str]) -> None:
        if path:
            self.set("vlc_path", path)
        else:
            self.clear("vlc_path")

    def get_pending_progress(self) -> Dict[str, Dict[str, int]]:
        stored = self.get("pending_progress", {})
        if isinstance(stored, dict):
            return {str(k): dict(v) for k, v in stored.items() if isinstance(v, dict)}
        return {}

    def get_pending_entry(self, rating_key: str) -> Dict[str, int]:
        progress = self.get_pending_progress()
        return progress.get(str(rating_key), {})

    def upsert_pending_progress(self, rating_key: str, position: int, duration: int, state: str = "playing") -> None:
        progress = self.get_pending_progress()
        progress[str(rating_key)] = {
            "position": int(max(0, position)),
            "duration": int(max(0, duration)),
            "state": state,
        }
        self.set("pending_progress", progress)

    def remove_pending_progress(self, rating_key: str) -> None:
        progress = self.get_pending_progress()
        if str(rating_key) in progress:
            del progress[str(rating_key)]
            self.set("pending_progress", progress)

    def clear_pending_progress(self) -> None:
        self.set("pending_progress", {})

