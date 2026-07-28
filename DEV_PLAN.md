# zxide — Development Plan

zxide is becoming a **"Unity for ZX Spectrum"**: an IDE built around a from-scratch
pure-Python Z80 core. This document is the plan for all of it — what each milestone was,
what shipped, and the architecture decisions behind them, so intent survives between work
sessions. `dev-support/STATUS.md` is the companion: session-by-session narrative and
handoff notes.

**Where things stand:** Milestones 1–4 are done (emulator core → IDE shell + debugger →
hardware & audio → asset workflow), and Milestone 3's last deferred piece — **tape edge
replay** — has landed too, so M3 is complete. Since then the emulator has grown a third
machine: **Pentagon 128 with a Beta 128 interface, TR-DOS, and `.trd`/`.scl` disks**, which
has its own design document — see **[TRDOS.md](TRDOS.md)**, not repeated here.

The milestone sections below are kept as written, with ✅ marks and follow-up notes added as
work landed, because *why* something was sequenced the way it was outlives the sequencing.
**Next up** is Milestone 5, Visual Logic. The memory-dumper (1b) is done -- see that
section and `dev-support/STATUS.md`.

The raw original vision notes are preserved verbatim at the end ("Appendix: original vision").

---

## The shape of the IDE

A dockable, rearrangeable shell, Visual-Studio-style. A `File` menu owns project entry
(New / Open Project / Open Folder / Recent); the emulator carries its own control strip.

```
┌────────────────────────────────────────────────────────────────────┐
│ File  View  Build  Debug  Help                              (menu)  │
├──────────┬─────────────────────────────────┬───────────────────────┤
│ PROJECT  │  main.asm │ notes.txt   (tabs)  │  ▶ ⏸ ⏭ ⭮   EMULATOR  │
│ ▾ Source │                                 │  ┌─────────────────┐  │
│  main.asm│        EDITOR (central,         │  │  screen (48K)   │  │
│ ▾ Assets │        multi-view / split)      │  └─────────────────┘  │
│  hero.bmp│                                 ├───────────────────────┤
│  map.bin │                                 │  MEMORY CELLS (hex)   │
│  song.pt3│                                 │  [Memory|Output|Disasm]│
│          ├─────────────────────────────────┼───────────────────────┤
│          │  INSPECTOR (floatable)          │  REGISTERS / FLAGS    │
│          │                                 ├───────────────────────┤
│          │                                 │  MEMORY MAP  [Des|Dbg]│
├──────────┴─────────────────────────────────┴───────────────────────┤
│  50 fps | timer 100Hz | emulate 12ms/frame             (status bar) │
└────────────────────────────────────────────────────────────────────┘
```

Left = code work · Center = editor · Right = the running machine. See the live mockup for
proportions and interactions.

## Window & docking model

Built on stock Qt `QMainWindow` + `QDockWidget` — no third-party docking library
(evaluated the Qt Advanced Docking System / PyQtAds for full VS-style floating + auto-hide
pins, but the model below needs no extra dependency, and the core stays pure Python).

- **Editor = the central widget** — the fixed anchor everything docks around; being central
  it is inherently non-floatable. It is a **multi-view split area** (nested `QSplitter`s of
  tab groups) so files can sit side-by-side, VSCode-style (ship single-pane first, enable
  splitting once open/edit/save + Z80 highlighting + the breakpoint gutter work). Two views
  of one file share a single `QTextDocument` so edits and debugger markers stay in sync.
- **Project tree = a locked dock** on the left (movable/floatable features off) — always
  where you expect it.
- **Every other panel is a floatable `QDockWidget`** — emulator, memory cells (hex),
  registers/flags, memory map, inspector, output — so users can drag them, **tab them
  together** (drop one onto another), float them as windows, or hide them (each dock gives a
  View-menu toggle for free).
- **Layout persistence & presets:** `saveState()`/`restoreState()` serialise the whole
  arrangement; named presets give us the **Design** and **Debug** workspaces (Design
  foregrounds the memory map + inspector + assets; Debug foregrounds registers +
  disassembly + memory).
- **Emulator** keeps its own control strip (Run/Pause/Step/Reset) and scales responsively
  inside whatever dock size it's given.
- Trade-off accepted vs. full Visual Studio: no auto-hide "pushpin" (could adopt PyQtAds
  later if wanted).

---

## Load-bearing decision: memory is modeled as banks

The core is already paging-ready: `Memory` is four 16K slots, each backed by a swappable
`Bank`, with a `page(slot, bank)` hook (`zxemu_core/memory.py`). 48K wires it statically
(1 ROM + 3 RAM); 128K becomes a bank *pool* paged via port 0x7FFD. The UI must mirror this
**from day one**, even while we are 48K-only:

- **Model memory as banks (16K each), not a flat 64K array.** The 64K address space is a
  *projection* — whichever banks are currently paged into slots 0–3.
- The memory panel offers two views:
  - **"As the CPU sees it"** — the live 64K window (what PC/SP point at, what the ULA reads).
    The debugging default.
  - **"By bank"** — every bank (ROM0/1, RAM0–7), including ones *not* currently mapped in, so
    a paged-out bank is still inspectable and editable.
- **Assets and addresses are identified as `(bank, offset)`, not a bare 16-bit address**, so
  placement survives paging on 128K. On 48K this degenerates to the fixed map — nothing lost.
- The memory view surfaces the **current paging state** (the 0x7FFD value / which bank sits
  where).

The payoff: 128K becomes a *data* change, not a UI rewrite, and it costs essentially nothing
now because 48K is the trivial case.

---

## The memory view: two modes, one widget

A single bank-oriented widget with a **Design ⇄ Debug** toggle:

- **Design (before build)** — *where do assets live?* Drag-drop an asset onto a
  `(bank, offset)`, or hit **auto-locate** to place it in free space; this generates the
  `ORG` / `incbin` directives (or a memory manifest) the assembler consumes.
- **Debug (at run-time)** — *what is memory doing right now?* Live values, PC/SP markers,
  edit-a-byte, watch the screen bank change. The visual map is the overview you click into
  for hex detail.

---

## The debugger track

Cheap to build, because the core already exposes the pieces:

- `cpu.step()` runs exactly one instruction and returns its T-states → **single-step is
  nearly free**.
- `cpu.regs` holds every register (PC, SP, AF, BC/DE/HL + primes, IX, IY, I, R, IM) → a
  **registers/flags panel** is a read-out.
- `memory.read_byte` / `write_byte` → a **live, editable hex/memory view**.
- The **one real core addition** is a *debug run mode*: step instruction-by-instruction and
  check breakpoints (halt when `PC == bp`), instead of the fast atomic `run_frame()`. So the
  emulator controller carries two modes — **normal** (fast, frame-at-a-time) and **debug**
  (slower, can stop mid-frame).

v1 debugger minimum-viable = **registers + single-step + live memory view**; breakpoints,
disassembly, and watchpoints follow.

---

## Milestone 2 roadmap (phased)

Milestone 2 (the IDE shell) is **substantially complete** — the "Full IDE" commit landed
Phases A–D plus the editor and debugger tracks. What remains of the original plan is the
visual-memory centerpiece (Phase E), now deferred behind a new **Milestone 3: hardware &
audio** (128K, AY, beeper, TAP) — see below.

- **Phase A — IDE shell layout** ✅ *done*: the dockable `QMainWindow` per the **Window &
  docking model** above — editor central, Project a locked left dock, and emulator /
  memory-cells / registers / memory-map / inspector / output as floatable docks; File / View /
  Build menus; layout save/restore. The frame pump lives in an `EmulatorController`
  (run/pause/reset/step + breakpoints, `frame_ready` / `status_changed` / `breakpoint_hit`
  signals); the emulator has its own control strip and the fps readout is in the status bar.
- **Editor track** ✅ *done* *(supersedes "no built-in editor")*: an in-app multi-tab text
  editor (`editor.py`), Z80 syntax highlighting (`z80_highlighter.py`), a breakpoint gutter,
  and an execution-line marker that tracks PC. Doubles as the debugger's source view.
- **Phase B — Project & asset system** ✅ *core done*: a folder-based project with a
  `zxide.json` manifest (`project.py`), a starter `main.asm` template, and the left tree bound
  to the real folder with New File / New Folder. *Remaining:* first-class **asset import**
  (bmp / binary / pt3 / beeper sfx) — folds into Phase E.
