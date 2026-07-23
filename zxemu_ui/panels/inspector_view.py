"""InspectorView -- properties of the selected asset or memory region.

A placeholder for now. Once the project/asset system lands, selecting an asset in
the Project tree (or a region in the memory map) will show its details here --
type, size, and where it's placed as (bank, offset) -- and let you retarget or
auto-locate it. Kept as its own dockable panel so that wiring is a drop-in later.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget


class InspectorView(QWidget):
    """Shows details of the current selection; empty until the project system exists."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        message = QLabel(
            "Nothing selected.\n\n"
            "Select an asset in the Project panel to inspect its type, size, and where "
            "it lives in memory. (Arrives with the project & asset system.)"
        )
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignTop)
        message.setStyleSheet("color: palette(mid);")
        layout.addWidget(message)
        layout.addStretch(1)
