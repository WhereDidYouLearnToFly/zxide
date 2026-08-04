"""Where a project's bytes land, read from the *source* instead of from a build.

``org $8000``, a label, and a ``MODULE`` already say where a program's parts live. That
is a memory plan, written in the one place that cannot go stale, and this module reads it
back out: source in, a list of :class:`Region` out, each with a bank, an offset, a length
and the line that opened it. The memory map draws those; :mod:`zxemu_core.memlayout`'s
free-space search consumes them so auto-locate stops dropping an asset on top of code.

It is the third module here that reads source rather than memory, and it leans on the
other two rather than re-parsing anything:

* :func:`asm_meter.split_line` splits a line into its label and statements (a label is
  what names a region, so the meter now returns it instead of dropping it).
* :func:`asm_meter.measure_statement` prices every statement this module does not
  intercept, and its ``unknown`` count is exactly the signal for "this length is a guess"
  -- a macro invocation the meter cannot see through is why a region gets flagged.
* :func:`asm_symbols.collect` supplies the ``equ`` table, because real projects do not
  write ``org $7b00`` -- they write ``org AppStart`` against a hand-maintained table of
  addresses, which is the memory plan the author actually edits. An ``org`` this module
  could not evaluate would be a region it could not place at all.

**What it promises, and what it does not.** Like everything in this package, it says so
rather than bluffing. An unexpanded macro, a ``DUP``/``REPT`` block, or a conditional
whose branches it counts blind all set ``estimated`` -- the length is the right order of
magnitude, not the truth. A bare ``org $c000`` on a 128K sets ``ambiguous_bank``, because
which of the eight banks sits in slot 3 depends on a port write no static reader can see
(``workspace/sld.py`` refuses the same question for the same reason). The exact answer
exists only after a build, in the ``.sld``, and the caller is expected to prefer it where
it has one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from zxemu_core.debug import asm_meter, asm_symbols
from zxemu_core.memlayout import PAGED_MODELS, default_bank_for_slot, slot_for_address
from zxemu_core.memory import BANK_SIZE

#: Matches ``asm_symbols``' cap: deep enough for real projects, shallow enough to stay instant.
MAX_INCLUDE_DEPTH = 8

_QUOTED = re.compile(r"""["'<]([^"'>]+)["'>]?""")

#: Placement constraints, written as a comment because the source is the plan and this
#: belongs beside the ``org`` it constrains rather than in a file somewhere else:
#:
#:     ; zxide: pin IM2 handler -- its address is the fill byte doubled
#:     ; zxide: align 256       -- movable, but only onto 256-byte boundaries
#:
#: Deliberately *not* a vocabulary of hardware concepts. What an IM 2 vector table, an RST
#: target, a jump-table entry and a routine whose address got poked into a struct have in
#: common is not interrupts -- it is that something outside the bytes depends on where they
#: are. One generic constraint covers all of them, and stays right for whatever the next
#: project invents. The trailing text is the *reason*, carried through to the UI so the
#: next reader learns why rather than just being refused.
#:
#: Read from the raw line before comments are stripped, and applied to the next ``org``.
#:
#: Two patterns, not one, and the reason matters: these are *attributes*, not comments that
#: happen to be read. So anything addressed to ``zxide:`` is claimed first, and only then
#: checked -- a mistyped ``pinn``, or an ``align`` with no number, is reported rather than
#: ignored. Silently doing nothing is the worst possible answer here: you would believe a
#: block was pinned, and Arrange would move it.
_ADDRESSED = re.compile(r"(?:;+|//)\s*zxide\s*:\s*(.*)$", re.IGNORECASE)
_ATTRIBUTE = re.compile(r"^(pin|pinned|align|size|reserve)\b[ \t]*(.*)$", re.IGNORECASE)

# A macro or struct *definition* emits nothing where it is written -- only where it is
# called. Counting its body as bytes would inflate whichever region happened to contain it.
_DEFINITION_OPEN = frozenset({"macro", "struct"})
_DEFINITION_CLOSE = frozenset({"endm", "mend", "endmacro", "ends"})

# Directives whose presence means a length is no longer exact: repeat blocks emit their body
# more than once, conditionals emit one branch and we count both, and a Lua block can emit
# anything at all. All of them cost zero bytes *themselves*, so the meter is quite right to
# price them at nothing -- the uncertainty is about the lines around them.
_UNCERTAIN = frozenset({"dup", "edup", "rept", "endr", "if", "ifdef", "ifndef", "ifn", "ifused", "else", "elseif", "lua", "endlua"})


@dataclass
class Region:
    """One ``org``'d run of bytes: what it is called, where it lands, and how sure we are."""

    name: str
    kind: str                      # "code" or "data" -- whichever contributed more bytes
    slot: int                      # 0-3, the 16K address-space slot it sits in
    bank: str                      # memlayout bank id ("ram1", "ram5", ...); "" when ambiguous
    offset: int                    # within the bank
    length: int
    address: int                   # the CPU address it was org'd to
    origin: str = ""               # source file it came from
    line: int = 0                  # 1-based line of the `org` that opened it
    estimated: bool = False        # length is a guess -- macros, repeats, conditionals
    ambiguous_bank: bool = False   # 128K slot 3: the bank depends on runtime paging
    # What the `org` was written as -- "$8000", or a name like "AppStart". Kept verbatim
    # because moving a region means rewriting whichever line decides that address, and a
    # symbol sends the edit to the `equ` that defines it rather than to the `org` itself.
    org_expression: str = ""
    module: str = ""               # the MODULE enclosing it, if any
    # Constraints the source states about where this block may live, because nothing else
    # can know them. An IM 2 vector table has to start on a 256-byte boundary (the Z80
    # builds the vector from the I register as a high byte and cannot express anything
    # else), and its handler has to sit at the address its fill byte spells out -- neither
    # is visible in the bytes, and moving either one silently kills the interrupt.
    pinned: bool = False           # `; zxide: pin` -- never move this
    align: int = 0                 # `; zxide: align 256` -- movable, but only onto boundaries
    reason: str = ""               # what the annotation said, so the UI can explain the refusal
    # `; zxide: size 512` -- the room this block is *given*, as opposed to the bytes it
    # currently emits. Room to grow into, declared once, so a module putting on a hundred
    # bytes doesn't shove everything above it up the bank. Costs nothing in the output:
    # unlike padding with `defs`, no bytes are emitted, so it adds nothing to a tape.
    reserved: int = 0

    @property
    def claimed(self) -> int:
        """The bytes this block holds against the rest of memory.

        Its declared size if it has one, else what it emits -- and the declared size only
        while it is the larger of the two. A block that outgrows its budget claims what it
        actually needs, because the alternative is a map saying everything fits while the
        assembler quietly writes over the next thing along.
        """
        return max(self.length, self.reserved)

    @property
    def end(self) -> int:
        return self.offset + self.claimed


