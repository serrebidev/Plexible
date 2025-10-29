import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigStore:
    """Handles reading and writing lightweight configuration for the client."""

    CONFIG_FILENAME = "config.json"
    def __init__(self) -> None:
        self._config_dir = Path(__file__).resolve().parent.parent
        self._config_path = self._config_dir / self.CONFIG_FILENAME
        self._data: Dict[str, Any] = {}
        self._loaded = False

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
