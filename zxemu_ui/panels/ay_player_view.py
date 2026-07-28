"""The music player: play a file, watch the chip, drag it out of the window if you like.

Playback itself lives in the core (``zxemu_core.sound.ay_module_player``) and knows nothing
about Qt: it hands over one frame of PCM at a time. This panel is the clock and the face --
a 50Hz timer pulling frames, an audio sink to hear them, and a small display of what the AY
is doing while they go past.

**What the display can honestly show.** These formats are Z80 programs, not note lists (see
``ay_program.py``), so there is no pattern, no row and no position to display -- nobody
knows them, including the program itself in any way we could read. What *is* knowable is the
chip: three channels, each with a volume, a tone period, whether tone and noise are mixed
in, and whether the envelope generator is driving it. That is what is drawn, because it is
what is true.

**Being poppable is free.** This is a ``QDockWidget`` like every other panel, so dragging its
title bar out of the window makes it a floating window -- no separate code path, and it
keeps the same behaviour as the rest of the IDE.
"""

from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from zxemu_core.sound import music_file
from zxemu_core.sound.ay_module_player import AyModulePlayer, RoutineDidNotReturn

FRAME_S = 0.02  # 50Hz, the rate the music itself is written for

#: How often the timer *wakes*, which is not the frame rate. It ticks faster than 50Hz and
#: renders however many frames real time says are due, because a QTimer asked for 20ms on
#: Windows fires at the system's ~15.6ms granularity and therefore drifts *slow* -- about
#: 47 frames a second, which starves the audio device and is heard as stuttering. The
#: emulator's own loop hit this and solved it the same way; see ``controller._tick``.
TICK_MS = 8

#: Frames rendered ahead before playback starts. The device wants a continuous stream from
#: its first read, and rendering costs ~5ms a frame, so starting empty means the first
#: buffer is half-filled from a standing start and the tune opens with a stumble.
PRIME_FRAMES = 6

#: Ceiling on catch-up in one wake-up. Without it, a stall (a build, a breakpoint, the
#: machine swapping) is repaid by rendering hundreds of frames at once -- which freezes the
#: UI and fast-forwards the music. Dropping the backlog is the lesser evil: audio that
#: skipped is better than an IDE that hung.
MAX_CATCHUP = 4

#: One colour per channel, warm to cool left to right, so a glance tells you which is which
#: without a legend taking up the height of a bar.
_CHANNEL_COLOURS = ("#e8913a", "#4aa3df", "#7ac74f")
_LABELS = ("A", "B", "C")


