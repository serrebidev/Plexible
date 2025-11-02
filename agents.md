# Agents Playbook

## Mission
- Ship the Windows Plex client that blind and sighted users can fly without guessing.
- Keyboard-first paths, loud state announcements, resilient playback at all costs.

## Startup
- Run `python main.py` from the repo root; first launch pulls `requirements.txt` automatically.
- Sign in via **File > Sign In...**, approve the browser PIN, libraries populate the navigation tree.

## Navigation Facts
- Arrow keys move focus; Enter or Numpad Enter always plays the focused node.
- Shows and seasons auto-resolve to the first playable episode before playback starts.
- Every selection refreshes metadata/status with `wx.CallAfter` so screen readers get the change immediately.

## Playback Facts
- LibVLC is the renderer; we only fall back to the Plex HLS stream if the direct URL fails—no external players.
- Resume offsets apply before playback (`_maybe_seek_to_resume`) and timeline polling runs roughly every 5 seconds.
- Fullscreen exists only for LibVLC (toolbar toggle or F11; Escape/F11 exits and focus snaps back to the player).

## Progress + Continue Watching
- `ConfigStore` tracks `pending_progress`; there is no persistent local resume cache.
- Tree-view plays trigger a queue refresh a few seconds after playback starts so Continue Watching updates automatically.
- Zero-position stops skip timeline pushes, so we do not wipe resume data when playback exits instantly.
- On shutdown we snapshot LibVLC, flush pending progress synchronously, and poll Plex until it echoes the updated `viewOffset` (up to about 2.5 seconds) before the app exits.
- Plex remains the single source of truth for resume state; the client only reflects what the server reports.

## Controls
- `Space` / toolbar Play resumes; `Shift+Space` pauses; `Ctrl+.` stops.
- `Ctrl+Up` / `Ctrl+Down` adjust volume, `Ctrl+0` toggles mute, and every change re-announces state for screen readers.
- `F5` always reloads Continue Watching and Up Next regardless of which list owns focus.

## Failure Rules
- Log every failure, announce it, fall back instantly, and never strand the transport controls.
- If LibVLC breaks, try the Plex HLS stream and stay visible; do not spawn external players.
- When Plex API calls fail, surface the raw error (toast/dialog), log it, and keep the UI responsive.

## Hot Files
- `main.py` — wxPython bootstrapper.
- `plex_client/plex_service.py` — Plex auth, discovery, timeline/progress calls plus server confirmation loop.
- `plex_client/ui/main_frame.py` — navigation, queues, shutdown flushing, progress scheduling.
- `plex_client/ui/playback.py` — LibVLC orchestration, resume seek, timeline polling.
