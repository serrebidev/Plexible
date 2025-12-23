# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Collect all submodules for key packages
hidden_imports = collect_submodules('plexapi')
hidden_imports += collect_submodules('plex_client')
hidden_imports += collect_submodules('wx')
hidden_imports += collect_submodules('requests')
hidden_imports += collect_submodules('urllib3')
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

added_files = [
    ('requirements.txt', '.'),
    ('agents.md', '.'),
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
    excludes=[],
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
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Plexible',
)
