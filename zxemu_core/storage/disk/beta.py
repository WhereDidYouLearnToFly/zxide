"""The Beta 128 disk interface: five ports, two drives, and a ROM that pages itself.

The Beta 128 is a cartridge that plugs into the expansion port and carries three things:
a WD1793 floppy controller, up to four drive connectors, and a 16K ROM holding **TR-DOS**.
On a Pentagon it is not an add-on at all -- it is soldered in and live from power-on.

The clever, and initially baffling, part is how its ROM appears
-----------------------------------------------------------------
There is no port that pages TR-DOS in. The interface watches the **address bus during
instruction fetch** and swaps itself into 0x0000-0x3FFF the moment the CPU fetches from a
particular page of the ROM:

    page IN   when TR-DOS is not currently paged,
              the fetch address is in 0x3D00-0x3DFF,
              and ROM 1 (48 BASIC) is the selected ROM.

    page OUT  when TR-DOS *is* paged,
              ROM 1 is selected,
              and the fetch address is 0x4000 or above.

That is the whole mechanism, and it explains the incantation every Spectrum owner of a
certain vintage still remembers: ``RANDOMIZE USR 15616``. 15616 is 0x3D00. Calling it
from BASIC makes the CPU fetch an instruction from inside the trigger page, the hardware
notices, and TR-DOS is suddenly *there* -- at an address that a moment ago held the 48K
ROM's tape routines. The Pentagon's own menu ROM does exactly this for its TR-DOS entry:
the 65 bytes that separate it from a Sinclair 128 ROM are that menu item and the code
behind it (see TRDOS.md).

The page-out rule is the same idea in reverse: TR-DOS finishes, jumps to code in RAM, and
the act of fetching from 0x4000+ takes the interface back out of the map. Nothing has to
remember to unpage it.

Both conditions test the fetch (M1) address only -- *reading* data from 0x3D00 does not
page anything. That is why this needs ``Z80.m1_hook`` rather than the existing
single-address trap or a port write.

The ports
---------
Decoded on the low byte of the port address alone::

    0x1F   write: command      read: status
    0x3F   write/read: track register
    0x5F   write/read: sector register
    0x7F   write/read: data register
    0xFF   write: system (drive select, side, reset, density)
           read:  INTRQ (bit 7) and DRQ (bit 6)

The first four are the WD1793's own registers and are passed straight through to it. The
0xFF "system" port is the interface's own latch -- the bits the cartridge added around the
chip -- so it is handled here.
"""

from __future__ import annotations

# Fetching from anywhere in this 256-byte page pages TR-DOS in.
TRDOS_ENTRY_PAGE = 0x3D00
TRDOS_ENTRY_MASK = 0xFF00
# ...and fetching at or above this address (the start of RAM) pages it back out.
RAM_BASE = 0x4000

# Port low bytes. The interface decodes only these eight bits, so the high byte -- which
# on a Spectrum IN carries whatever was in B or A -- is deliberately ignored.
PORT_COMMAND_STATUS = 0x1F
PORT_TRACK = 0x3F
PORT_SECTOR = 0x5F
PORT_DATA = 0x7F
PORT_SYSTEM = 0xFF

# System-latch bits (port 0xFF, write).
SYSTEM_DRIVE_MASK = 0x03   # which of the four drive connectors is selected
SYSTEM_RESET = 0x04        # active *low*: clearing this bit resets the controller
SYSTEM_SIDE = 0x10         # 0 = side 1, 1 = side 0 -- inverted, see select_side
SYSTEM_DENSITY = 0x40      # 0 = double density (MFM), which is all TR-DOS ever uses

# Status-port read bits.
STATUS_DRQ = 0x40
STATUS_INTRQ = 0x80

DRIVE_COUNT = 4


