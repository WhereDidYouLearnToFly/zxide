# zxide — project status & handoff

_Last updated: 2026-07-27._ A snapshot to make it easy to pick the project back up.

## Latest session (2026-07-27, later) — AY music preview

Six music files in a real project (`E:\github\rehq\music`) all play now: an `.ay` container,
a `.c` compiled module, and raw `.pt3`/`.pt2`. Double-click opens a floating Music Player;
selecting shows details in the Inspector.

**The decision that shrank this by an order of magnitude.** The first plan was a PT3
interpreter in Python — ~1000 lines, then the same again for PT2. Then two things landed:
`.c` and `.ay` files are *Z80 programs*, not note lists, so they cannot be parsed as music
at all; and this project already owns a Z80 and an AY. So the engine became "load the blob,
call init, call play once a frame, drain the chip", and when pre-assembled player binaries
turned up in `E:\github\ZiFi`, raw `.pt3`/`.pt2` went through the *same* engine. The PT3
interpreter was deleted unwritten.

**Everything headerless is derived and cross-checked, never assumed.** A compiled module has
no load address; it is computed as `LD HL operand − file offset of the tracker signature`,
and the two facts check each other. A player binary is accepted only if its header's module
pointer equals `ORG + its own length`. Both refuse loudly rather than run a stranger's bytes
— which matters, because the failure mode of guessing is not an error but an emulated CPU
executing whatever the bytes happen to mean. Verified on the real files: `SH_promise.c` is
Bulba's player at `$C000` with a PT3 3.5 module at `$C851`.

**Three `.ay` details that fail silently**, all now tested:
- The block list terminates on a zero **address alone**. Requiring length 0 too walked off
  into 130 nonsense blocks that all looked almost real.
- **HiReg/LoReg select the song.** The Hero Quest file is three tunes sharing one 8976-byte
  block, differing *only* in that preload (2, 1, 3). Ignore it and all three play as one —
  proven by rendering all three and comparing hashes.
- Pointers are signed and relative to **their own position**, not the file start.

**Playback never touches the emulator on screen** — its own private `Machine128`, thrown
away on stop, same reasoning as `beeper_preview.py`. It also has its own audio sink, so a
preview does not fall silent when the machine is paused.

**No player binary is bundled**, deliberately: Bulba's players are third-party work whose
terms are not stated in either copy on this machine. They are autodetected near the project
instead, identified by shape rather than filename, which is what makes scanning arbitrary
`.bin` files safe. Same pattern as the assembler.

**Two bugs found by actually listening**, which is why it was worth testing before writing
any of this down:

- **The music lagged.** Not CPU — a frame renders in 5.2ms of its 20ms budget. It was
  `QTimer(20ms)` plus *one frame per tick*: Windows' timer granularity is ~15.6ms, so the
  tick rate was never 50Hz and the tune played at whatever rate the OS delivered events.
  `controller.py` documents this exact trap for the emulator loop and paces by elapsed time;
  the player now does the same, plus six frames pre-rendered so the device is not fed from a
  standing start. Confirmed better by the user.
- **"It says it needs some library."** It did not — that was the wording of "no PT3 player
  binary found", which reads like a broken install when the truth is that a `.pt3` file
  contains notes and no way to play them. Message rewritten, and a **Find player…** button
  added, because an explanation beside a dead button is still a dead end.

**The players are bundled now** (`zxemu_core/players/`, with `LICENSE-players.txt`), at the
project owner's decision after the licence gap was flagged: both are builds of Bulba's
universal PT2/PT3 player with no licence text in the copies on this machine. Search order is
chosen-folder → project → bundled, so a project carrying its own player still wins.

Also not done: interrupt-driven `.ay` songs (interrupt address 0) are refused rather than
mis-played, and an incidental find — an untouched AY emits a −0.25 DC step that its blocker
decays over the first frame, so every playback starts with a faint click.

**Rename in the project tree** went in alongside (`F2`, or the context menu). Same split as
delete: `workspace/project_files.py` owns the part with consequences and is Qt-free. The
manifest is the whole point — an asset's source follows its file, a renamed folder carries
its subtree including every frame of a sequence, while the *symbol* stays put (assembly
source refers to it) and the build cache stays valid (keyed by symbol; only the name moved).

## Earlier session (2026-07-27) — the Kempston Mouse, a review of it, then the Joystick

**1361 tests pass** (1332 unit + 29 integration; the zexall harness is separate and runs
for minutes by design — it is why `pytest tests` looks like it has hung, and why the two
suites above are worth running on their own).

The interface itself is small (`zxemu_core/mouse.py`: two counters, a buttons byte) and
went in cleanly. The interesting half of the session was reviewing it against
`E:/github/fuse` afterwards, which turned up three things worth recording — one bug in
the new code, one fidelity gap, and one pre-existing bug the new code walked into.

**Address decoding is by *line*, not by address, and that changes the picture.** The
first implementation matched the three addresses the manuals quote — 0xFADF buttons,
0xFBDF X, 0xFFDF Y. Real hardware decodes four address lines and ignores twelve: A0 must
be set, A5 must be clear, then A8 picks buttons-or-counter and A10 picks which counter.
Matching the literal addresses leaves software that arrives with different high bits
talking to nothing. Fixed, and the consequence is worth internalising: because A8 and
A10 between them cover every remaining case, the interface claims **every** port with A0
set and A5 clear. It is a greedy device that sits on its neighbours — 0x1F, the Kempston
*joystick* port, among them, which is exactly why the two were mutually exclusive on real
machines. Two design points follow from that and should not be quietly undone:

- **Off by default is not timidity.** Beyond software probing for a mouse that isn't
  there, enabling it puts this device on top of a swathe of the port map.
- **The Beta 128 is decoded first** (`MachinePentagon._io_read`, before delegating up),
  so ports 0x1F and 0x5F belong to the disk controller while TR-DOS is paged. Reverse
  that precedence and enabling a mouse silently stops disks working.

**A held button could latch forever.** Capture can end mid-click — Esc, lost focus, the
menu toggle — and the matching physical release then lands wherever the pointer went, not
on the view; since `mouseReleaseEvent` only talks to the interface while captured, the bit
stayed low for the rest of the session, surviving even re-capture. `release_mouse_capture`
now calls `KempstonMouse.release_all_buttons` on the way out. The general shape is worth
remembering for anything else that grabs input: **every path that stops you receiving
events needs to also let go of whatever you were holding**, because you will never be told.

**Then the Kempston Joystick, and both moved to the Model menu.** Five active-high switches
at 0x1F (`zxemu_core/joystick.py`), arrows plus Ctrl for fire, and those keys are *taken
away* from the Spectrum keyboard while it is fitted — feeding both would have a game see
each nudge twice, the arrows being CAPS SHIFT + 5/6/7/8. Active high is the thing to
remember: an unfitted port reads 0xFF off the undriven bus, which is every direction and
fire held at once, so "no joystick" and "no interface" look nothing alike to a game.

