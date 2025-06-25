# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller spec-файл для чистой публичной версии SLAVA под Windows.
• без пользовательских скриптов/сессий (только templates)
"""

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
hiddenimports = collect_submodules('PyQt6')

a = Analysis(
    ['main.py'],
    pathex=[str(Path.cwd())],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('resources', 'resources'),
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
    name='SLAVA',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='resources/icon.ico' if Path('resources/icon.ico').exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SLAVA',
) 