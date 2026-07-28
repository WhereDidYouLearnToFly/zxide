"""The music player panel, and how a music file finds its way into it.

Two behaviours here are worth guarding beyond "it does not crash":

* **content decides, not the extension.** A compiled module is conventionally ``.c``, which
  is also C source -- so the same suffix must reach the player for one and the editor for
  the other, decided by looking inside.
* **a silent channel still shows a slot.** Drawing nothing for a quiet channel is
  indistinguishable from drawing nothing because the player is broken.

Fixtures are built here rather than checked in: real modules are somebody's music.
"""

import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from zxemu_core.sound.tracker_player import identify_player  # noqa: E402
from zxemu_ui.panels.ay_player_view import AyPlayerView, ChannelMeter  # noqa: E402
from zxemu_ui.workspace.settings import detect_tracker_players  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _compiled_module() -> bytes:
    """A blob shaped like a compiled module whose "player" returns immediately."""
    blob = bytearray(0x80)
    blob[0] = 0x21                      # LD HL,nnnn -> its own data
    blob[1], blob[2] = 0x40, 0xC0       # 0xC040
    blob[3] = 0xC9                      # RET (init falls straight through)
    blob[5] = 0xC9                      # play
    blob[8] = 0xC9                      # mute
    blob[0x40:0x40 + 14] = b"ProTracker 3."
    return bytes(blob)


def _player_binary(setup: int, size: int = 0x40) -> bytes:
    """A blob satisfying the player self-check: LD HL == ORG + its own length."""
    blob = bytearray(size)
    pointer = 0xC000 + size
    blob[0] = 0x21
    blob[1], blob[2] = pointer & 0xFF, pointer >> 8
    blob[3], blob[4] = 0x18, 0x06       # JR
    blob[5] = 0xC3                      # JP play
    blob[8] = 0xC3                      # JP mute
    blob[0x0B], blob[0x0C] = 0x3E, setup  # LD A,setup
    return bytes(blob)


# --- finding a player -------------------------------------------------------------

def test_a_player_is_found_by_shape_not_by_name(tmp_path):
    """Deliberately misleading names: these things are called pt3_c000.bin, PT3.BIN,
    player.bin and worse, so the contents have to be the deciding evidence."""
    (tmp_path / "something.bin").write_bytes(_player_binary(0x20))
    (tmp_path / "notes.bin").write_bytes(b"this is not a player at all" * 4)

    found = _from(detect_tracker_players("", str(tmp_path)), tmp_path)

    assert [player.plays for player in found] == ["pt3"]  # the misnamed one, not the junk
    assert found[0].path.endswith("something.bin")


def test_both_formats_are_recognised(tmp_path):
    (tmp_path / "a.bin").write_bytes(_player_binary(0x02))
    (tmp_path / "b.bin").write_bytes(_player_binary(0x20))
    found = _from(detect_tracker_players("", str(tmp_path)), tmp_path)
    assert sorted(player.plays for player in found) == ["pt2", "pt3"]


def _from(players, directory):
    """Only the players discovered in ``directory`` -- the bundled ones are always found
    too, and these tests are about what the *search* turns up in a given place."""
    return [player for player in players if str(directory) in player.path]


def test_a_blob_whose_header_disagrees_with_its_length_is_rejected():
    """The self-check that makes scanning arbitrary .bin files safe: a real player expects
    its module immediately after itself, so LD HL must equal ORG + length."""
    blob = bytearray(_player_binary(0x20))
    blob[1] = (blob[1] + 1) & 0xFF  # move the pointer by one byte
    assert identify_player(bytes(blob)) is None


def test_the_bundled_players_are_found_with_nothing_configured():
    """Raw .pt2/.pt3 must play out of the box -- the whole point of shipping them."""
    plays = sorted(player.plays for player in detect_tracker_players("", ""))
    assert plays == ["pt2", "pt3"]


def test_a_project_player_takes_precedence_over_the_bundled_one(tmp_path):
    """A project carrying its own player means that one, which may be the version its
    music needs. Bundled is the fallback, never the override."""
    (tmp_path / "players").mkdir()
    (tmp_path / "players" / "mine.bin").write_bytes(_player_binary(0x20))

    found = detect_tracker_players(str(tmp_path), "")

    assert found[0].path.endswith("mine.bin")  # ahead of the shipped pt3 player


# --- the panel ---------------------------------------------------------------------

def test_loading_a_module_shows_it_without_playing(qapp, tmp_path):
    path = tmp_path / "tune.c"
    path.write_bytes(_compiled_module())
    view = AyPlayerView(None)

    view.load(str(path), path.read_bytes())

    assert "ProTracker 3." in view._title.text()
    assert view._play_button.isEnabled()
    assert not view._timer.isActive()  # loading is not playing


def test_a_raw_module_is_not_playable_until_a_player_is_found(qapp, tmp_path):
    """The Play button has to tell the truth about a file zxide cannot play on its own."""
    path = tmp_path / "tune.pt3"
    path.write_bytes(b"ProTracker 3.3 compilation of Nothing" + bytes(200))
    view = AyPlayerView(None)

    view.load(str(path), path.read_bytes())
    assert not view._play_button.isEnabled()

    view.set_player_binaries([identify_player(_player_binary(0x20))])
    view.load(str(path), path.read_bytes())
    assert view._play_button.isEnabled()