- **Phase C — External tools** ✅ *done*: sjasmplus auto-detected on `PATH` (overridable) via
  app `Settings` + a `SettingsDialog`; per-project build args in the manifest. (VS-Code "open
  in external editor" not wired — the in-app editor made it optional, as planned.)
- **Phase D — Build pipeline** ✅ *done*: `builder.py` shells out to sjasmplus, streams output
  to the Output console, and on success loads the emitted **.sna** (`zxemu_core/snapshot.py`)
  and runs. Source-level debug info (`sld.py` + `zxemu_core/disassembler.py`) maps source
  lines ⇆ addresses for breakpoints. *Later formats:* .szx / .tap / raw binary.
- **Debugger track** ✅ *v1 done*: registers/flags panel, live hex memory view, **breakpoints**
  (Build & Debug = F5 honours them; Build & Run = Ctrl+F5 ignores them) with the execution line
  highlighted in the editor, and **Step Into (F11) / Step Over (F10) / Step Out (Shift+F11)** —
  step-over runs CALLs, RSTs and repeating block ops (LDIR/...) to completion; step-out runs to
  the current subroutine's RET. Both honour breakpoints hit inside, and share one
  `_run_until` engine. A **live disassembly panel** (`disassembly_view.py`, own Disassembly menu)
  decodes around PC as you step. **Watchpoints** (own Watch menu) pause on a memory
  value changing or on IN/OUT of a port — ports by true interception (the CPU's io hooks
  are swapped, so the fast path is untouched when unused), memory by value comparison in
  the debug loop rather than by instrumenting the emulator's hottest methods.
  A **call stack** panel infers the caller chain from raw stack contents (the Z80 records
  no frames), **conditional breakpoints** (`debug_expr.py`) gate a stop on an expression,
  **ROM routine names** (`rom_symbols.py`) annotate disassembly and call stack, and the
  registers panel carries a **T-state read-out** (frame position, cost of the last step).
  Memory watchpoints cover **reads as well as writes** via an instrumented `Memory`
  subclass swapped in only while watches exist. **Run to Cursor / Run to Address**
  (one-shot breakpoints), plus **editing**: poke a byte in the Memory panel, click a
  register to set it. The **RE toolkit** landed too (`analysis.py` + `analysis_view.py`,
  own Reversing menu): memory search, cross-references, a coverage map, and a bounded
  execution trace; plus a **symbol database** — `sld.py` now reads the SLD's label
  records, so your own names appear in the disassembly and Go-to-Label works.
- **Phase E — Visual memory management** ⏸ *deferred* *(the centerpiece)*: the bank-oriented
  memory map (`memory_map_view.py`) and hex cells (`memory_cells_view.py`) exist as debug
  read-outs; the **drag-drop asset placement + auto-locate** design step (generating
  `ORG` / `incbin`) is not built yet. Picked up after Milestone 3.

---

## Milestone 3 roadmap: hardware & audio ✅ *(complete)*

The next push makes the emulated machine *complete* — sound, the 128K model, and tape
loading — before returning to the Phase-E visual tooling. All of this is **core** work
(`zxemu_core/`), UI-agnostic, with thin UI hooks. Chosen order and why:

- **1. Beeper (1-bit sound)** ✅ *done* — port `0xFE` bit 4 drives the speaker. Establishes
  the **audio output pipeline**, built in two layers: `zxemu_core/beeper.py` (`Beeper`, a
  UI-agnostic stage that resamples timestamped 1-bit speaker flips → float PCM via time-
  weighted duty-cycle averaging + a DC blocker so held levels fall silent), and
  `zxemu_ui/audio_output.py` (`AudioOutput`, a QtMultimedia push-mode 16-bit sink that fails
  quiet and drops-rather-than-lags). The `Machine` timestamps each speaker flip at its frame
  T-state and calls `beeper.end_frame()`; the `EmulatorController` pushes samples each tick
  and mutes during pause/debug. Audio is opt-in (`beeper.enabled`) so tests/headless pay
  nothing. **This is the stream the AY mixes into.**
- **2. 128K machine + AY-3-8912** ✅ *done* — `Machine128(Machine)` on the existing paging
  abstraction: port `0x7FFD` (RAM bank→slot 3, ROM select, screen bank 5/7, paging lock),
  the two bundled 128 ROMs, the 70908-T frame. `create_128k_memory` builds the 8-RAM + 2-ROM
  pool; shadow screen via `machine.display_memory()`; 128K `.sna` loading via `load_sna_128k`.
  The **AY-3-8912** (`zxemu_core/ay.py`: 3 tone gens, 17-bit noise LFSR, 10-shape envelope,
  logarithmic amplitude table, timestamp-then-render like the beeper) mixes into the beeper
  stream through a new `SoundMixer` exposed as `machine.audio`. Machine model is per-project
  (`zxide.json` `model`), chosen at New Project and swapped **on project open** via
  `MainWindow.set_machine`/`EmulatorController.set_machine`/`machine_factory.build_machine`.
  The memory-map pane shows per-slot bank identity + a live `0x7FFD` readout; a `project128`
  sjasmplus template (`device zxspectrum128`, demonstrates paging + AY) was added. All
  behaviours cross-checked against fuse (E:/github/fuse) as a **reference only** (GPLv2,
  independent reimplementation — no code copied), the same policy used for the CPU.
- **3. TAP support** ✅ *fast load done* — `.tap` images load instantly
  by intercepting the ROM loader (`zxemu_core/storage/tape.py` + `Machine._tape_trap`).
  The trap sits on **`0x0562`, not `LD-BYTES`'s entry at `0x0556`** — that is the routine's
  first tape *sample*, past the preamble, and it is where multi-part game loaders `CALL` in
  after doing the preamble's work themselves. A trap on `0x0556` catches only BASIC's
  `LOAD ""` and leaves such loaders spinning in the ROM's edge-sampling loop forever, waiting
  for pulses that fast loading never generates (Aliens: Neoplasma II was the case that
  exposed this). The price of the later address is that the wanted flag byte and the
  LOAD/VERIFY carry are in the **shadow `AF'`** (moved there by the preamble's `ex af,af'`),
  which is what `fast_load` reads.
- **4. Edge-level replay** ✅ *done — this completes Milestone 3* (`zxemu_core/storage/pulse.py`).
  The tape is turned back into the pulse train a real ULA samples on port `0xFE` bit 6:
  pilot, sync pair, two pulses per bit, pause. Three things follow from it, and only the
  first was the stated goal:
  * **turbo loaders load.** Speedlock and its imitators never call the ROM routine, so no
    trap can ever serve them; they bit-bang their own sampling loop and want real pulses at
    the real speed. That is why the TZX parser now *keeps* the per-block timings it used to
    discard, and keeps the dataless entries (pure tone `0x12`, pulse sequence `0x13`, pause
    `0x20`) in running order — a `0x12` tone in front of a `0x14` "pure data" block is one
    load split across two container entries, and dropping the tone loses the load.
  * **the loading stripes come back for free.** Nobody draws them: the loader is OUT-ing to
    the border between samples, and once it is genuinely running you see what it does.
  * **the tape is audible**, because the EAR input is summed into the speaker on real
    hardware (`Machine._refresh_speaker` ORs the two 1-bit sources).

  Two design decisions worth keeping:
  * **One play head, two loaders.** `TapeDeck.index` is shared between fast loading and edge
    replay, because a commercial multi-part tape typically starts under the ROM loader and
    hands over to its own turbo loader partway through. Separate heads would disagree.
  * **The motor is not free-running.** A real cassette spools whether or not the Spectrum is
    listening, and reproducing that would be actively wrong here: you spend seconds typing
    `LOAD ""`, and a multi-load game spends *minutes* playing part one before asking for part
    two — both would eat the rest of the tape. So the motor starts when the machine is
    plainly sampling (≥200 reads of port `0xFE` in one frame, against a few dozen for a
    keyboard poll) and stops at the pause ending each block, which is both where a person
    would have hit stop and what the TZX spec means by "pause". Play/Stop/Rewind override it.
    It stops only at a pause with a *duration* — never merely at an item boundary, because a
    bare `0x12` tone runs straight into the block it introduces and a gap there lands in the
    window the loader is hunting for sync in.

  UI: **Load ▸ Tape Deck** — Fast Load (on by default), Tape Sound, Play/Stop/Rewind/Eject.
  Fast Load now has a real "off" position, which is why it was deliberately absent before.
  Verified end to end by `tests/integration/test_edge_replay.py`: the real 48K ROM decodes a
  block with the trap disabled, taking ~105 frames — i.e. at genuine tape speed. Against real
  tapes, **1942 loads completely** from a cold boot and `LOAD ""`; **Speedlock 4 (Renegade)
  plays its whole tape but does not yet come up**, which is the next thing to chase.

*Deferred to Milestone 4:* Phase E visual memory management (drag-drop asset placement +
auto-locate + asset import), disassembly/watchpoint debugger polish, .szx/.pt3 playback.

Rough order: **beeper → 128K+AY → TAP → edge replay**, with Phase E taken in between.

---

## Future directions (the full backlog)

The agreed roadmap of where zxide can go after Milestone 3. **★ marks the educational
wins** -- the north star is "a learner can search a name, step through real code, and
understand what the machine is doing." Grouped by theme, not strictly ordered; the
**recommended sequence** is at the end.

### 1. Debugging & reverse-engineering (the RE toolkit)
- **★ Live disassembly panel** -- disassemble around PC as you step; the foundation for
  everything else here (the core `disassembler.py` already exists).
- **★ Annotated ROM source for debugging** -- when PC is in ROM, show the *labelled*
  disassembly (`KEY-SCAN`, `PRINT-A`, `CHAN-OPEN`, ...) from a public ROM map, with
  comments, so stepping through the ROM shows *which routine you're in*. The standout
  educational feature.
- **Symbol / label database** -- labels from the build's SLD + the ROM map + user-defined,
  surfaced everywhere (disasm, memory, breakpoints); go-to-label / go-to-address.
- **Cross-references** -- "what calls this address / reads this byte?" (static scan + trace).
- **Execution trace / history** -- a rolling log of executed instructions; step *backwards*.
- **Coverage map** -- highlight which addresses have actually executed.
- **Conditional & data breakpoints / watchpoints** -- break on `A==5`, or on a read/write to
  an address (not only PC).
- **Call-stack view** -- reconstruct the return-address chain.
- **Memory search** -- find bytes / text / patterns; mark regions as code vs data.
- **★ Register/flag tooltips & a T-state (cycle) counter** -- hover a flag to learn what it
  means; show the selected instruction's cycle cost.

### 1b. Memory → sources: turn a running program into a debuggable project ✅ *done*

*Menu home: **Reversing**, alongside the RE toolkit above — the dumper consumes exactly
those results (coverage decides what is code, cross-references supply the labels), so
they belong under one heading rather than as a separate feature.*

Dump a machine's RAM into `.asm` sources plus a `zxide.json`, so an existing program
becomes a project you can build, step through, and annotate. The educational payoff is
large — "here is a game, here is its source, now step through it" is a far better
on-ramp than an empty `main.asm` — and it is the natural consumer of the RE toolkit
above rather than a separate feature.

**The whole difficulty is telling code from data**, which is undecidable statically:
the same bytes are a valid instruction stream *and* a valid bitmap. So don't decide
statically.

- **Coverage is the ground truth.** An address that executed *is* code — observed, not
  inferred. Load the snapshot, run it while recording coverage (play the menu, trigger
  the thing you care about), then dump: executed regions become disassembly, everything
  else stays `db`. The more you exercise, the better the source gets.
- **Degrade gracefully.** A region wrongly left as `db` still assembles to the right
  bytes and still runs — you just have a blob you have not understood yet. So v1 can
  dump *everything* as `db`: correct, useless, and a complete foundation.
- **The invariant that makes it trustworthy: assemble the dump and compare bytes with
  the original memory.** Byte-identical means the source provably represents the
  program. Build this check *first* — it works from day one against an all-`db` dump,
  before any classification exists, and then every promotion of a region from `db` to
  disassembly is individually verifiable by the same test.
- Labels come from cross-references (anything called/jumped to becomes `label_8123:`)
  and `rom_symbols` for ROM targets.

Known traps: skip the ROM (`$0000-$3FFF` is not yours); self-modifying code makes a
mid-run dump differ from a load-time one (dump both and diff); a 128K dump must record
which bank each region came from; 48K of RAM is too much for one file, so split by
region.

**Classifying the leftover blobs** — in cost order, cheapest first, because the early
steps do most of the work:

1. **Where it is copied to.** A block `LDIR`'d to `$4000-$57FF` is a screen bitmap; to
   `$5800-$5AFF`, attributes. That is the hardware memory map, not a guess, and
   cross-references already tell us what loads a pointer to the region.
2. **Render it.** Draw the blob as a 1bpp Spectrum bitmap in the Inspector and a human
   recognises a sprite sheet or a font instantly. The screen renderer already exists;
   pointing it at an arbitrary address is nearly free. Nothing beats eyes here.
3. **Cheap statistics.** Attribute bytes cluster in a narrow range; text is ASCII-ish;
   ZX0-compressed data is high-entropy; a region where many bytes decode to illegal
   opcodes is not code.
4. **ML, last.** Its real niche is the residue — "a structured table, 6 bytes per entry,
   but of what?" — which is stride/field-regularity detection. Smallest slice, and it
   needs labelled examples from already-disassembled games to train on.

**The dump should be *runnable*, not just readable** — it is a snapshot, expressed as
assembly. That means it must carry what a snapshot carries: not only RAM but the CPU
state — PC, SP, AF/BC/DE/HL and their shadows, IX, IY, I, R, the interrupt mode and
IFF, the border, and on a 128K the `$7FFD` latch.

That creates one genuinely awkward problem: **you cannot restore registers without
using registers.** It needs a small stub that sets SP, pushes the saved values, pops
them into place and ends with `RET` — which is precisely how `.sna` itself works, with
PC left on the stack for that final `RET` to jump to. So the assembly can mirror the
format it came from.

But the stub has to *live* somewhere, and the dump has already claimed every byte of
RAM. That is the one place the output cannot be byte-faithful. Usual homes: the printer
buffer at `$5B00` (256 bytes, almost nothing uses it) or screen memory, if the program
redraws it on entry anyway.

**So emit two artefacts, not one** — otherwise the correctness invariant gets littered
with "except these twelve bytes":

  * a **faithful dump** — pure `db`/code, no stub, byte-identical to the original. This
    is what the round-trip test checks, and it stays exact.
  * a **runnable project** — the same data, with the snapshot written by a Lua block
    in the generated source so no restore code is injected into the program. This
    is what you build and step through, and it gets its *own* exact test: build it,
    load the resulting `.sna`, and compare the emulator's full state — registers
    included — against the original snapshot's.

Two tests, each precise about its own thing, instead of one test with excuses.

Note the symmetry with Phase E: that places assets *into* memory, this pulls them
*out*. Both need the same "what lives where" model, so they should share it.

### 2. Tape & snapshot formats
- **TAP loading** -- ROM-trap fast load ✅ (covers BASIC `LOAD ""` *and* loaders that call the
  sampling entry `0x0562` directly). **Edge replay** ✅ (`zxemu_core/storage/pulse.py`) --
  turbo/custom-timed loaders, plus the loading stripes and tape sound. Closed Milestone 3.
- **TZX** ✅ *loading* (`zxemu_core/storage/tzx.py`) -- the container is walked in full and
  everything audible is kept **in running order**: data blocks (`0x10` standard, `0x11` turbo,
  `0x14` pure data) *with their own pulse timings*, plus the dataless `0x12` tone, `0x13` pulse
  sequence and `0x20` pause. The timings used to be discarded, which was safe only while fast
  loading was the sole loader; they are exactly what a turbo loader times against, and the
  dataless entries matter because a `0x12` tone in front of a `0x14` block is one load split
  across two entries. Everything else (groups, loops, jumps, menus, credits) is reported in the
  Output rather than silently dropped, and an unknown block ID stops the walk instead of
  inventing blocks. Re-validated across the local library: 20/20 `.tzx` and 8/8 `.tap` parse;
  4 of the 20 use genuinely non-ROM bit timings (one is a Speedlock 4 release), and 35 blocks
  across the set are `0x14` pure data with no pilot of their own — those depend entirely on
  the preceding `0x12` tone, which is precisely what used to be thrown away.
- **More snapshots** -- `.z80` ✅ *loading* (`zxemu_core/storage/z80.py`: v1/v2/v3, 48K and
  128K, RLE-compressed pages, border/AY/paging restored). Still open: `.szx`, and **saving**
  in any format -- nothing in zxide writes machine state yet.
- **Tape-deck UI** ✅ *partly* -- Load ▸ Tape Deck has Fast Load, Tape Sound,
  Play / Stop / Rewind / Eject. A visible **block list** with the play head marked is
  still open, and would be the natural home for per-block timing detail.

### 3. Visual memory management (Phase E -- the "Unity" centerpiece)
Superseded by the detailed **Milestone 4: Asset workflow (Phase E)** section below --
this backlog line is kept only as an index pointer.

### 4. Sound & hardware completeness
- AY **stereo** (ACB/ABC), and an **AY register/scope panel** to watch the chip live. ★
- **128K RAM disk**.
- **PT3 / beeper-SFX playback** for imported audio assets.
- **Kempston Mouse** ✅ *done* -- `zxemu_core/mouse.py`: a buttons byte and two
  free-running X/Y counters, with the interface's real four-line address decode rather
  than the three addresses the manuals quote (so aliased reads reach it, as on hardware).
  Model ▸ Kempston Mouse fits it, off by default and persisted; clicking the emulator
  grabs the pointer and Esc gives it back. **Off by default is load-bearing**, twice
  over: software probes these ports to decide whether a mouse exists, and the decode is
  greedy enough (any port with A0 set and A5 clear) to sit on top of its neighbours --
  0x1F, the Kempston *joystick* port, included. That collision is authentic; the Beta
  128's ports are decoded ahead of it so a fitted mouse can never break disks.
- **Kempston Joystick** ✅ *done* -- `zxemu_core/joystick.py`: five **active-high** switches
  in one byte at port 0x1F (bits 0-4 = right/left/down/up/fire), decoded on A5/A6/A7 clear.
  Active high is the trap: an *unfitted* port reads 0xFF from the undriven bus, which to a
  game is every direction and fire held at once. Driven from the arrow keys with Ctrl as
  fire, and those keys stop reaching the Spectrum keyboard while it is fitted (feeding both
  would have a game see each nudge twice, since the arrows are CAPS SHIFT + 5/6/7/8).
  **Mutually exclusive with the mouse**, in the menu and on the machine — they share 0x1F.
- Both Kempston items now live under **Model**, not View: what is plugged into the emulated
  Spectrum is the same question as which Spectrum it is, whereas View is about how the IDE
  looks and Settings is about *your* PC. Fitting one logs a line saying software checks at
  startup, so a running game needs a reset before it notices.
- **Gamepad input** for the joystick ✅ *done* -- `zxemu_ui/gamepad.py`. A USB pad polled
  once per controller tick, before the frames that tick will run, so the switches a frame
  reads are the ones held when it began. SDL reports buttons only by index, so indices 0/1
  become the two fires and 8/9 (where NES-style pads put Select/Start) become A and START,
  with anything unrecognised falling back to fire so an unfamiliar pad is never mute. D-pads
  are accepted as either axes or a hat, since pads disagree about which they are.
  **pygame/SDL2 is a shipped dependency** — PyQt5 has no QtGamepad and XInput sees only
  Xbox-protocol devices, not the plain-HID USB NES clones. Every failure is survivable and
  silent: no pad, no SDL backend, and the arrow keys still play the game.
- **Extended (8-bit) Kempston** ✅ *done*, following the **ZX Spectrum Next** — chosen over
  ZX Evolution's because the latter is redefinable in software, so there is no fixed layout
  to be faithful to. The Next's is the Mega Drive pad's: bit 7 START, 6 A, 5 C, 4 B, 3-0
  U/D/L/R. Traced to the Next's own VHDL through the local jnext checkout
  (`zxnext.vhd:3441-3442` for the layout, `:3478-3479` for the masking; the reference pack
  is `E:\github\zxnext-ref`, section 9.4).
  The decisive detail, and the thing that would be wrong in a from-memory implementation:
  **the Next's two modes differ only in a mask.** Kempston mode passes bits 5:0 and forces
  7:6 to zero; MD 3-button mode passes the whole byte. So a second fire button works in
  plain Kempston mode while A and START need the wider one, and `Model ▸ 8-bit extended
  (MD 3-button)` is that mask, not a separate device or port. Original five-switch hardware
  reads identically in either mode, which is why no third mode exists.
- *(Skipping +2/+3 machine variants -- little used today.)*

### 5. Editor & project
- **Find in Project (Ctrl+F)** ✅ -- `zxemu_ui/workspace/search.py` (Qt-free) searches every
  editable text file, skipping assets, build output and generated files; results land in the
  Output panel as **clickable lines** that open the file at the line. Project-wide rather than
  within-file because a Z80 project is a dozen small includes, so "where is this label used"
  is nearly always a question about the project.
- **Go to Line (Ctrl+G)** ✅ -- bounded by the open file's own length.
- **Show in Explorer** ✅ -- project-tree context menu; `zxemu_ui/system_open.py` builds the
  argv per platform (Windows selects the file, macOS reveals it, Linux opens its folder).
- **Output panel Clear** ✅ -- on the console's **right-click menu**, beside Copy/Select All,
  not a button: a rare action shouldn't cost a permanent row of height in the one panel whose
  job is showing as many lines as possible. Empties the text *and* the link map together.
- **Build-error jump** -- click an sjasmplus error -> jump to the source line. *Now a small
  job:* the clickable-line plumbing (`OutputConsole.append_link`) already exists, so this is
  parsing `--fullpath` error output into (path, line) pairs and logging them as links.
- **Symbol navigation** in the editor (go-to-definition for labels).
- **★ Lua syntax support** ✅ *done* -- sjasmplus embeds a Lua interpreter (`LUA ... ENDLUA`
  blocks, the `sj.` emit/label API) for compile-time metaprogramming, and zxide's own memory
  dumper generates such a block to write the `.sna`. `z80_highlighter.py` is now a two-state
  machine: assembly rules outside the block, Lua rules inside, the state carried between
  lines with `setCurrentBlockState` -- the only way a line-at-a-time `QSyntaxHighlighter` can
  know it is halfway through something that began earlier. `LUA` and `ENDLUA` themselves
  colour as directives, because they are the assembler's syntax, not Lua's.
  Standalone `.lua` files are deliberately **not** supported: the Lua that matters here lives
  inside `.asm`, and nothing in zxide reads or writes a `.lua` file.
- **Multiple build targets / configs**; **.szx or .tap as a build output**.
- **Richer project templates** (a game skeleton, an AY music demo).

### 6. Polish / fixes
- **Emulator fullscreen** ✅ *done* -- `Alt+Enter` gives the emulator the whole display, `Esc`
  returns to the IDE (View ▸ Emulator fullscreen; both keys are free because a Spectrum has
  neither). `panels/fullscreen_stage.py` **lends** the existing `EmulatorStage` to a bare
  black window rather than building a second renderer: reparenting a live widget keeps the
  same `EmulatorView` object, so its signal connections, the Spectrum's key matrix and any
  held keys survive, and going fullscreen mid-game does not drop a frame. The one invariant
  is that every exit route ends in that window closing, so a single `closing` handler puts
  the stage back -- including when the IDE itself is closed while fullscreen.
- **Runtime swap-pause bug** -- opening a 128K project *while running* pauses the controller
  without resuming (startup swap is fine; only a live swap is affected).
- Per-scanline **border effects** and tighter **contention** (a cycle-accuracy pass).
- Optional **zexall under PyPy** as a conformance gate.

### 7. Extended machines: ZX Spectrum Next and TS-Conf — *investigated, not scheduled*

Two full hardware reference packs and staged implementation plans exist, produced by a
separate investigation and **verified against this codebase**:

- `E:\github\zxnext-ref` — ZX Spectrum Next (TBBlue), distilled from the **jnext** emulator.
- `E:\github\tsconf-ref` — TS-Conf (ZX-Evolution/Pentevo), distilled from `tslabs/zx-evo`.

Each pack holds `spec.md`, a machine-readable `registers.json` (**meant to be loaded at
runtime as a decode table, not transcribed**), a `vm-guide.md`, and an
`IMPLEMENTATION_PLAN.md` with zxide `file:line` anchors. Both plans are marked *shelved*.

**Why this is recorded rather than started.** Two reasons, and the second is the real one.

*Scale.* The Next plan is 10 stages, TS-Conf 6, several rated Large; between them they are
bigger than everything zxide has built so far, and they compete for attention with
**Milestone 5 (Visual Logic)** — the part that makes this an IDE rather than an emulator.
Worse, doing the Next *adds a second code-generation target* to Visual Logic.

*Nostalgia — the user's objection, and the decisive one.* **"Next has some potential in some
way, but nostalgia is not with it."** The Next is a *new* machine in a Spectrum's shape:
2017, not 1982. Nobody's childhood is on it. The machines people are nostalgic for are the
ones zxide already emulates — 48K, 128K, Pentagon. Supporting the Next would make zxide a
better tool for a scene already served by CSpect and ZEsarUX, at the cost of attention to
the thing only zxide is trying to be. That is a positioning argument, not a technical one,
and it outranks every row in the tables below. **Recorded here so it is not re-litigated:
the answer was "no" for a good reason, not for lack of a plan.**

**What was independently verified in our code** (2026-07-25), because a plan's value is
entirely in whether its claims are true:

| claim | anchor | outcome |
|---|---|---|
| `ED_TABLE` is module-global with a silent-NOP default, so Z80N needs a per-instance table | `cpu/instructions/_dispatch.py:29-31,36`, `cpu/z80.py:176-178` | accurate |
| IM2 reads the vector with a hardcoded low byte; a vectored interrupt fabric needs a `bus_value` seam | `cpu/z80.py:128` | accurate |
| `install_watch` swaps `__class__` to `WatchedMemory` *unconditionally* | `memory.py:110-137` | accurate, and a real trap |
| `PAGED_MODELS` is the highest-surprise touchpoint for a new paging scheme | `memlayout.py:36,49,57` | accurate |

The `install_watch` finding is worth keeping even if neither machine is ever built. It
saves `_unwatched_class` to restore *from*, but hardcodes the class it swaps *to*, and
`WatchedMemory` calls `Memory.read_byte(self, …)` directly. **Any** future `Memory`
subclass therefore loses its overrides the instant a watchpoint is set — and the symptom
would be "setting a watchpoint breaks paging", which nobody would connect to watchpoints.
It is not a live bug (nothing else subclasses `Memory` today); it is a trap already laid.

**If this is ever revived, the cheap part is worth doing on its own.** Both plans share a
Stage 0 of small, self-contained changes that have value with or without a new machine:

1. `Machine._finish_frame()` — factoring `run_frame`'s tail so anything that executes a
   frame differently still reaches the seam. ✅ **already done**, as `Machine.end_frame()`
   (see §6 and the audio fix it came from) — arrived at independently, which is mild
   evidence the rest of the analysis is sound.
2. `WATCHED_CLASS` as a per-class attribute (above).
3. `maskable_interrupt(bus_value=0xFF)`.
4. A `Machine.framebuffer() -> FrameBuffer | None` contract, `None` on classic models so
   the existing render path is untouched. Any non-ULA display needs this.

Then **Z80N alone** (Next Stage 1) is the natural next stopping point if we go that way:
~30 ED opcodes, no video work, and sjasmplus already assembles them — it would make zxide a
Next *assembler and debugger* without emulating a Next. Small, shippable, reversible.

**Two asymmetries to weigh when deciding**, neither of which is about the hardware:

- **ROMs.** TS-Conf's `zxevo.rom` is redistributable, so it would boot out of the box like
  everything else here. The Next's cannot ship; every Next test would be skip-gated on
  user-supplied files, which is a real dent in "clone it and it runs".
- **Oracle.** jnext runs headless with a pinned clock and golden PNGs — a differential
  oracle is what makes this class of work tractable. Unreal needs an MSVC build. Strongly
  favours the Next.

Also: jnext is itself AI-generated (its own README says so, and the pack repeats it), so
Next facts are a distillation *of a distillation*, carrying VHDL citations that were never
mechanically checked. TS-Conf's come from a maintained register spreadsheet. Both packs
state their own weak points, which is the main reason to trust either.

**Performance, stated once so it is never quietly assumed away:** neither machine can run
at speed in pure Python — the Next's 28MHz turbo especially. Both plans accept this and
isolate two hot seams for an optional native path. If these are built, they are built to
*develop for* those machines, not to play them at full speed.

### Recommended sequence

*The original sequence — TAP, then the RE/debugging toolkit, then Milestone 4 / Phase E —
is **complete**, along with tape edge replay, Pentagon/TR-DOS/disks and the memory dumper.
What follows is the sequence from here.*

The foundation is done, so the question is no longer "what is missing from the emulator"
but **"what makes this an IDE rather than an emulator"**. In that light:

1. **The two dumper follow-ons** (§1b) -- split a dump into files by what the code *does*,
   and recognise pictures/music inside data blobs. Small, and they extend something that
   already works rather than opening a front.
2. **Milestone 5: Visual Logic** -- the first piece of the actual "Unity" layer, and the
   thing nothing else in the backlog substitutes for.
3. **Extended machines** (§7) -- deliberately last, and currently **declined**. Largest item
   here by a wide margin, it would *add a target* to Visual Logic's code generation, and
   the nostalgia is not with those machines. Reference packs and verified plans exist if
   that judgement ever changes.

The through-line is unchanged from the start: the RE toolkit is where the *teaching*
happens, Phase E is where zxide feels like "Unity for the Spectrum", and Visual Logic is
where it stops being an assembler IDE.

---

## Milestone 4: Asset workflow (Phase E)

Today there is **zero asset tooling**: no importers, no placement UI, no build-time asset
codegen. The memory map is a read-only debug view (PC/SP markers only); the project
manifest has no `assets` concept. This milestone builds the whole pipeline end to end --
import, place, build, preview -- in six steps, each independently testable before the next
begins.

**1. Core, Qt-free asset modules** (`zxemu_core/assets/`, mirrors the `debug/`/`sound/`
package split):
- `manifest.py` -- `AssetKind` enum (`bitmap`, `sprite_sheet`, `sprite_sequence`, `font`,
  `tilemap`, `binary`, `pt3`, `beeper_sfx`) and `AssetEntry` (`id`, `source` -- a path, or
  a list of paths for `sprite_sequence` -- `kind`, `symbol`, `placement`: `"auto"` or
  `{bank, offset}`, plus kind metadata below), with `to_dict`/`from_dict`. `sprite_sheet`,
  `sprite_sequence`, and `font` all produce the same shape -- a `FrameSequence` (ordered
  frames, common `frame_width`/`frame_height`/`frame_stride`, optional mask) -- so
  anything downstream (Inspector preview, Milestone 5's `draw_sprite`) treats them
  identically regardless of import path. There is **no separate "tileset" kind** -- a
  tileset/palette is just a `sprite_sheet`/`sprite_sequence` asset used in a different
  role (see `tilemap`).
- `bmp_convert.py` -- BMP -> Spectrum format:
  - **`bitmap`** (full-screen 256x192) -> 6144-byte bitmap + 768-byte attributes
    (nearest-color match per 8x8 cell against the 8-color normal/bright palette --
    `emulator_view.py`'s RGB tables are the reference, duplicated here since core can't
    import `zxemu_ui`); attribute-clash warnings (>2 colors/cell) returned to the caller.
  - **`sprite_sheet`** -- a BMP holding a grid or strip of equal-sized frames. Explicit
    params (no auto-detection, ambiguous for irregular sheets): `frame_width` (multiple
    of 8), `frame_height` (any), `layout` (`{"grid": {cols, rows}}` or `{"strip": {axis,
    count}}`). Frames pack 1bpp row-major MSB-first, no screen interleaving, all the same
    byte stride so code addresses any frame as `label + frame_index * frame_stride`; a
    frame-count constant is emitted alongside the label.
  - **`sprite_sequence`** (the animation-flip case) -- an ordered list of individual
    same-sized image files, each file *is* one whole frame. Dimensions read off the first
    file and validated identical across the rest; frame order is the list order (natural
    filename sort by default, reorderable). Converts to the identical `FrameSequence`
    shape as `sprite_sheet`, through the same mask path, so both feed one packing routine.
  - **Mask generation is a per-asset toggle** (`generate_mask`, off by default, both
    `sprite_sheet` and `sprite_sequence`): converts a chosen `mask_color` (sampled from
    the source image's own palette) into a paired AND-mask plane per frame, adjacent to
    its pixel data; off emits only the raw bitmap. Toggling later just re-runs the
    converter.
  - **`font`** -- a `FrameSequence` of glyphs, reusing the grid slicer wholesale, with
    `frame_width`/`frame_height` defaulted to 8x8 and no mask (glyphs are OR/XOR-plotted,
    not overlay-masked). The one new bit of metadata is `first_char_code` (default `32`),
    emitted as an `equ` so code indexes a glyph as
    `label + (char_code - first_char_code) * frame_stride`. Two source paths land on the
    same converter: a BMP grid, or a pre-packed raw binary charset (skips slicing, just
    `binary_convert` passthrough plus the same metadata attached).
- `binary_convert.py` -- passthrough with optional length check.
- `tilemap_convert.py` -- **`tilemap`**, the level-layout asset: instead of a full pixel
  bitmap per screen, a grid of small tile-index bytes referencing a tileset (any
  `sprite_sheet`/`sprite_sequence` asset, at whatever tile size it was imported at --
  8x8, 16x16, custom). The actual space win: a 32x24 grid of 8x8 tiles is 768 index bytes
  vs. 6144+768 for a raw bitmap; a 16x16 tileset over the same area is 192 bytes.
  - Metadata: `tileset_symbol` (the "palette" asset's symbol), `map_width`/`map_height`
    (in tiles). A tileset can be shared across levels or dedicated to one -- structurally
    identical either way, just which `AssetEntry` the symbol points at.
  - Source format (v1, hand-authored -- no in-app level editor yet): a plain JSON grid,
    e.g. `{"tileset": "tileset_forest", "width": 32, "height": 24, "tiles": [[0,0,1,2,...],
    ...]}`, indices validated against the tileset's real frame count at convert time. This
    is the one converter needing the full asset registry, not just its own source file.
  - Packing: one byte/tile by default (up to 256 tiles); an optional `pack_nibble` toggle
    (mirrors `generate_mask`) halves this to 4 bits/tile when the tileset has <=16 frames.
  - **Deferred**: importing an existing level-editor format (Tiled's `.tmx`/`.json`). The
    representation above is chosen so that's a straightforward later converter, not a
    restructure.
- `pt3_convert.py` -- passthrough + `PT3` magic-header check (playback stays a separate
  backlog item).
- `beeper_sfx.py` -- v1 text format (`period_tstates,duration_frames` pairs) compiled to a
  sentinel-terminated binary table.
- `registry.py` -- suffix -> converter dispatch, used by both the import UI and the
  build-time regenerator.
- `preview.py` -- `render_frame_rgb(frame_bytes, width, height, attr_byte)`, a
  non-screen-scrambled renderer for standalone frame previews (kept separate from
  `emulator_view.render_screen_rgb`, which assumes live hardware screen layout).
  `render_sheet_rgb(sequence)` tiles every frame into one grid image (fonts, and sprites
  too). `render_tilemap_rgb(tilemap, tileset_sequence)` composites a whole level preview
  by stamping tileset frames into the grid the tilemap specifies.

**2. Free-space / placement model** (`zxemu_core/memlayout.py`, a top-level sibling of
`memory.py` -- not nested under `assets/`, since the future memory-dumper (see "1b" above)
needs the same "what lives where" model):
- `bank_ids_for_model(model)` -- `["rom","ram1","ram2","ram3"]` (48K) vs.
  `["rom0","rom1","ram0".."ram7"]` (128K).
- Reserved-range table per bank (ROM fully reserved; the screen bank reserves its first
  `SCREEN_BYTES` -- reuse the constants already in `memory_map_view.py`).
- `FreeSpaceIndex`: `place(bank, offset, length)`, `free_ranges(bank)`,
  `auto_locate(length, prefer_banks=...)` (first-fit bin packing, RAM before screen-bank
  leftover space, never ROM).
- **Known v1 limitation, stated explicitly**: "free" only excludes hardware-reserved
  ranges and other placed assets -- it does not yet know where the user's own hand-written
  `ORG`'d code lives (the same undecidable-without-execution problem as "1b" above). The
  UI must warn accordingly; a real fix extends `sld.py` to capture the currently-ignored
  `page` column.

**3. Manifest additions** (`zxemu_ui/workspace/project.py`): `"assets": [...]` in
`default_manifest()`; `Project.assets()`, `add_asset(source, kind, symbol=None)`
(auto-derives a sjasmplus-safe label), `set_asset_placement(id, bank, offset)`,
`set_asset_auto(id)`, `remove_asset(id)` -- thin read/write, matching `set_model()`.

**4. Memory Map Design mode** (`zxemu_ui/panels/memory_map_view.py`): one class, a
Design <-> Debug toggle (Debug unchanged; Design draws placed-asset rectangles from
`project.assets()`) plus an Auto-locate button. Drag-drop reuses the project tree's
existing `QFileSystemModel` `text/uri-list` drag data (`setDragEnabled(True)`) --
`MemoryMapView` adds `setAcceptDrops(True)` + drag/drop handlers and a `_hit_test(pos) ->
(bank, offset)` (inverse of `_draw_marker`). Dropping a single `.bmp` prompts a small
dialog to choose `bitmap` vs `sprite_sheet` vs `font`. `sprite_sequence` gets its own
"Import Animation Sequence..." multi-select command on the tree's context menu, since it
doesn't fit a single-file drop.

**5. Build integration** (`zxemu_ui/workspace/asset_build.py` + `builder.py`):
`regenerate_assets_asm(project)` runs each asset's converter (cached under
`.zxide/generated/<symbol>.bin`, keyed by source mtime/hash), resolves `"auto"`
placements via `memlayout`, and emits `assets_generated.asm` (generated/do-not-edit
header; one `ORG`/label/`incbin` per asset -- 48K banks map to fixed addresses, 128K uses
sjasmplus's native `SLOT`/`PAGE` directives). Every `FrameSequence` asset also gets
`equ` constants beside its label (`_FRAME_COUNT`, `_FRAME_STRIDE`, `font`s also
`_FIRST_CHAR`); `tilemap` gets `_WIDTH`/`_HEIGHT` plus a comment naming its
`tileset_symbol`, with tileset assets regenerated before the tilemaps referencing them.
`builder.build()` calls this first; a converter failure (including a bad
`tileset_symbol`) is a normal build-log error, never a crash. New templates bake in
`include "assets_generated.asm"`; existing projects get a one-time idempotent append the
first time an asset is imported.

**6. Inspector integration** (`zxemu_ui/panels/inspector_view.py`): a `set_selection(...)`
entry point wired from the project tree's selection and a new `asset_selected` signal on
`MemoryMapView`. `bitmap` reuses `emulator_view.render_screen_rgb` via a small
`Memory`-shaped adapter; `sprite_sheet`/`sprite_sequence` use `render_frame_rgb` with a
frame-index scrubber; `font` uses `render_sheet_rgb` to show the whole charset at once;
`tilemap` uses `render_tilemap_rgb` plus a field naming (and jumping to) its
`tileset_symbol`. Everything else (`binary`/`pt3`/`beeper_sfx`) gets symbol/size/placement
fields and a per-asset auto-locate action.

**Verification**: unit tests per converter asserting exact byte output for small
fixtures (including `sprite_sheet` grid/strip/mask variants, `sprite_sequence` ordering
and mismatched-size rejection, `font`'s two source paths, and `tilemap`'s packing/
nibble-packing/out-of-range/bad-reference cases); `FreeSpaceIndex` and `Project` manifest
unit tests; one integration test building a project with imported assets through the
real sjasmplus pipeline and diffing the resulting `.sna`; a manual pass in the running
app (drag a bmp onto the Design-mode map, auto-locate, Build & Run, confirm render and
Inspector preview).

**Since delivered, on top of the above -- drawing sprites in zxide, not just importing them:**
- `FrameSequence` gained an optional attribute plane (`has_attrs`): one real Spectrum
  attribute byte (ink/paper/bright) per 8x8 cell, alongside the pixel plane, instead of
  a sprite being plotted in one colour chosen at draw time. `bmp_convert.py`'s
  `generate_attrs` toggle reuses the exact same colour-clash quantization `bitmap`
  already does for the full screen, scoped to each frame.
- A native `.zxspr.json` format (`zxemu_core/assets/native_sprite.py`) for sprites
  *drawn* in zxide rather than imported -- plain pixels+attributes as human-readable
  JSON, no BMP round-trip for data that never had a source image.
  `zxemu_ui/panels/sprite_editor_view.py` is the pixel editor: ink/paper palette rows
  (real ZX colours, normal + bright), a canvas with 8x8 attribute-cell gridlines, and
  the key invariant that makes the "2 colours per cell" hardware limit a consequence of
  the tool rather than a rule you could break -- **every paint action reclaims its
  whole cell's attribute** for whatever ink/paper/bright is currently selected, so
  there is no way to accidentally leave a third colour in a cell. Autosaves on every
  edit, matching the rest of the asset system's "writes straight through" convention.
  "New Sprite Asset…" (project tree context menu) creates a blank one at a chosen
  size (8x8/16x16/custom) and frame count and opens it directly; opening an existing
  `.zxspr.json` from the tree does the same rather than treating it as generic text.
  `asset_build.py` emits an extra `_ATTR_OFFSET` equ for attributed frames (where the
  attribute plane starts within each frame's stride), and Inspector/tilemap/sheet
  previews all render true per-cell colour automatically when `has_attrs` is set.

**Also since delivered -- two follow-ups the live smoke tests surfaced or suggested:**
- **Auto-locate now avoids known hand-written code, best-effort.** The exact collision
  hit twice in testing -- a fresh asset auto-locating to `ram2` offset 0, exactly where
  a template's own `org $8000` begins -- is fixed for the common case. `sld.py` now
  parses the SLD's `page` column, which turns out (checked empirically against real
  sjasmplus output) to be the **slot** index, not a physical 128K bank. Slots 1/2 are
  hardware-fixed on both 48K and 128K (always RAM5/RAM2, never repaged), so tracing
  code there reliably means "this bank, always" -- `asset_build.reserved_code_ranges`
  reads the *previous* build's SLD (if any) and reserves those addresses before
  auto-locating. This converges over builds rather than fixing everything at once
  (there's no way to know where code lands before a first build ever runs -- the same
  undecidable-without-execution problem the memory-dumper backlog item already names),
  and **128K's slot 3 is deliberately left alone**: it can hold any of 8 banks
  depending on runtime paging the SLD has no way to see, so guessing there would be
  false confidence, not a fix. The real, complete fix stays the originally-planned one
  (treating a build's *entire* emitted image as occupied, not just traced instruction
  addresses) -- this is a meaningfully-scoped step toward it, not a replacement.
- **`beeper_sfx` playback preview.** `zxemu_core/sound/beeper_preview.py` renders a
  `beeper_sfx` asset's tone/duration list to PCM via a standalone `Beeper` (no live
  machine needed -- same "one frame at a time" contract the real machine drives it
  with), and the Inspector's new "▶ Play" button pushes the result through a freshly
  sized `AudioOutput`. (Real PT3 preview remains out of scope -- that needs an actual
  tracker player driving the AY chip live, a separate and much larger feature.)
- **A Beeper SFX editor**, since a raw T-state period is not a format anyone can
  hand-author without documentation. Unlike sprites, the existing `.zxsfx` text format
  (renamed from a plain `.sfx` to avoid colliding with other tools' generic SFX files)
  needed no new native format -- `period,duration` pairs were already a fine storage
  shape, just not a friendly *display* one. `zxemu_core/assets/beeper_sfx.py` gained
  `period_to_hz`/`hz_to_period` (period is T-states between speaker flips; frequency is
  `3500000 / (2 * period)`, the Z80 clock) and `format_beeper_sfx` (the inverse of
  `parse_beeper_sfx`). `zxemu_ui/panels/beeper_sfx_editor_view.py` is the editor: rows
  of Hz + frames + a remove button, "+ Tone"/"+ Rest"/"▶ Play", autosaving every edit
  straight to the `.zxsfx` file (same convention as the sprite editor and the rest of
  the asset system). "New Beeper SFX Asset…" (project tree) creates a blank one and
  opens it directly; opening an existing `.zxsfx` does the same.
- **Save Screenshot**, a button on the emulator control strip (next to Run/Pause/Step/
  Reset), saving the current picture two ways at once into a `screenshots/` folder
  (in the open project, or next to the app itself -- the same anchor `layout.json`
  uses -- if none is open): a real `.scr`, the classic Spectrum screen-dump format,
  exactly the 6912 bytes of display memory (`machine.display_memory()`, which already
  picks the right bank on 48K/128K, shadow screen included, so it has no concept of a
  border and never carries one) -- openable by any Spectrum-aware tool; and a `.bmp`,
  a normal viewable image. The `.bmp` is *not* a grab of the emulator widget -- that
  would only capture whatever size the dock happens to be scaling the picture to right
  now -- but `EmulatorView`'s own native 320x256 `QImage` (a new `current_image()`
  accessor), so it's always crisp at the Spectrum's real resolution, border included,
  regardless of window size.

### Polish pass over the asset editors and the project tree

*A round of usability work after living with the above for a while. Two of the decisions
recorded earlier are deliberately reversed here; both entries above are left as written,
because why they were made the first way is worth keeping.*

- **Native sprites are now raw binary, and the extension carries the format.**
  `.zxspr.json` is superseded by six extensions, differing along two axes -- how the frame
  size is known, and whether colour is stored:

  | | pixels + attributes | pixels only |
  |---|---|---|
  | 8x8 frames | `.zx8x8` | `.zx8x8pix` |
  | 16x16 frames | `.zx16x16` | `.zx16x16pix` |
  | any size | `.zxsprite` | `.zxspritepix` |

  The file **is** the bytes the Z80 gets -- pixel plane then attribute plane per frame,
  no container and no encode step at build time. The two fixed sizes carry no header,
  since the extension already says the size and repeating it would be dead weight; the
  arbitrary-size pair opens with **byte 0 = width, byte 1 = height**, which is the only
  place that information could live. Frame *count* isn't stored either -- it follows from
  the file length divided by the stride, keeping every number in the file a number the
  program actually needs. The `…pix` variants exist because a great many sprites are
  coloured by the code that plots them, and for those an attribute plane is bytes of
  nothing; the editor drops to black-and-white when it opens one. `FrameSequence` gained
  a `header` field (kept *out* of `data`, so frame indexing by stride from byte zero still
  works for every source format) and the build emits `_DATA`/`_WIDTH`/`_HEIGHT` equs
  beside the existing `_FRAME_COUNT`/`_FRAME_STRIDE`/`_ATTR_OFFSET`. Old `.zxspr.json`
  files still load and still save as JSON -- zxide does not quietly rewrite, rename, or
  delete a file the user didn't ask it to touch.
- **Drawing still claims the cell -- but the left button toggles.** The "every paint action
  reclaims its whole cell's attribute" invariant above is *kept*; what was wrong with it was
  never the claiming, it was the left-ink/right-paper button scheme around it, under which
  erasing a stray pixel meant first switching the selected colour to whatever that cell's
  paper happened to be. Splitting drawing and colouring into two tools was tried as the fix
  and was the wrong one -- it made the common case (draw a pixel in the colour I picked) two
  actions to save the rare one. So: one tool, no modes. Press decides the stroke's value
  from the pixel under the cursor and the drag paints that one value (so dragging back over
  pixels you just set doesn't undo them), and every paint -- setting *or* clearing -- writes
  the selected ink/paper/bright into that cell. Erasing is clicking a lit pixel. Two escape
  hatches keep that from being restrictive, and neither is a mode, just something the mouse
  does: **right-drag** recolours cells without touching pixels, **alt+click** eyedrops a
  cell's colours back into the palette.
- **The palette now shows which colours are selected**, which it previously did not at all.
  The swatch rows were checkable `QPushButton`s carrying a `background-color` stylesheet,
  and that stylesheet replaced the whole button rendering -- so the *checked* state, the one
  thing indicating the selection, was never drawn. `_PaletteBar` paints the row itself: the
  selected swatch is drawn markedly larger **and** ringed, two signals because one is not
  enough for a palette containing both black and white. The ring goes in the cell's margin,
  never over the colour -- the first attempt drew it inside, and a 2px ring in a small
  swatch swallowed most of it, so selecting black produced a mostly-white square: the
  indicator hiding the one thing it was pointing at. (Found by rendering the panel to a PNG
  and looking at it, not by reading the code.) A `_ColorPreview` tile beside the rows shows
  the ink/paper pair as a cell actually looks, since knowing which two *entries* are picked
  is not the same as seeing what they look like together.
- **The Beeper SFX editor is a piano roll.** The Hz-and-frames spin boxes were honest and
  unusable: an effect is a *shape over time*, and no one hears a shape by reading a column
  of numbers. Time across, pitch up, one row per semitone; drag to paint, right-drag to
  erase. Saving is run-length coding the columns back into `period,duration` entries, which
  is also why a held note draws as one bar. **Columns hold periods, not rows**: loading maps
  a period to the nearest semitone only to decide where to *draw* it, so a table hand-typed
  at some deliberate off-note frequency round-trips exactly and only a repainted column
  snaps to the grid. The file format is unchanged; `beeper_sfx.py` gained the note grid
  (`note_period`/`nearest_semitone`/`note_name`) and the run-length coding
  (`expand_to_frames`/`pack_frames`).

  Getting it *readable* took three passes, all driven by rendering the panel to a PNG rather
  than by reading the code.

  The first two built a musical piano roll -- semitone rows, a piano keyboard down the side,
  pitches snapping to notes -- and it was wrong, in a way only using it revealed: **a beeper
  effect is a swoop or a thud, not a melody**, and quantising a swoop to the chromatic scale
  fights what you are drawing. All of that machinery is gone. Recorded because the mistake is
  a general one: the semitone grid was chosen up front from a menu of options, sounded
  obviously right, and stayed wrong for two rebuilds because each round improved the
  *drawing* without questioning the *model*. `beeper_sfx.py`'s note-grid helpers went with
  it, rather than lingering as tested dead code.

  What it is now: **a bar chart of frequency over time.** Each bar rises from the baseline,
  its height the tone and its width the duration -- drag up for higher, sideways to hold.
  What survived the rewrite, and why:

  - **One column is one video frame, and there is no setting for it.** This one went the
    long way round and the detour is the lesson. A configurable "step" of several frames
    was added because per-frame columns had looked like a wall of slivers; the control was
    then relabelled twice trying to make it comprehensible (`bar: 4 frames`, which had to
    be explained out loud on first reading -- itself the verdict; then `Draw in steps of
    [80 ms]`, with the noun outside the box and a unit anyone can act on). Both were
    answers to the wrong question. **Length already comes from how far you drag**, so the
    step only ever decided the *floor* -- and the right floor is simply the shortest sound
    that exists. The control was deleted, the grid fixed at one frame, and nothing was lost.

    Worth keeping because the failure repeats: the original problem was never the
    granularity, it was that *clicking* produced sliver-sized bars. Fixing the interaction
    (drag for length) dissolved the need for the setting entirely, and two rounds of
    polishing the setting's label had made it look progressively more reasonable while
    leaving it just as unnecessary. A control that needs a good label is worth re-examining
    before it gets one.

    One consequence had to be handled: mouse moves are sampled far more coarsely than one
    report per column, so a quick drag skips whole frames and leaves a comb of gaps. Every
    stroke fills in the frames between the last reported position and this one,
    interpolating the pitch across them, so a fast diagonal drag draws a smooth ramp
    instead of a dotted line.

    A column is 12px, which is deliberately generous -- the shortest possible sound, a
    single 20ms frame, is still a solid block you can see and hit, and that is the whole
    point of drawing this as bars rather than as a line graph. It costs horizontal room (a
    second of audio is 600px) and that is what the scrollbar is for; effects are rarely
    more than a second or two long.
  - **The frequency axis is logarithmic**, one octave per equal step, 32Hz to 4096Hz. A
    linear axis puts everything below 500Hz in the bottom eighth of the panel -- and the low
    end is where thuds, rumbles and engine noises live, so a linear axis makes unusable
    exactly the half an effect most often needs. Seven octaves at 56px each also means the
    whole range fits without vertical scrolling, which deleted the "scroll to the content"
    machinery the piano roll had needed.
  - **The frequency scale and the time ruler are *pinned*** to the viewport, painted at the
    current scroll offset. A header that scrolls away is a label for something you can no
    longer see.
  - **Shift holds the pitch for a stroke.** Frequency is continuous now, so "drag sideways to
    hold the tone" would otherwise produce a row of almost-equal bars -- one entry per
    wobble of the hand -- instead of one held bar. Without shift a diagonal drag sweeps,
    which is the other thing you want to draw.
  - **The summary line quotes the compiled size in bytes**, beside the duration and the
    entry count. The two questions an effect raises are "how long does it sound" and "how
    much room does it cost", and only the second competes with the rest of the program --
    but the price is invisible in the drawing, because a bar is one 3-byte entry however
    long it is, so holding a tone is free and sweeping costs 3 bytes per frame it changes
    on. The arithmetic lives in `beeper_sfx.table_size`, not in the panel, and is tested
    against `convert_beeper_sfx`'s real output so the quoted number cannot drift from it.
  - **Tuning, stated accurately.** A period is a whole number of T-states, so a drawn
    frequency round-trips with an error up to ~0.11% at the top of the range. That is about
    2 cents, comfortably below the ~5 cents where pitch discrimination gives out -- but it is
    *not* "well under a tenth of a percent", which is what the first version of the test
    asserted and what had already been said out loud. The test now states the bound in cents,
    the unit that says whether it matters, and sweeps the whole range rather than checking a
    few round numbers.
- **Assets are now visible *as assets* in the project tree.** They were always listed --
  the tree has no name filter -- but with the generic OS icon and nothing else, so
  `hero.zx8x8` (converted, placed, addressable as `hero`) and a stray file of exactly the
  same type looked identical, and telling them apart meant opening `zxide.json`. (The
  `zxemu_ui` overview had claimed `asset_icons.py` drew "icons for the asset kinds in the
  project tree" for some time; it didn't, and now it does.) `zxemu_ui/project_tree_model.py`
  is a `QFileSystemModel` subclass that overlays the manifest onto the listing: the kind's
  icon as the file's decoration and a `symbol — kind asset` tooltip, using the same
  `asset_icons` table as the Inspector badge and the Design-mode map, so one asset looks
  like itself everywhere. Deliberately a *decoration and never a filter* -- a project is a
  folder you can put anything in, and a tree that hid what it didn't recognise would be
  lying about what is on disk. The asset map is rebuilt on demand through one
  `MainWindow._assets_changed()` (rather than re-read on every repaint), which every path
  that can change the manifest now calls -- including a new `MemoryMapView.assets_changed`
  signal for the drag-drop import, which previously told nobody.
- **Double-clicking a sprite/SFX file that isn't in the manifest offers to adopt it.** It
  used to do nothing at all -- no editor, no message -- which is indistinguishable from
  the IDE being broken. The extension already says exactly what the file is; the only
  thing missing was the manifest entry, so it asks for that. The two near-identical
  `_open_sprite_editor_for_path` / `_open_beeper_sfx_editor_for_path` methods collapsed
  into one `_open_asset_editor_for_path` plus an extension→(panel, dock, kind) lookup, so
  adding a third asset editor is one table row rather than a third copy of the method.
- **Delete from the project tree** (context menu, and the Delete key while the tree has
  focus), for files and for folders recursively. Deleting is three things at once, because
  leaving any of them behind produces a state that looks fine until the next build: the
  file, its editor tab, and its manifest asset entry plus that asset's cached bytes. The
  confirmation says up front what else is going -- how many items are inside a folder,
  which assets it will drop -- and the project folder itself is refused.
- **A Z80 Assembly Meter** in the status bar (`zxemu_core/debug/asm_meter.py`): bytes and
  T-states for the editor selection, or for the whole file when nothing is selected. On a
  machine with 48K of RAM and 69888 T-states a frame, "does this fit" and "does this
  finish in time" are the two questions that decide whether a routine works, and both are
  answerable from the source alone -- if you have the instruction table memorised. This
  module *is* that table. Timing is a **range** wherever a conditional jump, call, return
  or repeating block instruction costs different amounts taken and not taken, rather than
  picking one and being quietly wrong half the time; the figures are the published
  uncontended ones (no ULA contention -- that depends on where the code sits and when the
  beam is, neither of which source text can know -- and no M1 waits). `db`/`dw`/`ds` count
  toward bytes and cost no time. Anything unrecognised (a macro invocation, an `incbin`
  whose file it can't see) is counted as *unknown* and shown alongside the totals, so the
  number is never quietly short. It is a source-text table with nothing to share with
  `disassembler.py`, which goes the other way and carries no timing.

  **It moved out of the status bar** and is now a strip along the bottom of the editor,
  which is where it belonged from the start: it measures the text directly above it, and
  the bottom-right corner of the window is both the furthest point on screen from that
  text and the most crowded spot on it. The corner belongs to the size grip, and a
  *maximized* window has no grip -- so `QStatusBar` stopped reserving that space and the
  label ran flush to the screen edge with its last glyph clipped. Windowed, the grip holds
  the space open and nothing looks wrong, which is why it took a maximized screenshot to
  see it at all. As the editor's own footer it has the full width of the central widget
  and nothing can squeeze it; the strip hides itself entirely when there is nothing to
  measure, rather than leaving an empty row under a text file.

  The status bar had one real argument in its favour, and moving out satisfies it rather
  than ignoring it: the controller pushes transient messages ("running", "paused at
  $8000") through `showMessage`, which hides ordinary status-bar widgets -- so the meter
  had to be a *permanent* widget there, i.e. pinned to exactly the corner that turned out
  to be the problem. Outside the status bar the conflict doesn't exist.

  The readout also names its scope in full now -- `selection: …` / `whole file: …` rather
  than `sel:`/`file:` -- because which of the two it is decides how to read every number
  after it, and the abbreviation was quiet enough that the meter looked like it simply
  never followed the selection.

## Milestone 5: Visual Logic (design, not yet started)

*Sequenced after Milestone 4 -- actions like `draw_sprite` need assets to already exist.
This section records the design direction; nothing here is implemented yet.*

**Scope decision**: v1 is GameMaker-style linear/branching **action lists per event**,
not a full Unreal-style typed-pin data-flow graph -- much cheaper to build and codegen on
Z80-constrained hardware, and still expressive enough for real small games.

**Runtime model**: a fixed-size **array-of-structs** entity table (AoS suits the Z80's
`LD A,(IX+d)` addressing; no hardware multiply rules out SoA's stride math), driven by
the existing 50Hz frame loop with **zero changes** to `zxemu_core/machine.py`/`cpu/` --
this milestone only changes what assembly text gets generated and run inside the
already-working frame.

**IR**: one JSON file per Object (`logic/*.zxobj.json`) with events (Create / Step / Draw
/ Key Down / Collision), each holding a linear/branching action list. v1 action
vocabulary (8 ops): `set_var`, `if`, `move_by`, `set_border`, `play_tone` (blocking),
`draw_sprite` (references a Phase-E asset **symbol** -- the clean dependency edge between
the two milestones), `wait_frames` (single-pending-wait-per-object, not a real stall),
`call_event`.

**Codegen**: generate **plain sjasmplus text per action, not `LUA...ENDLUA`**. Decisive
reason: the SLD attributes one label per emitted action, so the existing
breakpoint/disassembly/step machinery works on generated logic code with **zero debugger
changes**; routing through Lua would collapse everything to one source line and break
per-action stepping.

**Editor**: a new `logic_view.py` dockable panel -- a reorderable action-list widget (not
a `QGraphicsView` node canvas; nothing in the codebase uses one today, and linear action
lists don't need it), following the same dock/tree-open patterns as the editor.

**Phased build-out** ends in a demoable vertical slice: a Phase-E-imported sprite moved
by arrow keys via `key_down`, colliding with a second object to change the border.

---

## Settled during layout review

- **Docking:** stock Qt docks; editor central, Project locked-left, everything else floatable
  (see Window & docking model). *(was open Q: docks vs splitter)*
- **Memory map form:** **bank-segmented columns** (one bar per slot, coloured by region, with
  PC/SP markers) — validated as genuinely useful in the mockup. Paired with a **hex memory
  cells** view for detail. *(was open Q: strip vs grid vs columns)*
- **Memory map placement:** its **own dock** on the right, under registers; the hex cells dock
  sits directly under the emulator. *(was open Q: tab vs dock)*
- **Editor:** in-app, central, multi-view/split — supersedes "external editor only".
- **Interface:** dark theme, High-DPI, Segoe UI + monospace console, adjustable UI scale.

## Open questions

Settled since:

1. ~~Confirm **`(bank, offset)`** as the universal addressing convention.~~ **Yes** — it is
   what the manifest stores for asset placement (`{"bank": "ram2", "offset": 100}`), what
   `memlayout` searches in, and what the memory map drags around. Addresses are derived from
   it, never the other way round, which is what makes a 128K bank that isn't currently paged
   in still describable.
2. ~~Debugger v1 scope: "inspect + step" first, or the whole thing as one milestone?~~ **The
   whole thing** — and it was the right call: breakpoints, stepping, watchpoints and the
   disassembly panel share so much state that splitting them would have meant building the
   seams twice.
4. ~~Default proportions & which panels start visible.~~ Settled in `_apply_default_sizes`
   plus a saved-layout file, with View ▸ Reset layout to get back.

Still open:

3. How exactly the debug workflow is *used* day-to-day (still being explored — the RE
   toolkit was built partly to find out).
5. **Whether `zxide.json`'s `main` should exist at all**, now that F5 assembles the file you
   have open and `main` is only a fallback. It still matters for any build with no editor tab
   involved (a future CLI, task runner, or build-on-run), so it stays until something needs
   to decide.

---

## Appendix: original vision

> since this application is going to be "Unity" for ZX Spectrum. We need to think about UI
> and zxide project setup. I see that that in the middle will be our created previous
> zxemu_widget. on the left will project structure: source assets (imported asset?),
> sourcecode
>
> Beside this we have to have direct access to memory (since we have emulator intergrated it
> should be not so hard), memory management before compil. Literally locate assets in memory
> visaully. with drag and drop (but should have auto locate button).
>
> Imported assets could be bmp, binary, pt3 (for audio?), some asset for beeper sfx?
>
> We are going to use sjasmplus. and path to it could be taken from PATH environment.
> Default editor is VS (also should be findable via system)
>
> But can be changed to any other.
