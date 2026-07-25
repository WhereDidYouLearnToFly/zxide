"""DiskView -- what is in the drives, and what is on it.

The Load menu can already mount, eject, protect and save a disk, so this panel is not
about adding commands. It is about answering the questions the menu cannot, because a
menu is a list of verbs and a disk is a *state*:

    which drive am I looking at, and is anything in it?
    what is on this disk, and is the file I want actually there?
    has the machine written to it -- i.e. would ejecting now lose something?
    is it write-protected, and is that why the game just failed to save?

Those are the questions you have while debugging a disk load, and every one of them is
answered by looking rather than by opening a dialog and cancelling it.

The catalogue is the centre of it. TR-DOS's own ``CAT`` shows the same list, but only
from inside the machine and only if the machine is well enough to ask -- which is
precisely not the case when a load has gone wrong. Reading it here goes straight to the
image, so it works with the emulator paused, mid-crash, or before you have booted at all.

Like the other machine-watching panels this keeps the ``machine`` / ``refresh`` contract
so MainWindow can treat it like the rest; it holds no state of its own beyond which drive
is selected, and re-reads everything from the image on each refresh.
"""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

#: Drive letters, in the order the Beta 128's connector numbers them.
DRIVE_LETTERS = ("A", "B", "C", "D")


class DiskView(QWidget):
    """A drive selector, a summary line, and the catalogue of whatever is mounted."""

    #: Asked for by the buttons; MainWindow owns the file dialogs and the machine, so the
    #: panel requests an action rather than performing one. Keeps this widget free of any
    #: knowledge of projects, settings or where images live on disk.
    mount_requested = pyqtSignal(int)
    eject_requested = pyqtSignal(int)
    save_requested = pyqtSignal(int)
    write_protect_changed = pyqtSignal(int, bool)

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self._drive = 0
        self._updating = False   # guards the write-protect box against its own signal

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        controls = QHBoxLayout()
        self._drive_box = QComboBox()
        self._drive_box.addItems([f"Drive {letter}" for letter in DRIVE_LETTERS[:2]])
        self._drive_box.currentIndexChanged.connect(self._on_drive_changed)
        controls.addWidget(self._drive_box)

        self._mount_button = QPushButton("Mount…")
        self._mount_button.clicked.connect(lambda: self.mount_requested.emit(self._drive))
        controls.addWidget(self._mount_button)

        self._eject_button = QPushButton("Eject")
        self._eject_button.clicked.connect(lambda: self.eject_requested.emit(self._drive))
        controls.addWidget(self._eject_button)

        self._save_button = QPushButton("Save As…")
        self._save_button.clicked.connect(lambda: self.save_requested.emit(self._drive))
        controls.addWidget(self._save_button)

        self._protect_box = QCheckBox("Write protect")
        self._protect_box.toggled.connect(self._on_protect_toggled)
        controls.addWidget(self._protect_box)
        controls.addStretch(1)
        layout.addLayout(controls)

        self._summary = QLabel("No disk.")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["File", "Type", "Bytes", "Position"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        layout.addWidget(self._table, 1)

        self.refresh()

    # --- the panel contract ---------------------------------------------------

    def refresh(self) -> None:
        """Re-read the mounted image. Cheap enough to call whenever the UI repaints."""
        image = self._image()
        self._updating = True
        try:
            self._protect_box.setChecked(bool(image and image.write_protected))
        finally:
            self._updating = False
        for button in (self._eject_button, self._save_button):
            button.setEnabled(image is not None)
        self._protect_box.setEnabled(image is not None)

        if image is None:
            self._summary.setText(
                "No disk in this drive."
                if self._has_drives() else
                "This machine has no disk interface — switch to Pentagon 128."
            )
            self._table.setRowCount(0)
            return

        info = image.info()
        files = image.catalogue()
        parts = [
            f"<b>{image.name or 'disk'}</b>",
            f"label {info.label or '(none)'}",
            f"{len(files)} file(s)",
            f"{info.free_sectors} free sector(s)",
            f"{image.tracks}×{image.sides}",
        ]
        if not info.valid:
            parts.append("<i>no TR-DOS identifier — unformatted?</i>")
        if image.dirty:
            # The one piece of state you cannot get at any other way, and the one that
            # costs you work if you miss it.
            parts.append("<b>modified — unsaved</b>")
        self._summary.setText(" · ".join(parts))
        self._fill_table(files)

    def set_machine(self, machine) -> None:
        self.machine = machine
        self.refresh()

    def set_mono_scale(self, _scale: float) -> None:
        """Part of the shared panel contract; this view uses no monospaced grid."""

    # --- internals ------------------------------------------------------------

    def _has_drives(self) -> bool:
        return bool(getattr(self.machine, "beta_drives", None))

    def _image(self):
        drives = getattr(self.machine, "beta_drives", None)
        if not drives or self._drive >= len(drives):
            return None
        return drives[self._drive]

    def _fill_table(self, files) -> None:
        self._table.setRowCount(len(files))
        for row, entry in enumerate(files):
            # "Position" is the logical track and sector from the catalogue, shown as
            # TR-DOS records it rather than converted to a cylinder/side -- it is what you
            # compare against a disassembly or a port trace when a load goes wrong.
            cells = (
                entry.display_name,
                entry.extension,
                str(entry.length),
                f"T{entry.start_track}/S{entry.start_sector}",
            )
            for column, text in enumerate(cells):
                self._table.setItem(row, column, QTableWidgetItem(text))
        self._table.resizeColumnsToContents()

    def _on_drive_changed(self, index: int) -> None:
        self._drive = index
        self.refresh()

    def _on_protect_toggled(self, protected: bool) -> None:
        if not self._updating:
            self.write_protect_changed.emit(self._drive, protected)
