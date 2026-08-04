"""The memory plan as a window you can actually work in: every bank, one row per block.

The Design-mode map in the dock draws memory *to scale*, which is honest and nearly
useless for rearranging: a 43-byte routine in a 16K column is two pixels, too small to
read, click or aim at. It also draws **slots**, so on a 128K it can only ever show the
four banks that happen to be paged in -- and the moment a project spreads across the other
four, half its plan is invisible.

This window answers both by giving up on proportion. Every block is the same height, and
what a block *is* -- its name, where it starts and ends, how big it is, which file put it
there -- is written in it as text. Free space is a row of its own, labelled with how much,
so "where would this fit" is something you read rather than measure. Every bank the
machine has gets a column, whether or not it is currently paged in, because where bytes
are *assembled* has nothing to do with what the CPU can see right now.

It is a real top-level window: maximise it and a project with eight populated banks is
still one screen. There was a to-scale dock version of this first, and it was removed:
neither of its ideas survived a real project.

Moving a block is the same one-line source edit ``zxemu_ui.workspace.memory_edit`` makes
anywhere else: drag a row and drop it where you want it, and it lands in the gap you
released it over -- the space between the two blocks you were pointing between.
"""

from __future__ import annotations

from PyQt5.QtCore import QMimeData, Qt, pyqtSignal
from PyQt5.QtGui import QDrag, QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from zxemu_ui.workspace import memory_edit
from zxemu_core.memlayout import PAGED_MODELS, SLOT_BASE, bank_ids_for_model, hardware_reserved, slot_for_bank
from zxemu_core.memory import BANK_SIZE

#: One row per block, always this tall. The whole point of the window: a 43-byte routine
#: and a 6912-byte screen are equally clickable, and the byte count is text rather than
#: something you estimate from a rectangle.
ROW_HEIGHT = 52
FREE_ROW_HEIGHT = 26
#: Wide enough for the longest detail line a row can carry -- "$8C50 - $90B9  1.1K
#: (estimate)" -- and no wider. A 128K can populate eight banks, and eight generous
#: columns is a horizontal scrollbar instead of a plan you can take in at once.
COLUMN_WIDTH = 182

#: Mime type carrying the dragged block's identity. A private type so a drag from here
#: can't be dropped somewhere that would misread it.
MIME_REGION = "application/x-zxide-region"

_CODE = "#35526f"
_DATA = "#4b4068"
_ASSET = "#3f5f4a"
_CONFLICT = "#e05252"
_FIXED_TEXT = "#8a8f96"


def column_order(model: str) -> list:
    """Banks in the order the machine actually presents memory, not in bank-number order.

    A 128K's numbering has nothing to do with its layout: banks 5 and 2 are soldered to
    ``$4000`` and ``$8000`` and are always there, while 0/1/3/4/6/7 exist only when ``$7FFD``
    pages one of them into ``$C000``. Listing them 0..7 therefore buries the two banks that
    are always in front of the CPU between six that usually are not. So: the fixed 64K
    first, in address order, then the pool.

    On a 48K there is nothing to reorder -- its banks are its slots and already in address
    order -- which is the same reason it needs no ``SLOT``/``PAGE`` when a block moves.
    """
    if model not in PAGED_MODELS:
        return bank_ids_for_model(model)
    fixed = ["rom0", "rom1", "ram5", "ram2"]
    return fixed + [bank for bank in bank_ids_for_model(model) if bank not in fixed]


def bank_position(bank: str, model: str) -> str:
    """How a bank reaches the CPU, for its column header."""
    if model not in PAGED_MODELS:
        return "slot {} · always".format(slot_for_bank(bank, model))
    if bank in ("ram5", "ram2"):
        return "slot {} · always".format(slot_for_bank(bank, model))
    if bank.startswith("rom"):
        return "slot 0 · $7FFD bit 4"
    return "slot 3 · when paged"


