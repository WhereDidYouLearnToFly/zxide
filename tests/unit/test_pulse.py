"""Unit tests for edge-level tape replay (zxemu_core.storage.pulse).

Two things are being checked here, and they fail in very different ways.

*The pulse train* is a pure function of the bytes and the timings, and a mistake in it
produces a tape that parses perfectly and then loads nothing -- so the numbers are
asserted against the ROM's published ones rather than against whatever we happened to
generate first.

*The motor* is a policy, not a fact: a real cassette would run continuously, and this
one deliberately doesn't (see the module docstring for why). Those decisions are the
ones a future change is most likely to break by accident, so each has a test naming the
situation it exists for.
"""

import pytest

from zxemu_core.storage import pulse, tape


def _block(flag: int, payload: bytes) -> bytes:
    body = bytes([flag]) + bytes(payload)
    checksum = 0
    for byte in body:
        checksum ^= byte
    return body + bytes([checksum])


def _tap(*blocks: bytes) -> bytes:
    return b"".join(bytes([len(b) & 0xFF, len(b) >> 8]) + b for b in blocks)


def _deck(*blocks: bytes) -> tape.TapeDeck:
    return tape.TapeDeck(tape.parse_tap(_tap(*blocks)))


# --- the signal ---------------------------------------------------------------

def test_a_data_block_is_pilot_then_sync_then_two_pulses_per_bit():
    data = bytes([0xFF, 0x00])  # flag 0xFF: eight 1-bits, then eight 0-bits
    got = list(pulse.data_pulses(data))

    pilot = [pulse.PILOT_PULSE] * pulse.PILOT_PULSES_DATA
    sync = [pulse.SYNC_FIRST, pulse.SYNC_SECOND]
    ones = [pulse.ONE_PULSE] * 16   # 8 bits x 2 pulses each
    zeros = [pulse.ZERO_PULSE] * 16
    assert got == pilot + sync + ones + zeros


def test_a_header_gets_the_long_pilot_and_a_data_block_the_short_one():
    """The ROM picks the leader from the flag byte, and the difference is the whole
    reason you can start a tape in the middle and still find the next program."""
    header = list(pulse.data_pulses(bytes([0x00, 0x01])))
    data = list(pulse.data_pulses(bytes([0xFF, 0x01])))

    assert header.count(pulse.PILOT_PULSE) == pulse.PILOT_PULSES_HEADER
    assert data.count(pulse.PILOT_PULSE) == pulse.PILOT_PULSES_DATA


def test_a_turbo_block_uses_every_timing_it_was_given():
    """A turbo tape is an ordinary tape with smaller numbers -- so if any one of them is
    ignored, the loader is timing against a pulse length that was never sent."""
    timing = pulse.BlockTiming(
        pilot_pulse=1000, pilot_count=3, sync_first=100, sync_second=110,
        zero_pulse=200, one_pulse=400,
    )
    got = list(pulse.data_pulses(bytes([0x80]), timing))

    assert got == [1000, 1000, 1000, 100, 110] + [400, 400] + [200, 200] * 7


def test_only_the_named_bits_of_a_final_partial_byte_are_sent():
    """Pure-data blocks routinely end mid-byte; sending the padding would hand the
    loader bits the original tape never carried."""
    timing = pulse.BlockTiming(has_pilot=True, pilot_count=0, used_bits_last_byte=3)
    got = list(pulse.data_pulses(bytes([0xFF, 0xE0]), timing))

    sync = [pulse.SYNC_FIRST, pulse.SYNC_SECOND]
    assert got == sync + [pulse.ONE_PULSE] * 16 + [pulse.ONE_PULSE] * 6


def test_pure_data_has_no_leader_of_its_own():
    timing = pulse.BlockTiming(has_pilot=False)
    got = list(pulse.data_pulses(bytes([0x00]), timing))

    assert got == [pulse.ZERO_PULSE] * 16  # straight into the bits


# --- the player ---------------------------------------------------------------

def test_the_level_flips_once_per_pulse_at_the_stated_times():
    deck = _deck(_block(0xFF, b"\x01"))
    player = pulse.TapePlayer(deck)
    player.start()

    # Sample either side of the first pilot pulse's boundary.
    assert player.ear_level(0) == 1
    assert player.ear_level(pulse.PILOT_PULSE - 1) == 1
    assert player.ear_level(pulse.PILOT_PULSE) == 0
    assert player.ear_level(pulse.PILOT_PULSE * 2) == 1


