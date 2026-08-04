"""Moving a region: finding the one line that decides its address, and rewriting it.

The memory map can show where everything lives (:mod:`memory_plan`); this is the other
half, the one that makes it a *tool* rather than a picture. Drag a block somewhere else
and something has to change in the source, because the source is the plan.

**One line changes, and it is the line the author would have changed.** Two shapes exist,
and which one applies is decided by what the ``org`` was written as:

    org Attributes     ->  rewrite `Attributes equ $8300` in sys/memmap.i
    org $8181          ->  rewrite the `org $8181` line itself

The first is the important one. A project of any size keeps its addresses in one table of
``equ``s and points every module's ``org`` at a name in it -- that table *is* the memory
plan its author maintains by hand. Moving a block by editing its ``equ`` keeps the table
and the code agreeing; rewriting the ``org`` instead would leave the table lying, which is
worse than not having the tool.

Rewrites are surgical: the value token is replaced and everything else on the line --
indentation, alignment, the trailing size comment -- is left exactly as it was, in the
notation it was already written in (``$8300`` stays ``$8300``, not ``0x8300``). A diff of a
drag should be one number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from zxemu_core.debug import asm_layout, asm_symbols
from zxemu_core.memlayout import PAGED_MODELS, SLOT_BASE, slot_for_bank
from zxemu_core.memory import BANK_SIZE
from zxemu_ui.workspace.memory_plan import entry_points

#: Manual drags land on this grid. A 16K column is a few hundred pixels, so byte-exact
#: dragging would produce addresses like $8C37; rounding keeps what lands in the source
#: table as readable as what the author would have typed.
DRAG_GRID = 256

#: How near another region's edge a drag has to come before it snaps flush against it.
#: Generous, because "pack this right after that" is the move you make constantly and
#: hitting it by hand at ~27 bytes per pixel is luck rather than aim.
MAGNET_BYTES = 512


@dataclass
class Anchor:
    """The single source line that decides a region's address."""

    path: str        # absolute path to the file holding it
    line: int        # 1-based
    kind: str        # "equ" (a constant the org points at) or "org" (a literal org)
    symbol: str      # the constant's name, for "equ"; empty otherwise
    display: str     # how to name this in a log line, e.g. "sys/memmap.i:19"


class NotMovable(Exception):
    """Why a region can't be dragged, phrased for the Output console rather than a stack trace."""


def symbol_table(project, read_source=None) -> dict:
    """The project's ``equ`` constants, resolved from its entry point down.

    From the *entry point*, not from the file the ``org`` sits in. A module deep in
    ``core/`` writes ``org Attributes`` without including the table that defines
    Attributes -- it doesn't need to, because whatever includes it did that first, and the
    assembler sees one translation unit rooted at the entry point. Looking the symbol up
    from the module's own file finds nothing, which is exactly the bug this replaced.
    """
    reader = read_source if read_source is not None else _read
    for entry in entry_points(project):
        path = project.folder / entry
        text = reader(str(path))
        if text is None:
            continue
        table = asm_symbols.collect(text, project.folder, reader)
        # Constants defined in the entry file itself carry no path of their own -- only
        # ones reached through an include do -- so fill that in; the edit needs a file.
        for constant in table.values():
            if not constant.path:
                constant.path, constant.origin = str(path), entry
        return table
    return {}


