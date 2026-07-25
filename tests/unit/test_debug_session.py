"""Tests for DebugSession -- the debugger's bookkeeping, without a window.

A fake controller records what was pushed to it, which is the whole contract: the session
owns the state, the controller receives it, and the window only ever reads it back to
write log lines.
"""

from __future__ import annotations

import importlib.resources as res

import pytest

from zxemu_core.debug import debug_expr
from zxemu_core.machine import Machine
from zxemu_ui.debug_session import DebugSession


class _FakeController:
    """Records the last value pushed for each kind of pause condition."""

    def __init__(self):
        self.breakpoints = None
        self.conditions = None
        self.memory_watchpoints = None
        self.port_watchpoints = None

    def set_breakpoints(self, addresses):
        self.breakpoints = set(addresses)

    def set_breakpoint_conditions(self, conditions):
        self.conditions = dict(conditions)

    def set_memory_watchpoints(self, writes, reads):
        self.memory_watchpoints = (set(writes), set(reads))

    def set_port_watchpoints(self, reads, writes):
        self.port_watchpoints = (set(reads), set(writes))


def _session():
    machine = Machine((res.files("zxemu_core") / "roms" / "48.rom").read_bytes())
    controller = _FakeController()
    return DebugSession(controller, machine), controller


class _FakeSourceMap:
    """Stands in for a parsed SLD: just the lookups the session asks of it."""

    labels = {"start": 0x8000}

    def breakpoint_addresses(self, path, lines):
        return {0x8000 + line for line in lines} if path == "main.asm" else set()

    def address_for(self, path, line):
        return 0x8000 + line if path == "main.asm" else None

    def address_for_label(self, name):
        return self.labels.get(name.strip())

    def line_for(self, address):
        return ("main.asm", address - 0x8000) if address >= 0x8000 else None


# --- breakpoints -------------------------------------------------------------

def test_breakpoints_are_only_applied_while_debugging():
    """Build & Run must ignore the gutter marks without you having to clear them."""
    session, controller = _session()
    session.source_map = _FakeSourceMap()

    session.debugging = False
    assert session.sync_breakpoints({"main.asm": {1, 2}}) == set()
    assert controller.breakpoints == set()

    session.debugging = True
    assert session.sync_breakpoints({"main.asm": {1, 2}}) == {0x8001, 0x8002}
    assert controller.breakpoints == {0x8001, 0x8002}


def test_breakpoints_need_a_source_map():
    """Before a build there is no line->address map, so a gutter mark is just a line."""
    session, controller = _session()
    session.debugging = True

    assert session.sync_breakpoints({"main.asm": {1}}) == set()
    assert controller.breakpoints == set()


# --- conditions --------------------------------------------------------------

def test_a_condition_is_validated_against_the_live_machine():
    session, controller = _session()

    session.set_condition(0x8000, "A == $FF")

    assert session.conditions == {0x8000: "A == $FF"}
    assert controller.conditions == {0x8000: "A == $FF"}


def test_a_bad_condition_raises_and_is_not_stored():
    """Reported while the dialog is still open, rather than by silently never matching."""
    session, controller = _session()

    with pytest.raises(debug_expr.ExpressionError):
        session.set_condition(0x8000, "this is not an expression")

    assert session.conditions == {}
    assert controller.conditions is None  # nothing was pushed


def test_conditions_are_keyed_by_16_bit_address():
    session, _controller = _session()
    session.set_condition(0x1_8000, "A == 0")  # a stray high bit is masked off
    assert session.condition_for(0x8000) == "A == 0"


def test_removing_and_clearing_conditions_pushes_the_new_set():
    session, controller = _session()
    session.set_condition(0x8000, "A == 0")
    session.set_condition(0x9000, "B == 1")

    session.remove_condition(0x8000)
    assert controller.conditions == {0x9000: "B == 1"}

    session.clear_conditions()
    assert session.conditions == {} and controller.conditions == {}


# --- watchpoints -------------------------------------------------------------

def test_watching_memory_keeps_reads_and_writes_apart():
    session, controller = _session()

    session.watch_memory(0x4000, write=True)
    session.watch_memory(0x5000, write=False)

    writes, reads = controller.memory_watchpoints
    assert writes == {0x4000} and reads == {0x5000}


def test_watching_ports_keeps_in_and_out_apart():
    session, controller = _session()

    session.watch_port(0xFE, write=True)
    session.watch_port(0x7FFD, write=False)

    reads, writes = controller.port_watchpoints
    assert reads == {0x7FFD} and writes == {0xFE}


def test_clearing_watchpoints_empties_all_four_sets():
    session, controller = _session()
    session.watch_memory(0x4000, write=True)
    session.watch_memory(0x4001, write=False)
    session.watch_port(0xFE, write=True)
    session.watch_port(0xFE, write=False)

    session.clear_watchpoints()

    assert controller.memory_watchpoints == (set(), set())
    assert controller.port_watchpoints == (set(), set())
    assert not any([session.watched_reads, session.watched_writes,
                    session.watched_ports_read, session.watched_ports_write])


# --- the source map ----------------------------------------------------------

def test_source_map_lookups_are_safe_before_any_build():
    """Every debug action has to cope with "no build yet", so none of these may raise."""
    session, _controller = _session()
    assert session.source_map is None
    assert not session.has_labels
    assert session.address_for("main.asm", 1) is None
    assert session.address_for_label("start") is None
    assert session.location_of(0x8000) is None


def test_loading_a_missing_sld_reports_failure_rather_than_raising(tmp_path):
    """No SLD just means the build gave us no source-level view of itself."""
    session, _controller = _session()
    assert session.load_source_map(tmp_path / "nope.sld", tmp_path) is False
    assert session.load_source_map(None, tmp_path) is False
    assert session.source_map is None


def test_lookups_work_once_a_map_is_present():
    session, _controller = _session()
    session.source_map = _FakeSourceMap()

    assert session.has_labels
    assert session.address_for("main.asm", 4) == 0x8004
    assert session.address_for_label(" start ") == 0x8000
    assert session.location_of(0x8007) == ("main.asm", 7)
