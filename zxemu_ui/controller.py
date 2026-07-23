"""EmulatorController -- drives a Machine in real time and exposes IDE controls.

In Milestone 1 the frame loop lived inside the application window: the window
*was* the emulator, so the window pumped it. As zxide becomes an IDE the emulator
is just one panel among many, so the thing that drives it has to stand on its own.

This controller is that thing. It owns the ``Machine`` and a ``QTimer``, paces
emulation against the wall clock (so the Spectrum runs at true speed regardless of
timer jitter), and offers the buttons an IDE needs -- run, pause, reset, step. It
speaks to the rest of the UI only through Qt signals:

    frame_ready(int)     emitted after each batch of emulated frames, carrying the
                         running count of *emulated* frames (real time). The view
                         connects this to its refresh(); passing the emulated-frame
                         count -- not a repaint count -- keeps FLASH/cursor blink
                         locked to real time.
    status_changed(str)  a human-readable fps / timer / emulate-ms line for the
                         status bar (this used to be written to the window title).
    running_changed(bool) run/pause transitions, so toolbar actions can enable and
                         disable themselves.

Keeping all of this out of the window means the same controller could later drive a
headless run, a test, or a second view without change.
"""

from __future__ import annotations

import time

from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal

from collections import deque

from zxemu_core.debug import analysis, debug_expr
from zxemu_core import memory as memory_module
from zxemu_core.machine import Machine

FRAME_PERIOD_S = 1.0 / 50.0  # one Spectrum frame = 1/50s of emulated time
TICK_INTERVAL_MS = 10  # poll often; real-time catch-up (not the tick rate) sets emulation speed
MAX_CATCHUP_FRAMES = 2  # cap per tick: keeps a slow machine degrading smoothly, not freezing in bursts

# Opcodes that "step over" runs to completion (they return control to the next
# instruction). CALL nn / conditional CALL, RST, and the repeating block ops.
_CALL_OPCODES = frozenset({0xC4, 0xCC, 0xD4, 0xDC, 0xE4, 0xEC, 0xF4, 0xFC})  # + 0xCD (CALL nn)
_RST_OPCODES = frozenset({0xC7, 0xCF, 0xD7, 0xDF, 0xE7, 0xEF, 0xF7, 0xFF})
_BLOCK_REPEAT_OPCODES = frozenset({0xB0, 0xB8, 0xB1, 0xB9, 0xB2, 0xBA, 0xB3, 0xBB})  # after an ED prefix
_STEP_OVER_MAX_INSTRUCTIONS = 50_000_000  # safety net: a routine that never returns can't hang the UI

# Instructions that pop a return address: RET, the eight conditional RETs, and (after
# an ED prefix) RETI/RETN. "Step out" watches for these -- see _is_ret_instruction.
_RET_OPCODES = frozenset({0xC9, 0xC0, 0xC8, 0xD0, 0xD8, 0xE0, 0xE8, 0xF0, 0xF8})
_RET_ED_OPCODES = frozenset({0x4D, 0x45})  # RETI, RETN


def _stack_unwound(sp: int, start_sp: int) -> bool:
    """Whether SP has risen above ``start_sp`` -- i.e. the stack popped past where we began.

    Not simply ``sp > start_sp``: the stack pointer is 16-bit and wraps. A routine
    entered with SP at $FFFE leaves it at $0000 after the RET pops, and a plain
    comparison reads that as "the stack went *down*" and never terminates. Comparing
    the wrapped difference against half the address space treats $0000 as just above
    $FFFE, which is what the hardware actually did.
    """
    return 0 < ((sp - start_sp) & 0xFFFF) < 0x8000


def _is_ret_instruction(memory, address: int) -> bool:
    """Whether the instruction at ``address`` is a RET of some kind."""
    opcode = memory.read_byte(address & 0xFFFF)
    if opcode in _RET_OPCODES:
        return True
    if opcode == 0xED:
        return memory.read_byte((address + 1) & 0xFFFF) in _RET_ED_OPCODES
    return False


