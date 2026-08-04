# zxide

A ZX Spectrum development IDE, built around a pure-Python emulator core and a
PyQt5 UI.

## Status

**Milestones 1–4 complete, plus a full debugger.** A from-scratch pure-Python Z80
CPU with 48K, 128K and Pentagon 128 machine models (memory paging, ULA, keyboard, beeper,
AY-3-8912), tape and snapshot loading (`.tap`/`.tzx`, both instant and at
authentic pulse-level tape speed; `.sna`/`.z80` snapshots), wrapped in a dockable IDE with an assembler build pipeline, a
source-level debugger, and an asset workflow that imports art and audio, places it in
memory and generates the assembly to include it. The screen can be saved as a
still (`.scr` + `.bmp`) or recorded frame by frame and exported as an animated GIF.
1389 tests pass; the CPU is cross-checked against the FUSE reference emulator. See
`dev-support/STATUS.md` for the full state and `DEV_PLAN.md` for what's next.

## Layout

- `main.py` — application entry point (composition root).
- `zxemu_core/` — the emulator, with no Qt dependency and independently testable.
  The machine itself is at the top level (`machine.py`, `memory.py`, `ula.py`,
  `keyboard.py`, plus `memlayout.py` for where things fit in the address space);
  everything else is grouped by subsystem:
  - `cpu/` — the Z80: `z80.py` (fetch/decode/execute), `registers.py`, `flags.py`,
    and `instructions/` (one explicit handler per opcode, grouped by family).
  - `sound/` — `beeper.py`, `ay.py`, the `mixer.py` that sums them, and
    `beeper_preview.py` for auditioning an effect without a running machine.
  - `storage/` — `tape.py` (.tap + the ROM-trap fast loader), `tzx.py`,
    `pulse.py` (edge-level replay: blocks back into the pulses a ULA hears),
    `snapshot.py` (.sna), `z80.py` (.z80), and `disk/` — the Beta 128
    interface, a WD1793, and `.trd`/`.scl` TR-DOS images.
  - `assets/` — converters (`bmp_convert.py`, `tilemap_convert.py`,
    `binary_convert.py`, `pt3_convert.py`, `beeper_sfx.py`, `native_sprite.py`),
    the `manifest.py` that records them, and `preview.py` that draws them.
  - `debug/` — `disassembler.py`, `rom_symbols.py`, `debug_expr.py`, `analysis.py`,
    `dumper.py` (memory back into source), `asm_meter.py` (source into
    bytes and T-states), and the editor's hover help: `asm_help.py` (what an
    instruction is for) with `asm_symbols.py` (what your `equ` constants come to).
- `zxemu_ui/` — the PyQt5 layer. Shell at the top level (`main_window.py`,
  `controller.py`, `editor.py`, `recorder.py`, `project_tree_model.py`,
  `theme.py`, `system_open.py`, …), plus:
  - `panels/` — the dockable views: screen, registers, memory, memory map,
    disassembly, call stack, analysis, Output, Inspector, and the sprite and
    beeper-SFX editors.
  - `workspace/` — your project rather than the machine: manifest, settings,
    sjasmplus build, asset codegen, project-wide search, and the SLD source map.
