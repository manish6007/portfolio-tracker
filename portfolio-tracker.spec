# -*- mode: python ; coding: utf-8 -*-
"""One file someone can download and run, with no Python on their machine.

The built frontend is carried inside the bundle; the portfolio is not --
that goes to the operating system's own place for a user's data, because a
PyInstaller bundle unpacks into a temporary folder that is deleted on quit.
See backend/paths.py.
"""
import os

block_cipher = None
HERE = os.path.abspath(os.getcwd())
DIST = os.path.join(HERE, 'frontend', 'dist')

if not os.path.isdir(DIST):
    raise SystemExit(
        'Build the frontend first:  cd frontend && npm install && npm run build')

a = Analysis(
    [os.path.join('backend', 'desktop.py')],
    pathex=[os.path.join(HERE, 'backend')],
    binaries=[],
    # The frontend keeps its layout inside the bundle, so paths.py can find
    # it at frontend/dist exactly as it does from source.
    datas=[(DIST, os.path.join('frontend', 'dist'))],
    hiddenimports=[
        # Imported by name at runtime rather than at the top of a module,
        # so PyInstaller's import graph cannot see them.
        'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan.on',
        'demo_data', 'analytics', 'calculators', 'capmix', 'config', 'db', 'export',
        'family_record', 'fi', 'importers', 'matching', 'netlog', 'paths',
        'pricing', 'profiles', 'schemas', 'service',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'pytest', 'numpy', 'pandas'],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='PortfolioTracker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # A console window is the app's status display: it prints the address to
    # open and where the data is kept, and closing it stops the app.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