class EmulatorController(QObject):
    """Owns a Machine and drives it at ~50 fps, with run/pause/reset/step controls."""

    frame_ready = pyqtSignal(int)  # count of emulated frames elapsed (for the view's FLASH timing)
    status_changed = pyqtSignal(str)  # fps / timer / emulate-ms readout for the status bar
    running_changed = pyqtSignal(bool)  # True when running, False when paused
    breakpoint_hit = pyqtSignal(int)  # PC address where execution stopped on a breakpoint
    watchpoint_hit = pyqtSignal(str)  # human-readable description of the access that tripped

    def __init__(self, machine: Machine, parent: QObject | None = None):
        super().__init__(parent)
        self.machine = machine
        self._running = False

        # The sound sink is created lazily in start() -- it needs a live
        # QApplication, and building it here would drag Qt audio into headless
        # tests that only construct a controller.
        self.audio = None

        # Debugging: breakpoint addresses, a private t-state clock for firing
        # interrupts while single-stepping through code, and the address to ignore
        # on the first check after resuming (so we step off a breakpoint we stopped on).
        self._breakpoints: set[int] = set()
        self._memory_watch_reads: set[int] = set()
        self._memory_watch_writes: set[int] = set()
        # {address: expression} -- a breakpoint with no entry here stops every time.
        self._breakpoint_conditions: dict[int, str] = {}
        self._temp_breakpoint: int | None = None  # one-shot, for run_to
        # Coverage and trace are both off by default: each costs work per *instruction*,
        # so they force the debug loop and must never be paid for unasked.
        self.coverage = analysis.CoverageMap()
        self._trace: deque | None = None
        self._debug_tstates = 0
        self._skip_breakpoint: int | None = None

        # Real-time pacing state (see _tick for why we pace by wall clock).
        self._emulated_frames = 0
        self._last_time = time.perf_counter()
        self._time_accumulator = 0.0

        # Live fps instrumentation, summarised once per second into status_changed.
        self._fps_window_start = self._last_time
        self._fps_frames = 0  # frames actually emulated in the current 1s window
        self._fps_ticks = 0  # timer ticks in the current window (shows the true timer rate)
        self._emulate_ms = 0.0  # summed run_frame() wall time (shows emulation cost)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)

    # --- lifecycle / controls -------------------------------------------------

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Begin ticking and running the machine (call once, after the UI is built)."""
        from zxemu_ui.audio_output import AudioOutput  # local import: needs a live QApplication

        self.audio = AudioOutput(sample_rate=self.machine.audio.sample_rate, parent=self)
        self._timer.start(TICK_INTERVAL_MS)
        self.set_running(True)  # also enables sound via _update_audio

    def set_running(self, running: bool) -> None:
        """Run or pause emulation. Resuming resets the clock so no backlog fast-forwards."""
        if running == self._running:
            return
        self._running = running
        if running:
            # Drop any time that passed while paused, so we don't try to "catch up"
            # thousands of frames the instant we resume.
            self._last_time = time.perf_counter()
            self._time_accumulator = 0.0
            # If we're sitting on a breakpoint, don't re-trigger it immediately --
            # step off it first.
            self._skip_breakpoint = self.machine.cpu.regs.pc
        else:
            self.status_changed.emit("paused")
        self._update_audio()
        self.running_changed.emit(running)

    def pause(self) -> None:
        self.set_running(False)

    def resume(self) -> None:
        self.set_running(True)

    def set_breakpoints(self, addresses) -> None:
        """Set the PC addresses at which a running machine should pause."""
        self._breakpoints = set(addresses)
        self._update_audio()  # debug runs are muted (see _update_audio)

    def set_coverage_enabled(self, on: bool) -> None:
        """Start or stop recording which addresses execute."""
        self.coverage.enabled = bool(on)
        self._update_audio()

    def set_trace_enabled(self, on: bool, length: int = 2000) -> None:
        """Start or stop the rolling execution trace, keeping the last ``length`` steps.

        A *bounded* history, not a full recording. An unbounded trace of a Spectrum
        running flat out would be millions of entries a second and would exhaust memory
        in under a minute; the last couple of thousand instructions is what you actually
        read after something goes wrong.
        """
        self._trace = deque(maxlen=length) if on else None
        self._update_audio()

    def trace_entries(self) -> list[tuple[int, int]]:
        """The recorded (address, sp) pairs, oldest first. Empty when tracing is off."""
        return list(self._trace) if self._trace is not None else []

    def run_to(self, address: int) -> None:
        """Resume, stopping at ``address`` once (a one-shot, self-removing breakpoint).

        The everyday alternative to littering code with breakpoints you then have to
        remember to remove: "just get me to there". It behaves like a real breakpoint
        while it lasts -- other breakpoints still fire on the way, and it is cleared
        whether it was reached or something else stopped first.
        """
        self._temp_breakpoint = address & 0xFFFF
        self.set_running(True)

    def set_breakpoint_conditions(self, conditions: dict) -> None:
        """Attach ``{address: expression}`` conditions; addresses absent stop unconditionally."""
        self._breakpoint_conditions = dict(conditions)

    def _breakpoint_applies(self, pc: int) -> bool:
        """Whether a breakpoint at ``pc`` should actually stop, honouring its condition.

        A condition that fails to evaluate stops anyway. Silently running past a
        breakpoint because its expression broke would be the worst possible outcome --
        you would conclude the code never runs. Stopping is the safe failure.
        """
        expression = self._breakpoint_conditions.get(pc)
        if not expression:
            return True
        try:
            return debug_expr.evaluate(expression, self.machine)
        except debug_expr.ExpressionError:
            return True

    def set_memory_watchpoints(self, writes=(), reads=()) -> None:
        """Pause when the program writes to (or reads from) any of these addresses.

        True interception, not value-change guessing: a write that stores the byte
        already there still counts, and reads can be caught too -- which is what you
        want for "who is *reading* this flag?". The cost is paid only while watchpoints
        exist; see :func:`zxemu_core.memory.install_watch` for how.
        """
        self._memory_watch_reads = set(reads)
        self._memory_watch_writes = set(writes)
        memory_module.install_watch(self.machine.memory, reads, writes)
        self._update_audio()

    def set_port_watchpoints(self, reads=(), writes=()) -> None:
        """Pause on IN/OUT of the given ports (true interception -- see Machine)."""
        self.machine.set_port_watchpoints(reads, writes)
        self._update_audio()

    @property
    def _watching(self) -> bool:
        return bool(
            self._memory_watch_reads
            or self._memory_watch_writes
            or self.machine.watch_ports_read
            or self.machine.watch_ports_write
        )

    def _check_watchpoints(self) -> str | None:
        """Return a description of any watchpoint tripped since the last check, else None."""
        port_hit = self.machine.port_watch_hit
        if port_hit is not None:
            self.machine.port_watch_hit = None
            direction = "OUT" if port_hit.is_write else "IN"
            return (
                f"{direction} port ${port_hit.port:04X} = ${port_hit.value:02X} "
                f"(near PC ${port_hit.pc:04X})"
            )
        access = memory_module.take_access(self.machine.memory)
        if access is not None:
            verb = "wrote" if access.is_write else "read"
            return (
                f"{verb} ${access.address:04X} = ${access.value:02X} "
                f"(near PC ${self.machine.cpu.regs.pc:04X})"
            )
        return None

    def _update_audio(self) -> None:
        """Enable sound only while free-running; mute during pause and debugging.

        The beeper is produced only on the fast ``run_frame`` path. While paused
        there are no frames, and while debugging we run the slower, breakpoint-
        checked loop that can't hold 50 fps -- audio there would just stutter -- so
        we mute whenever breakpoints or watchpoints are armed. Toggling the beeper also
        clears its buffered samples, so resuming never replays stale sound.
        """
        on = (
            self._running
            and not self._breakpoints
            and not self._watching
            and self._temp_breakpoint is None
            and not self._recording
        )
        self.machine.audio.enabled = on
        if self.audio is not None:
            self.audio.resume() if on else self.audio.suspend()

    def set_machine(self, machine) -> None:
        """Swap the driven machine (e.g. 48K <-> 128K when the open project changes).

        Pauses first, rebinds, and clears the debug clocks so stepping restarts clean
        on the new machine. The sound sink is rebuilt only if it already exists and
        the new machine's sample rate differs (each machine owns its own mixer); the
        real-time pacing clocks are model-independent and carry over untouched.
        """
        self.set_running(False)
        old_rate = self.machine.audio.sample_rate
        self.machine = machine
        self._debug_tstates = 0
        self._skip_breakpoint = None
        # Watchpoints belong to the machine they were set on: the instrumentation was
        # installed on the *old* Memory object, and port watches on the old Machine.
        self._memory_watch_reads = set()
        self._memory_watch_writes = set()
        if self.audio is not None and machine.audio.sample_rate != old_rate:
            self.audio.stop()
            from zxemu_ui.audio_output import AudioOutput

            self.audio = AudioOutput(sample_rate=machine.audio.sample_rate, parent=self)
        self._update_audio()

    def reset(self) -> None:
        """Reboot the machine (as if the power was cycled), repainting once."""
        self.machine.reset()
        self._emulated_frames += 1
        self.frame_ready.emit(self._emulated_frames)

    def step_frame(self) -> None:
        """Advance exactly one frame while paused -- the coarse 'step' for the IDE.

        Useful for eyeballing animation one frame at a time; step_instruction is the
        fine-grained step used by the debugger.
        """
        if self._running:
            return
        self.machine.run_frame()
        self._emulated_frames += 1
        self.frame_ready.emit(self._emulated_frames)

    def step_instruction(self) -> None:
        """Execute a single Z80 instruction while paused (the debugger's step *into*).

        Runs one cpu.step() -- no interrupt, no frame pacing -- so you can walk
        through code one opcode at a time. On a repeating block op (LDIR/CPIR/...)
        this advances a single iteration (PC rewinds to the instruction), and on a
        CALL it steps *into* the subroutine. Use step_over to run those to completion.
        Emits frame_ready so the views refresh.
        """
        if self._running:
            return
        self.machine.cpu.step()
        self.frame_ready.emit(self._emulated_frames)

    def step_over(self) -> None:
        """Step *over* the current instruction (Visual-Studio F10 semantics).

        Most instructions step exactly like step_instruction. But three kinds return
        control to the *following* instruction, and stepping into them is tedious:

          * CALL / conditional CALL and RST -- run the whole subroutine,
          * the repeating block ops (LDIR/LDDR/CPIR/.../OTDR) -- run every iteration,

        For those we run the machine until PC reaches the instruction that follows,
        with the stack unwound back to where it started (so nested calls and recursion
        don't stop us early). Interrupts fire on the normal 50Hz cadence -- a routine
        that waits on one (HALT) still proceeds -- and a breakpoint reached inside the
        stepped-over code stops us there, exactly as a real debugger would.
        """
        if self._running:
            return
        cpu = self.machine.cpu
        memory = self.machine.memory
        start_pc = cpu.regs.pc
        start_sp = cpu.regs.sp
        opcode = memory.read_byte(start_pc)
        sub_opcode = memory.read_byte((start_pc + 1) & 0xFFFF)

        if opcode == 0xED and sub_opcode in _BLOCK_REPEAT_OPCODES:
            length = 2
        elif opcode == 0xCD or opcode in _CALL_OPCODES:
            length = 3
        elif opcode in _RST_OPCODES:
            length = 1
        else:
            self.step_instruction()  # nothing to step over -- a plain single step
            return

        return_addr = (start_pc + length) & 0xFFFF
        self._run_until(
            lambda _previous_pc: cpu.regs.pc == return_addr and cpu.regs.sp >= start_sp,
            start_pc,
        )

    def step_out(self) -> None:
        """Run until the current subroutine returns (Visual-Studio Shift+F11).

        Stepping out means "finish this routine and stop at whoever called it". We
        detect that with two conditions together:

          * the stack has unwound past where it was when you asked (SP has risen), and
          * the instruction that just ran was a RET.

        The SP test alone isn't enough: a routine's epilogue often pops saved registers
        (``pop hl`` / ``pop de`` / ``ret``), and SP rises past the start on the first of
        those -- so we'd stop one or two instructions early, inside the routine we were
        trying to leave. Requiring a RET as well lands us at the caller.

        Interrupts fire normally while we run (their own push/RET pairs cancel out), and
        a breakpoint reached on the way stops us there. If you aren't inside a subroutine
        at all there is nothing to return from, and this runs until the instruction cap.
        """
        if self._running:
            return
        cpu = self.machine.cpu
        memory = self.machine.memory
        start_pc = cpu.regs.pc
        start_sp = cpu.regs.sp
        self._run_until(
            lambda previous_pc: (
                _stack_unwound(cpu.regs.sp, start_sp) and _is_ret_instruction(memory, previous_pc)
            ),
            start_pc,
        )

    def _run_until(self, should_stop, start_pc: int) -> None:
        """Single-step until ``should_stop`` or a breakpoint; the engine behind step over/out.

        ``should_stop`` is called after each instruction with the PC the instruction was
        fetched from (so a predicate can inspect what just ran without re-deriving it).
        Interrupts are driven off the private debug t-state clock, exactly as during a
        debug frame, so a routine that waits on one still proceeds.
        """
        cpu = self.machine.cpu
        frame_tstates = self.machine.frame_tstates
        hit = None
        for _ in range(_STEP_OVER_MAX_INSTRUCTIONS):
            if self._debug_tstates >= frame_tstates:
                self._debug_tstates -= frame_tstates
                cpu.maskable_interrupt()
            previous_pc = cpu.regs.pc
            self._debug_tstates += cpu.step()
            if should_stop(previous_pc):
                break
            pc = cpu.regs.pc
            if pc != start_pc and pc in self._breakpoints and self._breakpoint_applies(pc):
                hit = pc  # a breakpoint inside the code we were running through
                break
        if hit is not None:
            self.breakpoint_hit.emit(hit)
        self.frame_ready.emit(self._emulated_frames)

    # --- the frame pump -------------------------------------------------------

    def _tick(self) -> None:
        # Pace by real elapsed time rather than assuming one tick == one frame:
        # QTimer can't be trusted to fire at exactly 50Hz (Windows' ~15.6ms timer
        # granularity drags it slower), which made the emulated machine -- and so
        # the BASIC cursor blink -- run at roughly half speed. Here we run however
        # many whole frames the wall clock says are due, so emulation tracks real
        # time no matter how jittery the timer is.
        now = time.perf_counter()
        if not self._running:
            # Swallow the elapsed time while paused so resuming starts clean.
            self._last_time = now
            return

        self._time_accumulator += now - self._last_time
        self._last_time = now
        self._fps_ticks += 1

        ran = 0
        while self._time_accumulator >= FRAME_PERIOD_S and ran < MAX_CATCHUP_FRAMES:
            emulate_start = time.perf_counter()
            hit = self._run_one_frame()  # normal, or breakpoint-checked when debugging
            self._emulate_ms += (time.perf_counter() - emulate_start) * 1000.0
            self._time_accumulator -= FRAME_PERIOD_S
            self._emulated_frames += 1
            self._fps_frames += 1
            ran += 1
            if hit:  # paused on a breakpoint -- stop advancing
                break

        if self._time_accumulator > MAX_CATCHUP_FRAMES * FRAME_PERIOD_S:
            self._time_accumulator = 0.0  # fell too far behind; drop the backlog

        if ran:
            # Hand the frames' worth of mixed samples to the sound device (a no-op
            # when audio is unavailable or the sources produced nothing).
            if self.audio is not None:
                self.audio.push(self.machine.audio.take_samples())
            # FLASH/cursor timing is driven by emulated frames elapsed (real time),
            # not by how often we happen to repaint, so it blinks at the true rate.
            self.frame_ready.emit(self._emulated_frames)

        self._emit_status(now)

    def _run_one_frame(self) -> bool:
        """Run ~one frame. Returns True if it paused on a breakpoint or watchpoint."""
        if (
            not self._breakpoints
            and not self._watching
            and self._temp_breakpoint is None
            and not self._recording
        ):
            self.machine.run_frame()
            return False
        return self._run_debug_frame()

    @property
    def _recording(self) -> bool:
        """Whether coverage or trace is on -- either forces the per-instruction loop."""
        return self.coverage.enabled or self._trace is not None

    def _run_debug_frame(self) -> bool:
        """Execute ~a frame of instructions, stopping before any breakpoint PC.

        Uses a private t-state clock to fire the 50Hz interrupt, so we can stop and
        resume at any single instruction without the frame-boundary bookkeeping that
        run_frame relies on. Returns True (and pauses) if a breakpoint was reached.

        Watchpoints are checked *after* each instruction rather than before: a
        breakpoint stops you before the instruction runs, but a watchpoint is about
        something that has already happened, so you want to see the access that
        caused it.
        """
        frame_tstates = self.machine.frame_tstates  # per-model (69888 on 48K, 70908 on 128K)
        budget = 0
        while budget < frame_tstates:
            pc = self.machine.cpu.regs.pc
            if pc == self._temp_breakpoint and pc != self._skip_breakpoint:
                self._temp_breakpoint = None  # one-shot: consumed whether or not we go on
                self.breakpoint_hit.emit(pc)
                self.pause()
                return True
            if pc in self._breakpoints and pc != self._skip_breakpoint and self._breakpoint_applies(pc):
                self._temp_breakpoint = None  # something else stopped us; drop the one-shot
                self.breakpoint_hit.emit(pc)
                self.pause()
                return True
            self._skip_breakpoint = None  # only skips the first instruction after resume
            if self.coverage.enabled:
                self.coverage.mark(pc)
            if self._trace is not None:
                self._trace.append((pc, self.machine.cpu.regs.sp))
            if self._debug_tstates >= frame_tstates:
                self._debug_tstates -= frame_tstates
                self.machine.cpu.maskable_interrupt()
            elapsed = self.machine.cpu.step()
            self._debug_tstates += elapsed
            budget += elapsed
            tripped = self._check_watchpoints()
            if tripped is not None:
                self.watchpoint_hit.emit(tripped)
                self.pause()
                return True
        return False

    def _emit_status(self, now: float) -> None:
        window = now - self._fps_window_start
        if window < 1.0:
            return
        fps = self._fps_frames / window
        tick_hz = self._fps_ticks / window
        avg_emulate = self._emulate_ms / self._fps_frames if self._fps_frames else 0.0
        self.status_changed.emit(
            f"{fps:.0f} fps (target 50) | timer {tick_hz:.0f}Hz | emulate {avg_emulate:.1f}ms/frame"
        )
        self._fps_window_start = now
        self._fps_frames = 0
        self._fps_ticks = 0
        self._emulate_ms = 0.0