def anchor_for(project, region, read_source=None, symbols=None) -> Anchor:
    """Find the line that would have to change to move ``region``. Raises :class:`NotMovable`.

    Refuses rather than guesses. A region whose ``org`` is an expression (``Base + 32``),
    or whose symbol is defined somewhere this can't reach, has no single number to edit --
    and editing the wrong one silently would be far worse than saying so.

    ``symbols`` lets a caller checking many regions build the table once; without it, one
    is built per call.
    """
    if getattr(region, "pinned", False):
        reason = getattr(region, "reason", "")
        raise NotMovable("{} is pinned{}".format(region.name, ": " + reason if reason else " (; zxide: pin)"))

    expression = (region.org_expression or "").strip()
    if not expression:
        raise NotMovable("{} has no org of its own -- it follows whatever precedes it".format(region.name))

    if _is_literal(expression):
        if not region.origin:
            raise NotMovable("{} has no source file recorded".format(region.name))
        return Anchor(path=str(project.folder / region.origin), line=region.line, kind="org", symbol="", display="{}:{}".format(region.origin, region.line))

    if not _is_name(expression):
        raise NotMovable("{} is org'd to the expression '{}' -- move it by editing that expression".format(region.name, expression))

    table = symbols if symbols is not None else symbol_table(project, read_source)
    constant = table.get(expression.lower())
    if constant is None:
        raise NotMovable("cannot find where '{}' is defined".format(expression))
    if constant.line <= 0 or not constant.path:
        raise NotMovable("'{}' is defined somewhere without a line to edit".format(expression))
    display = "{}:{}".format(constant.origin or Path(constant.path).name, constant.line)
    return Anchor(path=constant.path, line=constant.line, kind="equ", symbol=constant.name, display=display)


def rewrite(line: str, anchor: Anchor, address: int) -> str:
    """Return ``line`` with its address replaced, everything else byte-for-byte unchanged."""
    pattern = _EQU_VALUE if anchor.kind == "equ" else _ORG_VALUE
    match = pattern.match(line)
    if match is None:
        raise NotMovable("{} no longer looks like the line it was ({})".format(anchor.display, line.strip()))
    return "{}{}{}".format(match.group(1), _format_like(match.group(2), address), match.group(3))


def _format_like(token: str, address: int) -> str:
    """Write ``address`` in the notation ``token`` already used -- $8300, #8300, 0x8300, 33536."""
    digits = "{:04X}".format(address)
    if token[:1] in ("$", "#"):
        return token[0] + _cased_like(token[1:], digits)
    if token.lower().startswith("0x"):
        return token[:2] + _cased_like(token[2:], digits)
    if token.lower().endswith("h"):
        return _cased_like(token[:-1], digits) + token[-1]
    return str(address)


def _cased_like(old_digits: str, digits: str) -> str:
    """Hex digits in the case the old ones used. Judged on the digits alone: the ``x`` in
    ``0x`` and the trailing ``h`` are notation, not something whose case anyone chose."""
    letters = [char for char in old_digits if char.isalpha()]
    upper = not letters or sum(char.isupper() for char in letters) * 2 >= len(letters)
    return digits if upper else digits.lower()


@dataclass
class BankChange:
    """The edits that put a block's bytes into a different bank.

    ``SLOT``/``PAGE`` are assembly-time statements and nothing else: they decide where in
    the assembled image the bytes go, independently of the paging the CPU will see later
    (verified against the real sjasmplus -- see ``asset_build``'s module docstring, which
    has relied on this for asset placement all along). So moving a block between banks is
    a *source layout* change like any other here, not a behavioural one; whether the
    program pages that bank in before calling into it is the program's business.
    """

    edits: list           # [(line, new text)] -- SLOT/PAGE lines already present
    insert_at: int = 0    # 1-based line to insert before; 0 when nothing to insert
    inserted: list = None # the lines to insert there

    def __post_init__(self):
        self.inserted = self.inserted or []

    @property
    def empty(self) -> bool:
        return not self.edits and not self.inserted


#: How far above an ``org`` to look for the ``SLOT``/``PAGE`` that belong to it. Directives
#: that place a block sit right on top of it, with at most a comment or blank line between;
#: anything further away belongs to something else and must not be rewritten.
_DIRECTIVE_SEARCH = 6


