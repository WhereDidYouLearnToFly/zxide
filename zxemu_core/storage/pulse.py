"""Edge-level tape replay: turning tape blocks back into the pulses the ULA hears.

``tape.py`` cheats. It watches for the ROM's ``LD-BYTES`` routine, hands over a whole
block at once and returns — instant, reliable, and completely fictional. A real
Spectrum never sees a "block": it sees a *wire*, and on that wire the tape's audio
signal swings between two voltages. Port 0xFE bit 6 reports which of the two it is
right now, and a loader works out the data by **timing the gaps between the swings**.

That is what this module reproduces. It is the difference between an emulator that
can load a tape and one that can load *the tapes people actually have*:

* **Turbo loaders work.** Speedlock and the hundred loaders like it never call the ROM
  routine, so no trap can ever help them — they bit-bang their own sampling loop. Give
  them edges and they load exactly as they did in 1987.
* **The loading stripes come back**, free of charge. Nobody draws them: the loader
  itself is OUT-ing to the border between samples, and once it's really running you
  see what it really does.
* **You hear the tape**, because the EAR signal reaches the speaker on real hardware
  (see ``Machine._refresh_speaker``).

The signal, from the top
------------------------
A pulse is *how long the level stays put before it flips*, measured in T-states. A
standard ROM-speed block is spelled out like this::

    pilot   8063 pulses of 2168 T   (a 5-second tone; 3223 pulses for a data block)
    sync     667 T, then 735 T      (the short pair that says "data starts here")
    data     each bit is TWO equal pulses: 855 T for a 0, 1710 T for a 1
    pause    ~1 second of silence before the next block

The loader measures one pulse and asks a single question — *was that longer or
shorter than halfway between a 0 and a 1?* — which is why the scheme survives a
stretched cassette, a dirty head and thirty years in a loft. A turbo loader uses the
same shape with every number made smaller; that is the whole of its "turbo".

Items, not just blocks
----------------------
A ``.tap`` is only data blocks, so ROM timings apply throughout. A ``.tzx`` may also
carry a bare tone, a hand-written list of pulses, or a silence as *separate* entries,
and a loader can depend on them: a pilot tone stored as a 0x12 block followed by a
0x14 "pure data" block is one load, split across two container entries. So the deck
holds an ordered list of **items** — anything with ``pulses()`` and a ``pause_ms`` —
and only some of them carry ``data`` for the fast loader to shortcut.

The motor
---------
:class:`TapePlayer` deliberately does *not* run the tape continuously from the moment
you insert it. A real cassette burns through its tape whether or not the Spectrum is
listening, and here that would be actively wrong: you spend a few seconds typing
``LOAD ""``, and a multi-load game spends *minutes* playing part one before it asks
for part two. Faithfully running the reel would eat the rest of the tape both times.

Instead the motor follows the machine's attention:

* it **starts** when the machine is plainly sampling the tape — thousands of reads of
  port 0xFE in a single frame, where polling the keyboard takes a few dozen
  (:data:`SAMPLING_READS_PER_FRAME`);
* it **stops** at the pause that ends each block, which is exactly where the person
  sitting in front of a real Spectrum would have hit the stop key.

The TZX specification asks for the second of those in so many words ("pause" means
stop the tape), and the first is just the same idea read off the machine instead of
off a person. Both can be overridden — the deck controls in the Load menu set
:attr:`TapePlayer.motor` by hand and turn :attr:`TapePlayer.auto` off.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

# The 48K's clock. The 128K's is 3.5469 MHz, a 1.3% difference that matters only for
# converting a pause in *milliseconds* into T-states — a pause is padding, and a 13ms
# error in a 1000ms one changes nothing. Pulse lengths themselves are quoted in
# T-states by every tape format, so they need no conversion at all.
CPU_HZ = 3_500_000
TSTATES_PER_MS = CPU_HZ // 1000

# --- the ROM loader's own timings (T-states) ---------------------------------
PILOT_PULSE = 2168
PILOT_PULSES_HEADER = 8063   # ~5s of leader before a header...
PILOT_PULSES_DATA = 3223     # ...and ~2s before the data that follows it
SYNC_FIRST = 667
SYNC_SECOND = 735
ZERO_PULSE = 855
ONE_PULSE = 1710
STANDARD_PAUSE_MS = 1000

# A header block is distinguished from a data block by its flag byte being < 0x80,
# and that choice is what selects the long pilot: the ROM gives a header the longer
# leader because that is the one you are hunting for when you press play mid-tape.
HEADER_FLAG_LIMIT = 0x80

# How many reads of port 0xFE in one frame mean "this machine is reading the tape".
# The gap between the two cases is enormous, so the exact number barely matters:
# reading the whole keyboard costs 8 reads, a generous game poll a few dozen, while a
# loader sampling for edges reads it thousands of times in the same frame.
SAMPLING_READS_PER_FRAME = 200


@dataclass(frozen=True)
class BlockTiming:
    """How one block's bytes are spelled out as pulses.

    The defaults are the ROM's own numbers, so ``BlockTiming()`` describes a normal
    ``.tap`` block. A TZX turbo block overrides every field from its own header, which
    is the only real difference between a turbo tape and an ordinary one.

    ``pilot_count`` of None means "decide from the flag byte" — the ROM's rule, where a
    header gets the long leader and a data block the short one. A turbo block always
    states its count outright, so it never has to guess.
    """

    pilot_pulse: int = PILOT_PULSE
    pilot_count: int | None = None
    sync_first: int = SYNC_FIRST
    sync_second: int = SYNC_SECOND
    zero_pulse: int = ZERO_PULSE
    one_pulse: int = ONE_PULSE
    used_bits_last_byte: int = 8   # a block may end mid-byte; only these bits are sent
    pause_ms: int = STANDARD_PAUSE_MS
    has_pilot: bool = True         # false for TZX "pure data": no leader, no sync


ROM_TIMING = BlockTiming()


def data_pulses(data: bytes, timing: BlockTiming = ROM_TIMING) -> Iterator[int]:
    """Yield the pulse lengths (T-states) that spell out ``data`` on tape.

    Lengths only — the level *alternates* on every pulse, so which voltage the wire
    happens to be at carries no information and nothing needs to record it. That is
    also why polarity never has to be matched across blocks: a loader counts edges.

    Generated lazily on purpose. A 48K game is on the order of a million pulses; built
    as a list that is tens of megabytes for a tape you will play once, in order.
    """
    if timing.has_pilot:
        count = timing.pilot_count
        if count is None:
            is_header = bool(data) and data[0] < HEADER_FLAG_LIMIT
            count = PILOT_PULSES_HEADER if is_header else PILOT_PULSES_DATA
        for _ in range(count):
            yield timing.pilot_pulse
        yield timing.sync_first
        yield timing.sync_second

    last = len(data) - 1
    for index, byte in enumerate(data):
        # Only a final partial byte sends fewer than 8 bits, and it sends the *top*
        # ones: bits leave the machine most-significant first.
        bits = timing.used_bits_last_byte if index == last else 8
        mask = 0x80
        for _ in range(bits):
            width = timing.one_pulse if byte & mask else timing.zero_pulse
            yield width   # each bit is two pulses of equal length, one per half-cycle
            yield width
            mask >>= 1


class PureTone:
    """A stretch of identical pulses with no data in it (TZX block 0x12).

    Usually a pilot tone that the tape's author chose to store separately from the
    data that follows it, so replaying the data alone would give the loader nothing to
    lock onto.
    """

    data = None   # nothing here for the fast loader to shortcut

    def __init__(self, pulse_length: int, count: int, pause_ms: int = 0):
        self.pulse_length = pulse_length
        self.count = count
        self.pause_ms = pause_ms

    def pulses(self) -> Iterator[int]:
        for _ in range(self.count):
            yield self.pulse_length

    def describe(self) -> str:
        return f"Tone ({self.count} pulses of {self.pulse_length}T)"


class PulseSequence:
    """A hand-written list of individual pulse lengths (TZX block 0x13).

    Loaders use these for the odd bespoke moment a formula can't express — a lead-in,
    a deliberate glitch a protection scheme looks for.
    """

    data = None

    def __init__(self, lengths, pause_ms: int = 0):
        self.lengths = list(lengths)
        self.pause_ms = pause_ms

    def pulses(self) -> Iterator[int]:
        return iter(self.lengths)

    def describe(self) -> str:
        return f"Pulse sequence ({len(self.lengths)} pulses)"


class Silence:
    """A gap in the signal (TZX block 0x20): no pulses at all, just a wait.

    A zero-millisecond one means "stop the tape" outright rather than "wait for no
    time", and :class:`TapePlayer` treats every pause as a stopping point anyway, so
    the two land in the same place.
    """

    data = None

    def __init__(self, pause_ms: int):
        self.pause_ms = pause_ms

    def pulses(self) -> Iterator[int]:
        return iter(())

    def describe(self) -> str:
        return "Stop the tape" if self.pause_ms == 0 else f"Silence ({self.pause_ms}ms)"


class TapePlayer:
    """Plays a deck's items as a pulse train, reporting the EAR bit at any instant.

    The player is driven *by being asked*: the machine calls :meth:`ear_level` with its
    absolute T-state clock every time the CPU reads port 0xFE, and the player rolls the
    tape forward to that moment. Nothing runs on a timer, nothing is precomputed, and a
    paused emulator pauses the tape for free — its clock simply stops advancing.

    The play head is the *deck's* index, not a private one, so the fast loader and the
    edge player are always looking at the same place on the same tape. Either can move
    it; whichever moves it, the other notices (see :meth:`_sync_to_deck`).
    """

    def __init__(self, deck, start_clock: int = 0, tstates_per_ms: int = TSTATES_PER_MS):
        self.deck = deck
        self.tstates_per_ms = tstates_per_ms
        self.motor = False
        self.auto = True          # let the machine's own behaviour work the motor
        self.level = 0            # the EAR bit as it stands right now
        self.reads_this_frame = 0
        self.finished = False     # the tape ran out; don't restart it on its own
        # The machine's clock is already running when a tape goes in, and starting from
        # zero would make the first Play look like it happened hours ago.
        self._clock = start_clock
        self._pulse_ends = 0      # when the current level stops being current
        self._pulses: Iterator[int] | None = None
        self._pause_left = 0
        self._stop_after = False  # does the current item end at a pause the motor stops at?
        self._item_index = -1     # which deck item _pulses came from

    # --- what the machine asks ------------------------------------------------

    def ear_level(self, now: int) -> int:
        """The tape input bit at absolute T-state ``now``, rolling the tape to get there.

        Also counts the read: a burst of them in one frame is how :meth:`end_frame`
        recognises a machine that is listening to the tape rather than the keyboard.
        """
        self.reads_this_frame += 1
        self._clock = now
        if self.motor:
            self._roll_to(now)
        return self.level

    def end_frame(self) -> None:
        """Close out a frame: start the motor if the machine was clearly sampling.

        Called once per emulated frame, which is what makes the decision cheap — the
        alternative is asking on every single port read whether this one is the start
        of a load.
        """
        sampling = self.reads_this_frame >= SAMPLING_READS_PER_FRAME
        self.reads_this_frame = 0
        if sampling and self.auto and not self.motor and not self.finished:
            self.start()

    # --- deck controls --------------------------------------------------------

    def start(self) -> None:
        """Run the motor from the current clock — the Play button, and the auto-start."""
        self.motor = True
        self.finished = False
        self._pulse_ends = self._clock   # the next pulse begins now, not in the past

    def stop(self) -> None:
        """Stop the motor and let the wire settle low — the Stop button."""
        self.motor = False
        self.level = 0

    def rewind(self) -> None:
        """Wind back to the tape's first item, stopped."""
        self.deck.rewind()
        self.stop()
        self.finished = False
        self._pulses = None
        self._pause_left = 0
        self._item_index = -1

    # --- rolling the tape -----------------------------------------------------

    def _roll_to(self, now: int) -> None:
        """Advance through pulses until the one that covers ``now`` is current."""
        self._sync_to_deck()
        while now >= self._pulse_ends:
            if not self._advance_one():
                return

    def _sync_to_deck(self) -> None:
        """Notice a play head that the *other* loader moved.

        Fast loading and edge replay share the deck's index, and the fast loader
        advances it a whole block at a time. A half-played pulse stream from the block
        it just consumed would otherwise keep running against the wrong item.
        """
        if self._item_index != self.deck.index:
            self._pulses = None
            self._pause_left = 0

    def _advance_one(self) -> bool:
        """Take the tape's next step; False if there is nothing to play right now.

        A step is one of three things: the next pulse of the current item, the silent
        pause that follows the item, or moving on to the item after it.
        """
        while True:
            if self._pulses is None:
                item = self.deck.current_item()
                if item is None:
                    self.stop()
                    self.finished = True   # the end of the tape, not a pause
                    return False
                self._pulses = item.pulses()
                self._pause_left = item.pause_ms * self.tstates_per_ms
                # Only a *real* pause is a stopping point. An item with no pause runs
                # straight into the next one -- see the end of this method.
                self._stop_after = item.pause_ms > 0
                self._item_index = self.deck.index
                continue

            width = next(self._pulses, None)
            if width is not None:
                self.level ^= 1            # every pulse is a flip; that is all a pulse is
                # A damaged tape can name a zero-length pulse. Bill it one T-state so the
                # clock always moves forward and _roll_to's loop cannot spin for ever.
                self._pulse_ends += width if width > 0 else 1
                return True

            if self._pause_left > 0:
                self.level = 0             # the gap between blocks sits low and quiet
                self._pulse_ends += self._pause_left
                self._pause_left = 0
                return True

            self._pulses = None
            stop_here = self._stop_after
            self.deck.advance()
            self._item_index = self.deck.index
            if self.auto and stop_here:
                # A pause is where a real person stops the tape, and where the TZX format
                # says to. Leaving it running is what would silently spool a multi-load
                # game's part two past the head while part one plays.
                self.stop()
                return False
            # No pause after that item, so the next one follows it immediately -- roll
            # straight on. This is not a nicety: a bare pilot tone (TZX 0x12) exists only
            # to introduce the block after it, and the two are stored as separate items
            # with nothing between them. Stopping there would drop a frame of silence
            # into the gap the loader is about to look for its sync pulses in.
