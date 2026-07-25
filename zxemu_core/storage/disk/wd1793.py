"""The WD1793 floppy disk controller, at sector granularity.

The chip TR-DOS talks to. Four registers, eleven commands, and one status byte whose
*meaning changes depending on which command you last issued* -- which is the single most
confusing thing about it and the reason :meth:`WD1793.read_status` is written the way it
is.

How a real one works, and what we do instead
--------------------------------------------
A real WD1793 reads a magnetic flux stream. It hunts for address marks in the bit cells,
checks CRCs, and hands over bytes as they pass under the head. Emulating that faithfully
means modelling MFM encoding, and would be both enormous and far too slow in Python.

We don't. A ``.trd`` is a plain sector dump (see ``trd.py``), so the controller here is a
**command decoder plus a byte buffer**: a Read Sector command looks the sector up, fills a
buffer, and serves it one byte per Data-register read. The disk's *contents* are exactly
right; what is missing is everything between the sectors.

That is a real limitation and worth being explicit about. Copy protection works precisely
by putting things between the sectors -- deliberate CRC errors, sectors numbered 0 or 250,
tracks longer than they should be. None of that can be expressed here, so protected disks
will fail. Ordinary ones, which is the overwhelming majority of what exists, are fine.

The one piece of timing we cannot skip
--------------------------------------
The **index pulse**: the once-per-revolution mark on the disk. TR-DOS uses it to decide
whether a drive is spinning at all, so a controller that never pulses index reads as an
empty drive no matter what is mounted. It is synthesised from the machine's T-state clock
at 5 revolutions per second (:data:`REVOLUTION_TSTATES`).

DRQ, in contrast, is asserted immediately. TR-DOS polls for it in a tight loop and does
not care how fast the answer comes.
"""

from __future__ import annotations

# A controller importing from a disk *format* looks backwards, and is deliberate: this
# chip only ever meets 256-byte sectors, 16 to a track, because that is what TR-DOS
# formats and what a .trd stores. Restating the numbers here would let the two drift
# apart silently -- and a controller that disagrees with its images about sector size
# fails as garbled data rather than as an error.
from .trd import SECTOR_SIZE, SECTORS_PER_TRACK

# A 5.25" drive spins at 300rpm = 5 revolutions a second. At 3.5MHz that is 700000
# T-states per turn, of which the index hole is visible for a fraction.
REVOLUTION_TSTATES = 700_000
INDEX_PULSE_TSTATES = 15_000

#: How long a raised DRQ may go unanswered before the transfer is declared lost.
#:
#: Real hardware cannot hang here, and the reason is worth understanding: the disk is
#: *physically spinning*, so a byte the host fails to collect has gone past the head for
#: good. The chip's answer is LOST DATA -- raise the flag, end the command, move on. It
#: has no option to wait.
#:
#: Emulation has exactly that option, and it is a trap. Our "disk" is a bytearray that
#: will wait patiently for ever, so a host that abandons a transfer -- crashes, takes an
#: error path, gets reset mid-sector -- leaves the controller holding DRQ and BUSY until
#: the session ends. TR-DOS polls, sees BUSY, and waits for a byte that will never be
#: asked for. The machine looks hung, and nothing says why.
#:
#: One revolution is deliberately generous: a real chip gives the host about 32
#: microseconds per byte, but instruction-granular timing here would make that trip on
#: perfectly healthy transfers. 200ms is far beyond any legitimate gap between bytes --
#: an interrupt routine in the middle of a load is orders of magnitude quicker -- while
#: still recovering an abandoned transfer in a fifth of a second.
DRQ_TIMEOUT_TSTATES = REVOLUTION_TSTATES

MAX_TRACK = 86  # the head stop; a Restore that gets this far has failed

# --- status bits ---------------------------------------------------------------
# Bit 0 and bits 6-7 mean the same thing for every command. Bits 1-5 do not: after a
# seek they describe the *drive*, and after a read or write they describe the *transfer*.
S_BUSY = 0x01
S_INDEX = 0x02          # type I only
S_DRQ = 0x02            # type II/III only -- the same bit, a different question
S_TRACK0 = 0x04         # type I
S_LOST_DATA = 0x04      # type II/III
S_CRC_ERROR = 0x08
S_SEEK_ERROR = 0x10     # type I
S_RECORD_NOT_FOUND = 0x10  # type II/III
S_HEAD_LOADED = 0x20    # type I
S_WRITE_FAULT = 0x20    # type II/III
S_WRITE_PROTECT = 0x40
S_NOT_READY = 0x80

# --- controller states ---------------------------------------------------------
IDLE = "idle"
READING = "reading"      # serving bytes to the CPU
WRITING = "writing"      # accepting bytes from the CPU
FORMATTING = "formatting"


