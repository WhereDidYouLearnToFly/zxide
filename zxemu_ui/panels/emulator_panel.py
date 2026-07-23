"""EmulatorPanel -- the emulator as a self-contained IDE panel.

Rather than scatter the machine controls into a global toolbar, we group them
with the screen they act on: a small control strip (Run / Pause / Step / Reset)
sits on top of the emulator display, the way a media player puts its transport
bar above the picture. The whole thing is one widget you can dock, move, or
resize as a unit.

Two pieces live here:

    EmulatorStage  hosts the EmulatorView and sizes it responsively -- a share of
                   the available height (default ~1/3), centred, and always at the
                   Spectrum's 5:4 (320:256) aspect ratio so pixels never distort.
    EmulatorPanel  stacks the control strip above the stage and wires the controls
                   to an EmulatorController, keeping the buttons' enabled state in
                   step with whether the machine is running or paused.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAction,
    QHBoxLayout,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from zxemu_ui.controller import EmulatorController
from zxemu_ui.panels.emulator_view import FULL_HEIGHT, FULL_WIDTH, EmulatorView


class EmulatorStage(QWidget):
    """Fits the emulator view to whatever space its dock gives it.

    The view is scaled to the largest 5:4 (320:256) rectangle that fits the
    available area and centred, so the picture fills the emulator dock without
    distortion and grows/shrinks as the user drags the dock's borders.
    """

    ASPECT = FULL_WIDTH / FULL_HEIGHT  # 320/256 = 1.25

    def __init__(self, view: EmulatorView, parent=None):
        super().__init__(parent)
        self._view = view
        self._view.setParent(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        # Clicking anywhere on the emulator -- including the letterbox margins around
        # the aspect-locked screen -- gives the view keyboard focus, so a slightly
        # off-target click can't leave the Spectrum unable to "hear" the keyboard.
        self._view.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        self._layout_view()

    def _layout_view(self) -> None:
        avail_w, avail_h = self.width(), self.height()
        if avail_w <= 0 or avail_h <= 0:
            return
        # Largest aspect-locked rectangle that fits inside the available area.
        target_w = avail_w
        target_h = round(target_w / self.ASPECT)
        if target_h > avail_h:
            target_h = avail_h
            target_w = round(target_h * self.ASPECT)
        x = (avail_w - target_w) // 2
        y = (avail_h - target_h) // 2
        self._view.setGeometry(x, y, target_w, target_h)


class EmulatorPanel(QWidget):
    """Control strip (Run/Pause/Step/Reset) stacked above the emulator screen."""

    def __init__(self, view: EmulatorView, controller: EmulatorController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._stage = EmulatorStage(view)

        self._build_actions()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_control_bar())
        layout.addWidget(self._stage, 1)  # the stage soaks up the remaining space

        self.controller.running_changed.connect(self._on_running_changed)
        self._on_running_changed(self.controller.running)

    # --- controls -------------------------------------------------------------

    def _build_actions(self) -> None:
        style = self.style()
        self.run_action = QAction(style.standardIcon(QStyle.SP_MediaPlay), "Run", self)
        self.run_action.setToolTip("Run / continue (to the next breakpoint)")
        self.run_action.triggered.connect(self.controller.resume)

        self.pause_action = QAction(style.standardIcon(QStyle.SP_MediaPause), "Pause", self)
        self.pause_action.setToolTip("Pause execution")
        self.pause_action.triggered.connect(self.controller.pause)

        # Debugger step into: one Z80 instruction at a time (one LDIR iteration, or
        # into a called subroutine).
        self.step_action = QAction(style.standardIcon(QStyle.SP_MediaSeekForward), "Step Into", self)
        self.step_action.setToolTip("Step one instruction — into calls, one block-op iteration (F11)")
        self.step_action.setShortcut("F11")
        self.step_action.triggered.connect(self.controller.step_instruction)

        # Step over: run CALLs/RSTs and repeating block ops (LDIR/...) to completion,
        # stopping at the next instruction in the current routine.
        self.step_over_action = QAction(style.standardIcon(QStyle.SP_ArrowForward), "Step Over", self)
        self.step_over_action.setToolTip("Step over calls and block ops — run them to completion (F10)")
        self.step_over_action.setShortcut("F10")
        self.step_over_action.triggered.connect(self.controller.step_over)

        # Step out: finish the current subroutine and stop at whoever called it.
        self.step_out_action = QAction(style.standardIcon(QStyle.SP_ArrowUp), "Step Out", self)
        self.step_out_action.setToolTip("Run until the current subroutine returns (Shift+F11)")
        self.step_out_action.setShortcut("Shift+F11")
        self.step_out_action.triggered.connect(self.controller.step_out)

        # Coarser step: a whole 50Hz frame (handy for eyeballing animation).
        self.frame_action = QAction(style.standardIcon(QStyle.SP_MediaSkipForward), "Frame", self)
        self.frame_action.setToolTip("Advance one frame (while paused)")
        self.frame_action.triggered.connect(self.controller.step_frame)

        self.reset_action = QAction(style.standardIcon(QStyle.SP_BrowserReload), "Reset", self)
        self.reset_action.setToolTip("Reboot the machine")
        self.reset_action.triggered.connect(self.controller.reset)

    def _build_control_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("emulatorControlBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        row.addStretch()
        actions = (self.run_action, self.pause_action, self.step_action,
                   self.step_over_action, self.step_out_action, self.frame_action,
                   self.reset_action)
        for action in actions:
            button = QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            row.addWidget(button)
        row.addStretch()
        return bar

    def _on_running_changed(self, running: bool) -> None:
        """Run only when paused; Pause only when running; stepping only while paused."""
        self.run_action.setEnabled(not running)
        self.pause_action.setEnabled(running)
        self.step_action.setEnabled(not running)
        self.step_over_action.setEnabled(not running)
        self.step_out_action.setEnabled(not running)
        self.frame_action.setEnabled(not running)