The menu move was the right shelf, not decoration. View is about how the IDE looks and
Settings is about *your* PC (its first group is literally "Global (this machine)" meaning
the developer's); what is plugged into the emulated Spectrum is the same question as which
Spectrum it is. The two items are check items rather than a `QActionGroup`, because an
exclusive group insists something be chosen and the normal state is neither — but they do
untick each other, since both interfaces answer 0x1F and on hardware they fight over the
bus. Fitting either now logs "software checks at startup, so reset or reload", which was
the actual cause of the first "it doesn't work" report.

**Gamepad support went in, and pygame is now a third shipped dependency.** The obvious
cheaper routes are closed and it is worth writing down why, so nobody re-litigates it:
PyQt5 ships no QtGamepad (ImportError here), and XInput — the zero-dependency Windows route
— speaks only the Xbox protocol, so it cannot see the plain-HID USB NES clones people
actually use. SDL2 via pygame handles them, and the call was made to ship it rather than
make it an extra.

`zxemu_ui/gamepad.py` polls the pad from a new `EmulatorController.input_poll` hook at the
top of each tick, *before* the frames that tick will run — the switches a frame reads should
be the ones held when it began. Two details worth keeping:

- **The joystick holds two masks, keyboard and pad, OR-ed at the port.** One shared field
  cannot work: the keyboard arrives as edges while a pad is polled wholesale fifty times a
  second, so each poll would wipe whatever key was being held.
- **`event.get()`, not `event.pump()`.** Both refresh SDL's cached device state, but nothing
  else in this application ever reads the event queue, and a queue nobody drains fills up
  and stops accepting updates.

Probed against a real device rather than guessed: a "usb gamepad" NES clone, two axes (rest
-0.01, directions snapping to ±1.0), no hat, ten reported buttons of which only 0, 1, 8 and
9 exist. Hence the loose 0.5 deadzone, and a button map keyed on those indices: 0/1 are the
two fires (the pair under your thumb), 8/9 become A and START (where such pads put Select and
Start), and anything unrecognised falls back to fire so an unfamiliar pad is never mute.
SDL exposes buttons by index only, so there is nothing more semantic to key on.

**Then extended (8-bit) Kempston, to the Next's layout.** ZX Evolution's is redefinable in
software, so there is no fixed thing to be faithful to there; the Next's is the Mega Drive
pad's — bit 7 START, 6 A, 5 C, 4 B, 3-0 U/D/L/R.

Worth reading the source rather than trusting a memory of it, because the substance is not
the bit order. **The Next's Kempston and MD 3-button modes differ in exactly one thing: a
mask.** Kempston passes bits 5:0 and forces 7:6 to zero, MD 3-button passes all eight
(`zxnext.vhd:3478-3479`). Two consequences an "all eight bits, always" implementation would
get wrong: a *second fire button works in plain Kempston mode* (bit 5 is in the low lane),
and A/START must not reach software that never heard of them. So `KempstonJoystick.extended`
masks at the port rather than at the switches — a pad's buttons close either way, and
switching modes reveals what was already held instead of needing it pressed again.

Sourced locally, not from memory: `E:\github\zxnext-ref` section 9.4 pointed at
`jnext/src/input/joystick.h:14-33`, which documents the layout from the VHDL, and
`joystick.cpp`'s `compose_1f_lane` shows the two lanes and their `0xC0` / `0x3F` masks. Both
checkouts are on this machine.

Original five-switch hardware never closes the upper switches, so it reads identically in
either mode — no third mode needed, and none added.

**Esc never actually left fullscreen** — a pre-existing bug the mouse work surfaced.
`FullScreenStage.keyPressEvent` closes on Esc, but fullscreen gives the *view* focus, and
`EmulatorView.keyPressEvent` neither called `super()` nor ignored the event; Qt only walks
the parent chain for keys a widget declined, so the window never saw it. `test_fullscreen`
passed throughout because it posted Esc straight to the window. The view now calls
`event.ignore()` for Esc, and the two uses layer correctly: captured, the first Esc frees
the pointer and a second leaves fullscreen. The new test drives it the way Qt does
(`QTest.keyClick` at the focused view) rather than calling the handler directly — the
distinction is the whole reason the bug survived.

## Earlier session (2026-07-25, last) — a polish pass over the asset editors and the project tree

**1194 tests pass** (1165 unit + 29 integration). All of this came from actually *using* the
IDE for a while rather than from the plan — which is why two of it reverses decisions that
looked right when they were made. The full write-up is in DEV_PLAN.md ("Polish pass over the
asset editors and the project tree"); what follows is what a future session needs to know.

**Native sprites are raw binary now, and the extension is the format.** `.zxspr.json` is
superseded by six extensions across two axes — fixed size (`.zx8x8`, `.zx16x16`) vs
arbitrary (`.zxsprite`, whose **first two bytes are width and height**), each with a `…pix`
variant carrying no attribute plane. The file *is* the bytes the Z80 gets. The decision
worth keeping: the two-byte header exists **only** where nothing else could supply the size,
because a format whose whole point is that it needs no unpacking shouldn't spend bytes
repeating what the filename already says. Frame count isn't stored either — it falls out of
the file length. Old `.zxspr.json` files still load *and still save as JSON*: zxide does not
quietly rewrite, rename or delete a file the user didn't ask it to touch.

**The sprite editor keeps "drawing claims the cell", but the left button now toggles.**
Worth recording because it took two attempts. The original complaint was that erasing a
stray pixel meant switching the selected colour to that cell's paper first — under the old
left-ink/right-paper scheme. The first fix split drawing and colouring into two tools, which
removed the problem and introduced a worse one: the *common* case (draw a pixel in the
colour I picked) became two actions in order to save the rare one. The right fix was
smaller — keep one tool, make the left button toggle. Press decides the stroke's value from
the pixel under the cursor, so a drag never alternates, and erasing is just clicking a lit
pixel. Right-drag recolours without touching art; alt+click eyedrops. Neither is a mode.

**The palette had never shown which colours were selected.** Checkable `QPushButton`s with a
`background-color` stylesheet — and the stylesheet replaces the whole button rendering, so
the checked state was silently never drawn. `_PaletteBar` paints the row itself now. The
detail worth keeping: the selection ring must sit in the cell's *margin*, not inside the
swatch. Drawing it inside was the obvious thing and it made selecting black produce a
mostly-white square. That was found by rendering the panel to a PNG and looking at it, which
no test would have flagged — the pixel-level tests around it were written afterwards, and
one of them was then weakened in its claims once it turned out it wouldn't have caught the
original layout.

**The SFX editor is a bar chart of frequency over time**, and getting there took three
passes. Each bar rises from the baseline: height = tone, width = duration. Drag up for
higher, sideways to hold, shift to keep the pitch level, right-drag to erase.

**The two passes before that built a musical piano roll — semitone rows, a piano keyboard,
snapping — and it was the wrong model.** Worth recording, because the failure is a general
one rather than a detail. The semitone grid was picked up front from a menu of plausible
options, sounded obviously right, and survived two rebuilds because each round improved the
*drawing* without ever questioning the *model*. A beeper effect is a swoop or a thud, not a
melody; quantising a swoop to the chromatic scale fights the thing you are drawing. All that
machinery is gone, including `beeper_sfx.py`'s note-grid helpers — they'd have lingered as
tested dead code otherwise.

What carried over, and why:

- **One column is one video frame, with no setting for it.** This took a detour worth
  remembering. A configurable "step" of several frames was added because per-frame columns
  had looked like a wall of slivers, and it then got relabelled twice trying to make it
  comprehensible. Both attempts answered the wrong question: **length already comes from how
  far you drag**, so the step only decided the floor, and the right floor is the shortest
  sound that exists. Deleting the control lost nothing. The real defect had always been that
  *clicking* made sliver bars — fixing the interaction dissolved the setting, while two
  rounds of polishing its label had made it look steadily more reasonable and left it just
  as unnecessary. **A control that needs a good label is worth re-examining before it gets
  one.** (Side effect that did need handling: mouse moves are sampled far more coarsely than
  one report per column, so a fast drag skips frames — strokes now fill the gap and
  interpolate the pitch across it.) Columns are 12px, generous on purpose: a single 20ms
  frame has to be a block you can see and hit, or drawing it as bars buys nothing.
- **The frequency axis is logarithmic**, 32Hz–4096Hz, one octave per equal step. Linear
  would bury everything under 500Hz — where thuds and rumbles live — in the bottom eighth.
  Seven octaves at 56px each also fits without vertical scrolling, which let the whole
  "scroll to the content" mechanism the piano roll needed be deleted.
- **The frequency scale and time ruler are pinned by painting at the scroll offset.** A
  header that scrolls away labels something you can't see.
- **Shift locks the pitch for a stroke**, because with continuous frequency a hand-drawn
  "sideways" drag is never level and every wobble would otherwise be its own entry.

Two notes for whoever works here next. `_step_at` takes widget coordinates and rejects the
pinned-header band, which is correct — a real click can only land on a visible point — but it
means synthetic mouse events must be sent with the scroll position known; the test helper
parks both scrollbars at zero for exactly that reason. And the period↔frequency round trip is
lossy by up to ~0.11% (≈2 cents) at the top of the range: inaudible, but *not* the "well under
a tenth of a percent" an earlier version of the test asserted and that had already been said
out loud. The test now states the bound in cents and sweeps the whole range.

**Assets are visible as assets in the tree.** They were always *listed* — no name filter has
ever been set — but with the generic OS icon, so `hero.zx8x8` and a stray file of the same
type were indistinguishable without opening `zxide.json`. (The `zxemu_ui` overview had been
claiming otherwise for some time.) `project_tree_model.py` overlays the manifest onto the
listing as a decoration, never a filter. Double-clicking an unregistered sprite/SFX file
used to do *nothing at all*; it now offers to adopt it.

**Z80 Assembly Meter** (`zxemu_core/debug/asm_meter.py`) in the status bar: bytes and
T-states for the selection, or the whole file. Timing is a range wherever branching makes
one. It is a source-text table with nothing to share with `disassembler.py` — that goes the
other way and carries no timing, so coupling them would be coincidence, not reuse.

**Two structural notes for next time.** `MainWindow` is at ~1780 lines and is the one place
in the codebase that has outgrown itself; the delete feature was written straight into it
and then pulled back out into `workspace/project_files.py` (a decision that paid for itself
immediately — that logic is now tested with no `QApplication` at all). The same treatment
would suit the build/run and dump plumbing whenever someone has the appetite. Also, every
path that changes the manifest now goes through one `MainWindow._assets_changed()`, so a
new one can't update half the UI — the drag-drop import used to notify nobody, and now
emits `MemoryMapView.assets_changed`.

## Earlier session (2026-07-25) — fullscreen, then two follow-ups from using the dumper

**866 tests pass.**

**Emulator fullscreen** — `Alt+Enter` in, `Esc` out, also on View ▸ Emulator fullscreen.
Both keys are free to borrow because **a Spectrum has neither**, which is asserted by a test
rather than left as a comment: if either is ever mapped into the key matrix, that is where
the collision surfaces.

The design decision worth keeping: `panels/fullscreen_stage.py` **lends** the existing
`EmulatorStage` to a bare black window instead of building a second renderer. Reparenting a
live QWidget preserves its identity, so the same `EmulatorView` keeps its `frame_ready`
connection, the Spectrum's key matrix and any keys currently held — going fullscreen
mid-game does not drop a frame, and there is no second copy of anything to keep in step.

That makes one invariant carry the whole feature: **the stage must always find its way
home.** Every exit route (Esc, the menu item, Alt+Enter again, the window manager, closing
the IDE while fullscreen) ends in the window closing, so a single `closing` handler
reclaims it. A stage left parented to a destroyed window would take the emulator with it.
Two details that would otherwise bite: the shortcut is `ApplicationShortcut`, because in
fullscreen the emulator is a *separate top-level window* and a window-scoped shortcut would
get you in and never out; and `MainWindow.closeEvent` leaves fullscreen first, or Qt's
quit-on-last-window-closed would leave the app running as a bare Spectrum screen.

## Earlier that session — two follow-ups from using the dumper

**859 tests pass.** Both of these came from the user actually running a dump, which is the
only way either would have been found.

**Sound was silent while recording coverage — and it took two fixes, because there were two
independent causes with one symptom.** Worth recording as a pattern: the first fix was
correct, verifiable and *insufficient*, and only re-testing against the real UI showed it.

1. **The mute policy.** `_update_audio()` muted whenever `self._recording` was set. That was
   a guess about cost measurement doesn't support — a 48K debug frame with coverage on costs
   ~15.1ms against a 20ms budget. Mute now applies only to pause, breakpoints and
   watchpoints: states where the machine genuinely isn't producing sound. (This also
   explained the second reported symptom, silence in the *rebuilt* project — "1. Record What
   Runs" was still ticked when it was run. One cause, two symptoms.)
2. **Nothing was being rendered anyway.** `_run_debug_frame` stepped `cpu.step()` directly
   against a private `_debug_tstates` clock and never reached `Machine.run_frame`'s tail —
   so `audio.end_frame()` was never called and no PCM existed to play. Worse, the beeper
   timestamps each level change against `machine.frame_t_state`, which the debug loop left
   frozen: every flip during a debug run was stamped at the moment the last full frame
   ended, collapsing the waveform to a point.

The fix removes the second clock rather than syncing it. `Machine.end_frame()` is now split
out of `run_frame` — the frame *seam* (carry the T-state remainder, run the tape motor,
resample sound) is a thing in its own right, because `run_frame` is not the only way to
execute a frame. The debug loop and `_run_until` (step over/out) advance
`machine.frame_t_state` and call `end_frame()` at the boundary, exactly as a free-running
frame does. Two clocks for one machine was the underlying defect; the silence was a symptom.

Side effect worth knowing: the tape motor now turns while stepping, so you can single-step
through a loader and watch it load.

**Lua is highlighted inside `LUA`/`ENDLUA` blocks** (`zxemu_ui/z80_highlighter.py`), which
closes the ★ item in DEV_PLAN §5. This stopped being cosmetic the moment the dumper started
generating such a block: highlighting Lua as assembly is *worse* than not highlighting it,
because `--` comments read as subtraction and `local`/`function` as labels.

The mechanism is a two-state machine with the state carried between lines via
`setCurrentBlockState` — the only way a line-at-a-time `QSyntaxHighlighter` can know it is
partway through something that started earlier. `LUA`/`ENDLUA` colour as directives (the
assembler's syntax, not Lua's), and `LUA PASS1` / `LUA ALLPASS` open a block too, so the
opener is a prefix match rather than a whole-line one. Standalone `.lua` files are
deliberately out of scope — the Lua that matters lives inside `.asm`.

Worth noting for the tests: an offscreen `QTextDocument` paints nothing, so Qt never runs
the highlighter and every block state reads back as `-1`. `tests/unit/test_highlighter_lua.py`
calls `rehighlight()` explicitly. The first run of those tests failed for that reason and not
for any reason in the code under test.

## Earlier this session (2026-07-25, later still) — the memory dumper (DEV_PLAN 1b)

**850 tests pass.** `Reversing ▸ Dump to Project…` turns the running program's RAM into a
**buildable, debuggable zxide project** — not a snapshot. `zxemu_core/debug/dumper.py` does
the reasoning (Qt-free), `zxemu_ui/workspace/dump_project.py` writes the files.

Coverage is the ground truth: an address that executed *is* code, observed rather than
guessed. Executed runs become disassembly with labels on branch targets and `equ`s for the
ROM routines called; everything else stays bytes, which assembles to the same program
either way. Emphatically **a project**, with a manifest carrying the model it came from, so
Open Folder gives you F5, breakpoints and the memory map immediately.

**The invariant is the whole point: assemble the dump and compare bytes with the memory it
came from.** Proven end to end on a real program — Spectrofon booted from a `.trd` on
Pentagon, dumped mid-run, reassembled with sjasmplus, **byte-identical**, with recognisable
recovered source (`di / push af / push bc / push de / push hl` — an interrupt prologue).

**Two things that test caught, and nothing else would have:**

1. **`.sna` is the wrong thing to compare against.** A 48K snapshot has no PC field: its
   loader `RET`s to an address pushed on the stack, so saving one *necessarily* overwrites
   two bytes of the program at SP-2. The first end-to-end run came back with exactly one
   differing byte. The dump now also emits `savebin "main.bin"` — a raw image with no such
   artefact — and that is what verification compares.
2. **Coverage marks instruction *starts*, not every byte.** `ld a,7 / out ($fe),a / ret`
   marks three addresses and leaves the operand bytes unmarked, so treating only
   *consecutive* marks as a run shreds real code into one-byte fragments that all fall
   below the minimum run length -- and an executed routine dumps as data. `plan_regions`
   now expands each mark to the whole instruction it begins. This hid for a while because
   the early tests set coverage as a solid block of addresses, which no real program ever
   produces; it only surfaced against a machine that had genuinely executed something.
3. **Disassembly is not injective, and here that is fatal.** `DD DE nn` is `sbc a,n` with a
   redundant IX prefix: the CPU ignores it, the disassembler rightly doesn't mention it, and
   sjasmplus then emits *two* bytes where there were three. Everything after shifts by one —
   which surfaced as a **branch displacement changing thirty bytes earlier**, because the
   label had moved. Same problem with the seven duplicate `ED` encodings that all mean
   `neg`. `dumper._round_trips` keeps those as raw bytes, falling back one byte at a time so
   the damage stays local. Neither is exotic: both appear in the first kilobyte of the 48K
   ROM, because both are what ordinary *data* decodes to when misclassified as code.

**All eight banks are captured**, and the reason it was easier than expected is worth
recording. On real hardware you would have to halt the machine, page each bank in, read it,
and carefully restore the previous mapping. In an emulator a bank is a plain bytearray we
can read whether or not it is mapped -- `Machine128.display_memory` already relies on
exactly that for the shadow screen. Measured on Spectrofon running on Pentagon: **80K of
RAM the address-space view would have missed**, byte-identical to the machine's own banks,
and it still assembles.

**Paged banks are disassembled too, now.** `CoverageMap` keeps a per-bank record for the
one ambiguous window (0xC000+; below it slot 1 is always RAM5 and slot 2 always RAM2, so a
flat address already identifies the bank). `Machine128.set_paging` announces the new bank
through a `paging_listener`, which `EmulatorController` points at `coverage.select_bank` --
so the bank is recorded *as it happens*.

It has to be. The tempting idea is to compare banks afterwards and deduce which was
running; that cannot work, because the information was never written down and is not latent
in the bytes -- two banks may hold identical data, a bank may be modified after its code
ran, and a program can swap banks at one address hundreds of times a second.

**A dump restores RAM; it does not restore the machine -- and that difference is what a
user hits first.** Reported symptoms: the rebuilt program ran, but with a white border and
a dead keyboard. Same cause. `savesna` writes memory plus an entry address and *defaults
every register*, so a game reading keys from an **IM 2** interrupt handler came back with
IM 1, the wrong `I` (the vector-table base), and interrupts disabled. Alive and deaf.

**The fix went through two designs, and the second is much better -- the user's idea.**

The first was a **restore stub**: ~50 bytes of generated Z80 that set everything back and
jumped to the real PC. It worked, and cost four bugs to place safely (the search picked
**0x4000, the screen bitmap**, because a blank screen is a huge run of zeros coverage never
marks as executed; `savesna` writes its entry address at the bottom of RAM, clobbering the
stub's first bytes; `pop af` reads the word *at* SP, not below it, so `ld sp,label+2`
silently swapped `AF` with `AF'`; and on a paged machine the stub must live below 0xC000 or
it vanishes with the next bank switch -- found on a real Pentagon dump where it landed at
0xC9B0 and never ran).

Worse than the bugs was the premise. The stub had to sit *somewhere in the program's own
memory*, chosen by the inference "unexecuted and currently zero". Coverage means **"not
yet"**, and a large run of zeros is very often a buffer the program has not filled yet --
a decompression target, a level scratch area. Exactly the kind of guess that breaks
something later and elsewhere.

**sjasmplus embeds Lua (5.4, since v1.20.0), so the snapshot can just be written
correctly.** The generated `main.asm` now carries a `LUA`/`ENDLUA` block that reads the
assembled bytes back with `sj.get_byte`, reaches every bank with `sj.set_page`, and writes
the `.sna` itself with a proper register header. Nothing is injected into the program:

| model | PC stored in | RAM bytes modified |
|---|---|---|
| 128K / Pentagon | the extra header | **zero** |
| 48K | on the stack (no PC field) | 2, at SP-2 -- below the stack pointer, i.e. memory the program overwrites itself on its next push |

Verified on the real case: Spectrofon on Pentagon, dumped mid-run, rebuilt -- **RAM
byte-identical, all eight banks identical, border/I/IM/PC/0x7FFD all restored**. And the
byte-identity invariant is **absolute again**, with no "except these fifty bytes" clause.

`zx.save_snapshot_sna` is worth knowing about and does *not* help: same signature as
`SAVESNA`, filename and start address only.

**Two paging traps in the generated source, both caught by the byte-identity test rather
than by reasoning.** sjasmplus starts a `zxspectrum128` device with **bank 0** in slot 3, so
(a) the 0xC000-0xFFFF part of the flat dump was being assembled into the wrong bank, leaving
the bank that was actually mapped empty; and (b) each bank's source ends with its own `PAGE`
in effect, and both `SAVEBIN` and `SAVESNA` write whatever is mapped *at that point* -- so
the saved image took its top 16K from whichever bank was included last. The generated
`main.asm` now pages the live bank in before the includes and puts it back before saving.
Worth noting the shape: the first of these made verification compare against the *wrong
memory* and still pass, which is the failure mode a correctness test is supposed to prevent.

**Cost: ~3.4% on the 48K debug loop; on 128K it is inside run-to-run noise.** Worth knowing
*how* that was measured, because the first attempt said 60.9% and was wrong: it timed
"coverage off" and then "coverage on" in sequence on the same machine, so the second run
executed entirely different code. Re-run from identical state, alternating, the addition is
free. A benchmark that advances the thing it is benchmarking measures nothing.

**The doc guard earned its keep immediately**: added earlier the same session, it failed on
this very work because `dumper.py` and `dump_project.py` were missing from their package
overviews.

## Latest session (2026-07-25, later) — Pentagon 128, Beta 128, TR-DOS, disks

**760 tests pass**, up from 727. Design document: **[../TRDOS.md](../TRDOS.md)** — read that
for the architecture and the hardware facts; this is the narrative.

A third machine model, and with it a whole storage medium. `Load ▸ Load TRD…` mounts a disk,
the Pentagon menu's TR-DOS entry works, `CAT` lists the disk, and the machine can write back.
**1852 images from the local library parse, 0 refused** (946 `.trd`, 906 `.scl`).

**Three things worth knowing before touching this code again:**

1. **The ROM identification was checked, not assumed.** `128p-0.rom` differs from the stock
   `128-0.rom` in **65 bytes**: the menu string `"Tape Tester"` becomes `"TR-DOS"`, and new
   code appears containing the literal `"15616"`. `RANDOMIZE USR 15616` is 0x3D00 — the exact
   address the Beta 128 watches for. The ROM patch and the interface agree, which is what
   confirms the pair. `128p-1.rom` is byte-identical to `128-1.rom`.
2. **`LICENSE-roms.txt` now separates three cases** rather than implying one. Amstrad's
   permission covers `48.rom`/`128-*.rom`/`128p-1.rom`. **No distribution statement could be
   located** for `trdos.rom` or `128p-0.rom`'s patch — they are in the fuse checkout but in
   neither its `Makefile.am` nor its `README.copyright`. Bundled deliberately, with the
   position stated.
3. **The CPU gained an `m1_hook`** because the Beta pages its ROM by watching the *address
   bus* during instruction fetch, which neither a port write nor the single-address trap can
   express. Measured cost: **48K 11.0ms, 128K 15.3ms, Pentagon 16.6ms per frame** — ~8% on
   Pentagon only, nothing elsewhere (the hook is `None`). Inside the 20ms budget, so it stands.

**The bug worth remembering.** The first `CAT` on a good disk said **"No disk"**. Everything
checked out: the catalogue parsed, the geometry was right, TR-DOS had seeked to track 0 and
asked for sector 9. Port tracing found it — TR-DOS polls **port 0xFF** for DRQ/INTRQ and never
reads the status register mid-transfer, so a **stale INTRQ from the previous Restore** made the
first Read Sector look already-finished. It took one byte and gave up. The datasheet clears
INTRQ on a status read *or a command write*; only the first was implemented. One line, now
pinned by `test_writing_a_command_clears_intrq` — nothing about the symptom points at the cause.

**Also worth knowing:** a catalogue "track" is a *logical* track with the two sides folded in
(cylinder = track // sides, head = track % sides), which is why the TRD layout interleaves
sides. My own first test asserted otherwise and was wrong, not the code.

**The boot sweep, and what it was worth.** 60 disks sampled at random from the library, each
booted into TR-DOS with `CAT` typed on the emulated keyboard and the screen decoded back to
text; TR-DOS's file count compared against the parser's. **59/60 agreed immediately.** The
60th (*Spectrum Progress 01*) said 27 against TR-DOS's 12 — catalogue slots past the file
count held a maker's **signature** rather than files, with zero length and a start position
of track 0 sector 0, and no 0x00 terminator in front of them. `catalogue()` now bounds itself
by the information block's file count when that block is genuine, which is the number TR-DOS
trusts, falling back to the terminator when it isn't. Worth noting the shape of this: three
disks by hand all passed, and it took an arbitrary sample to turn up a disk built by someone
with a sense of humour.

**Then four bugs turned up in minutes of hands-on use, none of which 762 tests had caught.**
They share a shape worth remembering — each was *a state machine with no way out*:

* **`RUN` wedged the machine, and the first fix was worse.** TR-DOS writes `0xFF` to the
  command register while probing; that decodes to **Write Track**, which parked with DRQ
  raised waiting for a track's worth of bytes that never came. Fixing it by *blanking the
  track and finishing* unwedged the machine and started **erasing disks**: the probe lands
  while the head is on **track 0**, so it wiped the catalogue and information block, and
  the loader reported "Disk Error" on a disk that had been fine seconds before. Write Track
  now completes immediately and **writes nothing**. The rule: *a command we cannot interpret
  faithfully must not modify the disk.* Nothing is lost — images start blank and `FORMAT`
  lays down its catalogue through ordinary Write Sector commands.
* **Reset couldn't rescue it.** `Machine128.reset()` re-pages slot 0 via `rom_for_slot0()`,
  which answers "TR-DOS" while the Beta is paged — so resetting from inside TR-DOS restarted
  the CPU *executing TR-DOS from address 0*. That was the garbage screen. The reset line
  reaches the interface now, as it does in hardware.
* **Multi-sector transfers were never implemented.** `_multiple` was decoded and then unused,
  so `0x90`/`0xB0` served one sector and stopped — anything bigger than 256 bytes would stall.
* **Switching model left the new machine unbooted**, so doing it while paused gave a black
  screen and a dead keyboard that read as a broken model. `set_machine` now power-cycles.
* **An abandoned transfer hung the drive for ever** (`STUCK-FDC`, found by sweeping real
  disks — Spectrofon 15). A real chip is attached to a spinning disk, so an uncollected
  byte is *gone*: it raises LOST DATA and ends the command. Ours is a bytearray that waits
  patiently, so any abandoned transfer left DRQ and BUSY raised until the session ended.
  There is now a one-revolution deadline (`DRQ_TIMEOUT_TSTATES`), enforced through the
  `drq` property so every observer applies it whichever port is polled; each byte moved
  resets it, so slow-but-living transfers are untouched.

**The pattern in all five:** *a state machine with no way out* — a command that could be
entered and never left, or a reset that didn't reach far enough. **None** was a mistake
about what the bytes mean; the format work was right from the start. They were all about
what happens when something goes wrong, which is precisely what a test suite written by
the author of the code will not think to probe. Two things found them where unit tests
could not: sweeping real disks, and using the IDE by hand.

**Also settled this session:**
* The disk primer — what TR-DOS *is*, for someone who has only used tapes — now lives in
  `zxemu_core/storage/disk/__init__.py`, per the project's convention that a package's
  `__init__` is its educational overview. `TRDOS.md` links to it and stays the design
  record. Every other `__init__.py` was audited for staleness at the same time; four were
  out of date (no Pentagon, no disks, no `m1_hook`) and are fixed.
* **Load dialogs share a remembered folder** (`last_media_dir` in settings): media lives in
  a collection, not in your project, so all six formats plus Mount B and Save Disk As open
  where you last were. Recorded on load rather than in the dialog, so Load Recent updates
  it too; a folder that has since vanished is forgotten rather than reopened.
* **`RUN` sweep over 40 disks**: 13 RAN, 1 MOVED, 1 STUCK-FDC (now fixed), 25 NO-CHANGE.
  The 25 are **not** a bug — those disks hold a single `.B` file named after the issue and
  are started with `RUN "NAME"`; bare `RUN` looks for a file literally called `boot`. The
  harness was naive, not the emulator. Worth remembering before reading that sweep again.

**Spectrofon N1 (1994) now boots from a `.trd` and runs**, and Reset returns to a clean
Pentagon menu. 770 tests, with a regression test per bug.

The lesson to carry: the automated tests all drove the *controller* correctly, so they never
issued the malformed command a real ROM issues, and never reset from a state a person can
easily reach. Hands-on use found in minutes what a test suite built from my own assumptions
could not.

**Demos: laggy, sometimes hanging — measured, and it is _not_ the disk.** Five disks run from
a cold boot, core only (no Qt, no rendering, no audio device):

| disk | mean ms/frame | worst | frames >20ms | LOST DATA | controller at end |
|---|---|---|---|---|---|
| DIHALT19 | 15.4 | 25.8 | 62/900 | 0 | idle |
| Spectrofon 06 | 12.8 | 27.0 | 128/900 | 2 | idle, still running |
| GAMES041 | **23.5** | 43.8 | **717/900** | 0 | idle |
| Body 09 | 17.1 | 24.9 | 366/900 | 0 | idle |
| Optron 23 | 14.4 | 41.6 | 90/900 | 0 | idle |

The controller ends **idle in all five** — no stuck transfers, no held DRQ. The two LOST DATA
events were the new timeout *working*: it recovered an abandoned transfer and the demo carried
on. Before it existed those were permanent hangs.

So the lag is **raw emulation speed**. A frame is 20ms of wall clock at 50Hz; GAMES041 averages
23.5ms before Qt is even counted. Pentagon is the heaviest model by construction — a longer
frame (71680 vs 69888 T) plus the `m1_hook` — roughly 10% over a 128K, enough to push
borderline software under the line. The *hangs* are far more likely cycle-accuracy (contention
not applied per access, no per-scanline border effects) than anything to do with the drive.

**Decided:** not optimising for now. Speed is fine for games and an acceptable starting point
for demo work, and this is a development platform rather than a preservation-grade emulator.
If it is ever revisited, the two candidates are profiling the CPU dispatch loop and making the
`m1_hook` cheaper — this codebase already has the right trick for the latter, since port
watchpoints swap the hooks in and out rather than testing a flag on the fast path.

**Deliberately not done:** `.fdi` (needs bit-level geometry) and `Write Track` (writes nothing,
on purpose — see above).

## Latest session (2026-07-25) — tape edge replay, and Milestone 3 finally closes

**716 tests pass** (`pytest tests/unit tests/integration`), up from 682.

The last deferred item in Milestone 3 is done: tapes can now be replayed **as pulses**
rather than shortcut through the ROM. New module `zxemu_core/storage/pulse.py`.

**Why it was worth doing.** Fast loading works by trapping the ROM's `LD-BYTES`. A
commercial game's own turbo loader never calls that routine — it bit-bangs its own
sampling loop — so *no trap can ever serve it*. Measured across the 20 `.tzx` files in
the library on this machine: **4 use genuinely non-ROM bit timings** (Renegade is a
Speedlock 4 release, plus Barbarian II, Ms. Pacman, The Untouchables), and separately
**35 blocks are `0x14` "pure data" with no pilot of their own** — those depend entirely
on the preceding `0x12` tone that the parser used to discard. That was the ceiling, and
it is now gone.

*(Careful with the numbers: 15 more tapes differ from `ROM_TIMING` only in `pause_ms`,
which is not turbo. An early draft of this note counted those as turbo and claimed 19/20;
what makes a tape turbo is the pilot/sync/bit lengths, not the gap after a block.)*

Two things came free with it: the **loading stripes** (nobody draws them — the loader is
OUT-ing to the border between samples, so once it's genuinely running you see what it
really does) and the **tape sound** (EAR is summed into the speaker on real hardware; we
model it as an OR of the two 1-bit sources in `Machine._refresh_speaker`).

**What changed, and why each file had to move:**

1. **`pulse.py`** (new) — `BlockTiming`, `data_pulses()` (pilot → sync pair → two pulses
   per bit), the dataless items (`PureTone`/`PulseSequence`/`Silence`), and `TapePlayer`.
   Pulses are generated *lazily*: a 48K game is on the order of a million of them, which
   as a list is tens of megabytes for something played once, in order.
2. **`tape.py`** — this is not a TZX-only feature, which is the thing worth remembering.
   A `.tap` needs replay too (it just uses the ROM's timings), so `TapeBlock` gained
   `timing`/`pulses()`. More importantly `TapeDeck` now holds **mixed items** and both
   loaders share **one play head**: a commercial multi-part tape starts under the ROM
   loader and hands over to its own turbo loader partway through, and separate heads
   would disagree about where the tape is.
3. **`tzx.py`** — now *keeps* the per-block timings it used to throw away, and keeps the
   dataless entries in running order. A `0x12` tone in front of a `0x14` "pure data"
   block is **one load split across two container entries**; dropping the tone loses the
   load. `parse_tzx` therefore returns all audible items, and `tape.data_blocks()`
   narrows to the ones a fast load can serve.
4. **`ula.py` / `machine.py`** — bit 6 of port 0xFE is the whole of tape input. It idles
   high, so a machine with an empty deck reads exactly what it always did. The machine
   owns the clock (`tape_tstate`, which unlike `frame_t_state` never restarts — a pause
   runs for fifty frames), feeds the player from `_io_read`, and `Machine128._io_read`
   now delegates to `super()` instead of answering the ULA directly, which would have
   silently left the 128K with no tape input at all.
5. **UI** — **Load ▸ Tape Deck**: Fast Load (on), Tape Sound, Play/Stop/Rewind/Eject.
   Fast Load has a real "off" position now, which is exactly why it was deliberately
   absent before (with no replay, "off" would just hang the ROM). Deck preferences live
   on the window, not the machine, so switching model doesn't silently re-enable them.

**The one genuinely opinionated decision: the motor does not free-run.** A real cassette
spools whether or not the Spectrum is listening, and copying that would be actively
wrong here — you spend seconds typing `LOAD ""`, and a multi-load game spends *minutes*
playing part one before asking for part two; both would eat the rest of the tape. So the
motor **starts when the machine is plainly sampling** (≥200 reads of port 0xFE in one
frame, against a few dozen for a keyboard poll — the two regimes are orders of magnitude
apart, so the threshold barely matters) and **stops at the pause ending each block**,
which is both where a person would have hit stop and what the TZX spec means by "pause".
Play/Stop/Rewind override it.

**A subtlety that bit once and would bite again:** the motor stops only at a *real* pause
(`pause_ms > 0`), never merely at an item boundary. A bare `0x12` pilot tone exists solely
to introduce the block after it and is stored with no pause between the two; stopping
there dropped up to a frame of silence into exactly the gap where the loader was hunting
for its sync pulses. `test_an_item_with_no_pause_runs_straight_into_the_next_one` pins it.

**Where it stands against real tapes** (cold boot, `LOAD ""` typed in, fast load off):
* **1942 (Elite)** — loads **completely**, all 7 blocks, ~287s emulated, screen drawn and
  game code running. This is the headline result: a commercial tape loading from nothing
  but pulses.
* **Renegade (Speedlock 4)** — plays through all 392 items and does **not** come up, but it
  gets meaningfully further than it did: before the zero-pause fix above it drew *nothing*
  (0 of 6144 screen bytes); after it, 794. The loader is clearly running rather than the
  tape spooling past it — items are consumed at their real durations — so this is a
  timing/protection detail, not a structural failure. **Next suspects**, in order: the
  `0x2A` "stop the tape in 48K mode" and `0x2B` "set signal level" blocks, which are
  currently only logged and not acted on (`0x2B` in particular sets the *starting polarity*,
  and Speedlock is exactly the kind of loader that would care); then the one-item-per-frame
  jump visible in the trace around block 389, which suggests an item occasionally being
  stepped over inside a single frame.

So: **turbo tapes are now reachable, and one class of them demonstrably works end to end.**
Speedlock specifically is not claimed.

**Testing note worth keeping.** `tests/integration/test_edge_replay.py` hands the
judgement to the ROM itself: fast load off, `LD-BYTES` called the way BASIC calls it, and
150 bytes of Sinclair's Z80 left to decode the signal. Nothing else can tell you the
timings are right. It takes ~105 frames — that isn't overhead, that's the feature; 16
bytes took two seconds on real hardware too.

*(A debugging detour worth recording: the first scratch harness ran 600 frames past the
loader's return, so the CPU executed whatever address 0xFFFF held and overwrote the very
buffer being checked — it reported a total failure while the load had been working all
along. `_run_until_the_loader_returns` stops at the return for exactly that reason.)*

## Latest session (2026-07-24) — build target, tape trap, new formats, editor navigation

**682 tests pass** (`pytest tests/unit tests/integration`).

1. **F5 assembles the file you have open**, not a hard-coded `main.asm`. The manifest's
   `main` is only a fallback now, because a folder zxide didn't scaffold names its entry
   point whatever it names it. The snapshot's name follows the source's own `savesna`
   directive too — sjasmplus has no `--sna` flag, so believing the manifest meant hunting
   for a file the assembler never wrote. See `_compile_target` in `main_window.py`.
2. **The tape trap moved to 0x0562** — see the TAP section below. This is the fix that
   made Aliens: Neoplasma II load.
3. **`.z80` and `.tzx` loading** — see item 4 of Milestone 3 below.
4. **Editor navigation**: Find in Project (Ctrl+F, results as clickable Output lines),
   Go to Line (Ctrl+G), Show in Explorer (project-tree menu), and Clear on the Output
   console's right-click menu.
5. **`main_window.py` broken up** — it had reached 1463 lines and 82 methods, owning docks,
   menus, project state, builds, media loading, debug bookkeeping and screenshots. Now
   ~1180, with three focused modules beside it: `menu_builder.py` (the menu bar as data --
   its 200 lines of `QAction` plumbing were the single biggest lump), `debug_session.py`
   (the six loose debug attributes as one object), `media.py` (format dispatch and log
   wording, Qt-free). Also deduplicated: `Project.relative()` replaced seven copies of the
   same try/except, `_refresh_all_panels()` three copies of a six-line refresh, and
   `_reveal_dock()` seven `show()`+`raise_()` pairs. 37 new tests came with it, including a
   menu-shape test — nothing about a menu fails loudly, so a dropped shortcut or an
   unconnected handler would otherwise look like a working IDE until you reached for it.
6. **Three bugs found by using the IDE, none of which raised anything:**
   * **Loading a snapshot left a paused machine paused** while logging "— running". After a
     Build & Debug breakpoint or a Pause, a loaded `.z80`/`.sna` showed its screen and then
     did nothing — which reads as a dead keyboard, not a paused emulator. It resumes now,
     as the tape path always did.
   * **The emulated keyboard was completely dead under a non-Latin keyboard layout.**
     The key maps were keyed on `event.key()`, which is layout-dependent: with a Cyrillic
     layout active the physical J key reports Cyrillic О, matching no Spectrum key, so
     *nothing* worked — you could not even type `LOAD ""` to start a tape. There is now a
     physical-position fallback (`_SCANCODE_TO_QT_KEY`), used only when the logical key
     means nothing to a Spectrum, so Latin layouts behave exactly as before. The scan-code
     offset is chosen per platform, not guessed: X11 keycodes are set-1 codes +8 and the
     ranges overlap (X11's J is set-1's Z), so trying both would hand Linux users the wrong
     letters; macOS numbering is unrelated, so the fallback is disabled there.
   * **Keys held when the emulator lost focus were never released.** A widget that loses
     focus gets no key-*release*, so pressing a menu shortcut or opening a file dialog over
     the emulator could leave a key down in the matrix forever: the ROM auto-repeats it and
     `LOAD ""` becomes untypable. `focusOutEvent` now clears the held keys.
   * The Model menu retargets the open project's manifest as well as switching the
     emulator — kept deliberately (the choice has to stick, or reopening the project
     switches back), but it now logs exactly what it changed, and the same field is
     settable directly in **Settings ▸ Project ▸ Target machine**.

   Also new: an inserted tape that goes unread for ~8s now explains itself in the Output —
   either "type LOAD ''" (nothing loaded yet) or "this game has its own turbo loader, fast
   load can't feed it" (some blocks loaded, then it stopped). A stalled tape looks identical
   either way, and the two need opposite actions.
7. **Two test-infrastructure repairs**, both pre-existing and both worth knowing about:
   `tests/` now has `__init__.py` files (an unrelated `tests` package in site-packages was
   shadowing it, so five test modules couldn't even be collected), and `tests/conftest.py`
   redirects `MainWindow`'s settings path — every MainWindow test used to write the
   developer's real `settings.json`, leaving `last_project` pointing at a deleted pytest
   tmp folder.

## Earlier session (2026-07-22) — audio bug hunt, then the debugger

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

**342 tests pass** *(at the time of that session — 682 now)*.

## Where we are

**Milestone 1 (emulator core + live PyQt5 view) is complete and working.**
- Pure-Python Z80 CPU (full instruction set incl. undocumented behaviour),
  48K memory, ULA (timing/contention/border), 8x5 keyboard.
- PyQt5 view renders the screen (bitmap + attributes + border + FLASH) via a
  numpy fast path, driven by a real-time-paced frame loop at ~50 fps.
- Boots the real 48K ROM to the 1982 copyright screen; BASIC runs; typing
  `PRINT "HELLO"` works end to end.

**Milestones 2, 3 and 4 followed** — the IDE shell and debugger, hardware and audio, and
the asset workflow. `DEV_PLAN.md` is the authority on the phase-by-phase state; this file
keeps the session-by-session narrative and the reasoning that didn't fit there.

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
  machine.py       wires it together; run_frame() = one 50Hz frame  <- read first
  memory.py        16K-bank paged model (paging-ready for 128K) + the instrumented
                   variant memory watchpoints switch on
  ula.py           port 0xFE (border/keyboard), frame timing, contention table
  keyboard.py      8x5 matrix
  mouse.py         Kempston Mouse: buttons byte + two free-running X/Y counters,
                   found at 0xFADF/0xFBDF/0xFFDF and every alias of them (only four
                   address lines are decoded). Unfitted by default
  joystick.py      Kempston Joystick: active-high switches at 0x1F, 8-bit to the ZX
                   Spectrum Next's layout (A and START only in its MD 3-button mode).
                   Unfitted by default, and exclusive with the mouse -- they share
                   the port
  memlayout.py     free space per bank, reserved ranges, and the auto-locate search
                   that places an asset where it won't collide
  sound/           beeper.py + ay.py, summed by mixer.py (the resistor network's
                   software stand-in). Sources share a 3-member contract.
                   + beeper_preview.py (audition an effect with no live machine)
  storage/         tape.py (.tap + the ROM-trap fast loader), tzx.py,
                   pulse.py (edge-level replay: blocks -> the pulse train on port 0xFE
                   bit 6, and the motor policy that decides when the tape rolls),
                   snapshot.py (.sna), z80.py (.z80 v1/v2/v3)
  assets/          manifest.py + one converter per kind (bmp/tilemap/binary/pt3/
                   beeper_sfx/native_sprite), registry.py to pick one by suffix,
                   preview.py to draw them
  debug/           disassembler.py, rom_symbols.py, debug_expr.py, analysis.py
                   -- no Qt, so the debugger's reasoning is testable headless
zxemu_ui/          shell at top level: main_window (docks + wiring), menu_builder
                   (the menu bar as data), debug_session (source map, breakpoints,
                   conditions, watchpoints), media (which loader a file needs),
                   controller, editor, theme, system_open, asset_icons, ...
  panels/          the dockable views: emulator, registers, memory cells, memory
                   map, disassembly, call stack, analysis, inspector, output_console
                   + the in-app editors (sprite_editor_view, beeper_sfx_editor_view)
  workspace/       project.py, settings*, builder.py, asset_build.py, search.py,
                   sld.py -- your project and how it gets built, as opposed to
                   the machine
  templates/       project48 / project128 starter projects; addons/ (ZX0)
tests/             unit, integration (ROM boot), zexall harness. A package (see
                   tests/__init__.py for why), with conftest.py isolating settings.
dev-support/       this file, screenshots, ZEXALL binaries (git-ignored .com)
```

Design intent: the core is UI-agnostic and the instruction handlers are
spelled out explicitly for **educational readability** (a learner can search a
mnemonic and read its code). Each package `__init__.py` is an educational
overview — start there. `main.py` is now the composition root and the emulator view
is one dockable panel among many, as this section originally predicted.

## Key decisions made

- **Fresh pure-Python emulator**, not a port of FUSE. FUSE (`E:/github/fuse`,
  GPLv2) is used only as a reference. Only the ROM binaries are reused.
- **PyQt5** UI; **numpy** for fast rendering.
- **48K first, designed for 128K** (paged memory abstraction already in place).
  *Since done: the 128K is wired up, `Machine128` + both ROMs + the AY.*
- ~~**No built-in code editor** planned — the IDE will open sources in an external
  editor.~~ **Reversed in Milestone 2:** the editor is in-app, central and multi-tab,
  with a breakpoint gutter. Only the *assembler* stayed external.
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
- ~~**Turbo tape loaders don't load.**~~ **Fixed** by edge replay (see the 2026-07-25
  session). Fast loading still can't serve them — a loader that times its own bits never
  calls the ROM routine — but turning **Load ▸ Tape Deck ▸ Fast Load** off gives them the
  real pulse train instead. The cost is real tape speed: minutes for a full game, exactly
  as on hardware. Fast load stays the default because most of the time you want the bytes,
  not the ceremony.

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
3. **TAP support** — *fast (ROM-trap) load done*. `zxemu_core/storage/tape.py` parses `.tap`
   into blocks (`parse_tap`/`TapeBlock`/`TapeDeck`) and `fast_load()` emulates the ROM's
   `LD-BYTES` by delivering a whole block at once. Hooked via a generic
   `Z80.set_trap(pc, handler)` (near-zero-cost: one int compare per step) and
   `Machine._tape_trap`, which guards on a `LD-BYTES` byte signature so it fires on the
   48K ROM and only when the 128K's 48-BASIC ROM (ROM1) is paged — correct for both
   models. **The trap address is `0x0562`, the routine's first tape sample, not its entry
   at `0x0556`** — multi-part game loaders do the preamble themselves and `CALL 0x0562`,
   so a trap on the entry never sees them and the game hangs in the ROM's edge loop
   (found via Aliens: Neoplasma II). Consequences worth knowing: the flag byte and
   LOAD/VERIFY carry are read from the **shadow `AF'`** (the preamble's `ex af,af'` put
   them there), and the trap no longer forces `EI` — BASIC's path returns through
   `SA/LD-RET` (0x053F) which does that itself, which also means pressing BREAK/SPACE
   during a load now raises `D BREAK` as on real hardware. A second fix from the same
   session: a **flag mismatch now advances the play head**. It used to leave it parked, so
   a `LOAD ""` searching for a header past somebody else's data block re-read the same
   rejected block forever (~320k times in 1942 before we caught it) — a real cassette keeps
   rolling, and that is how LOAD finds a program that isn't first on the tape.
4. **`.z80` and `.tzx` loading** ✅ — `storage/z80.py` reads v1/v2/v3 snapshots (48K and 128K,
   RLE-compressed pages, border/paging/AY restored; strict about machine model, like `.sna`).
   `storage/tzx.py` reduces the TZX container to the blocks the fast loader can serve and
   logs what it skipped. Both wired into Load Snapshot… / Load Tape… / Load Recent.
   Validated against the whole library on disk: 74/74 `.z80` load, 44/45 `.tzx` parse (the
   45th is a ZX81 tape, correctly refused by name). Turbo-loader games still need edge replay. UI: a dedicated **Build ▸ Load Tape…** item (beside Load Snapshot…) inserts a
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
