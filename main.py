"""Entry point: boots the 48K ROM and shows a live emulator view in a window."""

from __future__ import annotations

import importlib.resources as res
import sys
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QMainWindow

from zxemu_core.machine import Machine
from zxemu_ui.emulator_view import EmulatorView

FRAME_PERIOD_S = 1.0 / 50.0  # one Spectrum frame = 1/50s of emulated time
TICK_INTERVAL_MS = 10  # poll often; real-time catch-up (not the tick rate) sets emulation speed
MAX_CATCHUP_FRAMES = 2  # cap per tick: keeps a slow machine degrading smoothly, not freezing in bursts


def load_48_rom() -> bytes:
    return (res.files("zxemu_core") / "roms" / "48.rom").read_bytes()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("zxide")
        self.machine = Machine(load_48_rom())
        self.view = EmulatorView(self.machine)
        self.setCentralWidget(self.view)

        self._emulated_frames = 0
        self._last_time = time.perf_counter()
        self._time_accumulator = 0.0

        # --- live FPS instrumentation (shown in the title bar) ---
        self._fps_window_start = self._last_time
        self._fps_frames = 0  # frames actually emulated in the current 1s window
        self._fps_ticks = 0  # timer ticks in the current window (shows timer rate)
        self._emulate_ms = 0.0  # summed run_frame() wall time (shows emulation cost)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TICK_INTERVAL_MS)

    def _tick(self) -> None:
        # Pace by real elapsed time rather than assuming one tick == one frame:
        # QTimer can't be trusted to fire at exactly 50Hz (Windows' ~15.6ms timer
        # granularity drags it slower), which made the emulated machine -- and so
        # the BASIC cursor blink -- run at roughly half speed. Here we run however
        # many whole frames the wall clock says are due, so emulation tracks real
        # time no matter how jittery the timer is.
        now = time.perf_counter()
        self._time_accumulator += now - self._last_time
        self._last_time = now
        self._fps_ticks += 1

        ran = 0
        while self._time_accumulator >= FRAME_PERIOD_S and ran < MAX_CATCHUP_FRAMES:
            emulate_start = time.perf_counter()
            self.machine.run_frame()
            self._emulate_ms += (time.perf_counter() - emulate_start) * 1000.0
            self._time_accumulator -= FRAME_PERIOD_S
            self._emulated_frames += 1
            self._fps_frames += 1
            ran += 1

        if self._time_accumulator > MAX_CATCHUP_FRAMES * FRAME_PERIOD_S:
            self._time_accumulator = 0.0  # fell too far behind; drop the backlog

        if ran:
            # FLASH/cursor timing is driven by emulated frames elapsed (real time),
            # not by how often we happen to repaint, so it blinks at the true rate.
            self.view.refresh(self._emulated_frames)

        self._update_fps_title(now)

    def _update_fps_title(self, now: float) -> None:
        window = now - self._fps_window_start
        if window < 1.0:
            return
        fps = self._fps_frames / window
        tick_hz = self._fps_ticks / window
        avg_emulate = self._emulate_ms / self._fps_frames if self._fps_frames else 0.0
        self.setWindowTitle(
            f"zxide — {fps:.0f} fps (target 50) | timer {tick_hz:.0f}Hz | "
            f"emulate {avg_emulate:.1f}ms/frame"
        )
        self._fps_window_start = now
        self._fps_frames = 0
        self._fps_ticks = 0
        self._emulate_ms = 0.0


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
