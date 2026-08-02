"""EmulatorPanel -- the emulator as a self-contained IDE panel.

Rather than scatter the machine controls into a global toolbar, we group them
with the screen they act on: a small control strip (Run / Pause / Step / Reset,
then Screenshot and the Record/Stop pair) sits on top of the emulator display,
the way a media player puts its transport bar above the picture. The whole thing
is one widget you can dock, move, or resize as a unit.

Both media buttons only *ask* -- they emit a signal and MainWindow acts, because
where a screenshot or a recording gets saved is a property of the open project,
which this panel knows nothing about. The frames themselves are collected by
``zxemu_ui/recorder.py``, hooked straight into the emulation loop.

Two pieces live here:

    EmulatorStage  hosts the EmulatorView and sizes it responsively -- a share of
                   the available height (default ~1/3), centred, and always at the
                   Spectrum's 5:4 (320:256) aspect ratio so pixels never distort.
    EmulatorPanel  stacks the control strip above the stage and wires the controls
                   to an EmulatorController, keeping the buttons' enabled state in
                   step with whether the machine is running or paused.

The panel also owns **fullscreen** (``toggle_fullscreen``), because it owns the stage:
going fullscreen lends that one widget to a bare window (``fullscreen_stage.py``) and
takes it back afterwards. Nothing is rebuilt, so the running machine is undisturbed.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, QPointF, QRectF, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QHBoxLayout,
    QLabel,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from zxemu_ui.controller import EmulatorController
from zxemu_ui.panels.emulator_view import FULL_HEIGHT, FULL_WIDTH, EmulatorView
from zxemu_ui.panels.fullscreen_stage import FullScreenStage


def camera_icon(color: QColor, size: int = 32) -> QIcon:
    """A minimal outline camera glyph for the Screenshot button.

    Stock Qt ships no camera icon -- its nearest save glyph is a diskette
    (SP_DialogSaveButton), which reads as "save machine state" and is better kept
    for a Save Snapshot action. This draws a small camera instead, in the caller's
    chosen colour so it tracks the theme.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    pen = QPen(color)
    pen.setWidthF(max(1.0, size / 12.0))
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    s = size
    body = QRectF(0.10 * s, 0.34 * s, 0.80 * s, 0.50 * s)
    painter.drawRoundedRect(body, 0.07 * s, 0.07 * s)
    viewfinder = QRectF(0.33 * s, 0.23 * s, 0.24 * s, 0.13 * s)
    painter.drawRoundedRect(viewfinder, 0.03 * s, 0.03 * s)
    lens_center = QPointF(0.50 * s, 0.60 * s)
    painter.drawEllipse(lens_center, 0.16 * s, 0.16 * s)
    painter.drawEllipse(lens_center, 0.06 * s, 0.06 * s)
    painter.end()
    return QIcon(pixmap)


#: The record dot stays red whatever the theme. Every recorder ever built uses a red dot,
#: and a themed one would be the only control on the bar you had to stop and read.
_RECORD_RED = QColor("#e04b4b")

#: Width reserved for the "● REC nnn frames (n.n s)" readout. Fixed rather than fitted, so
#: neither the counter ticking up nor the readout appearing at all moves the buttons.
_RECORD_READOUT_WIDTH = 170


