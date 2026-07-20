"""Parse sjasmplus SLD (Source Level Debug) files into a source<->address map.

sjasmplus emits an SLD file (``--sld=...``) describing where each source line ended
up in memory. It's pipe-delimited, one record per line:

    file | line | (defn) | (?) | page | address | type | data

We care about the ``T`` (trace) records -- one per emitted instruction -- which give
the ``address`` of the code at a given ``file``:``line``. From those we build both
directions: line -> address (to place a breakpoint) and address -> line (to show
where execution stopped). The ``page`` column is the memory bank; it matters for
128K and is ignored for now (48K has a single mapping).
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
    """Bidirectional map between source (file, line) and memory address."""

    def __init__(self):
        self.line_to_addr: dict[tuple[str, int], int] = {}
        self.addr_to_line: dict[int, tuple[str, int]] = {}

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
        if len(parts) < 7 or parts[6] != "T":  # only executable trace records
            continue
        try:
            line = int(parts[1])
            address = int(parts[5])
        except ValueError:
            continue
        if address < 0:
            continue
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
