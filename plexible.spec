# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None


def keep_wx_submodule(name):
    # Plexible does not use wx.lib.pubsub; collecting it emits wx deprecation
    # warnings and a non-fatal missing hidden-import error in PyInstaller.
    return not name.startswith('wx.lib.pubsub')


def keep_urllib3_submodule(name):
    # Browser-only urllib3 support imports pyodide/js modules that do not exist
    # in the Windows desktop runtime.
    return not name.startswith('urllib3.contrib.emscripten')


# Collect all submodules for key packages
hidden_imports = collect_submodules('plexapi')
hidden_imports += collect_submodules('plex_client')
hidden_imports += collect_submodules('wx', filter=keep_wx_submodule, on_error='ignore')
hidden_imports += collect_submodules('requests')
hidden_imports += collect_submodules('urllib3', filter=keep_urllib3_submodule, on_error='ignore')
hidden_imports += collect_submodules('vlc')
hidden_imports += [
    'vlc',
    'requests',
    'urllib3',
    'certifi',
    'idna',
    'charset_normalizer',
    'json',
    'uuid',
    'webbrowser',
    'threading',
    'platform',
    'ctypes',
    'shutil',
    'zipfile',
    'struct',
    'pathlib',
    'concurrent.futures',
]

excluded_imports = [
    'wx.lib.pubsub',
    'wx.lib.pubsub.core.datamsg',
    'urllib3.contrib.emscripten',
    'urllib3.contrib.emscripten.fetch',
    'ascii__mypyc',
    'confusion__mypyc',
    'escape__mypyc',
    'magic__mypyc',
    'orchestrator__mypyc',
    'statistical__mypyc',
    'structural__mypyc',
    'utf1632__mypyc',
    'utf8__mypyc',
    'validity__mypyc',
    'pycparser.lextab',
    'pycparser.yacctab',
]

added_files = [
    ('requirements.txt', '.'),
    ('agents.md', '.'),
    ('plex_client/update_helper.bat', '.'),
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=added_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_imports,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Plexible',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    # Add update_helper.bat to the root of the distribution
    [('update_helper.bat', 'plex_client/update_helper.bat', 'DATA')],
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Plexible',
)