@dataclass
class LayoutResult:
    """Everything one scan found."""

    regions: list[Region] = field(default_factory=list)
    device: str = ""                                     # the DEVICE the source selected, if any
    missing_includes: list[str] = field(default_factory=list)  # `include`s that couldn't be read
    bad_annotations: list[str] = field(default_factory=list)   # `; zxide:` lines that made no sense
    missing_binaries: list[str] = field(default_factory=list)  # `incbin`s whose file could not be read


def is_annotation(line: str) -> bool:
    """Is this line addressed to zxide? Public so the editor recognises its own attributes.

    One definition of "an attribute line", used both by the scanner that reads them and by
    the code that writes them from the memory plan window -- two regexes would drift, and
    the failure would be an attribute that could be written but never read.
    """
    return _ADDRESSED.search(line) is not None


def scan(text, model, origin="", base_dir=None, read_source=None, file_size=None) -> LayoutResult:
    """Walk ``text`` (and everything it ``include``s) and report the regions it defines.

    ``model`` is the project's machine, used to turn addresses into banks; a ``DEVICE``
    line in the source overrides it, since that is what the assembler will actually obey.
    ``read_source`` maps a path to its text -- the editor passes one that prefers the open,
    possibly-unsaved tab, which is what makes a Refresh reflect what you are looking at.
    ``file_size`` maps a path to its byte length, for ``incbin``: without it every asset
    include would be flagged as an estimate for no reason, since a binary's size is a fact
    on disk rather than something to infer.
    """
    scanner = _Scanner(model, read_source, file_size, base_dir)
    # The equ table first, over the whole include tree: `org AppStart` has to resolve, and
    # the constant that names it is usually in an include the org's own file pulled in.
    scanner.symbols = asm_symbols.collect(text, base_dir, scanner.read_source)
    scanner.run(text, origin)
    scanner.close_region()
    return LayoutResult(regions=scanner.regions, device=scanner.device, missing_includes=scanner.missing_includes, bad_annotations=scanner.bad_annotations,
                        missing_binaries=scanner.missing_binaries)