def plan_bank_change(lines: list, org_line: int, bank: str, model: str) -> BankChange:
    """What to change so the block org'd at ``org_line`` assembles into ``bank``.

    Updates a ``SLOT``/``PAGE`` pair already sitting above the ``org`` if there is one --
    the common case once a project pages at all -- and otherwise inserts the pair, matching
    the ``org``'s own indentation so the result looks written rather than generated. On an
    unpaged machine there is nothing to do: a 48K's banks *are* its slots, so the address
    alone says which one.
    """
    if model not in PAGED_MODELS or not bank.startswith("ram"):
        return BankChange(edits=[])

    slot, page = slot_for_bank(bank), int(bank[3:])
    found: dict = {}
    for number in range(max(1, org_line - _DIRECTIVE_SEARCH), org_line):
        match = _SLOT_OR_PAGE.match(lines[number - 1])
        if match is not None:
            found[match.group(2).lower()] = (number, match)

    edits = []
    for name, value in (("slot", slot), ("page", page)):
        if name in found:
            number, match = found[name]
            edits.append((number, "{}{}{}{}".format(match.group(1), match.group(2), match.group(3), value)))
    if "slot" in found and "page" in found:
        return BankChange(edits=edits)

    indent = _indent_of(lines[org_line - 1])
    return BankChange(edits=edits, insert_at=org_line, inserted=["{}SLOT {}".format(indent, slot), "{}PAGE {}".format(indent, page)])


@dataclass
class AnnotationChange:
    """How to give a block an attribute, or take one away: one line, one operation."""

    action: str = "none"   # "insert" | "replace" | "delete" | "none"
    line: int = 0          # 1-based
    text: str = ""

    @property
    def empty(self) -> bool:
        return self.action == "none"


def attribute_text(pinned: bool = False, align: int = 0, reserved: int = 0, reason: str = "") -> str:
    """The whole ``; zxide:`` payload for a block, from all of its constraints at once.

    Composed rather than appended because writing an attribute *replaces* the line: a menu
    that sent only the one you just changed would silently drop the others, so ticking
    "aligned" would quietly unpin an IM 2 handler. The block's full state goes in every
    time, and the line always says everything that is true of it.
    """
    parts = []
    if pinned:
        parts.append("pin")
    if align:
        parts.append("align({})".format(align))
    if reserved:
        parts.append("size({})".format(reserved))
    if not parts:
        return ""
    return ", ".join(parts) + (" " + reason if reason else "")


def plan_annotation(lines: list, org_line: int, attribute: str | None) -> AnnotationChange:
    """The edit that makes the block at ``org_line`` carry ``attribute`` (None removes it).

    Writing the attribute into the source rather than into a settings file is the whole
    point -- it is a fact about the code, it belongs next to the ``org`` it constrains, and
    it survives the project being moved, shared or opened by something that is not zxide.
    Editing it from the memory map is only a convenience over typing it there yourself.

    An attribute already sitting above the ``org`` is *replaced* rather than added to, so
    pinning something already aligned leaves one line, not two contradicting ones.
    """
    existing = 0
    for number in range(max(1, org_line - _DIRECTIVE_SEARCH), org_line):
        if asm_layout.is_annotation(lines[number - 1]):
            existing = number
    if attribute:
        text = "{}; zxide: {}".format(_indent_of(lines[org_line - 1]), attribute)
        if existing:
            return AnnotationChange("replace", existing, text)
        return AnnotationChange("insert", org_line, text)
    return AnnotationChange("delete", existing, "") if existing else AnnotationChange()


def _claimed(region) -> int:
    """What a block holds against its neighbours -- its declared size, or what it emits."""
    return getattr(region, "claimed", getattr(region, "length", 0))


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())] or "    "


