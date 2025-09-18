# -*- mode: python ; coding: utf-8 -*-

import sys
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# Personal build of the app with bundled user data

# Определяем иконку для сборки
def find_icon():
    """Находит подходящую иконку для текущей платформы."""
    icon_candidates = [
        'icon.icns',  # ICNS файл (предпочтительно для macOS)
        '28538791-c5e2-4ec8-9091-498b7e3e2ebd-_1_.ico',  # основная ICO
        'resources/icon.icns',  # ICNS для macOS (предпочтительно)
        'resources/icon.ico',   # ICO в resources
        'resources/icon.png',   # PNG как fallback
    ]

    for icon_path in icon_candidates:
        if os.path.exists(icon_path):
            return icon_path

    return None

app_icon = find_icon()
if app_icon:
    print(f"Используемая иконка: {app_icon}")
else:
    print("Иконка не найдена, приложение будет без иконки")

block_cipher = None

hiddenimports = collect_submodules('PyQt6')

a = Analysis(
    ['main.py'],
    pathex=[str(Path.cwd())],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        # Do NOT bundle user data or sessions by default
        # ('scripts', 'scripts'),
        # ('sessions', 'sessions'),
        # ('broadcast_logs', 'broadcast_logs'),
        # ('accounts.json', '.'),
        # ('settings.ini', '.'),
        # ('auth.log', '.'),
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
    icon=app_icon,
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
    icon=app_icon,
    bundle_identifier='com.aig.myslava',
) 