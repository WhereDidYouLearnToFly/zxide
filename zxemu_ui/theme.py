"""Application theming -- a dark palette and readable fonts for the whole IDE.

Qt's default look follows the host OS, so to give zxide a consistent dark
appearance everywhere we switch to the platform-independent "Fusion" style and
hand it a dark ``QPalette``. Doing it through the palette (rather than a big CSS
stylesheet) means every standard widget -- menus, docks, the tree, the console --
picks up the theme automatically, including the greyed-out look of disabled items.

Fonts live here too:

  * a clean UI font (Segoe UI, the same family VSCode uses on Windows) at a
    comfortably readable size, and
  * an interface-scale knob (``apply_ui_scale``) so the whole UI's text can be
    sized up on large / high-resolution displays where the default feels small.

A separate ``monospace_font`` is offered for code-ish surfaces like the build
console, where column alignment matters.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QApplication

# A restrained dark grey with a blue selection accent -- easy on the eyes for long
# sessions and neutral enough not to fight the emulator's own vivid colours.
_WINDOW = QColor(53, 53, 53)
_BASE = QColor(35, 35, 35)
_ACCENT = QColor(42, 130, 218)
_DISABLED_TEXT = QColor(127, 127, 127)

UI_FONT_FAMILY = "Segoe UI"  # clean, modern Windows UI font (VSCode uses it too)
BASE_UI_POINT_SIZE = 11.0  # a touch larger than Qt's default, for readability
MONOSPACE_FAMILIES = ["Cascadia Mono", "Cascadia Code", "Consolas", "Courier New"]


def apply_dark_theme(app: QApplication) -> None:
    """Switch the app to the Fusion style, install a dark palette, and set the UI font."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, _WINDOW)
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, _BASE)
    palette.setColor(QPalette.AlternateBase, _WINDOW)
    palette.setColor(QPalette.ToolTipBase, _BASE)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, _WINDOW)
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, _ACCENT)
    palette.setColor(QPalette.Highlight, _ACCENT)
    palette.setColor(QPalette.HighlightedText, Qt.black)

    # Greyed-out text/selection for disabled widgets (e.g. stubbed File actions).
    palette.setColor(QPalette.Disabled, QPalette.WindowText, _DISABLED_TEXT)
    palette.setColor(QPalette.Disabled, QPalette.Text, _DISABLED_TEXT)
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, _DISABLED_TEXT)
    palette.setColor(QPalette.Disabled, QPalette.Highlight, QColor(80, 80, 80))
    palette.setColor(QPalette.Disabled, QPalette.HighlightedText, _DISABLED_TEXT)

    app.setPalette(palette)
    apply_ui_scale(app, 1.0)


def apply_ui_scale(app: QApplication, scale: float) -> None:
    """Set the interface font size to ``scale`` x the base, across the whole UI.

    Setting the application font covers widgets built later; we also push it onto
    the already-open top-level windows so a live scale change takes effect at once
    (child widgets inherit it, except ones with a font of their own, like the
    monospace console).
    """
    font = QFont(UI_FONT_FAMILY)
    font.setStyleHint(QFont.SansSerif)
    font.setPointSizeF(BASE_UI_POINT_SIZE * scale)
    app.setFont(font)
    for window in app.topLevelWidgets():
        window.setFont(font)


def monospace_font(scale: float = 1.0) -> QFont:
    """A monospace font for code/console surfaces (build output, future hex view).

    Takes the same scale factor as apply_ui_scale so code surfaces grow in step with
    the rest of the UI while keeping their fixed-pitch family.
    """
    font = QFont()
    font.setStyleHint(QFont.Monospace)
    font.setFamilies(MONOSPACE_FAMILIES)
    font.setPointSizeF(BASE_UI_POINT_SIZE * scale)
    return font