class WD1793:
    """The controller: four registers, a current command, and a transfer buffer.

    ``drives`` is a list of mounted :class:`~zxemu_core.storage.disk.trd.TrdImage` (or
    None for an empty bay), shared with the machine so the UI can mount into it.
    ``clock`` returns a monotonically increasing T-state count, used only for the index
    pulse; it defaults to a stub so the controller can be unit-tested with no machine.
    """

    def __init__(self, drives, clock=None):
        self.drives = drives
        self.clock = clock if clock is not None else (lambda: 0)
        self.track = 0        # the track register: where the CPU *believes* the head is
        self.sector = 1
        self.data = 0
        self.status = 0
        self._drq = False
        self._last_service = 0   # when DRQ was last raised or a byte last moved
        self.intrq = False
        self.drive_index = 0
        self.side = 0
        self.direction = 1    # last step direction, for the bare Step command
        # Physical head position per bay. Kept separately from the track register because
        # they are allowed to disagree -- that disagreement is exactly what a Seek fixes,
        # and what a Restore recovers from when a program has lost track of the head.
        self.positions = [0] * len(drives)
        self._state = IDLE
        self._buffer = bytearray()
        self._cursor = 0
        self._type1 = True    # was the last command a seek-family one? (see read_status)
        self._write_target: tuple[int, int, int] | None = None
        self._multiple = False

    # --- DRQ, and the deadline that goes with it ------------------------------

    @property
    def drq(self) -> bool:
        """Whether a byte is waiting to move -- checking the deadline as it answers.

        A property rather than a plain flag so that *every* observer enforces the
        timeout, whoever asks and however they got here. The Beta's port 0xFF read, the
        status register and the data register all funnel through this, so an abandoned
        transfer cannot survive by being polled through a path that forgot to check.
        """
        self._expire_stalled_transfer()
        return self._drq

    @drq.setter
    def drq(self, value: bool) -> None:
        self._drq = bool(value)
        if self._drq:
            self._last_service = self.clock()

    def _expire_stalled_transfer(self) -> None:
        """Give up on a transfer nobody is servicing: LOST DATA, and end the command.

        This is the emulated stand-in for a spinning disk (see DRQ_TIMEOUT_TSTATES).
        Without it the controller can be parked mid-sector for ever, which reads to the
        machine as a permanently busy drive.
        """
        if not self._drq or self._state not in (READING, WRITING):
            return
        if self.clock() - self._last_service < DRQ_TIMEOUT_TSTATES:
            return
        self.status |= S_LOST_DATA
        self._buffer = bytearray()
        self._cursor = 0
        self._state = IDLE
        self._drq = False
        self.intrq = True

    # --- wiring ---------------------------------------------------------------

    def select(self, drive: int, side: int) -> None:
        self.drive_index = drive % len(self.drives)
        self.side = side & 1

    def master_reset(self) -> None:
        """What pulling the reset line low does: abort everything, seek to track 0."""
        self._state = IDLE
        self._buffer.clear()
        self._cursor = 0
        self.drq = False
        self.intrq = False
        self.track = 0
        self.sector = 1
        self.status = 0
        self._type1 = True
        self.positions = [0] * len(self.drives)

    @property
    def image(self):
        """The disk in the selected bay, or None."""
        return self.drives[self.drive_index] if self.drive_index < len(self.drives) else None

    @property
    def position(self) -> int:
        return self.positions[self.drive_index]

    @position.setter
    def position(self, value: int) -> None:
        self.positions[self.drive_index] = max(0, min(MAX_TRACK, value))

    # --- status ---------------------------------------------------------------

    def read_status(self) -> int:
        """The status register, whose middle bits mean different things per command type.

        Reading it also clears INTRQ, which is how TR-DOS acknowledges a completed
        command -- so this is not a pure query, and calling it from a debugger view would
        change the machine's behaviour.

        The stall check runs *first*, before BUSY is computed: leave it to the ``drq``
        property further down and the very call that expires a dead transfer would still
        report the drive busy, so a host polling once and giving up would see the old
        answer.
        """
        self._expire_stalled_transfer()
        self.intrq = False
        if self._type1:
            return self._type1_status()
        return self._type2_status()

    def _type1_status(self) -> int:
        """After a seek: where is the head, and is the drive alive?"""
        status = S_BUSY if self._state != IDLE else 0
        image = self.image
        if image is None:
            return status | S_NOT_READY
        if self.position == 0:
            status |= S_TRACK0
        if self._index_pulse():
            status |= S_INDEX
        status |= S_HEAD_LOADED
        if image.write_protected:
            status |= S_WRITE_PROTECT
        return status

    def _type2_status(self) -> int:
        """After a read or write: how is the transfer going?"""
        status = S_BUSY if self._state != IDLE else 0
        image = self.image
        if image is None:
            return status | S_NOT_READY
        if self.drq:
            status |= S_DRQ
        if image.write_protected and self._state in (WRITING, FORMATTING):
            status |= S_WRITE_PROTECT
        return status | self.status

    def _index_pulse(self) -> bool:
        """True while the index hole is under the sensor.

        Synthesised rather than modelled: the disk is not really spinning, but TR-DOS
        checks this bit to decide the drive is turning, and a bit that never changes
        reads as a dead drive.
        """
        if self.image is None:
            return False
        return (self.clock() % REVOLUTION_TSTATES) < INDEX_PULSE_TSTATES

    # --- the data register ----------------------------------------------------

    def read_data(self) -> int:
        """Take the next byte of a read transfer (or the last value, once it is over)."""
        self._expire_stalled_transfer()
        if self._state != READING:
            return self.data
        self._last_service = self.clock()   # the host is keeping up; reset the deadline
        self.data = self._buffer[self._cursor]
        self._cursor += 1
        if self._cursor >= len(self._buffer):
            # A multiple-sector read rolls straight on to the next sector rather than
            # stopping -- that is the entire difference between commands 0x80 and 0x90,
            # and it is how a loader pulls a whole file without issuing a command per
            # 256 bytes. It ends when the track runs out, or when the host aborts with a
            # Force Interrupt, which is the normal way out.
            if self._multiple and self._next_sector_for_multiple():
                return self.data
            self._finish_transfer()
        return self.data

    def _next_sector_for_multiple(self) -> bool:
        """Advance to the next sector of a multi-sector read; False if there isn't one."""
        image = self.image
        if image is None or self.sector >= SECTORS_PER_TRACK:
            return False
        self.sector += 1
        payload = image.read_sector(self.position, self.side, self.sector)
        if payload is None:
            return False
        self._buffer = bytearray(payload)
        self._cursor = 0
        self.drq = True
        return True

    def write_data(self, value: int) -> None:
        """Hand the controller the next byte of a write transfer."""
        self._expire_stalled_transfer()
        self.data = value & 0xFF
        if self._state == WRITING:
            self._last_service = self.clock()   # still being fed; reset the deadline
            self._buffer.append(self.data)
            if len(self._buffer) >= SECTOR_SIZE:
                self._commit_write()
        elif self._state == FORMATTING:
            self._buffer.append(self.data)

    def _finish_transfer(self) -> None:
        self._state = IDLE
        self.drq = False
        self.intrq = True

    # --- commands -------------------------------------------------------------

    def write_command(self, value: int) -> None:
        """Decode and run a command. The top four bits choose it; the rest are flags.

        Writing here clears INTRQ, exactly as reading the status register does. That is
        in the datasheet and it is not a detail: TR-DOS watches INTRQ on port 0xFF to
        decide a transfer has finished, and it does *not* read the status register first.
        Leave INTRQ set from the previous command and the very next Read Sector looks
        like it completed the instant it began -- TR-DOS takes one byte, gives up, and
        reports "No disk" for a disk that is sitting right there.
        """
        self.intrq = False
        command = value & 0xFF
        top = command >> 4
        if top in (0b1101,):
            self._force_interrupt()
        elif top < 0b1000:
            self._type1_command(top, command)
        elif top < 0b1100:
            self._read_or_write_sector(top, command)
        elif top == 0b1100:
            self._read_address()
        elif top == 0b1110:
            self._read_track()
        else:
            self._write_track()

    # -- type I: move the head

    def _type1_command(self, top: int, command: int) -> None:
        self._type1 = True
        self.status = 0
        self.drq = False
        if top == 0b0000:                      # Restore: wind back to track 0
            self.position = 0
            self.track = 0
        elif top == 0b0001:                    # Seek: to whatever is in the data register
            self.position = self.data
            self.track = self.data
        else:
            if top in (0b0100, 0b0101):        # Step In
                self.direction = 1
            elif top in (0b0110, 0b0111):      # Step Out
                self.direction = -1
            self.position = self.position + self.direction
            if command & 0x10:                 # the "update track register" flag
                self.track = (self.track + self.direction) & 0xFF
        self._state = IDLE
        self.intrq = True

    # -- type II: read or write a sector

    def _read_or_write_sector(self, top: int, command: int) -> None:
        self._type1 = False
        self.status = 0
        self._multiple = bool(command & 0x10)
        image = self.image
        if image is None:
            self._state = IDLE
            self.intrq = True
            return
        writing = top in (0b1010, 0b1011)
        if writing:
            self._begin_write(image)
        else:
            self._begin_read(image)

    def _begin_read(self, image) -> None:
        payload = image.read_sector(self.position, self.side, self.sector)
        if payload is None:
            # No such sector on this track: exactly what the chip's RECORD NOT FOUND is
            # for, and what TR-DOS turns into "disk error".
            self.status = S_RECORD_NOT_FOUND
            self._state = IDLE
            self.intrq = True
            return
        self._buffer = bytearray(payload)
        self._cursor = 0
        self._state = READING
        self.drq = True

    def _begin_write(self, image) -> None:
        if image.write_protected:
            self.status = 0
            self._state = IDLE
            self.intrq = True
            return
        if not image.has_track(self.position, self.side) or not 1 <= self.sector <= SECTORS_PER_TRACK:
            self.status = S_RECORD_NOT_FOUND
            self._state = IDLE
            self.intrq = True
            return
        self._buffer = bytearray()
        self._write_target = (self.position, self.side, self.sector)
        self._state = WRITING
        self.drq = True

    def _commit_write(self) -> None:
        cylinder, side, sector = self._write_target
        image = self.image
        if image is not None and not image.write_sector(cylinder, side, sector, bytes(self._buffer)):
            self.status = S_WRITE_FAULT
        self._buffer = bytearray()
        # The write side of the same rule: 0xB0 keeps going into the next sector where
        # 0xA0 stops, so a SAVE writes a whole file in one command.
        if self._multiple and image is not None and self.sector < SECTORS_PER_TRACK:
            self.sector += 1
            self._write_target = (cylinder, side, self.sector)
            self.drq = True
            return
        self._finish_transfer()

    # -- type III: the whole-track commands

    def _read_address(self) -> None:
        """Hand back the next sector's ID field: track, side, sector, size, CRC.

        TR-DOS uses this to work out where the head really is, so the track byte must be
        the *physical* position rather than the track register -- reporting the register
        back would make the two agree by construction and defeat the point of asking.
        """
        self._type1 = False
        self.status = 0
        if self.image is None:
            self._state = IDLE
            self.intrq = True
            return
        # Sector-size code 1 = 256 bytes. The CRC bytes are filler: nothing checks them
        # here, because we have no bit stream for them to describe.
        self._buffer = bytearray([self.position, self.side, self.sector, 0x01, 0x00, 0x00])
        self._cursor = 0
        self._state = READING
        self.drq = True
        # The chip copies the track it found into the sector register as a side effect.
        self.sector = self.position

    def _read_track(self) -> None:
        """Read a whole track. We can only offer its sectors back to back, with none of
        the gaps and address marks a real one would return -- enough for a copier that
        just wants the data, not enough for one inspecting the format."""
        self._type1 = False
        self.status = 0
        image = self.image
        if image is None:
            self._state = IDLE
            self.intrq = True
            return
        buffer = bytearray()
        for sector in range(1, SECTORS_PER_TRACK + 1):
            payload = image.read_sector(self.position, self.side, sector)
            if payload:
                buffer.extend(payload)
        self._buffer = buffer
        self._cursor = 0
        self._state = READING
        self.drq = True

    def _write_track(self) -> None:
        """Format a track -- and, deliberately, **touch nothing on the disk**.

        A real Write Track streams raw MFM (gaps, address marks, data, CRCs) and lays
        down whatever the host feeds it, ending at the next index pulse. We store sectors
        rather than flux, so that stream is unusable to us. It ends immediately.

        This method has now been wrong in both directions, which is why it is worth the
        space:

        * It first *waited* to be fed a track's worth of bytes, with DRQ raised and no
          completion condition. Anything issuing the command without feeding 6250 bytes
          wedged the controller for ever -- no INTRQ, no error, and Reset could not clear
          it either.
        * Then it **blanked the track and finished at once**. That unwedged the machine
          and quietly destroyed data instead: TR-DOS and disk loaders write ``0xFF`` to
          the command register while probing, that decodes to Write Track, and the target
          at the time is *track 0* -- the catalogue and the disk-information block. The
          disk was erased out from under the loader, which then reported "Disk Error" on
          a disk that had been perfectly good a moment earlier.

        So: finish immediately, and write nothing. A command we cannot interpret
        faithfully must not be allowed to modify the disk -- an unimplemented format is a
        missing feature, an erased catalogue is lost work. Nothing is lost in practice
        either: a disk image starts blank, and TR-DOS's FORMAT lays down its catalogue
        and information block afterwards through ordinary Write Sector commands, which
        *are* implemented.
        """
        self._type1 = False
        self.status = 0
        self._buffer = bytearray()
        self._state = IDLE
        self.drq = False
        self.intrq = True

    # -- type IV

    def _force_interrupt(self) -> None:
        """Abort whatever is running. TR-DOS issues this constantly, between commands."""
        self._state = IDLE
        self._buffer.clear()
        self._cursor = 0
        self.drq = False
        self.intrq = True
        self.status = 0
        self._type1 = True
