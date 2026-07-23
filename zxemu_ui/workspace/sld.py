"""Parse sjasmplus SLD (Source Level Debug) files into a source<->address map.

sjasmplus emits an SLD file (``--sld=...``) describing where each source line ended
up in memory. It's pipe-delimited, one record per line:

    file | line | (defn) | (?) | page | address | type | data

Two record types matter here:

  * ``T`` (trace) -- one per emitted instruction, giving the ``address`` of the code at
    a given ``file``:``line``. From those we build both directions: line -> address (to
    place a breakpoint) and address -> line (to show where execution stopped).
  * ``F`` (definition) -- a label and the address it ended up at. These give the
    disassembly your *own* names, the way ``zxemu_core.debug.rom_symbols`` does for the ROM,
    and let you jump to a label instead of hunting for its address.

The ``page`` column, checked empirically against real sjasmplus output, is actually
the **slot index** (0-3, i.e. ``address >> 14``) the code assembled into -- not which
physical 128K bank a ``SLOT``/``PAGE`` override targeted. That distinction matters to
``asset_build.reserve_code_ranges``, which uses ``addresses_by_slot`` to avoid placing
an asset on top of hand-written code: slots 1 and 2 are hardware-fixed (always RAM5 and
RAM2, never repaged) on *both* 48K and 128K, so this data reliably identifies "occupied"
bytes there; slot 3 on 128K can hold any of eight banks depending on runtime paging the
SLD has no way to see, so it is deliberately left alone rather than guessed at.
"""

from __future__ import annotations

from pathlib import Path


def _norm(path) -> str:
    """A canonical key for a path (absolute, lower-cased for Windows)."""
    try:
        return str(Path(path).resolve()).lower()
    except OSError:
        return str(path).lower()


class SourceMap:
    """Bidirectional map between source (file, line) and memory address, plus labels."""

    def __init__(self):
        self.line_to_addr: dict[tuple[str, int], int] = {}
        self.addr_to_line: dict[int, tuple[str, int]] = {}
        # Your own labels, from the SLD's F (definition) records: name <-> address.
        # These are what make a disassembly of *your* code readable, the same way
        # rom_symbols does for the ROM.
        self.labels: dict[str, int] = {}
        self.addr_to_label: dict[int, str] = {}
        # Every address a T (trace) record named as real, executed-instruction code,
        # grouped by slot (see the module docstring on what "slot" reliably means here).
        self.addresses_by_slot: dict[int, set[int]] = {}

    def label_for(self, address: int) -> str | None:
        return self.addr_to_label.get(address)

    def address_for_label(self, name: str) -> int | None:
        """Look a label up by name, case-insensitively and ignoring any module prefix.

        sjasmplus qualifies labels inside a MODULE (``player.clear``), but you rarely
        type the prefix when you just want to jump somewhere, so a bare ``clear``
        matches too -- provided it's unambiguous.
        """
        wanted = name.strip().lower()
        if wanted in self.labels:
            return self.labels[wanted]
        suffix_matches = [
            address for label, address in self.labels.items() if label.rsplit(".", 1)[-1] == wanted
        ]
        return suffix_matches[0] if len(suffix_matches) == 1 else None

    def address_for(self, path: str, line: int) -> int | None:
        return self.line_to_addr.get((_norm(path), line))

    def line_for(self, address: int):
        return self.addr_to_line.get(address)

    def breakpoint_addresses(self, path: str, lines) -> set[int]:
        """Addresses for the given source lines that carry code."""
        key = _norm(path)
        found = {self.line_to_addr.get((key, line)) for line in lines}
        found.discard(None)
        return found


def parse(text: str, base_dir=None) -> SourceMap:
    """Build a SourceMap from SLD file text. Relative paths resolve against base_dir."""
    source_map = SourceMap()
    base = Path(base_dir) if base_dir else None
    for row in text.splitlines():
        parts = row.split("|")
        if len(parts) < 7:
            continue
        if parts[6] == "F":  # a label definition, with the address it landed on
            try:
                address = int(parts[5])
            except ValueError:
                continue
            name = parts[7].strip() if len(parts) > 7 else ""
            if name and address >= 0:
                source_map.labels.setdefault(name.lower(), address)
                source_map.addr_to_label.setdefault(address, name)
            continue
        if parts[6] != "T":  # otherwise only executable trace records interest us
            continue
        try:
            line = int(parts[1])
            slot = int(parts[4])
            address = int(parts[5])
        except ValueError:
            continue
        if address < 0:
            continue
        source_map.addresses_by_slot.setdefault(slot, set()).add(address)
        path = Path(parts[0])
        if not path.is_absolute() and base is not None:
            path = base / path
        try:
            path = path.resolve()
        except OSError:
            pass
        # Match case-insensitively (Windows), but keep the real-case path for opening.
        source_map.line_to_addr.setdefault((str(path).lower(), line), address)
        source_map.addr_to_line.setdefault(address, (str(path), line))
    return source_map
