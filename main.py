import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple


def _evaluate_runtime_requirements() -> Tuple[List[str], List[str]]:
    """Return missing modules and modules that require a forced reinstall."""
    missing: List[str] = []
    reinstall: List[str] = []

    try:  # noqa: SIM105 - separate handling for ImportError vs general failure
        import wx  # noqa: F401
    except ImportError:
        missing.append("wx")
    except Exception as exc:  # noqa: BLE001 - capture runtime load issues
        reinstall.append(f"wx (import error: {exc.__class__.__name__})")

    try:
        import plexapi  # noqa: F401
    except ImportError:
        missing.append("plexapi")
    else:
        try:
            from plexapi import myplex  # noqa: F401
        except ImportError:
            reinstall.append("plexapi (cannot import plexapi.myplex)")

    try:
        import vlc  # noqa: F401
    except ImportError:
        missing.append("python-vlc")
    except FileNotFoundError:
        # python-vlc is installed but libvlc DLLs are not discoverable; runtime will handle.
        pass
    except Exception as exc:  # noqa: BLE001
        reinstall.append(f"python-vlc (import error: {exc.__class__.__name__})")
    return missing, reinstall

BOOTSTRAP_FLAG = "PLEX_CLIENT_BOOTSTRAPPED"


def ensure_requirements_installed() -> None:
    """Install required third-party packages if they are not available."""
    if getattr(sys, "frozen", False):
        return

    requirements_path = Path(__file__).with_name("requirements.txt")
    missing, reinstall = _evaluate_runtime_requirements()

    if not missing and not reinstall:
        return

    if os.environ.get(BOOTSTRAP_FLAG) == "1":
        details = ", ".join(missing + reinstall) or "unknown state"
        raise RuntimeError(
            f"Dependencies remain unresolved after automatic installation: {details}."
        )

    if not requirements_path.exists():
        raise RuntimeError(
            "Required dependencies are not available and requirements.txt is missing."
        )

    reasons = []
    if missing:
        reasons.append(f"missing: {', '.join(missing)}")
    if reinstall:
        reasons.append(f"needs reinstall: {', '.join(reinstall)}")

    print(
        f"Ensuring dependencies via {requirements_path.name} ({'; '.join(reasons)})...",
        file=sys.stderr,
        flush=True,
    )

    pip_args = [sys.executable, "-m", "pip", "install"]
    if reinstall:
        pip_args.extend(["--upgrade", "--force-reinstall"])
    pip_args.extend(["-r", str(requirements_path)])

    try:
        subprocess.check_call(pip_args)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Automatic dependency installation failed. "
            "Run 'python -m pip install -r requirements.txt' manually."
        ) from exc

    os.environ[BOOTSTRAP_FLAG] = "1"
    print("Dependencies installed. Restarting application...", file=sys.stderr, flush=True)
    os.execv(sys.executable, [sys.executable, *sys.argv])


ensure_requirements_installed()

import wx

from plex_client.auth import AuthManager
from plex_client.config import ConfigStore
from plex_client.ui.main_frame import MainFrame


def main() -> int:
    config = ConfigStore()
    auth_manager = AuthManager(config)
    app = wx.App()
    frame = MainFrame(config, auth_manager)
    frame.Show()
    return app.MainLoop()


if __name__ == "__main__":
    raise SystemExit(main())
