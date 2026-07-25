"""What the debugger knows and what should make it stop.

Six pieces of state used to live as loose ``MainWindow`` attributes -- the source map, the
"are we debugging?" flag, four sets of watched addresses and ports, and the breakpoint
conditions -- touched from a dozen methods each. They belong together, because they answer
one question between them (*why would execution pause, and where are we when it does?*)
and because none of them means anything without the others: a breakpoint line is only an
address if the source map is loaded, and a condition is only checked at an address that is
a breakpoint.

Pulling them out leaves the window doing what a window should: put up a dialog, and write
what happened to the log. This class owns the state and pushes it to the controller;
returning descriptions rather than logging them keeps it free of any opinion about how the
IDE talks to you.

Kept Qt-free (the controller it drives is a Qt object, but nothing here imports Qt), so
the debugger's bookkeeping can be tested without a window.
"""

from __future__ import annotations

from pathlib import Path

from zxemu_core.debug import debug_expr
from zxemu_ui.workspace import sld


class DebugSession:
    """The live debug state for one machine, pushed through to a controller."""

    def __init__(self, controller, machine):
        self.controller = controller
        self.machine = machine  # rebound by MainWindow.set_machine, like the panels
        # The line<->address map from the last build. None means "no build yet", which is
        # why nearly every debug action has to check it first: without a map, a source
        # line is just a line.
        self.source_map = None
        # True after Build & Debug, False after Build & Run. Breakpoints exist either way
        # -- the gutter marks stay put -- but they are only *applied* when debugging, so
        # Ctrl+F5 runs straight through without you having to clear them.
        self.debugging = False
        self.watched_reads: set[int] = set()
        self.watched_writes: set[int] = set()
        self.watched_ports_read: set[int] = set()
        self.watched_ports_write: set[int] = set()
        self.conditions: dict[int, str] = {}  # address -> expression

    # --- the source map --------------------------------------------------------

    def load_source_map(self, sld_path, base_dir) -> bool:
        """Parse a build's SLD into the map. False if there was nothing to read.

        A failure here is not an error worth interrupting anyone over: it means the
        build produced no SLD, so the debugger simply has no source-level view of it.
        """
        self.source_map = None
        if sld_path is None:
            return False
        try:
            self.source_map = sld.parse(
                Path(sld_path).read_text(encoding="utf-8"), base_dir=base_dir
            )
        except OSError:
            return False
        return True

    @property
    def has_labels(self) -> bool:
        return self.source_map is not None and bool(self.source_map.labels)

    def address_for(self, path: str, line: int) -> int | None:
        """The address a source line assembled to, or None (no map, or no code there)."""
        if self.source_map is None:
            return None
        return self.source_map.address_for(path, line)

    def address_for_label(self, name: str) -> int | None:
        if self.source_map is None:
            return None
        return self.source_map.address_for_label(name)

    def location_of(self, address: int):
        """The (file, line) an address came from, or None -- for the execution marker."""
        if self.source_map is None:
            return None
        return self.source_map.line_for(address)

    # --- breakpoints -----------------------------------------------------------

    def sync_breakpoints(self, breakpoints_by_file: dict[str, set[int]]) -> set[int]:
        """Translate the editor's gutter marks into PC addresses and apply them.

        Applies an empty set unless we are debugging -- see ``debugging``.
        """
        addresses: set[int] = set()
        if self.debugging and self.source_map is not None:
            for path, lines in breakpoints_by_file.items():
                addresses |= self.source_map.breakpoint_addresses(path, lines)
        self.controller.set_breakpoints(addresses)
        return addresses

    def set_condition(self, address: int, expression: str) -> None:
        """Attach an expression to a breakpoint address.

        Raises ``debug_expr.ExpressionError`` if it doesn't evaluate against the live
        machine: a typo should be reported while you are still looking at the dialog, not
        by silently never matching later.
        """
        debug_expr.validate(expression, self.machine)
        self.conditions[address & 0xFFFF] = expression
        self.controller.set_breakpoint_conditions(self.conditions)

    def remove_condition(self, address: int) -> None:
        self.conditions.pop(address & 0xFFFF, None)
        self.controller.set_breakpoint_conditions(self.conditions)

    def condition_for(self, address: int) -> str:
        return self.conditions.get(address & 0xFFFF, "")

    def clear_conditions(self) -> None:
        self.conditions.clear()
        self.controller.set_breakpoint_conditions({})

    # --- watchpoints -----------------------------------------------------------

    def watch_memory(self, address: int, *, write: bool) -> None:
        target = self.watched_writes if write else self.watched_reads
        target.add(address & 0xFFFF)
        self.controller.set_memory_watchpoints(self.watched_writes, self.watched_reads)

    def watch_port(self, port: int, *, write: bool) -> None:
        target = self.watched_ports_write if write else self.watched_ports_read
        target.add(port & 0xFFFF)
        self.controller.set_port_watchpoints(self.watched_ports_read, self.watched_ports_write)

    def clear_watchpoints(self) -> None:
        for watched in (self.watched_reads, self.watched_writes,
                        self.watched_ports_read, self.watched_ports_write):
            watched.clear()
        self.controller.set_memory_watchpoints((), ())
        self.controller.set_port_watchpoints((), ())