def record_icon(size: int = 32) -> QIcon:
    """The filled red dot that means "start recording"."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(_RECORD_RED)
    painter.drawEllipse(QPointF(0.5 * size, 0.5 * size), 0.30 * size, 0.30 * size)
    painter.end()
    return QIcon(pixmap)


def stop_icon(color: QColor, size: int = 32) -> QIcon:
    """The filled square that means "stop recording", in the caller's colour.

    Drawn in the theme's text colour rather than literally black: on a dark theme a black
    square on a dark bar is an invisible button, and the shape is what carries the meaning.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawRect(QRectF(0.24 * size, 0.24 * size, 0.52 * size, 0.52 * size))
    painter.end()
    return QIcon(pixmap)


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

    #: Emitted when "Screenshot" is clicked -- MainWindow owns the project (and so
    #: where a screenshot gets saved), so it does the actual saving.
    screenshot_requested = pyqtSignal()

    #: Emitted by the red dot and the stop square. Same division of labour as the
    #: screenshot: the panel offers the buttons, the window knows where recordings go.
    record_requested = pyqtSignal()
    stop_record_requested = pyqtSignal()

    #: Emitted when fullscreen is entered (True) or left (False), so the window can keep
    #: a checkable menu item in step with a state the user can also leave by pressing Esc.
    fullscreen_changed = pyqtSignal(bool)

    def __init__(self, view: EmulatorView, controller: EmulatorController, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._view = view
        self._stage = EmulatorStage(view)
        self._fullscreen: FullScreenStage | None = None

        self._build_actions()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_control_bar())
        self._layout = layout
        layout.addWidget(self._stage, 1)  # the stage soaks up the remaining space

        self.controller.running_changed.connect(self._on_running_changed)
        self._on_running_changed(self.controller.running)

    # --- fullscreen -----------------------------------------------------------

    @property
    def is_fullscreen(self) -> bool:
        return self._fullscreen is not None

    def toggle_fullscreen(self) -> None:
        self.exit_fullscreen() if self.is_fullscreen else self.enter_fullscreen()

    def enter_fullscreen(self) -> None:
        """Lend the stage to a bare fullscreen window (see ``fullscreen_stage.py``)."""
        if self.is_fullscreen:
            return
        self._fullscreen = FullScreenStage(self._stage, near=self)
        self._fullscreen.closing.connect(self._reclaim_stage)
        self._fullscreen.showFullScreen()
        # Focus follows the picture: a fullscreen emulator you have to click first would
        # look broken, since there is nothing else on screen to click.
        self._view.setFocus(Qt.OtherFocusReason)
        self.fullscreen_changed.emit(True)

    def exit_fullscreen(self) -> None:
        if self._fullscreen is not None:
            self._fullscreen.close()  # closeEvent -> closing -> _reclaim_stage

    def _reclaim_stage(self) -> None:
        """Take the stage back into the panel. The only way out of fullscreen.

        Every exit route (Esc, the menu, Alt+Enter, the window manager) ends in the
        window closing, so putting the stage back here means no route can lose it.
        """
        window, self._fullscreen = self._fullscreen, None
        if window is None:
            return
        self._layout.addWidget(self._stage, 1)
        window.deleteLater()
        self._view.setFocus(Qt.OtherFocusReason)
        self.fullscreen_changed.emit(False)

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
        self.step_action = QAction(style.standardIcon(QStyle.SP_ArrowDown), "Step Into", self)
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

        self.screenshot_action = QAction(camera_icon(self.palette().color(QPalette.ButtonText)), "Screenshot", self)
        self.screenshot_action.setToolTip("Save a screenshot (.scr + .bmp) to the project's screenshots folder")
        self.screenshot_action.triggered.connect(self.screenshot_requested)

        # Recording: a transport pair rather than one toggle, so the button under the
        # pointer never changes meaning between the glance and the click.
        self.record_action = QAction(record_icon(), "Record", self)
        self.record_action.setToolTip("Record every frame, for export as an animated GIF")
        self.record_action.triggered.connect(self.record_requested)

        self.stop_record_action = QAction(stop_icon(self.palette().color(QPalette.ButtonText)), "Stop Recording", self)
        self.stop_record_action.setToolTip("Stop recording and save the animation")
        self.stop_record_action.triggered.connect(self.stop_record_requested)
        self.stop_record_action.setEnabled(False)

    def _build_control_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("emulatorControlBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)
        row.addStretch()
        # A blank twin of the recording readout, shown and hidden with it. Without it the
        # readout appearing would shove the whole transport left by half its width -- moving
        # Stop out from under the pointer at the exact moment you have just pressed Record.
        self._record_spacer = QWidget()
        self._record_spacer.hide()
        row.addWidget(self._record_spacer)
        actions = (self.run_action, self.pause_action, self.step_action,
                   self.step_over_action, self.step_out_action, self.frame_action,
                   self.reset_action, self.screenshot_action,
                   self.record_action, self.stop_record_action)
        for action in actions:
            button = QToolButton()
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            row.addWidget(button)
        # A running frame count, hidden until recording starts. Without it there is no way
        # to tell a recording in progress from a button that did nothing -- and no warning
        # that you are approaching the frame cap until you hit it. Fixed-width so the
        # numbers ticking up never re-lay-out the bar (see _record_spacer above).
        self._record_label = QLabel()
        self._record_label.setStyleSheet("color: {}".format(_RECORD_RED.name()))
        self._record_label.setFixedWidth(_RECORD_READOUT_WIDTH)
        self._record_spacer.setFixedWidth(_RECORD_READOUT_WIDTH)
        self._record_label.hide()
        row.addWidget(self._record_label)
        row.addStretch()
        return bar

    # --- recording state ------------------------------------------------------

    def set_recording(self, recording: bool) -> None:
        """Swap the transport pair over and show or hide the frame counter."""
        self.record_action.setEnabled(not recording)
        self.stop_record_action.setEnabled(recording)
        self._record_label.setVisible(recording)
        self._record_spacer.setVisible(recording)  # keeps the buttons where they were
        if not recording:
            self._record_label.clear()

    def set_recorded_frames(self, frames: int) -> None:
        """Update the "recording" readout; called once per frame batch, so it does nothing
        unless the tenth of a second it displays has actually changed."""
        text = "● REC  {} frames ({:.1f}s)".format(frames, frames / 50.0)
        if text != self._record_label.text():
            self._record_label.setText(text)

    def _on_running_changed(self, running: bool) -> None:
        """Run only when paused; Pause only when running; stepping only while paused."""
        self.run_action.setEnabled(not running)
        self.pause_action.setEnabled(running)
        self.step_action.setEnabled(not running)
        self.step_over_action.setEnabled(not running)
        self.step_out_action.setEnabled(not running)
        self.frame_action.setEnabled(not running)