- `tests/` — unit, integration (ROM boot), and the zexdoc/zexall harness.
- `dev-support/` — status/handoff notes, screenshots, the ZEXALL binaries.
- `build/` — packaging: the PyInstaller spec, the build scripts and the icon
  generator that turn the source tree into a standalone app. Not needed to run
  from source; see [Building a standalone app](#building-a-standalone-app).

**Each package's `__init__.py` opens with an educational overview — start there.**
Individual modules carry the reasoning: not just what the code does, but why it is
built that way and where the approach stops working.

## Running

```
python main.py
```

Run it from a terminal (or "Run Without Debugging" / Ctrl+F5 in VS Code) — the
emulator's hot loop is far slower under a debugger's per-line tracing.

## Using the IDE

Menus are grouped by what you're doing rather than by which code implements them:

| menu | for |
|---|---|
| **File** | projects and source files |
| **Edit** | finding your way around your own text: find in project, go to line |
| **Build** | turning *your* project into a running program |
| **Load** | running *someone else's* — one item per format (`.tap`, `.tzx`, `.trd`, `.scl`, `.sna`, `.z80`), plus the tape deck and disk drive |
| **Model** | which machine is emulated (48K / 128K / Pentagon 128), switchable any time; retargets the open project too |
| **Disassembly** | the disassembly panel and where it points |
| **Breaks** | breakpoint conditions, run-to-cursor |
| **Watch** | pause when a value or port is *touched* |
| **Reversing** | understanding someone else's program: search, cross-references, coverage, trace, and dumping it back out as source |
| **Compression** | optional addons (ZX0) copied into the open project |
| **View** | panel visibility, interface scale, saved dock layout |

### Keyboard

| key | action |
|---|---|
| `F5` | Build & Debug (breakpoints active) |
| `Ctrl+F5` | Build & Run (breakpoints ignored) |
| `F11` | Step Into — one instruction, entering calls |
| `F10` | Step Over — run calls and block ops to completion |
| `Shift+F11` | Step Out — run until the current subroutine returns |
| `Ctrl+F10` | Run to Cursor |
| `Ctrl+F` | Find in Project — results in Output, click one to jump to it |
| `Ctrl+G` | Go to Line |
| `Ctrl+S` / `Ctrl+Shift+S` | Save / Save All |
| `F2` / `Delete` | Rename / delete the selected file — project tree only |
| `Alt+Enter` | Emulator fullscreen — `Esc` returns to the IDE |

**Renaming repoints the manifest.** An asset's source path follows its file, and a renamed
folder takes every asset inside it along — otherwise the next build fails on a file that is
sitting right there under a different name. The asset's *symbol* deliberately does not
change: that is what your assembly source refers to. Changing an asset's extension asks
first, because for sprites the extension **is** the format.

The emulator's keys work by **physical position**, so a non-Latin keyboard layout (Cyrillic,
Greek…) still types on the Spectrum: `LOAD ""` is the J key, then Ctrl+P twice, then Enter,
wherever your layout puts those letters.

`Alt+Enter` and `Esc` are safe to borrow because **a Spectrum has neither key** — nothing you
can type on the emulated machine is lost to them.

**F5 assembles the file you have open**, falling back to the manifest's `main` when the
focused tab isn't a source file. A folder zxide didn't scaffold calls its entry point
whatever it calls it, and a project can hold several buildable sources with no single
"main" among them.

### Kempston Mouse and Joystick

Both live under **Model**, beneath the machines — what's plugged into the emulated Spectrum
is the same question as which Spectrum it is. Both are **off by default**, and only one can
be fitted at a time: they share port 0x1F, and on real hardware two interfaces answering the
same port fight over the data bus.

| interface | how you use it |
|---|---|
| **Kempston Mouse** | Click the emulator screen to capture the pointer — the cursor hides and the mouse drives the Spectrum. `Esc` gives it back (twice in fullscreen: pointer first, then fullscreen). |
| **Kempston Joystick** | Arrow keys steer, `Ctrl` fires. A USB gamepad works too, if one is plugged in. |

The joystick port is **8-bit, following the ZX Spectrum Next** — which is really the Mega
Drive pad's layout:

| bit | 7 | 6 | 5 | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|
| | START | A | C | B | up | down | left | right |
| key | `End` | `Home` | `Insert` | `Ctrl` | ↑ | ↓ | ← | → |
| pad button | 9 | 8 | 1 | 0 | | | | |

**Model ▸ 8-bit extended (MD 3-button)** is what decides whether bits 7-6 reach the program
at all: the Next's Kempston mode masks them to 0 and its MD 3-button mode passes them, and
that masking is the entire difference between the two. A second fire (bit 5) works in either.
Off by default, because software written for a one-button stick can read those bits as
something else entirely. Original 1980s hardware simply never closes the upper switches, so
it behaves identically in either mode — which is why there's no third setting for it.