class ChannelMeter(QWidget):
    """Three bars: per-channel volume, with what the mixer and envelope are doing.

    Reads the AY's register file directly rather than being fed a summary, because the
    register file *is* the state -- anything in between would be a second copy to keep
    honest, and this only ever reads.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(72)
        self._ay = None

    def watch(self, ay) -> None:
        self._ay = ay
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))
        if self._ay is None:
            painter.setPen(QColor("#666"))
            painter.drawText(self.rect(), Qt.AlignCenter, "nothing playing")
            return

        registers = self._ay._reg
        mixer = registers[7]
        width = self.width() / 3.0
        for channel in range(3):
            raw = registers[8 + channel]
            # Bit 4 means "this channel follows the envelope generator". Its low bits are
            # then meaningless, so a meter reading them would jitter at random -- an
            # envelope-driven channel is drawn at full height in a paler shade instead.
            envelope = bool(raw & 0x10)
            volume = 15 if envelope else (raw & 0x0F)
            tone_on = not (mixer >> channel) & 1
            noise_on = not (mixer >> (channel + 3)) & 1

            colour = QColor(_CHANNEL_COLOURS[channel])
            if envelope:
                colour = colour.lighter(140)
            if not (tone_on or noise_on):
                colour = QColor("#3a3a3a")  # silent: mixed out entirely, whatever the volume

            left = channel * width + 6
            bar_width = width - 12
            full = self.height() - 22
            # An empty slot behind every bar, always. Without it a silent channel draws
            # nothing at all, which reads as "no data" rather than "not playing" -- and
            # those look identical exactly when you are trying to tell them apart.
            painter.fillRect(int(left), 6, int(bar_width), int(full), QColor("#2a2a2a"))
            height = int(full * volume / 15.0)
            if height:
                painter.fillRect(int(left), int(6 + full - height), int(bar_width), int(height), colour)

            painter.setPen(QColor("#999"))
            period = registers[channel * 2] | ((registers[channel * 2 + 1] & 0x0F) << 8)
            painter.drawText(int(left), self.height() - 6, _caption(_LABELS[channel], tone_on, noise_on, envelope, period))


class AyPlayerView(QWidget):
    """Play/stop, the song list for multi-song files, and the meter.

    Holds no emulator of its own: each play builds a fresh private machine inside
    ``AyModulePlayer`` and throws it away on stop, so nothing here can disturb the emulator
    the user is debugging with.
    """

    def __init__(self, audio, parent=None):
        super().__init__(parent)
        self.audio = audio
        self._player = None
        self._path = ""
        self._data = b""
        self._playable = False
        self._players = ()  # detected tracker player binaries, set by the window

        self._title = QLabel("No music loaded")
        self._title.setWordWrap(True)
        self._detail = QLabel("")
        self._detail.setStyleSheet("color: #999;")
        self._detail.setWordWrap(True)

        self._songs = QComboBox()
        self._songs.setVisible(False)  # only .ay files hold more than one tune
        self._songs.currentIndexChanged.connect(self._song_changed)

        # Play and Stop as two buttons rather than one that changes its label. A toggle
        # makes you read the button to find out what is happening; a pair shows it, and
        # "stop" is the one you reach for in a hurry.
        self._play_button = QPushButton("Play")
        self._play_button.clicked.connect(self.play)
        self._play_button.setEnabled(False)

        self._stop_button = QPushButton("Stop")
        self._stop_button.clicked.connect(self.stop)
        self._stop_button.setEnabled(False)

        # Shown only when a file cannot play for want of a player. A dead Play button with
        # an explanation is still a dead end -- the user has the file, and the shortest path
        # from "I have it" to "it plays" is a button that asks where.
        self._find_button = QPushButton("Find player…")
        self._find_button.setVisible(False)
        self._find_button.clicked.connect(self._locate_player)
        #: Set by the window: called with a chosen path, returns the players now available.
        self.on_locate_player = None

        self._meter = ChannelMeter()

        controls = QHBoxLayout()
        controls.addWidget(self._play_button)
        controls.addWidget(self._stop_button)
        controls.addWidget(self._find_button)
        controls.addWidget(self._songs, 1)
        # Keeps the button its own size when the song list is hidden, which is every format
        # but .ay -- otherwise it stretches across the panel and looks like a text field.
        controls.addStretch(0)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._detail)
        layout.addLayout(controls)
        layout.addWidget(self._meter, 1)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._last_time = 0.0
        self._accumulator = 0.0

    # --- loading ------------------------------------------------------------------

    def set_player_binaries(self, players) -> None:
        """Hand over whatever tracker players were found, for raw .pt2/.pt3 modules."""
        self._players = players

    def load(self, path: str, data: bytes) -> None:
        """Show a music file and get ready to play it. Does not start playing."""
        self.stop()
        self._path, self._data = path, data
        info = music_file.describe(path, data, self._players)

        self._title.setText(info["title"] or path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
        self._detail.setText(_detail_line(info))
        self._playable = bool(info["playable"])
        self._play_button.setEnabled(self._playable)
        # Offered exactly when it would help: a real module that only lacks its player.
        self._find_button.setVisible(bool(info.get("needs_player")) and not info["playable"])

        songs = info.get("songs") or []
        self._songs.blockSignals(True)
        self._songs.clear()
        self._songs.addItems(songs)
        self._songs.setVisible(len(songs) > 1)
        self._songs.blockSignals(False)

    # --- transport ----------------------------------------------------------------

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override name)
        """Stop the moment the panel goes away -- closing the popup means "stop".

        Closing a floating dock hides its contents rather than destroying them, so without
        this the timer keeps running and the tune plays on from a panel that is no longer
        on screen: audible, unattributable, and stoppable only by finding the panel again.
        Qt sends this to a widget when it is hidden, not when the main window is merely
        minimised, so a minimised IDE keeps playing -- which is what you want.
        """
        self.stop()
        super().hideEvent(event)

    def toggle(self) -> None:
        self.stop() if self._timer.isActive() else self.play()

    def play(self) -> None:
        if not self._data:
            return
        try:
            program = music_file.open_music(self._path, self._data, self._players, song=max(0, self._songs.currentIndex()))
            self._player = AyModulePlayer(program)
        except (music_file.CannotPlay, RoutineDidNotReturn) as problem:
            # Both are ordinary outcomes for files this cannot know about in advance: an
            # unsupported song, or a blob whose entry points turned out not to be code.
            self._detail.setText(str(problem))
            self._play_button.setEnabled(False)
            return
        self._meter.watch(self._player.machine.ay)
        if self.audio is not None:
            self.audio.resume()
            for _ in range(PRIME_FRAMES):
                self.audio.push(self._player.render_frame())
        self._last_time = time.perf_counter()
        self._accumulator = 0.0
        self._timer.start()
        self._play_button.setEnabled(False)
        self._stop_button.setEnabled(True)

    def stop(self) -> None:
        """Stop and let go of the machine. Safe to call when nothing is playing."""
        self._timer.stop()
        self._stop_button.setEnabled(False)
        # Not "is a file loaded" -- a raw module with no player found is loaded and still
        # unplayable, and re-enabling Play here would undo what ``load`` worked out.
        self._play_button.setEnabled(self._playable)
        if self.audio is not None:
            self.audio.suspend()
        self._player = None
        self._meter.watch(None)

    def _locate_player(self) -> None:
        """Ask for a player binary, check it really is one, and remember where it lives.

        The chosen file is verified before being accepted (see ``identify_player``) rather
        than trusted, so picking the wrong ``.bin`` says so instead of producing a machine
        that executes it and screams.
        """
        if self.on_locate_player is None:
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Find a PT2/PT3 player", "", "Player binary (*.bin);;All files (*)",
            options=QFileDialog.DontUseNativeDialog,
        )
        if not chosen:
            return
        players = self.on_locate_player(chosen)
        if not players:
            self._detail.setText("That file is not a player this can use -- expected something like pt3_c000.bin.")
            return
        self.set_player_binaries(players)
        self.load(self._path, self._data)  # re-describe: it may be playable now

    def _song_changed(self, _index: int) -> None:
        """Picking another tune restarts, since a song *is* a differently-initialised run."""
        if self._timer.isActive():
            self.play()

    def _tick(self) -> None:
        """Render however many frames real time says are owed -- not one per wake-up.

        The distinction is the whole fix: at one frame per tick the music plays at whatever
        rate the OS happens to deliver timer events, which on Windows is slower than asked
        and audibly wrong. Measuring elapsed time instead makes the tune's speed independent
        of the timer's accuracy.
        """
        if self._player is None:
            return
        now = time.perf_counter()
        self._accumulator += now - self._last_time
        self._last_time = now

        rendered = 0
        while self._accumulator >= FRAME_S and rendered < MAX_CATCHUP:
            try:
                samples = self._player.render_frame()
            except RoutineDidNotReturn as problem:
                self._detail.setText(str(problem))
                self.stop()
                return
            if self.audio is not None:
                self.audio.push(samples)
            self._accumulator -= FRAME_S
            rendered += 1

        if self._accumulator > MAX_CATCHUP * FRAME_S:
            self._accumulator = 0.0  # fell too far behind to catch up; drop the backlog
        if rendered:
            self._meter.update()


def _caption(label: str, tone_on: bool, noise_on: bool, envelope: bool, period: int) -> str:
    """What a channel is doing, in words rather than punctuation.

    An earlier version wrote this as sigils -- ``A~E`` for "noise, envelope, no tone" --
    which is compact and unreadable: it looks like damage rather than information, and the
    one channel most likely to show it is the drum channel, so it is the first thing anyone
    notices. Words cost a few pixels and explain themselves.

    A channel with no tone and no noise is mixed out entirely, whatever its volume says,
    which is worth stating plainly too -- it is why a bar can stand at full height in
    silence.
    """
    parts = []
    if tone_on:
        parts.append(str(period))
    if noise_on:
        parts.append("noise")
    if not parts:
        parts.append("off")
    if envelope:
        parts.append("env")
    return "{}  {}".format(label, " ".join(parts))


def _detail_line(info: dict) -> str:
    parts = [info["kind"], "{} bytes".format(info["size"])]
    if info.get("author"):
        parts.append(info["author"])
    if info["detail"]:
        parts.append(info["detail"])
    return "  ·  ".join(parts)
