# zxide

A ZX Spectrum development IDE, built around a pure-Python emulator core and a
PyQt5 UI.

## Status

**Milestones 1–4 complete, plus a full debugger.** A from-scratch pure-Python Z80
CPU with 48K, 128K and Pentagon 128 machine models (memory paging, ULA, keyboard, beeper,
AY-3-8912), tape and snapshot loading (`.tap`/`.tzx`, both instant and at
authentic pulse-level tape speed; `.sna`/`.z80` snapshots), wrapped in a dockable IDE with an assembler build pipeline, a
source-level debugger, and an asset workflow that imports art and audio, places it in
memory and generates the assembly to include it. 850 tests pass; the CPU is
cross-checked against the FUSE reference emulator. See `dev-support/STATUS.md` for
the full state and `DEV_PLAN.md` for what's next.

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
    `dumper.py` (memory back into source), and `asm_meter.py` (source into
    bytes and T-states).
- `zxemu_ui/` — the PyQt5 layer. Shell at the top level (`main_window.py`,
  `controller.py`, `editor.py`, `project_tree_model.py`, `theme.py`,
  `system_open.py`, …), plus:
  - `panels/` — the dockable views: screen, registers, memory, memory map,
    disassembly, call stack, analysis, Output, Inspector, and the sprite and
    beeper-SFX editors.
  - `workspace/` — your project rather than the machine: manifest, settings,
    sjasmplus build, asset codegen, project-wide search, and the SLD source map.
- `tests/` — unit, integration (ROM boot), and the zexdoc/zexall harness.
- `dev-support/` — status/handoff notes, screenshots, the ZEXALL binaries.

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
| `Alt+Enter` | Emulator fullscreen — `Esc` returns to the IDE |

The emulator's keys work by **physical position**, so a non-Latin keyboard layout (Cyrillic,
Greek…) still types on the Spectrum: `LOAD ""` is the J key, then Ctrl+P twice, then Enter,
wherever your layout puts those letters.

`Alt+Enter` and `Esc` are safe to borrow because **a Spectrum has neither key** — nothing you
can type on the emulated machine is lost to them.

**F5 assembles the file you have open**, falling back to the manifest's `main` when the
focused tab isn't a source file. A folder zxide didn't scaffold calls its entry point
whatever it calls it, and a project can hold several buildable sources with no single
"main" among them.

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

Not everything needs the machine running, though. The **Z80 Assembly Meter** in the
status bar costs whatever you select in the editor — or the whole file when nothing is
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

The one honest limit: auto-locate knows where *assets* and the screen live, and reads the
previous build's SLD to avoid where your code landed last time — so on a project's very
first build, before any SLD exists, it can still place an asset on top of hand-written
code. Build twice, or place it by hand.

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

## Licensing

Original code is MIT licensed (see `LICENSE`). Bundled ROM images under
`zxemu_core/roms/` are third-party binaries under separate terms — see
`zxemu_core/roms/LICENSE-roms.txt`. The optional ZX0 decompressor in
`zxemu_ui/addons/zx0addon/` is third-party (zlib licence); see its header.