class _OpenRegion:
    """A region being accumulated: its name is filled in by the first thing that names it."""

    def __init__(self, address: int, slot: int, bank: str, ambiguous: bool, origin: str, line: int, expression: str = "", module: str = "", pinned: bool = False, align: int = 0, reason: str = "", reserved: int = 0):
        self.address = address
        self.pinned = pinned
        self.align = align
        self.reason = reason
        self.reserved = reserved
        self.slot = slot
        self.bank = bank
        self.ambiguous = ambiguous
        self.origin = origin
        self.line = line
        self.expression = expression
        self.module = module
        self.name: str | None = None
        self.code_bytes = 0
        self.data_bytes = 0
        self.estimated = False


class _Scanner:
    """The assembler's own bookkeeping, kept just far enough to know where bytes go.

    Deliberately *not* an assembler: it tracks the address cursor, the current slot/page,
    the module stack and whether it is inside a macro definition, and nothing else. Every
    question beyond that (what an expression evaluates to, which branch of an ``if`` is
    taken) is answered "don't know" via the ``estimated`` flag rather than guessed.
    """

    def __init__(self, model: str, read_source=None, file_size=None, base_dir=None):
        self.model = model
        self.read_source = read_source if read_source is not None else _read_file
        self.file_size = file_size if file_size is not None else _file_size
        # Where relative paths resolve from. It follows the include chain rather than
        # staying at the project root, because that is what the assembler does: a file in
        # sub/ that includes "part.asm" means sub/part.asm.
        self.directory = Path(base_dir) if base_dir is not None else None
        self.device = ""
        self.regions: list[Region] = []
        self.missing_includes: list[str] = []
        self.missing_binaries: list[str] = []
        self.bad_annotations: list[str] = []
        self.cursor = 0                       # sjasmplus starts at 0 until an org says otherwise
        self.slot: int | None = None          # set by an explicit SLOT
        self.pages: dict[int, int] = {}       # slot -> page, from PAGE
        self.modules: list[str] = []
        self.open: _OpenRegion | None = None
        self.pending_label: str | None = None
        self.pending_pin = False              # a `; zxide: pin` awaiting its org
        self.pending_align = 0
        self.pending_reserved = 0
        self.pending_reason = ""
        self.definition_depth = 0             # >0 while inside a macro/struct definition
        self.seen: set[str] = set()
        self.symbols: dict = {}               # equ constants, for `org SomeLabel`

    def value_of(self, expression: str) -> int | None:
        """A literal, or a constant expression the ``equ`` table can settle. None if neither."""
        literal = asm_meter.parse_number(expression)
        if literal is not None:
            return literal
        return asm_symbols.evaluate(expression, self.symbols)

    # --- region bookkeeping ---------------------------------------------------------

    def close_region(self) -> None:
        """Finish the open region, discarding it if it never emitted a byte."""
        open_region = self.open
        self.open = None
        if open_region is None:
            return
        length = open_region.code_bytes + open_region.data_bytes
        if length <= 0 and not open_region.reserved and not open_region.estimated:
            # An `org` with nothing after it describes no bytes -- unless it has *asked* for
            # room, which is how you reserve space without emitting anything at all.
            return
        name = open_region.name or "org ${:04x}".format(open_region.address)
        kind = "data" if open_region.data_bytes > open_region.code_bytes else "code"
        self.regions.append(
            Region(
                name=name, kind=kind, slot=open_region.slot, bank=open_region.bank,
                offset=open_region.address % BANK_SIZE, length=length, address=open_region.address,
                origin=open_region.origin, line=open_region.line,
                estimated=open_region.estimated, ambiguous_bank=open_region.ambiguous,
                org_expression=open_region.expression, module=open_region.module,
                pinned=open_region.pinned, align=open_region.align, reason=open_region.reason,
                reserved=open_region.reserved,
            )
        )

    def open_region(self, address: int, origin: str, line: int, inherit_label: bool = False, expression: str = "") -> None:
        self.close_region()
        slot = slot_for_address(address)
        bank, ambiguous = self._bank_for(slot)
        self.open = _OpenRegion(address, slot, bank, ambiguous, origin, line, expression, ".".join(self.modules), self.pending_pin, self.pending_align, self.pending_reason, self.pending_reserved)
        self.pending_pin, self.pending_align, self.pending_reserved, self.pending_reason = False, 0, 0, ""  # consumed by the org they were written for
        if self.modules:
            self.open.name = ".".join(self.modules)
        elif inherit_label:
            # Source that emits bytes before any `org` opens its region on the *byte*, one
            # line after the label that names it -- so that label is held over rather than lost.
            self.open.name = self.pending_label
        self.pending_label = None

    def _bank_for(self, slot: int) -> tuple[str, bool]:
        """``(bank id, is_ambiguous)`` for a slot, honouring any ``PAGE`` the source set."""
        if self.model in PAGED_MODELS:
            page = self.pages.get(slot)
            if page is not None:
                return ("rom{}" if slot == 0 else "ram{}").format(page), False
        bank = default_bank_for_slot(self.model, slot)
        return (bank, False) if bank is not None else ("", True)

    def name_region(self, name: str) -> None:
        """The first label (or module) inside a region names it; later ones don't rename it."""
        if self.open is None:
            self.pending_label = name
        elif self.open.name is None:
            self.open.name = name

    def emit(self, code_bytes: int, data_bytes: int, origin: str, line: int) -> None:
        """Account for bytes at the cursor, opening an implicit region if none is open.

        Source before any ``org`` assembles at address 0 -- unusual but legal, and silently
        dropping it would make the map lie by omission rather than by imprecision.
        """
        if self.open is None:
            self.open_region(self.cursor, origin, line, inherit_label=True)
        self.open.code_bytes += code_bytes
        self.open.data_bytes += data_bytes
        self.cursor = (self.cursor + code_bytes + data_bytes) & 0xFFFF

    def mark_estimated(self) -> None:
        if self.open is not None:
            self.open.estimated = True

    # --- the walk -------------------------------------------------------------------

    def run(self, text: str, origin: str, depth: int = MAX_INCLUDE_DEPTH) -> None:
        for number, raw_line in enumerate(text.splitlines(), start=1):
            # Before the comment is stripped: a placement constraint lives in one, and
            # applies to the next org -- whether it is written above that line or on it.
            self._note_annotation(raw_line, origin, number)
            label, statements = asm_meter.split_line(raw_line)
            if self.definition_depth > 0:
                self._skip_definition(statements)
                continue
            if label:
                self.name_region(label)
            for statement in statements:
                self._statement(statement, origin, number, depth)

    def _note_annotation(self, raw_line: str, origin: str, line: int) -> None:
        """Read one ``; zxide:`` line -- one attribute or several, separated by commas."""
        addressed = _ADDRESSED.search(raw_line)
        if addressed is None:
            return
        body = addressed.group(1).strip()
        if not body:
            self._bad(origin, line, body, "expected pin, align(n) or size(n)")
            return
        for part in body.split(","):
            self._attribute(part.strip(), body, origin, line)

    def _attribute(self, part: str, body: str, origin: str, line: int) -> None:
        """One attribute: ``pin``, ``size(512)``, or the older ``size 512``.

        Both spellings, because the parenthesised one reads better in a list and the bare
        one was already written into a project before the list existed. Anything trailing
        that is not an attribute becomes the *reason*, which the UI shows when it refuses
        to move a block -- optional, and worth writing only when the constraint is not
        obvious from the code beside it.
        """
        if not part:
            return
        attribute = _ATTRIBUTE.match(part)
        if attribute is None:
            self._bad(origin, line, body, "'{}' is not an attribute -- expected pin, align(n) or size(n)".format(part))
            return

        keyword = attribute.group(1).lower()
        rest = (attribute.group(2) or "").strip()
        if keyword.startswith("pin"):
            self.pending_pin = True
            self.pending_reason = self.pending_reason or rest.strip(" \t-:()")
            return

        # `size(512) trailing words` and `size 512 trailing words` both land here.
        inside = rest[1:rest.index(")")] if rest.startswith("(") and ")" in rest else rest.split()[0] if rest.split() else ""
        value = asm_meter.parse_number(inside)
        if not value or value <= 0:
            self._bad(origin, line, body, "{} needs a number of bytes, e.g. '{}(512)'".format(keyword, keyword))
            return
        if keyword == "align":
            self.pending_align = value
        else:
            self.pending_reserved = value
        remainder = rest[rest.index(")") + 1:] if rest.startswith("(") and ")" in rest else rest.partition(" ")[2]
        self.pending_reason = self.pending_reason or remainder.strip(" \t-:")

    def _bad(self, origin: str, line: int, text: str, why: str) -> None:
        self.bad_annotations.append("{}:{}: zxide: {} -- {}".format(origin or "?", line, text, why))

    def _skip_definition(self, statements: list[str]) -> None:
        """Inside a macro/struct body: count nothing, just watch for the end of it."""
        for statement in statements:
            mnemonic = statement.split(None, 1)[0].lower()
            if mnemonic in _DEFINITION_OPEN:
                self.definition_depth += 1
            elif mnemonic in _DEFINITION_CLOSE:
                self.definition_depth -= 1

    def _statement(self, statement: str, origin: str, line: int, depth: int) -> None:
        head = statement.split(None, 1)
        mnemonic = head[0].lower()
        rest = head[1].strip() if len(head) > 1 else ""

        if mnemonic in _DEFINITION_OPEN:
            self.definition_depth += 1
            return
        if mnemonic in _UNCERTAIN:
            self.mark_estimated()
            return
        if mnemonic == "device":
            self.device = rest.split(",")[0].strip().lower()
            # Only override the project's model where the two genuinely disagree about
            # paging -- a Pentagon project selecting `zxspectrum128` (the only sensible
            # device for it) must stay a Pentagon, not be rewritten into a 128K.
            if "128" in self.device and self.model not in PAGED_MODELS:
                self.model = "128k"
            elif "48" in self.device and self.model in PAGED_MODELS:
                self.model = "48k"
            return
        if mnemonic == "org":
            address = self.value_of(rest.split(",")[0])
            if address is None:
                self.mark_estimated()  # an org we can't evaluate: everything after it is a guess
                return
            self.cursor = address & 0xFFFF
            self.open_region(self.cursor, origin, line, expression=rest.split(",")[0].strip())
            return
        if mnemonic == "module":
            self.modules.append(rest.strip() or "module")
            self.name_region(".".join(self.modules))
            # `org X` followed by `MODULE name` is the usual order, so a region opened a
            # line or two ago is still the one this module belongs to. Recording it is what
            # lets the map tell an org+MODULE block (a thing you can pick up and move) from
            # a bare org in the middle of a file.
            if self.open is not None and not self.open.module:
                self.open.module = ".".join(self.modules)
            return
        if mnemonic == "endmodule":
            if self.modules:
                self.modules.pop()
            return
        if mnemonic == "slot":
            value = self.value_of(rest)
            self.slot = value if value is not None else self.slot
            return
        if mnemonic == "page":
            self._page(rest, origin, line)
            return
        if mnemonic == "align":
            self._align(rest, origin, line)
            return
        if mnemonic == "include":
            self._include(rest, depth)
            return
        if mnemonic == "incbin":
            self._incbin(rest, origin, line)
            return

        cost = asm_meter.measure_statement(statement)
        if cost.unknown:
            self.mark_estimated()  # a macro call, or something the tables don't know
        if cost.total_bytes:
            self.emit(cost.code_bytes, cost.data_bytes, origin, line)

    def _page(self, rest: str, origin: str, line: int) -> None:
        """``PAGE n`` repoints the current slot at another bank, so bytes after it land elsewhere."""
        page = self.value_of(rest)
        if page is None:
            self.mark_estimated()
            return
        slot = self.slot if self.slot is not None else slot_for_address(self.cursor)
        self.pages[slot] = page
        if self.open is not None and slot == self.open.slot:
            self.open_region(self.cursor, origin, line)  # same address, different bank: a new region

    def _align(self, rest: str, origin: str, line: int) -> None:
        """``ALIGN n`` pads up to the next multiple of n -- padding is bytes, so the cursor moves."""
        boundary = self.value_of(rest.split(",")[0]) if rest else 4
        if not boundary or boundary <= 0:
            return
        padding = (-self.cursor) % boundary
        if padding:
            self.emit(0, padding, origin, line)

    def _include(self, rest: str, depth: int) -> None:
        """Follow an ``include`` with the cursor where it is -- that is what the assembler does."""
        match = _QUOTED.search(rest)
        path = match.group(1).strip() if match else rest.split(";")[0].strip()
        if not path:
            return
        resolved = self._resolve(path)
        if depth <= 0 or resolved in self.seen:
            self.mark_estimated()  # a cycle or a too-deep chain: stop, and admit the length suffers
            return
        text = self.read_source(resolved)
        if text is None:
            self.missing_includes.append(path)
            self.mark_estimated()
            return
        self.seen.add(resolved)
        previous = self.directory
        self.directory = Path(resolved).parent
        self.run(text, path, depth - 1)
        self.directory = previous

    def _incbin(self, rest: str, origin: str, line: int) -> None:
        """``INCBIN "file"[,offset[,length]]`` -- a file's size is a fact, so ask the filesystem.

        The meter can't price this one (a length that lives outside the source), and every
        generated asset include is nothing but incbins -- so without this, the region holding
        a project's assets would be marked an estimate purely for being made of files.
        """
        match = _QUOTED.search(rest)
        if match is None:
            self.mark_estimated()
            return
        parts = [part.strip() for part in rest[match.end():].split(",") if part.strip()]
        explicit = self.value_of(parts[1]) if len(parts) > 1 else None
        if explicit is not None:
            self.emit(0, explicit, origin, line)
            return
        name = match.group(1).strip()
        size = self.file_size(self._resolve(name))
        if size is None:
            # Same honesty as a missing include: the bytes are real, we just cannot count
            # them, and a block that quietly vanished would be worse than one sized zero.
            self.missing_binaries.append(name)
            self.mark_estimated()
            return
        start = self.value_of(parts[0]) if parts else 0
        self.emit(0, max(0, size - (start or 0)), origin, line)

    def _resolve(self, path: str) -> str:
        return str((self.directory / path) if self.directory is not None else Path(path))


def _read_file(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _file_size(path: str) -> int | None:
    try:
        return Path(path).stat().st_size
    except OSError:
        return None
