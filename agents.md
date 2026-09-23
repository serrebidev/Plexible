# Agent Knowledge Base - Plexible

## Project Overview
Plexible is a lightweight, wxPython-based Plex client for Windows. It provides a native interface for browsing Plex libraries, managing watch queues (Continue Watching/Up Next), and playing media via LibVLC.

## Key Technical Insights

### Dependency Management
- **Core Dependencies**: `wxPython`, `plexapi` (custom fork), `python-vlc`, `requests`.
- **Bootstrap Mechanism**: `main.py` contains a `_evaluate_runtime_requirements` function that checks for missing modules at startup and attempts to auto-install them via `pip` if they are missing or broken.

### VLC Integration & Playback
- **LibVLC Bootstrapping**: `plex_client/ui/playback.py` handles a complex VLC environment setup. It looks for local VLC installations or **automatically downloads a portable VLC version** (3.0.20) to `LOCALAPPDATA/Plexible/vlc` if no system VLC is found.
- **Playback Modes**: Primarily uses `libvlc` for integrated playback within the UI. It handles both HLS and Direct streams.
- **Fallback Sources**: LibVLC startup tries multiple candidate stream URLs (direct then fallback/HLS) before giving up.

### Configuration & Persistence
- **ConfigStore**: Managed in `plex_client/config.py`. It resolves the config path based on environment variables or the script location, defaulting to the project root or AppData for legacy migrations.
- **Authentication**: Uses a Plex PIN OAuth flow via `AuthManager` (`plex_client/auth.py`). Tokens are stored in `config.json`.

### Build System (PyInstaller)
- **Spec File**: `plexible.spec` is the source of truth for builds.
- **Distribution Mode**: Switched from `--onefile` to directory-based builds (`--onedir`) to resolve execution issues on some user systems.
- **Submodule Collection**: Use `collect_submodules` for `plexapi`, `plex_client`, `wx`, `requests`, `urllib3`, and `vlc`.
- **wxPython Issues**: Collecting all submodules for `wx` ensures UI stability but may trigger deprecation warnings (e.g., `wx.lib.pubsub`). These are expected and don't halt the build.
- **Hidden Imports**: Standard libraries like `concurrent.futures`, `urllib3`, and `ctypes`, plus `requests` dependencies (`certifi`, `idna`, `charset_normalizer`) should be explicitly listed to ensure they are available in the frozen bundle.

## Build & Release
- Local releases (this Windows host) stay Windows-only: `build_exe.bat release` (see BUILD.md).
- Cloud agents ONLY: `.github/workflows/cloud-release.yml` builds every platform on GitHub runners. Windows runs the same `build_exe.bat release`, signed from the `WINDOWS_CODESIGN_PFX`/`WINDOWS_CODESIGN_PASSWORD` secrets (thumbprint `FB99DDCECA07B170E0A950F0C780AD899D28D770`, pinned in `plex_client/updater.py`); the job fails unless `Plexible.exe` is signed by that cert. macOS (`Plexible-vX.Y.Z-macos.zip`) and Linux (`Plexible-vX.Y.Z-linux-x86_64.tar.gz`) then build the tag with `build.sh` and attach. Both need VLC installed by the user. `gh workflow run cloud-release.yml -f dry_run=true` builds all three as artifacts, publishes nothing; `-f dry_run=false` is real. Watch: `gh run watch <id> --exit-status`. Never run it while `build_exe.bat release` runs (both bump from the latest tag). It replaced the old `codex-release.yml`, which signed with a throwaway cert.
- `wx.Accessible` exists only on Windows; `content_panel.py` turns `SetAccessible`/`NamedAccessible` into no-ops elsewhere (GTK raised NotImplementedError at startup). Test Linux over `ssh root@serrebiradio.com` (Debian 13, distro `python3-wxgtk4.0` in a `--system-site-packages` venv, `xvfb-run`).

## Instructions for Future Agents
- **Build Quality**: Always fix any warnings, bugs, or errors encountered during the build process when possible. Do not ignore or skip over them.
- **Testing**: When adding features, test within the frozen environment context (check `sys.frozen`) as path resolution for `config.json` and assets changes.
- **VLC Pathing**: If playback fails in a build, verify the `PYTHON_VLC_MODULE_PATH` environment variable which is set dynamically by the app.
- **PlexAPI**: Always ensure the `plexapi` fork from `pushingkarmaorg` is used, as it contains specific fixes or features relied upon by the service layer.
