# zxide — project status & handoff

_Last updated: 2026-07-22._ A snapshot to make it easy to pick the project back up.

## Latest session (2026-07-22) — audio bug hunt, then the debugger

**Three real emulator bugs**, all found by chasing a "loud farting noise" over beeper
music and all verified by headless capture rather than by ear:

1. `beeper.py` — the speaker level never carried across frames (the flush sentinel
   reassigned it back to the frame's *starting* value, so it was permanently 0). Every
   frame restarted from low, injecting a full-amplitude pulse at each boundary: a 50Hz
   buzz that was **68% of the output's total energy**.
2. `machine.py` — `run_frame` computed its target relative to the carried remainder, so
   the remainder accumulated every frame's overshoot forever. Once non-zero, flips in
   the frame's tail were timestamped past `frame_tstates` and clamped onto one instant:
   **36,350 of ~670,000 flips destroyed per 1000 frames**, worsening the longer you
   listened. Fixed by making the target absolute.
3. `cpu/instructions/indexed.py` — forming `(IX+d)` was treated as free, so **every**
   indexed instruction ran 5 T-states short (2 for `LD (IX+d),n`). Engine-independent;
   affects anything that paces itself by instruction cycles.

**Audio modules split** one-per-chip, matching `ula.py`/`keyboard.py`: `beeper.py`
(Beeper), `ay.py` (AY8912), `mixer.py` (SoundMixer). `audio.py` is gone.

**The debugger is now complete** — see DEV_PLAN's debugger track. Panels:
disassembly (with ROM routine names and your own SLD labels), call stack, analysis.
Stepping: into / over / out, run-to-cursor. Stopping: conditional breakpoints,
watchpoints on memory reads *and* writes and on I/O ports. Editing: poke memory,
click a register to set it. Plus coverage recording, a bounded execution trace,
memory search and cross-references.

Two design decisions worth knowing, both about not taxing the fast path:
* **port watchpoints** swap `cpu.io_read`/`io_write` for instrumented versions only
  while watches exist — Danterrifik does 80k OUTs a frame, so even an empty-set check
  would have cost milliseconds;
* **memory watchpoints** rebind `memory.__class__` to an instrumented subclass rather
  than building a replacement object, because the CPU, the machine and the 128K paging
  code all hold that same reference.

**342 tests pass.**

## Where we are

**Milestone 1 (emulator core + live PyQt5 view) is complete and working.**
- Pure-Python Z80 CPU (full instruction set incl. undocumented behaviour),
  48K memory, ULA (timing/contention/border), 8x5 keyboard.
- PyQt5 view renders the screen (bitmap + attributes + border + FLASH) via a
  numpy fast path, driven by a real-time-paced frame loop at ~50 fps.
- Boots the real 48K ROM to the 1982 copyright screen; BASIC runs; typing
  `PRINT "HELLO"` works end to end.
- **342 tests pass** (`pytest tests/unit tests/integration`).

## How it's structured

```
main.py            entry point + frame loop (QTimer, real-time catch-up pacing)
zxemu_core/        emulator core, no Qt dependency
  cpu/
    z80.py         fetch/decode/execute loop, interrupts, HALT
    registers.py   registers + flag bits
    flags.py       ALU/flag math
    instructions/  one explicit handler per opcode, grouped by family
                   (load8/16, arith8/16, logic in arith8, rotate_shift, bit,
                    jump, call_return, control, blockio, exchange, indexed)
                   + indexed_bit.py (DDCB/FDCB, kept compact as a loop demo)
                   + _dispatch.py (tables + @base/@cb/@ed/@indexed decorators)
  memory.py        16K-bank paged model (paging-ready for 128K) + the instrumented
                   variant memory watchpoints switch on
  ula.py           port 0xFE (border/keyboard), frame timing, contention table
  keyboard.py      8x5 matrix
  beeper.py        1-bit speaker flips -> PCM      } one file per sound source,
  ay.py            AY-3-8912 (128K)                } summed by...
  mixer.py         ...the resistor network's software stand-in
  tape.py          .tap parsing + ROM-trap fast load
  snapshot.py      .sna load (48K/128K)
  disassembler.py  bytes -> Z80 mnemonics
  rom_symbols.py   names for 48K ROM entry points
  debug_expr.py    conditional-breakpoint expressions
  analysis.py      search / cross-references / coverage
  machine.py       wires it together; run_frame() = one 50Hz frame
zxemu_ui/          IDE shell + panels (see its __init__.py for the full list;
                   debug panels: disassembly, call stack, analysis, registers,
                   memory cells, memory map)
tests/             unit, integration (ROM boot), zexall harness
dev-support/       this file, screenshots, ZEXALL binaries (git-ignored .com)
```

Design intent: the core is UI-agnostic and the instruction handlers are
spelled out explicitly for **educational readability** (a learner can search a
mnemonic and read its code). Each package `__init__.py` is an educational
overview. When the IDE grows, `main.py` becomes the IDE shell and
`zxemu_ui`'s view becomes one dockable panel.

## Key decisions made

- **Fresh pure-Python emulator**, not a port of FUSE. FUSE (`E:/github/fuse`,
  GPLv2) is used only as a reference. Only the ROM binaries are reused.
- **PyQt5** UI; **numpy** for fast rendering.
- **48K first, designed for 128K** (paged memory abstraction already in place;
  `128-0.rom`/`128-1.rom` bundled but not wired up).
- **No built-in code editor** planned — the IDE will open sources in an
  external editor and build via an external assembler (Milestone 2).
- Instruction tables refactored to explicit per-family files; DDCB/FDCB kept
  generated on purpose as a contrast/demo.

## Known limitations / deferred (not bugs)

- **zexdoc/zexall not fully run** — impractically slow in CPython (~5B
  instructions / ~3h and still not done, zero errors seen). A FUSE
  cross-audit confirmed no observable-behaviour bugs. Full pass would need
  PyPy or an overnight run.
- **3 undocumented-flag simplifications** (don't affect real software; marked
  with `# NOTE:` in code): SCF/CCF X/Y sourced from A (no `Q` register);
  BIT b,(HL) X/Y from `(HL+1)>>8` instead of MEMPTR; EI enables interrupts
  immediately (no 1-instruction delay).
- **Block instructions run one iteration per step()** (LDIR/CPIR/INIR/OTIR/... rewind
  PC by 2 to repeat, like real hardware) — *changed from the old atomic loop*, which
  overshot the frame by ~1.2M T-states on the 128K boot RAM-clear and desynced audio.
  Now each iteration is correctly billed 21/16 T-states and the frame loop keeps control.
- **Beeper models one bit, not two.** Real hardware sums port 0xFE bit 4 (EAR) *and*
  bit 3 (MIC) into the speaker through different resistors, giving four output levels;
  `ula.py` keeps only bit 4, so we produce two. Engines that use MIC for extra dynamic
  range will sound flatter here than on hardware. No game tested so far uses MIC, so
  this is theoretical for now rather than an observed problem.
- **Timing** is functional, not cycle-accurate: contention is modelled/tested
  but not applied to every memory access; no per-scanline border effects.
- **Not a git repo yet** (user is handling version control separately).

## Performance notes

- ~12 ms to emulate one frame + ~0.5 ms to render → comfortable 50 fps.
- **Run without a debugger.** Under VS Code's debugger (F5) the per-line trace
  hook makes the CPU loop ~6x slower (~13 fps). Use `python main.py` or
  Ctrl+F5 ("Run Without Debugging"). The window title shows a live
  fps / timer / emulate-ms readout.

## Likely next steps

**Milestone 2 (the IDE shell) is substantially done** — the "Full IDE" commit
shipped the dock layout, an in-app editor (Z80 highlighting + breakpoint gutter),
a folder project system + `zxide.json`, sjasmplus settings, a sjasmplus build →
.sna load pipeline, and a v1 debugger (registers + step + breakpoints + live hex).
See DEV_PLAN.md for the phase-by-phase state. The one deferred piece is Phase E,
the visual drag-drop memory management.

**Milestone 3 — hardware & audio** (core work; make the machine complete):

1. **Beeper (1-bit sound)** ✅ *done* — port 0xFE bit 4. Two-layer audio pipeline:
   `zxemu_core/beeper.py` (`Beeper`: timestamped speaker flips → float PCM, duty-
   cycle resample + DC blocker) and `zxemu_ui/audio_output.py` (`AudioOutput`:
   QtMultimedia 16-bit push sink, fails quiet). Machine timestamps flips at the
   frame T-state; controller pushes samples per tick, mutes on pause/debug.
   Sound sources live one-per-file (`beeper.py`, `ay.py`) and are summed by
   `mixer.py` (`SoundMixer`) — the software stand-in for the resistor network that
   does the mixing in hardware. Sources share a three-member contract (`enabled` /
   `end_frame` / `take_samples`) and know nothing about each other.
2. **128K machine + AY-3-8912** ✅ *done* — `Machine128(Machine)` on the existing paging
   abstraction: port 0x7FFD (RAM→slot3, ROM select, screen bank 5/7, paging lock),
   the two bundled 128 ROMs, 70908-T frame. `create_128k_memory` builds the 8-RAM +
   2-ROM pool. Shadow screen via `machine.display_memory()`. 128K `.sna` load added
   (`load_sna_128k`). The **AY-3-8912** (`zxemu_core/ay.py`: 3 tone + noise + 10-shape
   envelope, log amplitude table) mixes into the beeper stream through
   `SoundMixer` (`machine.audio`). Machine model is per-project (`zxide.json` `model`
   field); chosen at New Project, swapped on project open via `MainWindow.set_machine`
   / `controller.set_machine` / `machine_factory.build_machine`. Memory-map pane shows
   bank identities + a live 0x7FFD readout. `project128` sjasmplus template added.
   fuse (E:/github/fuse) was the behavioural reference (reference-only, GPLv2).
3. **TAP support** — *fast (ROM-trap) load done*. `zxemu_core/tape.py` parses `.tap`
   into blocks (`parse_tap`/`TapeBlock`/`TapeDeck`) and `fast_load()` emulates the ROM's
   `LD-BYTES` (0x0556) by delivering a whole block at once. Hooked via a generic
   `Z80.set_trap(pc, handler)` (near-zero-cost: one int compare per step) and
   `Machine._tape_trap`, which guards on a `LD-BYTES` byte signature so it fires on the
   48K ROM and only when the 128K's 48-BASIC ROM (ROM1) is paged — correct for both
   models. UI: a dedicated **Build ▸ Load Tape…** item (beside Load Snapshot…) inserts a
   `.tap` (insert + reset + log; dev then types `LOAD ""`); also on Load-Recent. Fast
   load is always on for now — the core flag `Machine.fast_load_enabled` exists but there
   is deliberately **no UI toggle** yet, because with edge replay deferred "off" would
   just hang the ROM (it would poll for tape pulses that nothing generates); reintroduce
   the toggle when edge replay lands. Verified end-to-end: a real 48K boot + `LOAD ""`
   loads a BASIC program into PROG with no error. **Deferred:** authentic edge-level replay
   (pilot/sync/data pulses on port 0xFE bit 6 → loading stripes + tape sound); the block
   model is the shared foundation for it.

Order: beeper ✅ → 128K+AY ✅ → TAP fast-load ✅ → (optional TAP edge replay) → then
Phase E (visual memory management).

Still-optional backlog: full zexall pass under PyPy; the 3 undocumented-flag
items; disassembly/watchpoint debugger polish.