def _size_text(length: int) -> str:
    """Bytes for small things, K for big ones -- 348 reads better than 0.3K, 6912 doesn't."""
    if length >= 1024:
        return "{:.1f}K".format(length / 1024.0).replace(".0K", "K")
    return "{} b".format(length)


class MemoryPlanWindow(QDialog):
    """A column per bank, a uniform row per block, and the free space between them."""

    #: ``(source path, line)`` -- clicking a block opens the line that placed it.
    region_activated = pyqtSignal(str, int)
    #: ``(region, new address, target bank)`` -- a block was dropped somewhere else. The
    #: bank is carried separately because an address does not imply one: on a 128K every
    #: bank but RAM5 and RAM2 is addressed through the same slot 3.
    region_moved = pyqtSignal(object, int, str)
    #: The buttons; the window owns no logic of its own, the panel it mirrors does.
    #: ``(region, attribute)`` -- a right-click asked for `; zxide: <attribute>` on a
    #: block, or an empty string to remove whatever it has.
    attribute_requested = pyqtSignal(object, str)
    refresh_requested = pyqtSignal()
    arrange_requested = pyqtSignal()
    auto_locate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Memory plan")
        # A window, not a dialog-shaped box: minimise/maximise buttons and no modality, so
        # it can sit open on a second monitor while you work in the editor.
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.setModal(False)
        self.resize(1100, 720)

        self._plan = None
        self._model = "48k"
        self._movable: dict = {}
        self._show_empty = QCheckBox("Show empty banks")
        self._show_empty.setToolTip("Include RAM banks nothing is assembled into yet. ROM is never listed -- nothing can be placed there.")
        self._show_empty.setChecked(False)
        self._show_empty.toggled.connect(lambda _on: self.rebuild())

        refresh = QPushButton("Refresh")
        refresh.setToolTip("Re-read the project's sources")
        refresh.clicked.connect(self.refresh_requested)
        arrange = QPushButton("Arrange")
        arrange.setToolTip("Pack every movable block tight, in its current order")
        arrange.clicked.connect(self.arrange_requested)
        auto_locate = QPushButton("Auto-locate assets")
        auto_locate.clicked.connect(self.auto_locate_requested)

        self._summary = QLabel("")
        self._summary.setStyleSheet("color: #9aa0a6;")

        toolbar = QHBoxLayout()
        for widget in (refresh, arrange, auto_locate, self._show_empty):
            toolbar.addWidget(widget)
        toolbar.addSpacing(16)
        toolbar.addWidget(self._summary)
        toolbar.addStretch(1)

        self._columns = QWidget()
        self._columns_layout = QHBoxLayout(self._columns)
        self._columns_layout.setContentsMargins(0, 0, 0, 0)
        self._columns_layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._columns)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(scroll)

    def set_plan(self, plan, model: str, movable: dict) -> None:
        """Show ``plan``. ``movable`` is ``{id(region): region}`` for what can be dragged."""
        self._plan, self._model, self._movable = plan, model, movable
        self.rebuild()

    def rebuild(self) -> None:
        while self._columns_layout.count():
            # Take the widget out of the item *once* and work with that reference: the
            # layout item is a temporary, and asking it for its widget again after the
            # widget has been reparented reads a pointer Qt no longer owns.
            widget = self._columns_layout.takeAt(0).widget()
            if widget is not None:
                # Unparent now, delete later. Taking a widget out of a layout does not take
                # it off the screen -- it keeps its parent and its geometry until the
                # deferred delete runs, so without this a rebuild can leave the previous
                # columns drawn underneath the new ones until the event loop next turns.
                widget.setParent(None)
                widget.deleteLater()
        if self._plan is None:
            return

        claims_by_bank: dict = {}
        for claim in self._plan.claims:
            if claim.bank:
                claims_by_bank.setdefault(claim.bank, []).append(claim)

        shown = 0
        for bank in column_order(self._model):
            claims = sorted(claims_by_bank.get(bank, []), key=lambda claim: claim.offset)
            if not claims and (bank.startswith("rom") or not self._show_empty.isChecked()):
                # ROM is never a column you can plan into -- it is somebody else's bytes,
                # and the free-space search refuses it outright -- so an empty ROM bank is
                # pure noise here, even with "show empty" on. It appears only when the
                # project genuinely assembles into it (a ROM replacement, or a dump of
                # one), because then hiding it would be lying by omission.
                continue
            self._columns_layout.addWidget(_BankColumn(bank, self._model, claims, self._movable, self))
            shown += 1
        self._columns_layout.addStretch(1)

        used = sum(claim.length for claim in self._plan.claims if claim.bank)
        conflicts = len(self._plan.conflicts)
        # Which program this is a plan of, first: a project holds several buildable sources
        # (the game, and a test of one part of it) with entirely different memory maps, and
        # a plan that doesn't name its entry point is a map with no "you are here".
        entry = " · ".join(getattr(self._plan, "entries", []) or ["no source"])
        self._summary.setText("{} · {} blocks in {} banks · {} used · {}".format(
            entry, len(self._plan.claims), shown, _size_text(used),
            "no conflicts" if not conflicts else "{} conflict(s)".format(conflicts)))

    def conflicting_names(self) -> set:
        if self._plan is None:
            return set()
        return {name for conflict in self._plan.conflicts for name in (conflict.first, conflict.second)}

    # --- what the rows call back into ------------------------------------------

    def set_attribute(self, region, attribute) -> None:
        """Ask for ``; zxide: <attribute>`` on this block, or None to take it off."""
        self.attribute_requested.emit(region, attribute or "")

    def report(self, message: str) -> None:
        """Say something in the header line -- a drop that could not be honoured, mostly."""
        self._summary.setText(message)

    def activate(self, region) -> None:
        if getattr(region, "origin", ""):
            self.region_activated.emit(region.origin, region.line)

    def move(self, region, address: int, bank: str) -> None:
        """Move a block, into another bank if that is where it was dropped.

        Crossing banks is not a different kind of operation, just a slightly longer edit:
        ``SLOT``/``PAGE`` are assembly-time placement, exactly like the ``org`` itself, and
        placement is what this window is for. Whether the program pages that bank in before
        calling the code is the program's business -- the same division that has always
        applied to assets, which have been placed into arbitrary banks all along.
        """
        self.region_moved.emit(region, address, bank or region.bank)


