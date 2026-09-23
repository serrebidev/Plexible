#!/usr/bin/env bash
# macOS/Linux build. Windows uses build_exe.bat. Needs VLC installed at run time.
#   macOS: dist/Plexible-macos.zip (Plexible.app)
#   Linux: dist/Plexible-linux-x86_64.tar.gz (Plexible/ folder)
set -euo pipefail
cd "$(dirname "$0")"
PYTHON=${PYTHON:-python3}
"$PYTHON" -m pip install pyinstaller -r requirements.txt
"$PYTHON" -m PyInstaller --noconfirm --clean plexible.spec
case "$(uname -s)" in
  Darwin)
    codesign --force --deep --sign - dist/Plexible.app
    (cd dist && ditto -c -k --sequesterRsrc --keepParent Plexible.app Plexible-macos.zip)
    ;;
  Linux)
    tar -C dist -czf dist/Plexible-linux-x86_64.tar.gz Plexible
    ;;
  *) echo "build.sh is for macOS and Linux; use build_exe.bat on Windows." >&2; exit 1 ;;
esac
ls -l dist