def snap(address: int, region, others, grid: int = DRAG_GRID, magnet: int = MAGNET_BYTES) -> int:
    """Where a drag to ``address`` should actually land.

    Magnet first, grid second: if the dragged block comes close to another block's edge,
    it goes flush against it (which is the point of the gesture -- packing things tight
    leaves no gap to lose bytes in). Otherwise it rounds to the grid, so hand-placed
    addresses stay the kind of number a person would have typed.
    """
    base = SLOT_BASE[max(0, min(3, address // BANK_SIZE))]
    edges = []
    for other in others:
        if other is region or other.bank != region.bank or not other.bank:
            continue
        edges.append(base + other.end)                       # flush after it
        edges.append(base + other.offset - _claimed(region))  # flush before it
    # A block that states an alignment gets that and nothing else: an IM 2 vector table
    # snapped "helpfully" flush against its neighbour would stop being addressable at all.
    required = getattr(region, "align", 0)
    if required:
        return max(0, address - address % required)
    nearest = min(edges, key=lambda edge: abs(edge - address), default=None)
    if nearest is not None and abs(nearest - address) <= magnet and nearest >= 0:
        return nearest
    return max(0, address - address % grid)


def arrange(regions, movable, start: int | None = None) -> dict[int, int]:
    """Pack every movable region tight, per bank. Returns ``{id(region): new address}``.

    Deliberately dumb and predictable: within each bank, everything that *can* move is
    laid end to end in its current order, starting after the lowest fixed thing already
    there. Order is preserved rather than optimised -- a packer that also reordered would
    produce a diff nobody could review, and the order a project's blocks sit in is usually
    meaningful (interrupt table before the routine that uses it, and so on).

    Immovable regions are obstacles, not candidates: packing steps over them rather than
    through them, so a literal ``org`` in the middle of a file keeps its address.
    """
    moves: dict[int, int] = {}
    banks = sorted({region.bank for region in regions if region.bank})
    for bank in banks:
        in_bank = sorted([region for region in regions if region.bank == bank], key=lambda region: region.offset)
        fixed = [region for region in in_bank if id(region) not in movable]
        cursor = start if start is not None else min((region.offset for region in in_bank), default=0)
        base = SLOT_BASE[in_bank[0].slot] if in_bank else 0
        for region in in_bank:
            if id(region) not in movable:
                cursor = max(cursor, region.end)
                continue
            size = _claimed(region)
            cursor = _place(cursor, size, fixed, getattr(region, "align", 0))
            if cursor + size > BANK_SIZE:
                break  # out of bank: leave the rest where they are rather than wrap
            if cursor != region.offset:
                moves[id(region)] = base + cursor
            cursor += size
    return moves


def _place(cursor: int, length: int, fixed, align: int) -> int:
    """The first address at or after ``cursor`` that clears every fixed block *and* aligns.

    Both conditions, together, until they stop fighting: stepping over a pinned block can
    land off the boundary, and rounding up to the boundary can land back on another pinned
    block. Doing one then the other once -- which is what this did at first -- can leave an
    aligned block unaligned, and for an IM 2 vector table "nearly aligned" is simply broken.
    """
    for _attempt in range(len(fixed) * 2 + 2):  # each round clears at least one obstacle
        moved = _skip_fixed(cursor, length, fixed)
        if align and moved % align:
            moved += align - moved % align
        if moved == cursor:
            return cursor
        cursor = moved
    return cursor


def _skip_fixed(cursor: int, length: int, fixed) -> int:
    """Advance past any immovable region the proposed span would run into."""
    moved = True
    while moved:
        moved = False
        for region in fixed:
            if cursor < region.end and region.offset < cursor + length:
                cursor = region.end
                moved = True
    return cursor


_EQU_VALUE = re.compile(r"^(\s*[A-Za-z_@.][A-Za-z0-9_@.]*\s*:?\s*(?:equ|defl)\s+|\s*[A-Za-z_@.][A-Za-z0-9_@.]*\s*=\s*)(\S+)(.*)$", re.IGNORECASE)
_ORG_VALUE = re.compile(r"^(\s*org\s+)([^\s,;]+)(.*)$", re.IGNORECASE)
_NAME = re.compile(r"^[A-Za-z_@.][A-Za-z0-9_@.]*$")
#: A bare ``SLOT``/``PAGE`` directive, split so its indentation and spacing can be kept.
_SLOT_OR_PAGE = re.compile(r"^(\s*)(slot|page)(\s+)[^\s;]+\s*$", re.IGNORECASE)


def _is_literal(expression: str) -> bool:
    from zxemu_core.debug import asm_meter

    return asm_meter.parse_number(expression) is not None


def _is_name(expression: str) -> bool:
    return _NAME.match(expression) is not None


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
