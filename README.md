# Plexible

Plexible is a desktop Plex client built with wxPython and the latest [`python-plexapi`](https://github.com/pushingkarmaorg/python-plexapi) fork. It supports browser-based authentication, browsing any Plex library, and streaming video or audio through an embedded VLC.

## Features
- Plex account sign-in using the official browser PIN flow.
- Automatic discovery of your Plex servers and libraries.
- Lazy-loaded navigation tree for large libraries (movies, shows, music, photos, and collections).
- Metadata viewer with quick playback controls.
- Embedded playback surface powered by LibVLC.
- Global search across all Plex libraries with `Ctrl+F`, plus quick server switching from the File menu.

## Getting Started

1. Run the application:
   ```bash
   python main.py
   ```
   Missing dependencies are installed automatically on first launch. The script invokes `python -m pip install -r requirements.txt` under the hood and may restart itself once installation completes.

   > **Note:** wxPython and the custom `python-plexapi` fork both require build tools on some systems. Refer to their documentation if installation fails.

2. (Optional) Install dependencies manually if you prefer to control the environment:
   ```bash
   python -m pip install -r requirements.txt
   ```

3. Use **File > Sign In...** to launch the Plex browser login. After approving the request your libraries appear on the left.
4. Control playback using the toolbar above the video surface or the **Player** menu (play/pause, stop, volume slider, mute, and player selection). Use **File > Global Search...** (`Ctrl+F`) to find content quickly, or **File > Change Server...** to switch Plex servers.

## Development Notes
- Configuration and the Plex authentication token are stored in `config.json` in the project root (next to `main.py`).
- The client id persists between runs to avoid repeated approval prompts.
- Playback uses the Plex stream URLs directly. Depending on codecs installed locally, videos may sometimes fall back to Plex's transcoding pipeline.

## Troubleshooting
- If playback does not start, confirm that the stream URL opens in your default browser. Some file types may require additional codecs in Windows.
- LibVLC playback requires a local VLC installation that Python can discover. Install [VLC](https://www.videolan.org/vlc/) and, if needed, set `VLC_PATH` (for the desktop app) or `PYTHON_VLC_MODULE_PATH` to point at the VLC installation directory.
- For MPC-HC/BE fallback, install MPC-HC (or MPC-BE) and optionally set `MPC_PATH` to the player executable.
- Signing out clears the cached token. If your token expires, simply sign out and sign back in.

### Building
To build a standalone executable (directory-based for better compatibility):

**Using the build script:**
```batch
build_exe.bat build
```

**Using PyInstaller directly:**
```bash
pyinstaller plexible.spec
```
The output will be in the `dist/Plexible` folder. Run `Plexible.exe` from that directory.

### Releases
The build script now supports automated releases and update metadata generation.

**Prerequisites**
- Git and GitHub CLI (`gh`) installed and authenticated (`gh auth login`).
- Windows SDK signtool available (defaults to `C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\signtool.exe`).
- Code signing certificate installed and accessible by signtool.
- Optional: set `SIGNTOOL_PATH` to override the default signtool location.

**Commands**
```batch
build_exe.bat release
```
Runs end-to-end: computes the next version, updates `plex_client/version.py`, builds via `plexible.spec`, signs `Plexible.exe`, zips the `dist\Plexible` folder, generates `Plexible-update.json`, commits the version bump, tags, pushes, and creates a GitHub release with the zip + manifest attached.

```batch
build_exe.bat build
```
Builds, signs, zips, and generates update metadata locally (no git tag or GitHub release).

```batch
build_exe.bat dry-run
```
Prints the actions without modifying git or creating releases.

```batch
build_exe.bat
```
Legacy behavior (clean + build only).

### Updater
Plexible checks GitHub Releases for the latest tag and reads `Plexible-update.json` from the release assets.
It compares versions semver-style, downloads the release zip, validates its SHA-256 hash, and verifies the Authenticode signature before installing.
Updates are applied by a helper script that waits for Plexible to exit, swaps files with a staged copy, keeps a backup for rollback, and restarts the app.

**Controls**
- **Help > Check for Updates...** triggers a manual check.
- **Help > Automatically Check for Updates** toggles the startup auto-check (default on).

### Test Plan (Manual)
1) Build an older version (or edit `plex_client/version.py` to `1.37.0`) and run the app from `dist\Plexible\Plexible.exe`.
2) Publish a release using `build_exe.bat release` (ensures a newer version exists on GitHub).
3) In the older build, open **Help > Check for Updates...**, accept the update prompt, and confirm Plexible restarts on the new version.
4) Validate that the update folder is created under `%LOCALAPPDATA%\Plexible\updates` and that the new exe is signed.

## License

This project is provided without an explicit license. Adapt it to your needs or reach out if you require formal licensing terms.
