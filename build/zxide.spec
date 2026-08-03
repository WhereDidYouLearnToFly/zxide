# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for a standalone zxide build.

Run it through build/build.ps1 (Windows) or build/build.sh (Linux/macOS) rather than
by hand -- those set the output paths this project expects. What lives here is only
the *contents* question: which files go in the bundle and how it is packaged.

Two decisions worth explaining:

  * **One folder, not one file.** A --onefile exe unpacks itself into a fresh temp
    directory on every launch, and zxide writes its ``settings.json`` and ``layout.json``
    next to the package (see MainWindow.__init__), so with --onefile the user's assembler
    path and window layout would vanish after every run. One-folder keeps them.

  * **Data files are copied into the same relative places they occupy in the repo.**
    The ROMs are read with ``importlib.resources`` and the project templates with
    ``Path(__file__).parent``; both resolve inside the bundle exactly as they do in a
    source checkout, so no frozen-app special-casing is needed in the app code.

One thing this spec deliberately does *not* bundle is sjasmplus: zxide shells out to
whatever assembler the app Settings point at (see zxemu_ui/workspace/builder.py), so
it is the user's install, not ours. build/README.md covers that, the build
requirements, and where the frozen app keeps settings.json.
"""

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
ICON = Path(SPECPATH).resolve() / "icon" / "zxide.ico"

# Data that is loaded at runtime by path rather than imported. (source, destination-in-bundle)
DATAS = [
    (str(ROOT / "zxemu_core" / "roms"), "zxemu_core/roms"),
    (str(ROOT / "zxemu_core" / "players"), "zxemu_core/players"),
    (str(ROOT / "zxemu_ui" / "templates"), "zxemu_ui/templates"),
    (str(ROOT / "zxemu_ui" / "addons"), "zxemu_ui/addons"),
    (str(ROOT / "LICENSE"), "."),
]

# Imports PyInstaller's static analysis cannot see: both are deliberately deferred to
# runtime so a missing package costs one feature instead of the whole IDE.
HIDDEN = [
    "pygame",          # zxemu_ui/gamepad.py, imported inside the polling thread
    "PIL.Image",       # zxemu_ui/recorder.py, imported when a GIF is exported
]

# Large libraries nothing in zxide imports; naming them keeps them out of the bundle even
# if some dependency pulls them onto the analysis graph.
EXCLUDES = [
    "tkinter",
    "matplotlib",
    "scipy",
    "pandas",
    "IPython",
    "pytest",
    "PyQt5.QtWebEngineWidgets",
    "PyQt5.QtQuick",
    "PyQt5.QtQml",
]

# A console window is dead weight for a GUI app, but it is the only way to see a crash that
# happens before Qt is up. Set ZXIDE_CONSOLE=1 before building to get one for debugging.
CONSOLE = os.environ.get("ZXIDE_CONSOLE") == "1"


a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="zxide",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="zxide",
)
