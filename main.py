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

import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from zxemu_ui.controller import EmulatorController
from zxemu_ui.machine_factory import build_machine
from zxemu_ui.main_window import MainWindow
from zxemu_ui.theme import apply_dark_theme


def main() -> int:
    # Ask Qt to honour the display's DPI/scale factor -- without this the UI renders
    # tiny on high-resolution monitors. Must be set before the QApplication exists.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    apply_dark_theme(app)

    # Start as a 48K; opening a 128K project swaps the machine (see MainWindow).
    machine = build_machine("48k")
    controller = EmulatorController(machine)
    window = MainWindow(machine, controller)

    window.showMaximized()
    controller.start()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