def test_a_sampler_recovers_the_pulse_widths_that_were_written():
    """The end-to-end property the ROM depends on: time between flips == pulse length."""
    deck = _deck(_block(0xFF, b"\x01"))
    player = pulse.TapePlayer(deck)
    player.start()

    widths, level, last = [], player.level, 0
    for t in range(0, 8_000_000, 8):     # a tight sampling loop, like LD-SAMPLE's
        now = player.ear_level(t)
        if now != level:
            widths.append(t - last)
            level, last = now, t
        if len(widths) > pulse.PILOT_PULSES_DATA + 5:
            break

    widths = widths[1:]  # the very first flip is the tape starting, not a pulse width
    # Allow the sampling period itself as slack -- a sampler can only see a flip at the
    # moment it next looks, which is exactly the resolution a real loader has too.
    pilot = widths[:pulse.PILOT_PULSES_DATA]
    assert all(abs(w - pulse.PILOT_PULSE) <= 8 for w in pilot)
    sync_and_first_bit = widths[pulse.PILOT_PULSES_DATA:pulse.PILOT_PULSES_DATA + 3]
    assert abs(sync_and_first_bit[0] - pulse.SYNC_FIRST) <= 8
    assert abs(sync_and_first_bit[1] - pulse.SYNC_SECOND) <= 8
    assert abs(sync_and_first_bit[2] - pulse.ONE_PULSE) <= 8


def test_the_motor_starts_only_when_the_machine_is_really_sampling():
    """A game polls port 0xFE for the keyboard forever after it has loaded. If that
    counted as listening, the rest of a multi-load tape would spool past the head while
    part one was being played."""
    deck = _deck(_block(0xFF, b"\x01"))
    player = pulse.TapePlayer(deck)

    for _ in range(40):                 # a generous keyboard poll for one frame
        player.ear_level(0)
    player.end_frame()
    assert not player.motor

    for _ in range(pulse.SAMPLING_READS_PER_FRAME):
        player.ear_level(0)
    player.end_frame()
    assert player.motor


def test_the_motor_stops_at_the_pause_after_each_block():
    """Where a person would have hit stop, and what the TZX spec means by 'pause'."""
    deck = _deck(_block(0xFF, b"\x01"), _block(0xFF, b"\x02"))
    player = pulse.TapePlayer(deck)
    player.start()

    player.ear_level(50_000_000)        # long past the first block and its pause

    assert not player.motor
    assert deck.index == 1              # ...parked on the second block, not into it


def test_an_item_with_no_pause_runs_straight_into_the_next_one():
    """The tone-then-pure-data pattern, which is how a large slice of the .tzx library is
    built. A bare 0x12 tone exists *only* to introduce the block after it, and the two are
    stored as separate items with nothing between them. Stopping at that boundary would
    drop a gap into precisely the moment the loader is hunting for its sync pulses."""
    tone = pulse.PureTone(pulse.PILOT_PULSE, 4)            # pause_ms defaults to 0
    block = tape.parse_tap(_tap(_block(0xFF, b"\x01")))[0]
    deck = tape.TapeDeck([tone, block])
    player = pulse.TapePlayer(deck)
    player.start()

    player.ear_level(pulse.PILOT_PULSE * 6)   # past the whole four-pulse tone

    assert player.motor, "the motor stopped between a tone and the block it introduces"
    assert deck.index == 1


def test_the_motor_does_not_restart_itself_once_the_tape_has_run_out():
    deck = _deck(_block(0xFF, b"\x01"))
    player = pulse.TapePlayer(deck)
    player.start()
    player.ear_level(50_000_000)        # plays the block, then stops at its pause
    player.start()                      # ...and playing on finds nothing left
    player.ear_level(90_000_000)

    assert player.finished
    for _ in range(pulse.SAMPLING_READS_PER_FRAME):
        player.ear_level(90_000_000)
    player.end_frame()
    assert not player.motor


def test_a_fast_load_moving_the_play_head_is_noticed_by_the_player():
    """The two loaders share one head. A tape that starts under the ROM loader and hands
    over to the game's own is the normal case, not an exotic one."""
    deck = _deck(_block(0xFF, b"\x01"), _block(0x00, b"\x02"))
    player = pulse.TapePlayer(deck)
    player.start()
    player.ear_level(1000)              # part-way through block one's pilot

    deck.advance()                      # as fast_load() does when it consumes a block
    player.start()
    player.ear_level(player._clock)

    # Now playing block two -- whose header flag gives it the *long* pilot, so seeing
    # that count is proof we restarted on the new item rather than the stale generator.
    assert player._item_index == 1


def test_stop_and_rewind_put_the_tape_back_at_the_beginning():
    deck = _deck(_block(0xFF, b"\x01"), _block(0xFF, b"\x02"))
    player = pulse.TapePlayer(deck)
    player.start()
    player.ear_level(50_000_000)
    assert deck.index == 1

    player.rewind()

    assert deck.index == 0 and not player.motor and not player.finished


def test_a_zero_length_pulse_cannot_hang_the_player():
    """A damaged or hand-built tape can name a 0T pulse; the clock has to move anyway or
    the roll-forward loop never terminates."""
    deck = tape.TapeDeck([pulse.PulseSequence([0, 0, 0], pause_ms=0)])
    player = pulse.TapePlayer(deck)
    player.start()

    player.ear_level(1_000_000)         # would spin for ever if 0T pulses were free

    assert deck.index == 1


@pytest.mark.parametrize("item, expected", [
    (pulse.PureTone(2168, 3), [2168, 2168, 2168]),
    (pulse.PulseSequence([100, 200]), [100, 200]),
    (pulse.Silence(50), []),
])
def test_pulse_only_items_carry_signal_but_no_data(item, expected):
    assert list(item.pulses()) == expected
    assert item.data is None          # so a fast load steps over them
