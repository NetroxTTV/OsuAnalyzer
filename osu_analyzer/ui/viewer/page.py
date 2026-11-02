"""Replay Viewer page: header, stage, seek bar and transport controls."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QStackedLayout, QVBoxLayout, QWidget

from ...core import settings
from .. import icons
from ..widgets import (Button, Chip, ComboBox, EmptyState, PlayButton, SegmentedControl, VolumeSlider, hbox,
                       label)
from .playback import Playback
from .scene import ReplayScene
from .seekbar import SeekBar, fmt_time
from .stage import Stage

SPEEDS = [(0.25, "0.25×"), (0.5, "0.5×"), (0.75, "0.75×"), (1.0, "1×"), (1.5, "1.5×"), (2.0, "2×")]
BG_DIM = 0.16
SHORTCUTS = "Space  play / pause     ← →  ±1 s     , .  frame by frame     N / P  next / previous miss     M  mute"


class ViewerPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.analyses = []
        self.scene = None
        self.playback = Playback(self)

        self.stack = QStackedLayout(self)
        self.empty = EmptyState(icons.VIDEO, "Replay Viewer",
                                "Pick a replay on the left to watch it with the beatmap's music.")
        self.stack.addWidget(self.empty)
        content = QWidget()
        self.stack.addWidget(content)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(24, 18, 24, 14)
        lay.setSpacing(12)

        # Header: map, player and mods; a picker when several replays are combined
        self.title = label("", "h2")
        self.player = Chip("")
        self.mods = Chip("")
        self.info = label("", "caption")
        self.picker = ComboBox()
        self.picker.setMinimumWidth(360)
        self.picker.currentIndexChanged.connect(self._pick)
        head = QVBoxLayout()
        head.setSpacing(6)
        head.addWidget(self.title)
        head.addLayout(hbox(self.player, self.mods, 4, self.info, None, spacing=6))
        top = hbox(spacing=16)
        top.addLayout(head, 1)
        top.addWidget(self.picker, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        self.stage = Stage()
        self.stage.set_bg_dim(settings.get("bg_dim", BG_DIM))
        lay.addWidget(self.stage, 1)

        self.seekbar = SeekBar()
        self.seekbar.seekRequested.connect(self.playback.seek)
        lay.addWidget(self.seekbar)

        # Transport
        prev_miss = Button("Miss", icons.PREVIOUS, "ghost")
        prev_miss.setToolTip("Previous miss (P)")
        prev_miss.clicked.connect(self.playback.prev_miss)
        self.play = PlayButton()
        self.play.clicked.connect(self._toggle_clicked)
        next_miss = Button("Miss", icons.NEXT, "ghost")
        next_miss.setToolTip("Next miss (N)")
        next_miss.clicked.connect(self.playback.next_miss)
        self.time_now = label("0:00.000", "metric-sm")
        self.time_total = label("/ 0:00.000", "muted")
        self.speed = SegmentedControl(SPEEDS, 1.0, height=30, font_size=9)
        self.speed.changed.connect(self.playback.set_speed)
        self.volume = VolumeSlider(settings.get("volume", 0.5))
        self.volume.changed.connect(lambda eff: self.playback.set_volume(eff, self.volume.value))
        lay.addLayout(hbox(prev_miss, self.play, next_miss, 18, self.time_now, self.time_total, None,
                           self.speed, 20, self.volume, spacing=6))

        self.audio = label("", "caption")
        lay.addLayout(hbox(label(SHORTCUTS, "caption"), None, self.audio))

        pb = self.playback
        pb.timeChanged.connect(self._on_time)
        pb.playingChanged.connect(self.play.setChecked)
        pb.audioStatusChanged.connect(lambda text: self.audio.setText(f"♪  {text}" if text else ""))

        self._shortcuts = []
        for key, action in (("Space", pb.toggle), ("Left", lambda: pb.seek(pb.t - 1000)),
                            ("Right", lambda: pb.seek(pb.t + 1000)), (",", lambda: pb.step(-1)),
                            (".", lambda: pb.step(1)), ("N", pb.next_miss), ("P", pb.prev_miss),
                            ("M", self.volume.toggle_mute)):
            sc = QShortcut(QKeySequence(key), self, context=Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(action)
            sc.setEnabled(False)
            self._shortcuts.append(sc)

    # ---------------------------------------------------------- page API --

    def set_active(self, active):
        """Keyboard shortcuts only work while this page is shown."""
        for sc in self._shortcuts:
            sc.setEnabled(active)
        if not active:
            self.playback.pause()

    def set_analyses(self, analyses, analysis=None, at=None):
        self.analyses = list(analyses)
        if not self.analyses:
            self.playback.clear()
            self.scene = None
            self.stage.set_scene(None)
            self.seekbar.clear()
            self.stack.setCurrentWidget(self.empty)
            return
        self.stack.setCurrentIndex(1)
        a = analysis if analysis in self.analyses else self.analyses[0]
        self.picker.blockSignals(True)
        self.picker.clear()
        self.picker.addItems([f"{x.replay.player}  ·  {x.beatmap.artist} - {x.beatmap.title} "
                              f"[{x.beatmap.diff_name}]  +{x.replay.mod_string}" for x in self.analyses])
        self.picker.setCurrentIndex(self.analyses.index(a))
        self.picker.blockSignals(False)
        self.picker.setVisible(len(self.analyses) > 1)
        self.load(a, at)

    def load(self, a, at=None):
        self.scene = scene = ReplayScene(a)
        bm, rp = a.beatmap, a.replay
        self.title.setText(f"{bm.artist} - {bm.title} [{bm.diff_name}]")
        self.player.set_text(rp.player)
        self.mods.set_text(f"+{rp.mod_string}")
        self.mods.tone = None if rp.mod_string == "NM" else "#ffb347"
        self.info.setText(f"CS {bm.cs:.1f}   AR {bm.ar:.1f}   OD {bm.od:.1f}   ·   "
                          f"{len(a.hits)} hits   {len(a.misses)} misses")
        self.stage.set_scene(scene)
        self.seekbar.set_data(scene.t0, scene.t1, scene.obj_times, scene.miss_times, scene.judged_marks)
        self.time_total.setText("/ " + fmt_time(scene.t1))
        self.playback.load(scene, at)

    def show_note(self, analysis, obj):
        """Start playing a little before this hit / miss."""
        if self.scene is None or self.scene.analysis is not analysis:
            self.set_analyses(self.analyses or [analysis], analysis)
        self.playback.play_from(obj.time - 1500)

    def set_bg_dim(self, dim):
        self.stage.set_bg_dim(dim)

    @property
    def bg_dim(self):
        return self.stage.bg_dim

    def pause(self):
        self.playback.pause()

    def shutdown(self):
        self.playback.shutdown()

    # ----------------------------------------------------------- internal --

    def _pick(self, i):
        if 0 <= i < len(self.analyses):
            self.load(self.analyses[i])

    def _toggle_clicked(self):
        # The button flips itself; the playback decides (and emits playingChanged)
        self.play.setChecked(self.playback.playing)
        self.playback.toggle()

    def _on_time(self, t):
        self.stage.set_time(t)
        self.seekbar.set_time(t)
        self.time_now.setText(fmt_time(t))

