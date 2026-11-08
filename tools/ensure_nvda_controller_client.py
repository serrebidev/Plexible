"""Download the NVDA controller client DLL that Plexible uses to speak.

Adapted from BlindRSS (tools/ensure_nvda_controller_client.py, MIT, serrebidev).

The DLL comes from NV Access's official stable release index and is saved
with its license next to it. It is not tracked in git (see .gitignore);
build_exe.bat runs this before PyInstaller so plexible.spec can bundle it.

Usage: python tools/ensure_nvda_controller_client.py --dest bin
"""
from __future__ import annotations

import argparse
import io
import platform
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

STABLE_INDEX = "https://download.nvaccess.org/releases/stable/"


def _version_key(filename: str) -> tuple:
    match = re.search(r"nvda_([0-9][^_/]*)_controllerClient\.zip", filename)
    if not match:
        return (0,)
    parts = [int(part) for part in re.findall(r"\d+", match.group(1))]
    return tuple(parts or [0])


def _latest_controller_zip_url() -> str:
    with urllib.request.urlopen(STABLE_INDEX, timeout=60) as response:
        html = response.read().decode("utf-8", "replace")
    names = sorted(
        set(re.findall(r"nvda_[^\"'<>/]+_controllerClient\.zip", html)),
        key=_version_key,
        reverse=True,
    )
    if not names:
        raise RuntimeError("Could not find an NVDA controller client ZIP in the stable release index.")
    return STABLE_INDEX + names[0]


def _arch_folder() -> str:
    machine = platform.machine().lower()
    if "arm64" in machine or "aarch64" in machine:
        return "arm64"
    return "x64" if sys.maxsize > 2**32 else "x86"


def ensure_nvda_controller_client(dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_dll = dest_dir / "nvdaControllerClient.dll"
    if dest_dll.is_file():
        return dest_dll

    url = _latest_controller_zip_url()
    with urllib.request.urlopen(url, timeout=120) as response:
        archive = zipfile.ZipFile(io.BytesIO(response.read()))

    dll_name = f"{_arch_folder()}/nvdaControllerClient.dll"
    try:
        dll_bytes = archive.read(dll_name)
    except KeyError as exc:
        raise RuntimeError(f"NVDA controller client ZIP did not contain {dll_name}.") from exc
    dest_dll.write_bytes(dll_bytes)

    for source_name, output_name in (
        ("license.txt", "nvdaControllerClient-license.txt"),
        ("readme.md", "nvdaControllerClient-readme.md"),
    ):
        try:
            (dest_dir / output_name).write_bytes(archive.read(source_name))
        except KeyError:
            pass
    print(f"NVDA_CONTROLLER_CLIENT={dest_dll}")
    return dest_dll


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    ensure_nvda_controller_client(args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