Any pad button the table doesn't name also fires, so an unfamiliar pad is never mute.

**Fitting one mid-game does nothing until you reset**, and this catches everybody: software
reads these ports once at startup to decide what's attached, so a game already running has
long since concluded there's no mouse. The Output console says so when you fit one.

While the joystick is fitted the arrow keys and `Ctrl` stop reaching the Spectrum keyboard.
Feeding both would have a game see every nudge twice, the arrows being CAPS SHIFT + 5/6/7/8.

### AY music

Double-click a music file in the project tree and it opens in the **Music Player** — a
floating panel with play/stop and three channel meters. Selecting the file shows its details
in the Inspector.

| format | what it is | needs |
|---|---|---|
| `.ay` | a container of Z80 code plus the addresses to call; often several tunes in one file | nothing |
| `.c` | a *compiled module* — a tracker's output with its player welded on | nothing |
| `.pt3` / `.pt2` | raw tracker data, which carries no player | a player binary (see below) |

**Playback runs a real emulated machine underneath**, on its own private 128K — never the
emulator on screen, so auditioning a tune can't disturb what you were debugging. That's not
a shortcut: most Spectrum music *is* Z80 code rather than a note list, so running the
author's own player is the only faithful way to hear it.

The meters show what the chip is doing: bar height is volume, and each channel says whether
it is playing a tone (its period), `noise`, `env` when the envelope generator drives it, or
`off` when it is mixed out entirely. A drum channel typically reads `noise env` with no
tone. There is no pattern or row display — with a compiled player there is genuinely no such
thing to read.

Closing the panel stops playback immediately.

**Raw `.pt3`/`.pt2` need a player program**, because the file is only note data. Two are
bundled (`zxemu_core/players/`, third-party — see `LICENSE-players.txt`), so this works with
no setup. A player next to your project takes precedence over them: put one in the project
root, or `music/`, `players/`, `tools/`, `lib/`. Failing both, **Find player…** in the panel
asks for one and remembers where it lives.

Candidates are identified by *shape*, not filename — a player's header states where it
expects its module, and that must equal its own length — so pointing zxide at a folder of
assorted `.bin` files is safe.

`.c` is also the C source extension, so content decides: a real C file still opens in the
editor.

### Debugging

Click the editor gutter to set a breakpoint; **Build ▸ Build & Debug** honours them.
While paused you can edit as well as inspect — poke a byte in the Memory panel, click
a register to set it, hover a flag to read what it means.

Beyond that: **watchpoints** on memory reads *and* writes and on I/O ports;
**conditional breakpoints** (`A == $FF`, `(HL) == 0`, `B == 0 and C == 0`); a
**disassembly** panel annotated with ROM routine names and your own labels from the
build; an inferred **call stack**; **coverage** recording and a bounded **execution
trace**; and memory **search** and **cross-references**.

Some of these answer with certainty and some with inference, and the panels say
which — a call stack is reconstructed rather than recorded, cross-references are a
static scan that cannot follow computed jumps, and an address absent from coverage
means "not executed *yet*", never "unreachable".

Not everything needs the machine running, though. The **Z80 Assembly Meter** along the
bottom of the editor costs whatever you select — or the whole file when nothing is
selected — in bytes and T-states:

```
file: 24 bytes · 271–316 T · 14 instr
```

On a machine with 48K of RAM and 69888 T-states per frame, "does this fit" and "does
this finish in time" are the two questions that decide whether a routine works, and
both are answerable from the source alone. Timing is a **range** wherever a conditional
jump, call, return or repeating block instruction costs different amounts taken and not
taken, rather than picking one and being quietly wrong half the time. The figures are
the published uncontended ones — no ULA contention (which depends on where the code
sits and when the beam is, neither knowable from source text) and no M1 waits — so real
timing in contended memory will be higher. `db`/`dw`/`ds` count toward bytes and cost no
time, and anything the table doesn't recognise (a macro invocation, an `incbin` whose
file it can't see) is reported as *unrecognised* beside the totals rather than silently
counting as zero.

