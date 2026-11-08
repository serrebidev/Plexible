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

from plex_client import i18n
from plex_client.auth import AuthManager
from plex_client.config import ConfigStore
from plex_client.ui.main_frame import MainFrame


def relaunch() -> None:
    """Start a fresh Plexible process with the same arguments."""
    if getattr(sys, "frozen", False):
        args = [sys.executable, *sys.argv[1:]]
    else:
        args = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    subprocess.Popen(args, close_fds=True)


def main() -> int:
    config = ConfigStore()
    i18n.set_language(config.get_language())
    auth_manager = AuthManager(config)
    app = wx.App()
    restart_requested = []
    frame = MainFrame(config, auth_manager, on_restart_requested=lambda: restart_requested.append(True))
    frame.Show()
    result = app.MainLoop()
    # Relaunch only after the window has closed and saved playback progress,
    # so the two processes never write config.json at the same time.
    if restart_requested:
        relaunch()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