def test_playing_then_stopping_releases_the_machine(qapp, tmp_path):
    """Stop must drop the private machine, not merely pause it -- one 128K per audition
    left alive is how a music player becomes a memory leak."""
    path = tmp_path / "tune.c"
    path.write_bytes(_compiled_module())
    view = AyPlayerView(None)
    view.load(str(path), path.read_bytes())

    view.play()
    assert view._timer.isActive() and view._player is not None

    view.stop()
    assert not view._timer.isActive() and view._player is None


def test_a_file_that_cannot_be_played_reports_rather_than_raising(qapp, tmp_path):
    path = tmp_path / "tune.pt3"
    path.write_bytes(b"ProTracker 3.3 compilation of Nothing" + bytes(200))
    view = AyPlayerView(None)
    view.load(str(path), path.read_bytes())

    view.play()  # no player binary set

    assert not view._timer.isActive()
    assert "player" in view._detail.text().lower()


def test_playback_is_paced_by_elapsed_time_not_by_timer_ticks(qapp, tmp_path, monkeypatch):
    """The bug that made music stutter: one frame per wake-up.

    A QTimer asked for 20ms on Windows fires at the system's ~15.6ms granularity and drifts
    slow, so "a frame per tick" plays the tune at whatever rate the OS felt like -- heard as
    lag. Measuring elapsed time makes the speed independent of the timer's accuracy, so a
    tick arriving late owes more than one frame and says so.
    """
    import zxemu_ui.panels.ay_player_view as module

    clock = [1000.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])

    path = tmp_path / "tune.c"
    path.write_bytes(_compiled_module())
    view = AyPlayerView(None)
    view.load(str(path), path.read_bytes())
    view.play()
    before = view._player.frames_played

    clock[0] += 0.062          # 62ms late: three whole frames are owed, not one
    view._tick()

    assert view._player.frames_played - before == 3


def test_a_long_stall_drops_the_backlog_rather_than_fast_forwarding(qapp, tmp_path, monkeypatch):
    """After a freeze, repaying every owed frame would lock the UI and race the music.
    Skipping is the lesser evil -- audio with a gap beats an IDE that stopped responding."""
    import zxemu_ui.panels.ay_player_view as module

    clock = [1000.0]
    monkeypatch.setattr(module.time, "perf_counter", lambda: clock[0])

    path = tmp_path / "tune.c"
    path.write_bytes(_compiled_module())
    view = AyPlayerView(None)
    view.load(str(path), path.read_bytes())
    view.play()
    before = view._player.frames_played

    clock[0] += 5.0            # a five-second stall
    view._tick()

    assert view._player.frames_played - before == module.MAX_CATCHUP
    assert view._accumulator == 0.0  # backlog dropped, not carried


def test_closing_the_panel_stops_the_music_at_once(qapp, tmp_path):
    """Closing a floating dock hides its contents rather than destroying them, so without
    a hide handler the tune plays on from a panel that is no longer on screen -- audible,
    unattributable, and stoppable only by finding the panel again."""
    path = tmp_path / "tune.c"
    path.write_bytes(_compiled_module())
    view = AyPlayerView(None)
    view.show()  # Qt sends no hide event to a widget that was never shown
    view.load(str(path), path.read_bytes())
    view.play()
    assert view._timer.isActive()

    view.hide()

    assert not view._timer.isActive()
    assert view._player is None


def test_play_and_stop_are_two_buttons_that_track_the_state(qapp, tmp_path):
    path = tmp_path / "tune.c"
    path.write_bytes(_compiled_module())
    view = AyPlayerView(None)
    view.load(str(path), path.read_bytes())
    assert view._play_button.isEnabled() and not view._stop_button.isEnabled()

    view.play()
    assert not view._play_button.isEnabled() and view._stop_button.isEnabled()

    view.stop()
    assert view._play_button.isEnabled() and not view._stop_button.isEnabled()


def test_stopping_does_not_re_enable_play_for_an_unplayable_file(qapp, tmp_path):
    """A raw module with no player found is loaded and still unplayable -- Stop must not
    undo what loading worked out."""
    path = tmp_path / "tune.pt3"
    path.write_bytes(b"ProTracker 3.3 compilation of Nothing" + bytes(200))
    view = AyPlayerView(None)
    view.set_player_binaries([])  # nothing available, not even bundled
    view.load(str(path), path.read_bytes())

    view.stop()

    assert not view._play_button.isEnabled()


def test_a_channel_says_what_it_is_doing_in_words(qapp):
    """``A~E`` was compact and unreadable -- it looks like damage. The drum channel
    (noise plus envelope, no tone) is the one people see first, so it has to explain
    itself."""
    from zxemu_ui.panels.ay_player_view import _caption

    assert _caption("A", tone_on=False, noise_on=True, envelope=True, period=0) == "A  noise env"
    assert _caption("B", tone_on=True, noise_on=False, envelope=False, period=456) == "B  456"
    assert _caption("C", tone_on=False, noise_on=False, envelope=False, period=99) == "C  off"


def test_the_meter_draws_three_slots_even_in_silence(qapp):
    """A quiet channel and a broken player must not look the same."""
    from zxemu_core.machine import Machine128

    machine = Machine128(bytes(0x4000), bytes(0x4000))
    meter = ChannelMeter()
    meter.resize(300, 90)
    meter.watch(machine.ay)  # every register zero: nothing playing

    image = meter.grab().toImage()
    slot = image.pixelColor(20, 40)
    assert slot.name() == "#2a2a2a"  # the empty slot, not the panel background


def test_the_meter_says_nothing_playing_when_it_has_no_chip(qapp):
    meter = ChannelMeter()
    meter.resize(300, 90)
    meter.watch(None)
    meter.grab()  # must not raise
