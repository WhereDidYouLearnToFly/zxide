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

from PyQt5.QtCore import Qt, QTimer
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

    # Use Qt's own file/colour dialogs rather than the desktop's native ones. The native
    # path on Linux goes through an xdg-desktop-portal service that isn't always present
    # or well-behaved, which is where the dialog trouble showed up; set here for every
    # platform so the IDE's dialogs look and behave the same wherever it runs. One
    # attribute covers every dialog type -- QFileDialog, QColorDialog, future ones --
    # instead of an option argument repeated at each call site.
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)

    app = QApplication(sys.argv)
    apply_dark_theme(app)

    # Start as a 48K; opening a 128K project swaps the machine (see MainWindow).
    machine = build_machine("48k")
    controller = EmulatorController(machine)
    window = MainWindow(machine, controller)

    # showMaximized() called immediately, before the window has ever been shown, can
    # maximise against a stale screen geometry -- on XWayland (Qt running under a GNOME
    # Wayland session) it maximised to a size far smaller than the real monitor, because
    # Qt hadn't yet synced the real output geometry from the compositor. Showing first,
    # then deferring the maximise by one event-loop tick, lets that sync happen first.
    window.show()
    QTimer.singleShot(0, window.showMaximized)
    controller.start()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
