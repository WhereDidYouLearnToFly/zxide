"""Entry point: wires the emulator core, its controller, and the IDE shell together.

This is a thin composition root. The parts each live in their own module:

    Machine (zxemu_core)           the emulator itself
    EmulatorController (zxemu_ui)  drives it in real time; run/pause/reset/step
    MainWindow (zxemu_ui)          the IDE shell that hosts the emulator panel

main() just builds them in order, shows the window, starts the controller, and
hands control to Qt. Everything interesting -- the frame loop, the UI -- lives in
those modules, so this file stays boring on purpose.
"""

from __future__ import annotations

import importlib.resources as res
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from zxemu_core.machine import Machine
from zxemu_ui.controller import EmulatorController
from zxemu_ui.main_window import MainWindow
from zxemu_ui.theme import apply_dark_theme


def load_48_rom() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


def main() -> int:
    # Ask Qt to honour the display's DPI/scale factor -- without this the UI renders
    # tiny on high-resolution monitors. Must be set before the QApplication exists.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    apply_dark_theme(app)

    machine = Machine(load_48_rom())
    controller = EmulatorController(machine)
    window = MainWindow(machine, controller)

    window.showMaximized()
    controller.start()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
