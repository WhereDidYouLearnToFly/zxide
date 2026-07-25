"""Give the emulator the whole display, and hand it back afterwards.

An IDE and a Spectrum want opposite things from a screen. Most of the time you want the
picture small and everything else visible -- registers, disassembly, your source. But when
you are *playing* what you built, every pixel of chrome is in the way.

The mechanism is deliberately thin: this window **borrows the existing
:class:`~zxemu_ui.panels.emulator_panel.EmulatorStage`** rather than building a second
renderer. Reparenting a live QWidget keeps its identity -- the same ``EmulatorView`` object
stays connected to the controller's ``frame_ready`` signal, keeps the Spectrum's key matrix,
and keeps whatever keys are held down -- so going fullscreen mid-game does not so much as
drop a frame. A second view would need all of that duplicated and kept in step.

Only two keys are bound, and both are safe because a Spectrum has neither:

* **Esc** leaves fullscreen. Nothing in ``emulator_view``'s key map claims it.
* **Alt+Enter** toggles. Enter *is* a Spectrum key, but a shortcut is matched before the
  key event is delivered to a widget, so the machine never sees this one.

The one rule worth stating: **the stage must always find its way home.** If this window is
closed by any route -- Esc, the toggle, Alt+F4, the window manager -- the stage goes back to
the panel. A stage left parented to a destroyed window would take the emulator with it, and
the IDE would come back with an empty dock and no picture.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QVBoxLayout, QWidget


class FullScreenStage(QWidget):
    """A bare black window that hosts the emulator stage for as long as it is open.

    Emits :attr:`closing` whenever it is about to go away, for any reason. The owner
    listens to that one signal and takes its stage back -- there is no other exit path
    to get wrong.
    """

    #: About to close; the listener must reclaim the stage widget now.
    closing = pyqtSignal()

    def __init__(self, stage: QWidget, near: QWidget | None = None):
        # No parent: this is a top-level window, not a child of the IDE.
        super().__init__(None, Qt.Window)
        self.setWindowTitle("zxide — emulator")

        # Black, not the theme colour: the aspect-locked picture leaves letterbox margins,
        # and a Spectrum's own border is the only frame the image should appear to have.
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#000000"))
        self.setPalette(palette)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(stage)

        # Open on the screen the IDE is on, which is not necessarily the primary one.
        # showFullScreen() alone would use whichever screen Qt last placed us on.
        if near is not None and near.window().windowHandle() is not None:
            self.setGeometry(near.window().windowHandle().screen().geometry())

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Esc leaves. Everything else falls through to the emulator.

        Handled here rather than as a QAction because a shortcut would be global to the
        window and this must not exist at all once we are back in the IDE -- Esc means
        "cancel" everywhere else, and stealing it would be a bug in every dialog.
        """
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        self.closing.emit()  # the owner reparents the stage back before we are destroyed
        super().closeEvent(event)
