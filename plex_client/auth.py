import os
import platform
import threading
import webbrowser
from typing import Callable, Optional

from plexapi.exceptions import Unauthorized
from plexapi.myplex import MyPlexAccount

try:  # pragma: no cover - compatibility shim for upstream renames
    from plexapi.myplex import MyPlexPin
except ImportError:
    from plexapi.myplex import MyPlexPinLogin as _MyPlexPinLogin

    class MyPlexPin:  # type: ignore[override]
        """Compatibility wrapper for newer plexapi versions lacking MyPlexPin."""

        def __init__(self, clientIdentifier: str) -> None:
            hostname = os.environ.get("COMPUTERNAME") or platform.node() or "PlexWxClient"
            headers = {
                "X-Plex-Client-Identifier": clientIdentifier,
                "X-Plex-Product": "PlexWxClient",
                "X-Plex-Device": platform.system() or "Desktop",
                "X-Plex-Device-Name": hostname,
            }
            self._login = _MyPlexPinLogin(headers=headers, oauth=True)

        @property
        def oauthUrl(self) -> str:
            return self._login.oauthUrl()

        @property
        def pin(self) -> Optional[str]:
            return getattr(self._login, "pin", None)

        def waitForAuthToken(self, timeout: Optional[int] = None) -> Optional[str]:
            self._login.run(timeout=timeout)
            if self._login.waitForLogin():
                return self._login.token
            return None

from .config import ConfigStore


class AuthError(Exception):
    """Domain specific error for authentication failures."""


AuthCallback = Callable[[bool, Optional[MyPlexAccount], Optional[Exception]], None]


class AuthManager:
    """Coordinates browser-based Plex authentication and token persistence."""

    def __init__(self, config: ConfigStore) -> None:
        self._config = config
        self._account: Optional[MyPlexAccount] = None

    @property
    def account(self) -> Optional[MyPlexAccount]:
        return self._account

    def load_saved_account(self) -> Optional[MyPlexAccount]:
        token = self._config.get_auth_token()
        if not token:
            return None
        try:
            self._account = MyPlexAccount(token=token)
        except Unauthorized as exc:
            # Token is not valid anymore.
            self._config.set_auth_token(None)
            raise AuthError("Saved Plex token is no longer valid.") from exc
        return self._account

    def sign_out(self) -> None:
        self._account = None
        self._config.set_auth_token(None)

    def authenticate_with_browser(self, callback: AuthCallback, timeout: int = 600) -> None:
        """Start a browser OAuth flow using the Plex PIN API."""

        def worker() -> None:
            try:
                pin = MyPlexPin(clientIdentifier=self._config.get_client_id())
                webbrowser.open(pin.oauthUrl)
                token = pin.waitForAuthToken(timeout=timeout)
                if not token:
                    raise AuthError("Authentication timed out before approval.")
                account = MyPlexAccount(token=token)
                self._config.set_auth_token(token)
                self._account = account
                callback(True, account, None)
            except Exception as exc:  # noqa: BLE001 - downstream consumers need to know the root error
                callback(False, None, exc)

        thread = threading.Thread(target=worker, name="PlexAuthThread", daemon=True)
        thread.start()