class Beta128:
    """The interface: ROM paging, the system latch, and port dispatch to the controller.

    Holds the machine only to page its ROM; everything else it does is self-contained.
    The controller (``wd1793.py``) is passed in rather than constructed here so it can be
    tested without a machine at all.
    """

    def __init__(self, machine, rom_bank, controller=None):
        self.machine = machine
        self.rom_bank = rom_bank      # the 16K Bank holding TR-DOS
        self.controller = controller  # a WD1793, or None while the read path is unbuilt
        self.paged = False            # is TR-DOS currently mapped at 0x0000?
        self.system = 0               # last value written to port 0xFF
        self.drive = 0
        self.side = 0

    # --- ROM paging -----------------------------------------------------------

    def m1(self, pc: int) -> None:
        """Called before every instruction fetch; page TR-DOS in or out if this is the one.

        This runs for *every instruction the CPU executes*, so it is written to reach a
        decision in as few operations as possible: the common case (TR-DOS not paged, PC
        nowhere near the trigger page) costs one boolean test and one mask-and-compare.
        """
        if self.paged:
            if pc >= RAM_BASE and self._basic_rom_selected():
                self._unpage()
        elif (pc & TRDOS_ENTRY_MASK) == TRDOS_ENTRY_PAGE and self._basic_rom_selected():
            self._page()

    def _basic_rom_selected(self) -> bool:
        """Is ROM 1 (48 BASIC) the one port 0x7FFD has chosen?

        The interface only ever substitutes itself for the 48K ROM. With the 128 editor
        ROM paged, its 0x3Dxx page holds ordinary menu code that must be allowed to run.
        """
        return ((self.machine.port_7ffd >> 4) & 1) == 1

    def _page(self) -> None:
        self.paged = True
        self.machine.memory.page(0, self.rom_bank)

    def _unpage(self) -> None:
        self.paged = False
        # Hand slot 0 back to whichever ROM the paging latch currently names.
        self.machine.restore_rom_slot()

    # --- the system latch (port 0xFF) -----------------------------------------

    def write_system(self, value: int) -> None:
        """The interface's own control latch: drive, side, reset, density."""
        self.system = value & 0xFF
        self.drive = value & SYSTEM_DRIVE_MASK
        # Side select is *inverted* on this hardware: the bit is high for side 0. Getting
        # it backwards reads the wrong half of every double-sided disk, which looks like a
        # corrupt image rather than a wiring mistake.
        self.side = 0 if value & SYSTEM_SIDE else 1
        if self.controller is not None:
            if not value & SYSTEM_RESET:   # active low
                self.controller.master_reset()
            self.controller.select(self.drive, self.side)

    def read_system(self) -> int:
        """Port 0xFF read: the controller's two handshake lines, everything else high.

        TR-DOS polls this in a tight loop while transferring a sector, so the answer has
        to come from the controller's live state rather than anything cached.
        """
        if self.controller is None:
            return 0xFF
        value = 0x3F  # unused bits float high
        if self.controller.drq:
            value |= STATUS_DRQ
        if self.controller.intrq:
            value |= STATUS_INTRQ
        return value

    # --- port dispatch --------------------------------------------------------

    def handles(self, port: int) -> bool:
        """Whether this port belongs to the interface right now.

        Two conditions, and the second is not optional. The interface answers **only
        while its ROM is paged in** -- take that away and ordinary programs start
        colliding with the controller, because reading port 0xFF is the standard way to
        sample the floating bus and every 128K game does it. An ungated FDC would see
        those reads as status polls and quietly corrupt its own state.

        None of these ports can collide with the machine's own, incidentally: all five
        have bit 0 *and* bit 1 set, while the ULA needs bit 0 clear and both the AY and
        the 0x7FFD latch need bit 1 clear.
        """
        return self.paged and (port & 0xFF) in (
            PORT_COMMAND_STATUS, PORT_TRACK, PORT_SECTOR, PORT_DATA, PORT_SYSTEM
        )

    def read_port(self, port: int) -> int:
        low = port & 0xFF
        if low == PORT_SYSTEM:
            return self.read_system()
        if self.controller is None:
            return 0xFF
        if low == PORT_COMMAND_STATUS:
            return self.controller.read_status()
        if low == PORT_TRACK:
            return self.controller.track
        if low == PORT_SECTOR:
            return self.controller.sector
        return self.controller.read_data()

    def write_port(self, port: int, value: int) -> None:
        low = port & 0xFF
        if low == PORT_SYSTEM:
            self.write_system(value)
            return
        if self.controller is None:
            return
        if low == PORT_COMMAND_STATUS:
            self.controller.write_command(value)
        elif low == PORT_TRACK:
            self.controller.track = value & 0xFF
        elif low == PORT_SECTOR:
            self.controller.sector = value & 0xFF
        else:
            self.controller.write_data(value)
