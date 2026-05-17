# windrose_tool.spec
# Run with: pyinstaller windrose_tool.spec

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # PySide6 modules PyInstaller misses
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # rocksdict
        'rocksdict',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused heavy modules
        'matplotlib', 'numpy', 'pandas', 'PIL',
        'tkinter', 'unittest', 'email', 'html',
        'http', 'urllib', 'xml', 'xmlrpc',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='WindroseSaveRecovery',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    # Single-file exe – no folder needed
    runtime_tmpdir=None,
    console=False,          # no terminal window (GUI app)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows-specific
    version=None,
    uac_admin=False,
    icon=None,              # add icon.ico here if you have one
)
