"""MemoryMapView -- the visual, bank-oriented overview of memory.

The centrepiece of the "where did my bytes go?" story, with a **Design <-> Debug**
toggle (the toolbar at the top):

- **Debug** (the original view) draws the four 16K slots as columns, coloured by what
  occupies them -- ROM, screen, RAM -- with live PC/SP markers, so you can watch
  execution and the stack move.
- **Design** answers a different question, asked *before* a build: where do my
  imported assets live? Drag a file from the project tree onto a column to import it;
  each placed asset draws as a coloured rectangle (colour = kind, via
  ``zxemu_ui.asset_icons``) at its bank/offset; "Auto-locate" fills in a home for every
  asset still marked ``"auto"``.

Both modes share the same four slot columns, which is a deliberate simplification: an
asset's *placement* is recorded against a bank's real identity (e.g. ``"ram2"``), but
Design mode only draws it if that bank happens to be paged into a visible column right
now -- exactly the same "can't show what isn't mapped in" honesty the shadow-screen
readout already has (see ``_screen_slot``). A full "every bank, mapped or not" view is
future work, not needed for 48K (where the four banks are always all visible) and only
a real gap on 128K.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QPainter
from PyQt5.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from zxemu_core.assets.manifest import AssetKind
from zxemu_core.assets.registry import guess_kind
from zxemu_core.memlayout import bank_ids_for_model
from zxemu_core.memory import BANK_SIZE, SCREEN_BYTES, SCREEN_SLOT
from zxemu_ui.asset_icons import color_for_kind, glyph_for_kind
from zxemu_ui.workspace.asset_build import display_length, resolve_auto_placements

_BG = QColor("#2b2b2b")
_BORDER = QColor("#404040")
_MUTED = QColor("#9aa0a6")
_ROM = QColor("#3a3a3a")
_ROM_HATCH = QColor("#555555")
_RAM = QColor("#2f2f2f")
_SCREEN = QColor("#7a5aa6")
_CONTENDED = QColor("#3a3550")  # faint tint marking contended RAM
_PC = QColor("#e0a13a")
_SP = QColor("#4ec96b")
_ASSET_BORDER = QColor("#e8e8e8")
_PLACEHOLDER_HATCH = QColor("#ffffff")  # overlaid on assets whose size is still a guess

# Sensible defaults offered by the drag-drop import dialog -- 8x8 covers the common
# "one glyph/tile per frame" case, so accepting the defaults just works for a font or a
# simple tileset without any typing.
_DEFAULT_FRAME_SIZE = 8
_KIND_CHOICES = [
    ("Full-screen bitmap", AssetKind.BITMAP),
    ("Sprite sheet", AssetKind.SPRITE_SHEET),
    ("Font", AssetKind.FONT),
    ("Raw binary", AssetKind.BINARY),
]


class MemoryMapView(QWidget):
    """A toolbar (Design/Debug + Auto-locate) over the bank-column canvas."""

    #: Emitted with an AssetEntry's id when its placed rectangle is clicked in Design mode.
    asset_selected = pyqtSignal(str)

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.project = None
        self._canvas = _MapCanvas(machine)
        self._canvas.asset_selected.connect(self.asset_selected)

        self._design_button = QPushButton("Design")
        self._debug_button = QPushButton("Debug")
        for button in (self._design_button, self._debug_button):
            button.setCheckable(True)
        self._debug_button.setChecked(True)
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self._design_button)
        self._mode_group.addButton(self._debug_button)
        self._design_button.toggled.connect(self._on_mode_toggled)

        self._auto_locate_button = QPushButton("Auto-locate")
        self._auto_locate_button.clicked.connect(self.auto_locate_all)
        self._auto_locate_button.setVisible(False)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._design_button)
        toolbar.addWidget(self._debug_button)
        toolbar.addWidget(self._auto_locate_button)
        toolbar.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(toolbar)
        layout.addWidget(self._canvas)

    # --- machine/project plumbing (mirrors the .machine = ... convention other panels use) ---

    @property
    def machine(self):
        return self._canvas.machine

    @machine.setter
    def machine(self, value) -> None:
        self._canvas.machine = value

    def refresh(self, frame_count: int | None = None) -> None:
        self._canvas.refresh(frame_count)

    def set_project(self, project) -> None:
        self.project = project
        self._canvas.project = project
        self._canvas.update()

    def _on_mode_toggled(self, design_checked: bool) -> None:
        self._canvas.mode = "design" if design_checked else "debug"
        self._auto_locate_button.setVisible(design_checked)
        self._canvas.update()

    # --- auto-locate ------------------------------------------------------------

    def auto_locate_all(self) -> None:
        """Place every ``"auto"`` asset into the first free space that fits it.

        The button is a way to *see* where things land before building -- the same
        placement also happens automatically at build time (``asset_build.
        resolve_auto_placements``), so a project builds even if you never click this.
        """
        if self.project is None:
            return
        resolve_auto_placements(self.project)
        self._canvas.update()

    # --- drag-drop import --------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._canvas.mode == "design" and self.project is not None and event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        if self.project is None:
            return
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file():
                self._import_file(path)
        event.acceptProposedAction()

    def _import_file(self, path: Path) -> None:
        try:
            source = str(path.relative_to(self.project.folder))
        except ValueError:
            source = str(path)  # outside the project folder -- keep an absolute path rather than fail

        kind = guess_kind(path.name)
        options = [label for label, _kind in _KIND_CHOICES]
        default_index = next((i for i, (_l, k) in enumerate(_KIND_CHOICES) if k == kind), 0)
        label, ok = QInputDialog.getItem(
            self, "Import Asset", f"Import '{path.name}' as:", options, default_index, False
        )
        if not ok:
            return
        chosen_kind = dict(zip(options, (k for _l, k in _KIND_CHOICES)))[label]

        params: dict = {}
        if chosen_kind in (AssetKind.SPRITE_SHEET, AssetKind.FONT):
            width, ok = QInputDialog.getInt(self, "Frame size", "Frame width (px):", _DEFAULT_FRAME_SIZE, 8, 256, 8)
            if not ok:
                return
            height, ok = QInputDialog.getInt(self, "Frame size", "Frame height (px):", _DEFAULT_FRAME_SIZE, 1, 256, 1)
            if not ok:
                return
            params = {"frame_width": width, "frame_height": height}
            if chosen_kind is AssetKind.SPRITE_SHEET:
                cols, ok = QInputDialog.getInt(self, "Sheet layout", "Columns:", 1, 1, 256, 1)
                if not ok:
                    return
                rows, ok = QInputDialog.getInt(self, "Sheet layout", "Rows:", 1, 1, 256, 1)
                if not ok:
                    return
                params["layout"] = {"grid": {"cols": cols, "rows": rows}}
                answer = QMessageBox.question(
                    self, "Mask", "Generate a transparency mask for this sprite?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                params["generate_mask"] = answer == QMessageBox.Yes
                if params["generate_mask"]:
                    color = QColorDialog.getColor(QColor(255, 0, 255), self, "Pick the transparent colour")
                    if not color.isValid():
                        params["generate_mask"] = False
                    else:
                        params["mask_color"] = [color.red(), color.green(), color.blue()]

        entry = self.project.add_asset(source, chosen_kind, params=params)
        self._canvas.update()
        return entry


class _MapCanvas(QWidget):
    """The paintable bank-column surface -- Debug's PC/SP overlay, or Design's placed assets."""

    asset_selected = pyqtSignal(str)

    def __init__(self, machine, parent=None):
        super().__init__(parent)
        self.machine = machine
        self.project = None
        self.mode = "debug"  # "debug" or "design"
        self.setMinimumHeight(140)
        self._asset_rects: dict[str, QRectF] = {}

    def refresh(self, frame_count: int | None = None) -> None:
        if self.isVisible():
            self.update()  # schedule a repaint

    def _geometry(self):
        """Shared layout numbers so painting and hit-testing never disagree."""
        w, h = self.width(), self.height()
        paging = self.machine.paging_state()
        margin, label_h, legend_h, gap = 12, 18, 20, 8
        readout_h = 16 if (paging is not None and self.mode == "debug") else 0
        slots = self.machine.memory.slots
        cols = len(slots)
        bar_top = margin + label_h
        bar_bottom = h - margin - legend_h - readout_h
        bar_h = max(1, bar_bottom - bar_top)
        col_w = (w - 2 * margin - (cols - 1) * gap) / cols
        return paging, margin, gap, col_w, bar_top, bar_h, bar_bottom, cols

    def _bank_id_for_slot(self, slot: int, paging) -> str:
        """Which bank (by ``memlayout`` id, e.g. "ram5") currently occupies this visible column."""
        if paging is None:
            return bank_ids_for_model("48k")[slot]
        return paging.slot_labels[slot].lower()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, _BG)

        paging, margin, gap, col_w, bar_top, bar_h, bar_bottom, cols = self._geometry()
        slots = self.machine.memory.slots
        screen_slot = self._screen_slot(paging)
        for i, bank in enumerate(slots):
            x = margin + i * (col_w + gap)
            self._draw_slot_label(p, i, bank, x, margin, col_w, 18, paging)
            self._draw_slot_bar(p, i, bank, QRectF(x, bar_top, col_w, bar_h), screen_slot)

        if self.mode == "design":
            self._draw_design_mode(p, paging, margin, gap, col_w, bar_top, bar_h)
        else:
            self._draw_marker(p, self.machine.cpu.regs.pc, "PC", _PC, margin, gap, col_w, bar_top, bar_h)
            self._draw_marker(p, self.machine.cpu.regs.sp, "SP", _SP, margin, gap, col_w, bar_top, bar_h)
            if paging is not None:
                self._draw_paging_readout(p, paging, margin, bar_bottom + 2, w)
        legend_h = 20
        self._draw_legend(p, margin, h - margin - legend_h + 2, w)

    def _screen_slot(self, paging):
        """Which slot column currently shows the display file, or None if off-map.

        48K: always slot 1. 128K: the normal screen (RAM5) is in slot 1; the shadow
        screen (RAM7) is only visible if RAM7 happens to be paged into slot 3 --
        otherwise it is being displayed from a bank the CPU can't see, so no column
        shows it (the readout still names it).
        """
        if paging is None:
            return SCREEN_SLOT
        if paging.screen_bank == 5:
            return 1
        return 3 if paging.ram_bank == 7 else None

    def _draw_slot_label(self, p, i, bank, x, y, col_w, label_h, paging) -> None:
        # On 128K name the actual bank in the slot (ROM0/RAM5/...); on 48K just ROM/RAM.
        if paging is not None:
            text = f"slot {i} · {paging.slot_labels[i]}"
        else:
            text = f"slot {i} · {'ROM' if bank.readonly else 'RAM'}"
        p.setPen(_MUTED)
        p.drawText(QRectF(x, y, col_w, label_h), Qt.AlignCenter, text)

    def _draw_slot_bar(self, p, i, bank, rect: QRectF, screen_slot) -> None:
        if bank.readonly:
            p.fillRect(rect, _ROM)
            p.fillRect(rect, QBrush(_ROM_HATCH, Qt.BDiagPattern))
        else:
            p.fillRect(rect, _CONTENDED if bank.contended else _RAM)
            if i == screen_slot:  # the display file sits at the base of this bank
                screen_h = rect.height() * (SCREEN_BYTES / BANK_SIZE)
                p.fillRect(QRectF(rect.x(), rect.y(), rect.width(), screen_h), _SCREEN)
        p.setPen(_BORDER)
        p.drawRect(rect)

    def _draw_paging_readout(self, p, paging, x, y, w) -> None:
        """A compact one-line summary of the live 0x7FFD paging state (128K only)."""
        text = (
            f"$7FFD=${paging.port_7ffd:02X}  ROM{paging.rom_index}"
            f"  screen RAM{paging.screen_bank}" + ("  LOCK" if paging.locked else "")
        )
        p.setPen(_MUTED)
        p.drawText(QRectF(x, y, w - 2 * x, 14), Qt.AlignLeft | Qt.AlignVCenter, text)

    def _draw_marker(self, p, address, label, color, margin, gap, col_w, bar_top, bar_h) -> None:
        slot, offset = divmod(address & 0xFFFF, BANK_SIZE)
        x = margin + slot * (col_w + gap)
        y = bar_top + (offset / BANK_SIZE) * bar_h
        p.setPen(color)
        p.drawLine(int(x), int(y), int(x + col_w), int(y))
        p.drawText(QRectF(x, y - 13, col_w - 2, 12), Qt.AlignRight | Qt.AlignVCenter, f"{label} {address:04X}")

    def _draw_legend(self, p, x, y, w) -> None:
        items = [("ROM", _ROM), ("screen", _SCREEN), ("RAM", _RAM)]
        p.setPen(_MUTED)
        cursor = x
        for name, color in items:
            p.fillRect(QRectF(cursor, y + 3, 11, 11), color)
            cursor += 16
            p.drawText(QRectF(cursor, y, 60, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
            cursor += 60

    # --- Design mode: placed assets ---------------------------------------------

    def _design_mode_rects(self, paging, margin, gap, col_w, bar_top, bar_h) -> dict[str, QRectF]:
        """Every placed asset's rectangle, keyed by id -- pure geometry, no painting.

        Kept separate from drawing so hit-testing (``mousePressEvent``) can compute
        current rectangles on demand instead of trusting whatever the *last paint*
        happened to leave behind -- a click right after a resize, before any repaint,
        must still hit-test against where things really are now.
        """
        if self.project is None:
            return {}
        # Map each currently-visible column to the bank it shows, so a placed asset
        # is included if (and only if) its bank happens to be paged in right now.
        cols = len(self.machine.memory.slots)
        slot_for_bank = {self._bank_id_for_slot(i, paging): i for i in range(cols)}

        rects: dict[str, QRectF] = {}
        for entry in self.project.assets():
            if not isinstance(entry.placement, dict):
                continue  # "auto" and not yet located -- nothing to show yet
            bank, offset = entry.placement.get("bank"), entry.placement.get("offset", 0)
            slot = slot_for_bank.get(bank)
            if slot is None:
                continue  # placed in a bank not currently mapped into any visible column
            length, _is_placeholder = display_length(self.project, entry)

            x = margin + slot * (col_w + gap)
            y = bar_top + (offset / BANK_SIZE) * bar_h
            rect_h = max(2.0, (length / BANK_SIZE) * bar_h)
            rects[entry.id] = QRectF(x, y, col_w, rect_h)
        return rects

    def _draw_design_mode(self, p, paging, margin, gap, col_w, bar_top, bar_h) -> None:
        self._asset_rects = self._design_mode_rects(paging, margin, gap, col_w, bar_top, bar_h)
        if self.project is None:
            return
        assets_by_id = {entry.id: entry for entry in self.project.assets()}
        for asset_id, rect in self._asset_rects.items():
            entry = assets_by_id[asset_id]
            _length, is_placeholder = display_length(self.project, entry)

            p.fillRect(rect, color_for_kind(entry.kind))
            if is_placeholder:
                p.fillRect(rect, QBrush(_PLACEHOLDER_HATCH, Qt.Dense6Pattern))
            p.setPen(_ASSET_BORDER)
            p.drawRect(rect)
            p.setPen(Qt.white)
            label = f"{glyph_for_kind(entry.kind)} {entry.symbol}"
            text_rect = QRectF(rect.x() + 2, rect.y(), rect.width() - 4, max(12.0, rect.height()))
            p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, label)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.mode == "design":
            paging, margin, gap, col_w, bar_top, bar_h, _bottom, _cols = self._geometry()
            for asset_id, rect in self._design_mode_rects(paging, margin, gap, col_w, bar_top, bar_h).items():
                if rect.contains(event.pos()):
                    self.asset_selected.emit(asset_id)
                    return
        super().mousePressEvent(event)
