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
            try:
                return self._login.pin
            except Exception:
                # OAuth logins raise instead of exposing a four character PIN.
                return None

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

    def authenticate_with_browser(
        self,
        callback: AuthCallback,
        timeout: int = 600,
        on_pin_ready: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        """Start a browser OAuth flow using the Plex PIN API.

        If *on_pin_ready* is provided, it is called (on any thread!) with
        the PIN code and OAuth URL so the UI can display them for manual entry.
        """

        def worker() -> None:
            try:
                pin = MyPlexPin(clientIdentifier=self._config.get_client_id())
                # hasattr()/getattr() must not be used to probe these: they are
                # properties that raise (BadRequest for a PIN on an OAuth login),
                # and only AttributeError would be swallowed by getattr defaults.
                try:
                    pin_code = str(pin.pin or "")
                except Exception:
                    pin_code = ""
                oauth_url = str(pin.oauthUrl or "")
                if not oauth_url:
                    # Without a URL the flow can only sit until the timeout expires.
                    raise AuthError("Plex did not return a sign-in URL.")
                opened = webbrowser.open(oauth_url)
                # Always notify the UI of the PIN code / URL so the user can
                # paste them manually if the browser did not open.
                if on_pin_ready:
                    on_pin_ready(pin_code or "???", oauth_url or "https://plex.tv/link")
                if not opened:
                    print(f"[Auth] Browser may not have opened. PIN: {pin_code} URL: {oauth_url}")
                token = pin.waitForAuthToken(timeout=timeout)
                if not token:
                    raise AuthError("Authentication timed out before approval.")
                account = MyPlexAccount(token=token)
                self._config.set_auth_token(token)
                self._account = account
                callback(True, account, None)
            except Exception as exc:  # noqa: BLE001
                callback(False, None, exc)

        thread = threading.Thread(target=worker, name="PlexAuthThread", daemon=True)
        thread.start()