### Hover help in the editor

Hovering a line of assembly says what the instruction is for, what that exact operand
form costs, and which flags it disturbs — priced through the same tables as the meter, so
`ld a,(hl)` and `ld a,(ix+d)` are told apart rather than given a range covering both.
Assembler directives (`org`, `incbin`, `savesna`, …) get the same one-line treatment.

Any constant the line names is answered too, which is the part you'd otherwise leave the
file to look up:

```
ld de,ATTRS
Copy a value from the source (right) to the destination (left).
3 bytes · 10 T
Flags: unaffected
ATTRS = SCREEN + SCREEN_LEN = 22528 ($5800) · consts.asm
```

The working is shown when the constant was derived from others, and the file it came from
is named when it wasn't this one. Constants are found by reading the **source** — your
file plus everything it `include`s, in whatever form it is on screen right now, so a value
you changed a second ago and haven't saved is the value you're shown. Nothing needs to
have been built, and a file that doesn't yet assemble still answers.

Both `NAME: equ …` and `NAME equ …` are understood, as are `=`, `defl` and `DEFINE`, and
values may be written in any of the usual notations (`$4000`, `#4000`, `4000h`, `%1010`,
`1010b`, `0x10`, `'A'`). Expressions are worked out — `+ - * / % & | ^ ~ << >>` and
parentheses, including constants defined in terms of each other, in any order.