class _BankColumn(QFrame):
    """One bank: its blocks in address order, with the gaps between them spelled out."""

    def __init__(self, bank: str, model: str, claims: list, movable: dict, window: MemoryPlanWindow):
        super().__init__()
        self.bank, self.window = bank, window
        self.setAcceptDrops(True)
        self.setFixedWidth(COLUMN_WIDTH)
        self.setFrameShape(QFrame.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(3)

        # The always-mapped banks are brighter: at a glance you can tell the memory the CPU
        # can always reach from the memory it can only reach after a port write.
        always = bank in ("ram5", "ram2") or model not in PAGED_MODELS
        header = QLabel(bank.upper())
        header.setStyleSheet("font-weight: bold; color: {};".format("#d8dde3" if always else "#98a2ad"))
        position = QLabel(bank_position(bank, model))
        position.setStyleSheet("color: #7f8a96; font-size: 11px;")
        layout.addWidget(header)
        layout.addWidget(position)

        conflicted = window.conflicting_names()
        # Kept, not just used: a drop on the column itself needs them to find a home for
        # the block, and re-deriving them there would mean re-deriving the model too.
        self.base = SLOT_BASE[slot_for_bank(bank, model)]
        self.free = _free_ranges(bank, model, claims)
        base = self.base
        self._entries = []  # (widget, entry) in address order, for resolving a drop position
        for entry in _interleave(claims, self.free):
            if isinstance(entry, tuple):
                widget = _FreeRow(bank, base, entry[0], entry[1], window)
            else:
                widget = _RegionRow(entry, base, id(entry) in movable, entry.name in conflicted, window)
            self._entries.append((widget, entry))
            layout.addWidget(widget)
        layout.addStretch(1)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(MIME_REGION):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        """The block goes in the gap you released it over.

        One rule, resolved here rather than in each row, because three handlers deciding
        this separately is how they came to disagree. The rows are uniform height, so the
        vertical position in a column is not an address -- it is a place in the sequence.
        "The gap nearest the cursor" therefore means "the space between those two blocks",
        which is how you point at it in the first place.
        """
        dragged = _dragged_from(event)
        if dragged is None:
            return
        gap = self._gap_at(event.pos().y())
        if gap is None:
            self.window.report("{} has no free space at all".format(self.bank.upper()))
            return
        offset = fits_at(gap[0], gap[1], dragged.claimed, getattr(dragged, "align", 0))
        if offset is None:
            self.window.report("{} ({}) does not fit in the {} gap at ${:04X} -- largest free run in {} is {}".format(
                dragged.name, _size_text(dragged.claimed), _size_text(gap[1]), self.base + gap[0],
                self.bank.upper(), _size_text(max(available for _offset, available in self.free))))
            return
        self.window.move(dragged, self.base + offset, self.bank)
        event.acceptProposedAction()

    def _gap_at(self, y: int):
        """The free range the cursor is pointing at, as ``(offset, length)``.

        Released over a gap strip, it is that gap. Released over a *block*, it is the gap
        on the side of that block you released nearest -- top half means the space above
        it, bottom half the space below -- which is the ordinary list-insertion gesture and
        the only way to reach a gap too thin to aim at. Released past the last row, it is
        the last gap.
        """
        if not self.free:
            return None
        nearest, best = None, None
        for widget, entry in self._entries:
            box = widget.geometry()
            if isinstance(entry, tuple):
                distance = 0 if box.top() <= y <= box.bottom() else min(abs(y - box.top()), abs(y - box.bottom()))
                candidate = entry
            else:
                above = y < box.center().y()
                candidate = self._gap_beside(entry, above)
                distance = 0 if box.top() <= y <= box.bottom() else min(abs(y - box.top()), abs(y - box.bottom()))
            if candidate is not None and (best is None or distance < best):
                nearest, best = candidate, distance
        return nearest if nearest is not None else self.free[-1]

    def _gap_beside(self, region, above: bool):
        """The free range immediately before or after a block, or None if it is flush."""
        if above:
            fitting = [gap for gap in self.free if gap[0] + gap[1] <= region.offset]
            return fitting[-1] if fitting else None
        fitting = [gap for gap in self.free if gap[0] >= region.offset + region.length]
        return fitting[0] if fitting else None


def _badge(region) -> str:
    """A mark in front of the name for a block whose source states a constraint."""
    if getattr(region, "pinned", False):
        return "📌 "
    if getattr(region, "align", 0):
        return "⇥ "
    return ""


def _movability(region, movable: bool) -> str:
    """The last tooltip line: whether this block can be moved, and if not, why not."""
    reason = getattr(region, "reason", "")
    if getattr(region, "pinned", False):
        return "pinned: {}".format(reason or "something outside the bytes depends on this address")
    if not movable:
        return "fixed: its address is not a single editable line"
    if getattr(region, "align", 0):
        return "drag to move -- lands only on {}-byte boundaries{}".format(region.align, " ({})".format(reason) if reason else "")
    return "drag to move"


def fits_at(offset: int, available: int, length: int, align: int = 0) -> int | None:
    """Where a block starts inside one gap, or None if it doesn't fit in it.

    An alignment moves the start to the first boundary *inside* the gap, and the fit is
    then checked against what is left -- rounding up after accepting the gap would place
    the block past the end of it.
    """
    start = offset
    if align and start % align:
        start += align - start % align
    return start if start + length <= offset + available else None


def _free_ranges(bank: str, model: str, claims: list) -> list:
    """The unclaimed runs in a bank, from the *union* of everything that claims bytes.

    Computed by merging rather than by placing one claim at a time, because two claims can
    overlap -- that is precisely the situation this window exists to show. Placing them
    would reject the second, and the bytes under it would then be drawn as free, which is
    the one thing a free-space row must never say wrongly.
    """
    occupied = sorted(hardware_reserved(bank, model) + [(claim.offset, claim.claimed) for claim in claims if claim.claimed > 0])
    free: list = []
    cursor = 0
    for offset, length in occupied:
        if offset > cursor:
            free.append((cursor, offset - cursor))
        cursor = max(cursor, offset + length)
    if cursor < BANK_SIZE:
        free.append((cursor, BANK_SIZE - cursor))
    return free


def _interleave(claims: list, free: list) -> list:
    """Blocks and gaps in one ordered list, so a column reads top to bottom as memory does."""
    entries = [(claim.offset, claim) for claim in claims]
    entries += [(offset, (offset, length)) for offset, length in free if length > 0]
    return [entry for _offset, entry in sorted(entries, key=lambda pair: pair[0])]


class _RegionRow(QFrame):
    """One block, always the same height: name, where it starts and ends, and how big."""

    def __init__(self, region, base: int, movable: bool, conflicted: bool, window: MemoryPlanWindow):
        super().__init__()
        # The column already worked out this bank's base address for the model it is
        # drawing; keep it rather than re-deriving one here, where the model isn't known.
        self.region, self.base, self.movable, self.window = region, base, movable, window
        self.setFixedHeight(ROW_HEIGHT)
        self.setCursor(Qt.OpenHandCursor if movable else Qt.ArrowCursor)

        fill = {"asset": _ASSET, "data": _DATA}.get(region.kind, _CODE)
        border = _CONFLICT if conflicted else "#5c6b7a"
        self.setStyleSheet("QFrame {{ background: {}; border: 1px solid {}; border-radius: 3px; }}".format(fill, border))

        start = base + region.offset
        reserved = getattr(region, "reserved", 0)
        # "~1.1K" rather than "1.1K (estimate)": the same admission, in one character
        # instead of eleven, which is the difference between eight banks fitting on screen
        # and not. The tooltip spells it out for anyone who hasn't met the convention.
        # Two numbers when a block has asked for room: what it uses, and what it holds.
        # One number would have to be a lie in one direction or the other.
        size = "{}{}".format("~" if region.estimated else "", _size_text(region.length))
        if reserved:
            size = "{} / {}".format(size, _size_text(region.claimed))
        detail = "${:04X} - ${:04X}   {}".format(start, start + max(0, region.claimed - 1), size)

        # A constraint has to be visible without hovering: a pinned block that merely looks
        # like every other block is a trap, because the one thing you need to know about it
        # is that dragging it will not work.
        name = QLabel("{}{}".format(_badge(region), region.name))
        name.setStyleSheet("border: none; font-weight: bold; color: {};".format("#eef2f6" if movable else _FIXED_TEXT))
        info = QLabel(detail)
        # A size down, because the address range is reference text you glance at, while the
        # name is what you look for -- and because it has to fit a column, not a monitor.
        info.setStyleSheet("border: none; color: #b8c2cc; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(1)
        layout.addWidget(name)
        layout.addWidget(info)

        where = "{}:{}".format(region.origin, region.line) if region.origin else "no source"
        size = "{} bytes{}".format(region.length, " (estimated -- a macro or conditional this can't expand)" if region.estimated else "")
        self.setToolTip("{}\n{}\n{}\n{}\n{}".format(region.name, detail, size, where, _movability(region, movable)))


    def _ask_size(self, compose) -> None:
        """Ask how much room to hold, seeded with what the block currently uses."""
        current = getattr(self.region, "reserved", 0) or self.region.length
        value, ok = QInputDialog.getInt(
            self, "Reserve size",
            "Bytes to hold for {} (it uses {} today):".format(self.region.name, _size_text(self.region.length)),
            max(1, current), 1, BANK_SIZE, 16)
        if ok:
            compose(reserved=value)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        self._press = event.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self.movable or not (event.buttons() & Qt.LeftButton):
            return
        drag = QDrag(self)
        data = QMimeData()
        data.setData(MIME_REGION, str(id(self.region)).encode("ascii"))
        drag.setMimeData(data)
        drag.setPixmap(self.grab())
        _DRAGGED[id(self.region)] = self.region
        drag.exec_(Qt.MoveAction)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.window.activate(self.region)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """Right-click a block to constrain it, instead of typing the comment yourself.

        The attribute still lives in the source -- this only saves you finding the file and
        the line. Which is most of the work: a project has an ``org`` in every module, and
        the ones that must not move are exactly the ones you would forget to mark.
        """
        menu = QMenu(self)
        pinned = getattr(self.region, "pinned", False)
        align = getattr(self.region, "align", 0)
        reserved = getattr(self.region, "reserved", 0)
        reason = getattr(self.region, "reason", "")

        def compose(**changed):
            """Rewrite the whole attribute line, changing one thing and keeping the rest."""
            state = dict(pinned=pinned, align=align, reserved=reserved, reason=reason)
            state.update(changed)
            self.window.set_attribute(self.region, memory_edit.attribute_text(**state))

        pin = menu.addAction("Unpin" if pinned else "Pin — never move this block")
        pin.triggered.connect(lambda: compose(pinned=not pinned))

        size = menu.addAction("Reserve size…  ({})".format(_size_text(reserved)) if reserved else "Reserve size…")
        size.setToolTip("Hold room for this block to grow into. Reserves space in the plan without emitting any bytes.")
        size.triggered.connect(lambda: self._ask_size(compose))
        if reserved:
            clear = menu.addAction("Stop reserving size")
            clear.triggered.connect(lambda: compose(reserved=0))

        for boundary in (256, 1024):
            action = menu.addAction("Aligned to {} bytes".format(boundary))
            action.setCheckable(True)
            action.setChecked(align == boundary)
            action.triggered.connect(lambda _checked=False, b=boundary: compose(align=0 if align == b else b))

        menu.addSeparator()
        source = menu.addAction("Open {}:{}".format(self.region.origin, self.region.line) if self.region.origin else "No source")
        source.setEnabled(bool(self.region.origin))
        source.triggered.connect(lambda: self.window.activate(self.region))
        menu.exec_(event.globalPos())


class _FreeRow(QFrame):
    """A run of unclaimed bytes, labelled -- the thing you drop a block into."""

    def __init__(self, bank: str, base: int, offset: int, length: int, window: MemoryPlanWindow):
        super().__init__()
        self.bank, self.base, self.offset, self.length, self.window = bank, base, offset, length, window
        self.setFixedHeight(FREE_ROW_HEIGHT)
        self.setStyleSheet("QFrame { background: transparent; border: 1px dashed #4a5561; border-radius: 3px; }")

        label = QLabel("{} free   ${:04X} - ${:04X}".format(_size_text(length), base + offset, base + offset + length - 1))
        label.setStyleSheet("border: none; color: #7f8a96; font-size: 11px;")
        label.setAlignment(Qt.AlignCenter)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.addWidget(label)



#: Qt drags carry bytes, and a Region is a Python object, so the drag passes its id and
#: this maps it back. Scoped to the drag itself -- entries are only read during a drop.
_DRAGGED: dict = {}


def _dragged_from(event):
    try:
        return _DRAGGED.get(int(bytes(event.mimeData().data(MIME_REGION)).decode("ascii")))
    except (TypeError, ValueError):
        return None
