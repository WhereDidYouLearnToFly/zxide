# zxide

A ZX Spectrum development IDE, built around a pure-Python emulator core and a
PyQt5 UI.

## Status

**Milestones 1–4 complete, plus a full debugger.** A from-scratch pure-Python Z80
CPU with 48K and 128K machine models (memory paging, ULA, keyboard, beeper,
AY-3-8912), tape and snapshot loading (`.tap`/`.tzx`, both instant and at
authentic pulse-level tape speed; `.sna`/`.z80` snapshots), wrapped in a dockable IDE with an assembler build pipeline, a
source-level debugger, and an asset workflow that imports art and audio, places it in
memory and generates the assembly to include it. 716 tests pass; the CPU is
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
    `snapshot.py` (.sna), `z80.py` (.z80).
  - `assets/` — converters (`bmp_convert.py`, `tilemap_convert.py`,
    `binary_convert.py`, `pt3_convert.py`, `beeper_sfx.py`, `native_sprite.py`),
    the `manifest.py` that records them, and `preview.py` that draws them.
  - `debug/` — `disassembler.py`, `rom_symbols.py`, `debug_expr.py`, `analysis.py`.
- `zxemu_ui/` — the PyQt5 layer. Shell at the top level (`main_window.py`,
  `controller.py`, `editor.py`, `theme.py`, `system_open.py`, …), plus:
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
| **Load** | running *someone else's* — one item per format (`.tap`, `.tzx`, `.sna`, `.z80`), plus the tape deck |
| **Model** | which machine is emulated (48K / 128K), switchable any time; retargets the open project too |
| **Disassembly** | the disassembly panel and where it points |
| **Breaks** | breakpoint conditions, run-to-cursor |
| **Watch** | pause when a value or port is *touched* |
| **Reversing** | understanding someone else's program: search, cross-references, coverage, trace |
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

The emulator's keys work by **physical position**, so a non-Latin keyboard layout (Cyrillic,
Greek…) still types on the Spectrum: `LOAD ""` is the J key, then Ctrl+P twice, then Enter,
wherever your layout puts those letters.

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

### Assets

Drop a `.bmp`, `.bin`, `.pt3` or beeper-SFX file into the project and it becomes an
**asset**: recorded in `zxide.json`, converted to Spectrum bytes at build time, and
placed at an address you choose — drag it around the memory map in Design mode, or
press **auto-locate** and let the free-space search decide. The build writes
`assets_generated.asm` with the data and an `equ` constant per asset, so your code
refers to `sprite_hero` rather than to a hard-coded address that moves the moment
anything before it grows.

Bitmaps become bitmaps, sprite sheets, sprite sequences or fonts, with optional masks
and attribute planes. The **Inspector** previews whatever is selected. Two things can be
authored in the IDE rather than imported: sprites (in real ZX colours, with the
two-colours-per-cell limit enforced by the tool) and beeper effects (rows of Hz +
frames, with a Play button). Both autosave on every edit.

The one honest limit: auto-locate knows where *assets* and the screen live, and reads the
previous build's SLD to avoid where your code landed last time — so on a project's very
first build, before any SLD exists, it can still place an asset on top of hand-written
code. Build twice, or place it by hand.

### Tapes and snapshots

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
