"""Window-level tests for loading media: resuming, focus, and the stalled-tape notice.

These cover two bugs found by using the IDE rather than by testing it, which is why they
are worth pinning: both looked like "the emulator is broken" and neither raised anything.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.resources as res  # noqa: E402

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_ui import main_window as main_window_module  # noqa: E402
from zxemu_ui.controller import EmulatorController  # noqa: E402
from zxemu_ui.machine_factory import build_machine  # noqa: E402
from zxemu_ui.main_window import TAPE_STALL_FRAMES, MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def window(qapp):
    machine = build_machine("48k")
    window = MainWindow(machine, EmulatorController(machine))
    window.output_console.clear_output()
    return window


def _z80_48k(tmp_path):
    """A minimal but valid v1 (48K) .z80: header with a real PC, then a flat RAM image."""
    header = bytearray(30)
    header[6], header[7] = 0x00, 0x80   # PC = 0x8000 (non-zero => v1)
    path = tmp_path / "game.z80"
    path.write_bytes(bytes(header) + bytes(3 * 0x4000))
    return path


def _tap(tmp_path, *blocks):
    out = bytearray()
    for flag, payload in blocks:
        body = bytes([flag]) + payload
        checksum = 0
        for byte in body:
            checksum ^= byte
        block = body + bytes([checksum])
        out += bytes([len(block) & 0xFF, len(block) >> 8]) + block
    path = tmp_path / "game.tap"
    path.write_bytes(bytes(out))
    return path


# --- resuming ----------------------------------------------------------------

def test_loading_a_snapshot_resumes_a_paused_machine(window, tmp_path):
    """The bug: a snapshot loaded into a paused emulator stayed paused while the log
    claimed "— running". The screen showed the game and nothing responded -- which reads
    as a dead keyboard, not as a paused machine."""
    window.controller.start()
    window.controller.pause()
    assert not window.controller.running

    assert window._load_media(str(_z80_48k(tmp_path)))

    assert window.controller.running
    assert "— running." in window.output_console.toPlainText()


def test_loading_a_tape_also_resumes(window, tmp_path):
    window.controller.start()
    window.controller.pause()

    assert window._load_media(str(_tap(tmp_path, (0xFF, bytes([1, 2, 3])))))

    assert window.controller.running


def test_a_failed_load_does_not_resume_a_paused_machine(window, tmp_path):
    """Nothing was loaded, so nothing should start running."""
    window.controller.start()
    window.controller.pause()
    broken = tmp_path / "broken.z80"
    broken.write_bytes(b"not a snapshot")

    assert not window._load_media(str(broken))
    assert not window.controller.running


# --- keyboard focus ----------------------------------------------------------

def test_focus_is_handed_to_the_emulator_after_the_dialog_closes(window, monkeypatch):
    """Deferred on purpose: a modal file dialog restores focus to whatever held it before,
    and on Windows that can happen after this handler returns -- undoing a plain
    setFocus() and sending your keystrokes to the editor instead of the Spectrum."""
    deferred = []
    monkeypatch.setattr(main_window_module.QTimer, "singleShot",
                        lambda delay, slot: deferred.append((delay, slot)))

    window._focus_emulator()

    assert len(deferred) == 1
    delay, slot = deferred[0]
    assert delay == 0                                  # next event-loop turn
    assert slot == window.view.setFocus                # ...and it's the emulator's focus


# --- the stalled-tape notice -------------------------------------------------

def _stall(window):
    """Push the watch past its threshold, as a run of unproductive frames would."""
    for _ in range(TAPE_STALL_FRAMES + 1):
        window._check_tape_progress(0)


def test_an_untouched_tape_says_you_have_to_start_it(window, tmp_path):
    window._load_media(str(_tap(tmp_path, (0xFF, bytes([1, 2, 3])))))
    window.output_console.clear_output()

    _stall(window)

    text = window.output_console.toPlainText()
    assert "No tape block has been read" in text
    assert "0 of 1 loaded" in text
    assert 'LOAD ""' in text


def test_a_tape_that_stops_part_way_blames_the_loader_instead(window, tmp_path):
    """Blocks were read and then it stalled: the ROM loader started it, so what stopped
    it is the game's own turbo loader -- the opposite advice, and now an actionable one,
    because turning Fast Load off is exactly what such a loader needs."""
    window._load_media(str(_tap(tmp_path, (0xFF, b"\x01"), (0xFF, b"\x02"))))
    window.machine.tape.advance()  # as a first successful block read would
    window.output_console.clear_output()

    _stall(window)

    text = window.output_console.toPlainText()
    assert "1 of 2 loaded" in text
    assert "turbo loader" in text and "Fast Load" in text


def test_a_stall_with_fast_load_already_off_does_not_repeat_the_same_advice(window, tmp_path):
    """Telling someone to turn off a setting they already turned off is the fastest way
    to make them stop reading the Output."""
    window._load_media(str(_tap(tmp_path, (0xFF, b"\x01"), (0xFF, b"\x02"))))
    window.machine.tape.advance()
    window._set_fast_load(False)
    window.output_console.clear_output()

    _stall(window)

    text = window.output_console.toPlainText()
    assert "Turn off" not in text
    assert "Rewind" in text


def test_the_notice_is_reported_once_not_every_frame(window, tmp_path):
    window._load_media(str(_tap(tmp_path, (0xFF, b"\x01"))))
    window.output_console.clear_output()

    _stall(window)
    _stall(window)

    assert window.output_console.toPlainText().count("No tape block has been read") == 1


def test_progress_resets_the_watch(window, tmp_path):
    """A tape being read normally must never trip the notice."""
    window._load_media(str(_tap(tmp_path, (0xFF, b"\x01"), (0xFF, b"\x02"))))
    window.output_console.clear_output()

    for _ in range(TAPE_STALL_FRAMES - 1):
        window._check_tape_progress(0)
    window.machine.tape.advance()          # a block was read just in time
    for _ in range(TAPE_STALL_FRAMES - 1):
        window._check_tape_progress(0)

    assert "No tape block" not in window.output_console.toPlainText()


def test_a_finished_tape_is_not_reported(window, tmp_path):
    window._load_media(str(_tap(tmp_path, (0xFF, b"\x01"))))
    window.machine.tape.advance()  # every block read
    window.output_console.clear_output()

    _stall(window)

    assert "No tape block" not in window.output_console.toPlainText()


def test_no_tape_means_no_notice(window):
    window.machine.eject_tape()
    _stall(window)
    assert "No tape block" not in window.output_console.toPlainText()
