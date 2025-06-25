# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# Personal build of the app with bundled user data

block_cipher = None

hiddenimports = collect_submodules('PyQt6')

a = Analysis(
    ['main.py'],
    pathex=[str(Path.cwd())],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('scripts', 'scripts'),
        ('sessions', 'sessions'),
        ('broadcast_logs', 'broadcast_logs'),
        ('accounts.json', '.'),
        ('settings.ini', '.'),
        ('auth.log', '.'),
        ('Create Launcher.app', 'Create Launcher.app'),
        ('Set Icon.app', 'Set Icon.app'),
    ],
    hiddenimports=hiddenimports,
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
    name='MySLAVA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed
    bundle=True,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MySLAVA',
)

# Final macOS bundle – creates a proper .app with Contents/Info.plist
app = BUNDLE(
    coll,
    name='MySLAVA.app',
    icon=None,
    bundle_identifier='com.aig.myslava',
) 