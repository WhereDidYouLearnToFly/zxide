"""Tests for the registers panel's layout discipline.

Widths are asserted in *characters*, not pixels: the panel is monospace, so character
counts are what actually decide its width, and unlike pixels they don't depend on which
fonts the machine running the tests happens to have installed.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.panels.registers_view import FONT_SCALE, RegistersView  # noqa: E402
from zxemu_ui.theme import monospace_font  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _view(qapp, model="48k"):
    view = RegistersView(build_machine(model))
    view.show()  # refresh() is a no-op while hidden
    view.refresh()
    return view


def _grid_row_width(view) -> int:
    """Characters across the widest row of register cells -- the panel's natural width."""
    from zxemu_ui.panels.registers_view import _REG_ROWS

    return max(
        sum(len(view._value_labels[attr].text()) for _label, attr, _w in row)
        for row in _REG_ROWS
    )


def test_every_register_cell_has_the_same_text_width(qapp):
    """A 2-digit I must occupy the same cell as a 4-digit HL, or the columns go ragged."""
    view = _view(qapp)
    widths = {len(label.text()) for label in view._value_labels.values()}
    assert widths == {8}  # 3 for the name, a space, 4 for the value


def test_short_registers_are_right_aligned_under_the_wide_ones(qapp):
    view = _view(qapp)
    assert view._value_labels["af"].text() == " AF 0000"
    assert view._value_labels["hl2"].text() == "HL' 0000"
    assert view._value_labels["i"].text() == "  I   00"   # value right-aligned, not left
    assert view._value_labels["im"].text() == " IM    1"


def test_the_tstate_readout_is_two_lines_and_no_wider_than_the_register_grid(qapp):
    """As one line this was ~60 characters and set the whole dock's minimum width.

    A QLabel can never be narrower than its own text, so any single long line in here is
    stolen from the emulator sharing the column.
    """
    view = _view(qapp)
    limit = _grid_row_width(view)

    assert len(view._tstates_frame_label.text()) <= limit
    assert len(view._tstates_step_label.text()) <= limit


def test_the_tstate_readout_stays_narrow_with_big_numbers(qapp):
    """The totals grow forever while the machine runs -- an hour is eleven digits."""
    view = _view(qapp, "128k")
    view.machine.cpu.t_states = 12_600_000_000  # ~1 hour of emulated time
    view.machine.frame_t_state = view.machine.frame_tstates - 1
    view._previous_total = view.machine.cpu.t_states - 69_888
    view.refresh()

    limit = _grid_row_width(view)
    assert len(view._tstates_frame_label.text()) <= limit
    assert len(view._tstates_step_label.text()) <= limit
    assert "70907/70908" in view._tstates_frame_label.text()  # the 128K frame length


def test_the_panel_draws_smaller_than_body_monospace(qapp):
    view = _view(qapp)
    assert FONT_SCALE < 1.0
    assert view._value_labels["af"].font().pointSizeF() < monospace_font().pointSizeF()


def test_interface_scaling_keeps_the_panel_a_step_below_body_text(qapp):
    """View ▸ Interface scale must still scale this panel -- relative, not absolute."""
    view = _view(qapp)
    view.set_mono_scale(2.0)

    scaled = view._value_labels["af"].font().pointSizeF()
    assert scaled == pytest.approx(monospace_font(2.0).pointSizeF() * FONT_SCALE, rel=0.01)
    # Every label moves together, including the flags and the T-state lines.
    for label in (*view._flag_labels.values(), view._flags_caption,
                  view._tstates_frame_label, view._tstates_step_label):
        assert label.font().pointSizeF() == pytest.approx(scaled, rel=0.01)