What it will not do is guess. `equ $` (the assembler's current address), a macro argument,
an unknown name, or anything else only the assembler could resolve shows the expression as
written instead of a value. Addresses of *labels* are a different question, answered by
the disassembly panel from the build's SLD map rather than here.

**Settings ▸ Show instruction help when hovering code** turns the whole thing off.

### Assets

Drop a `.bmp`, `.bin`, `.pt3` or beeper-SFX file into the project and it becomes an
**asset**: recorded in `zxide.json`, converted to Spectrum bytes at build time, and
placed at an address you choose — drag it around the memory map in Design mode, or
press **auto-locate** and let the free-space search decide. The build writes
`assets_generated.asm` with the data and an `equ` constant per asset, so your code
refers to `sprite_hero` rather than to a hard-coded address that moves the moment
anything before it grows.

Bitmaps become bitmaps, sprite sheets, sprite sequences or fonts, with optional masks
and attribute planes. The **Inspector** previews whatever is selected, and the project
tree badges every file the manifest knows about with its kind's icon — so an asset is
distinguishable at a glance from a file of the same type that is merely sitting in the
folder. Double-clicking one of those offers to adopt it.

Two things can be authored in the IDE rather than imported, and both autosave:

- **Sprites**, in real ZX colours, with one tool rather than a mode to switch between:
  drawing a pixel also gives its 8×8 cell the selected ink and paper, because on this
  hardware those are the same decision. The left button *toggles*, so erasing a stray
  pixel is a click rather than a trip to the palette; right-drag recolours a cell without
  touching the art, and Alt+click picks a cell's colours back up. A native sprite file
  **is** the bytes the Z80 gets, and its extension says how to read it: `.zx8x8` /
  `.zx16x16` for fixed sizes, `.zxsprite` for anything else (its first two bytes are
  width and height), each with a `…pix` variant that stores pixels only, for sprites the
  code colours itself.
- **Beeper effects**, as a bar chart of frequency over time. Each bar rises from the
  baseline: its height is the tone, its width is how long that tone lasts. Drag up for
  higher, sideways to make it last longer (shift keeps the pitch level), right-drag to
  erase, and there's a Play button — no settings, because length is what the drag is for.
  One column is one video frame, 20ms, the shortest sound the format can express. The
  frequency axis is logarithmic; a linear one would squash everything below 500Hz, which
  is exactly where thuds and rumbles live.

Auto-locate places assets clear of your own code as well as of other assets, because it
reads the memory plan described next.

### The memory plan: your source *is* the map

You already write where things go — `org $8000`, a label, a `MODULE`. Design mode reads
that back. Press **Refresh** and the map draws one rectangle per region, named after the
module or label that opens it, behind the asset rectangles. Click one to open the line
that put it there.

It reads the directives that actually decide layout — `DEVICE`, `org`, `MODULE`,
`SLOT`/`PAGE`, `include`, `incbin` — through the whole include tree from your build entry
point, and it resolves `org` operands through your `equ` constants, because a real project
writes `org AppStart` against a table of addresses rather than a literal. Sizes come from
the assembly meter; where the last build left an `.sld`, the real figures replace the
measured ones.

It is a button rather than something that runs as you type. A scan you did not ask for is
one whose timing you cannot trust — press it when you want the map to catch up. Opening a
project and finishing a build each scan once, and nothing else does.

**What it admits.** A region whose length it had to guess — an unexpanded macro, a `DUP`
block, a conditional whose branches it counted blind — is drawn hatched, the same
convention an asset whose bytes have never been converted already uses. A bare `org $c000`
on a 128K is drawn in slot 3 but marked as having no known bank, because which of the
eight sits there depends on a port write no static reader can see. Regions that overlap
anything else are outlined in red and listed in the Output, never blocked: two routines
that are never resident at once are a legitimate thing to write.

#### The memory plan window (Ctrl+M)

**View ▸ Memory plan…** opens the plan as its own maximisable window, and that is where
the rearranging actually happens. The dock's map is drawn *to scale*, which is the right
picture for watching PC and SP move but the wrong one for editing: a 43-byte routine is
two pixels of a 16K column, too small to read or aim at. And it draws *slots*, so on a
128K it can only ever show the four banks paged in at that moment — while your code can
assemble into any of the eight.

The window gives up on proportion instead. Every block is one row of the same height,
carrying its name, `$start - $end`, its size, and `(estimate)` when the length is a guess.
Each run of unclaimed memory is a row of its own saying how much is there and where, so
"will this fit" is something you read rather than measure. Every bank gets a column —
including ones nothing is paged into — and empty banks are hidden until you ask for them.
The header line counts blocks, banks, bytes used and conflicts.

Drag a row onto a gap and the block starts there; drop it on another block and it packs
flush after it. Both are the same one-line source edit described below. Moving a block to
a *different bank* is refused for now with a note saying why: which bank bytes assemble
into is set by `SLOT`/`PAGE` beside the `org`, so it means inserting directives rather
than changing a number, and doing something structurally different under the same gesture
would be the wrong kind of surprise.

#### Moving a block

Regions can also be **dragged on the dock's map**. Pick one up, drop it where there is room, and the source moves
with it — *one line* rewritten:

| what your `org` says | what changes |
| --- | --- |
| `org Attributes` | the `Attributes equ $8300` line, wherever it is defined |
| `org $8181` | that `org` line itself |

The first case is the one that matters. Once a project has more than a few blocks its
addresses live in one table of `equ`s that every `org` points at — that table *is* the
memory plan you maintain by hand, and moving a block by editing it keeps the table and the
code agreeing. Rewriting the `org` instead would leave the table lying.

The rewrite is surgical: only the number changes. Indentation, alignment, the notation
(`$8300` stays `$8300`, not `0x8300`) and the trailing size comment are left exactly as
they were, so the diff of a move is one value. And it is applied **through the editor**
rather than to the file — the tab opens at the changed line, Ctrl+Z undoes it like any
other edit, and it reaches disk when you save. Anything you had unsaved in that file
survives.

A drag lands on a 256-byte boundary, or flush against a neighbour's edge when it comes
close, since packing one block hard against another is the move you make constantly and
aiming at ~27 bytes per pixel is luck. **Arrange** does that to everything at once: every
movable block packed tight, per bank, in its current order. It runs only when pressed —
nothing here ever moves your code on its own — and it edits one line per block, so undoing
it is one Ctrl+Z per block.

A block is movable when its address traces to exactly one line. One org'd to an expression
(`Base + 32`), or to a name whose definition can't be found, is drawn like any other and
stays put; the Output says which and why, rather than the IDE editing a line it only
half-understood.

### Reversing someone else's program

The **Reversing** menu answers questions about *the whole program*, as opposed to Breaks
and Watch, which are about what the machine is doing right now. Eight items in four groups:

| item | what it does |
|---|---|
| **Find Bytes…** | search memory for a hex sequence (`21 00 40`) |
| **Find Text…** | search memory for a string |
| **Cross-references…** | given an address, list every instruction that calls, jumps to, reads, writes or loads it |
| **1. Record What Runs** | mark every address the CPU executes |
| **2. Dump to Project…** | turn what you recorded into source — see below |
| **Show What Ran** | those addresses, collapsed into ranges |
| **Record Trace** | a rolling log of the last ~2000 instructions — *not* used by the dumper |
| **Show Trace** | print it |

Results go to the **Analysis** panel.

**Each of these says how much it can promise, and the differences matter.** Search is
exact. Cross-references are a *static* byte scan: they see references inside code that
never runs, and they **cannot see computed destinations at all** — `jp (hl)`, jump tables
and self-modified operands are invisible to them. Coverage never lies about what ran, but
only knows what has run *so far*, so an unmarked address means **"not yet", never
"never"**. The trace is bounded on purpose; an unbounded one would be millions of entries
a second.

**Cross-references and coverage are opposites, and that is why you want both.** One is
static and sees code that never executed; the other is observed and catches the computed
jumps the scan cannot follow. Where the two disagree is usually where the interesting code
is.

Recording and dumping are numbered and adjacent because the dependency between them is
otherwise invisible: **the dump is only as good as what you recorded.** Dump without
recording and you get a correct project in which nothing is disassembled — so it asks
first, and offers to start recording instead.

Both recording options force the slower per-instruction loop, which is why they are off by
default and say so in the Output when you switch them on.

### Turning a program back into source

**Reversing ▸ Dump to Project…** takes the RAM of whatever is running and writes it out as a
zxide **project** — a manifest, a `main.asm`, and one source file per region — so somebody
else's program becomes somewhere you can work: F5 builds it, the gutter sets breakpoints,
the disassembly panel gets its labels from the build.

Telling code from data is undecidable, so it isn't decided statically. **Coverage is the
ground truth**: turn on *Record Coverage*, exercise the program, and the addresses that
actually executed become disassembly while everything else stays bytes. Both assemble to
the same program, so the dump is correct from the first run and gets *better* the more of
the program you have exercised.

The dump also restores the machine, not just its memory — the border, the interrupt mode
and vector, every register and the paging latch, none of which live in RAM. Without them a
rebuilt game comes up with a white border and, far worse, no interrupts at all, so it never
reads the keyboard.

It does that by **writing the snapshot itself**, from a Lua block in the generated source
(sjasmplus embeds Lua), rather than by injecting restore code into the program. So nothing
is added to RAM: a 128K or Pentagon dump is byte-for-byte the original, and a 48K one
differs only in the two bytes the `.sna` format insists on keeping PC in, below the stack
pointer — memory the program overwrites itself on its next push.

What makes it trustworthy is that the build also writes a raw memory image, so you can
assemble the dump and compare it byte-for-byte with the machine it came from (everything
outside that stub must match exactly). Two honest
limits, stated in the generated source itself: a region left as data may simply be code you
have not run yet, and **only what was resident is captured** — a game that streams levels
from disk has just the part that was in memory at that instant.

### Tapes, disks and snapshots

There are two loaders, and **Load ▸ Tape Deck ▸ Fast Load** picks between them.

**On (the default), tapes load instantly**, by intercepting the ROM's loading routine
instead of replaying the pulses a real cassette produced. That covers BASIC's `LOAD ""`
and the many game loaders that call into the ROM — including the multi-part 128K ones
that page banks between blocks.

**Off, the machine loads the way it did in 1985**: the tape is turned back into the
pilot/sync/data pulse train and fed to port `0xFE` bit 6, and the loader works the bytes
out by timing the gaps. This is slower — a full game takes minutes, exactly as it did on
hardware — and it is the only thing that will satisfy a **turbo loader**, which times its
own bits and never touches the ROM. Two things come with it for nothing: the **loading
stripes**, because the loader itself is painting the border between samples, and the
**tape sound**, because on real hardware the tape signal reaches the speaker.

Real commercial tapes load this way (1942 is the worked example), but the heavily
protected loaders are not all there yet — Speedlock plays its whole tape without coming
up. If a tape stalls, the Output says which of the two loaders to reach for.

### Disks (Pentagon + TR-DOS)

**Load ▸ Load TRD… / Load SCL…** mounts a TR-DOS disk. Neither a 48K nor a Sinclair 128 has
anywhere to put one, so doing this switches the machine to a **Pentagon 128** — the Soviet
clone the whole disk world ran on — and says so in the Output.

Inside the machine, choose **TR-DOS** from the Pentagon menu (or `RANDOMIZE USR 15616`) and
type `CAT`. **Load ▸ Disk Drive** handles the disk you already mounted: drive B, write
protect, Save Disk As, eject. Disks are **writable** — TR-DOS can `SAVE` onto them and the
image saves back out, which is what makes a disk a development target and not just another
way to load somebody else's game.

`.scl` images are converted to a real disk on load, since an SCL is a list of files with no
disk around them. Saving always writes `.trd`, because an SCL cannot express free space or a
disk label. See **[TRDOS.md](TRDOS.md)** for how it works and what it can't do — chiefly
copy-protected disks, which hide their protection in the gaps between sectors that a
sector-level emulation has nowhere to put.

`.tzx` files are read for everything audible, in order — data blocks with their own pulse
timings, plus bare tones, pulse sequences and pauses. Anything else in the container
(groups, menus, credits) is reported in the Output rather than silently dropped.

## Development

```
pip install -e ".[dev]"
pytest
```

## Building a standalone app

To hand zxide to someone who has no Python at all, freeze it into `release/`:

```
pip install -e ".[build]"          # PyInstaller, on top of the runtime deps

powershell -ExecutionPolicy Bypass -File build\build.ps1     # Windows
build/build.sh                                               # Linux/macOS
```

That produces `release/zxide/` — an executable plus an `_internal/` folder holding
the Python runtime, Qt, and the app's ROMs, tracker players, project templates and
addons. Copy or zip the whole folder; the executable alone will not run.

Requirements and caveats worth knowing before you build:

- **Python 3.10+ 64-bit, with the runtime dependencies installed** (`pip install -e .`).
  PyInstaller bundles the copies it finds, so the interpreter first on `PATH` is the
  one that gets frozen.
- **No cross-compiling.** A Windows `.exe` has to be built on Windows and a Linux
  binary on Linux — hence the two scripts, both driving the same `build/zxide.spec`.
- **sjasmplus is not bundled.** zxide runs the assembler as an external process
  chosen in Settings, so a machine running the release still needs its own copy
  before the Build menu will do anything. Everything else — emulator, editor,
  debugger, asset tools — works without it.
- **The frozen app keeps `settings.json` and `layout.json` inside its own folder**,
  which is fine for unzip-and-run but not for an install under `C:\Program Files`.

On Linux there are two more steps, because a bundle folder does not register itself
with the desktop:

```
build/linux/install.sh     app menu entry, icon and a `zxide` command, into ~/.local
build/package.sh           pack the build into release/zxide-linux-<arch>-<version>.tar.gz
```

`build/README.md` has the details: what goes into the bundle and why, the `-Clean`
and `-Console` switches, how the icon is generated, the Linux install/uninstall and
glibc/xcb caveats, and what to do when a module or data file goes missing from a
build.

## Licensing

Original code is MIT licensed (see `LICENSE`). Bundled ROM images under
`zxemu_core/roms/` are third-party binaries under separate terms — see
`zxemu_core/roms/LICENSE-roms.txt`. The optional ZX0 decompressor in
`zxemu_ui/addons/zx0addon/` is third-party (zlib licence); see its header.
