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
build_exe.bat
```

**Using PyInstaller directly:**
```bash
pyinstaller plexible.spec
```
The output will be in the `dist/Plexible` folder. Run `Plexible.exe` from that directory.

## License

This project is provided without an explicit license. Adapt it to your needs or reach out if you require formal licensing terms.
