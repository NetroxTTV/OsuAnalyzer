"""
Replay viewer: plays an analysed replay on a Tk canvas - notes, approach circles,
sliders, cursor + trail, key presses, click points and judgements.
"""

import bisect
import math
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import osu_hit_analyzer as core
from widgets import FlatButton, PlayButton, Segmented, VolumeSlider, round_rect

BG, PANEL, FG, MUTED, PINK, AVG = core.BG, core.PANEL, core.FG, core.MUTED, core.PINK, core.AVG
FIELD_BG = "#0d0d13"
BORDER = "#33334a"
MISS_RED = "#ff4d5e"
DEFAULT_COMBO = [(255, 102, 170), (90, 200, 250), (126, 217, 87), (255, 179, 71)]
SPEEDS = ["0.25x", "0.5x", "0.75x", "1x", "1.5x", "2x"]
TRAIL_MS = 160
CLICK_MARK_MS = 450
JUDGE_MS = 500
MISS_MS = 800
UR_TICK_MS = 6000   # how long a hit stays on the hit error bar
TIMELINE_MS = 800   # key timeline shows +/- this much (real time) around "now"
BG_DIM = 0.16       # beatmap background brightness behind the replay
BG_COLOUR = 0.55    # and saturation (muted so the circles stand out)
K1_COLOUR = (232, 146, 22)
K2_COLOUR = (40, 200, 40)
RESULT_COLOURS = {300: core.JUDGE_COLORS[300], 100: core.JUDGE_COLORS[100],
                  50: core.JUDGE_COLORS[50], 0: MISS_RED}


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a, b, t):
    """Blend colour a towards b by t (0..1); a, b are (r, g, b)."""
    t = max(0.0, min(1.0, t))
    return _hex(tuple(x + (y - x) * t for x, y in zip(a, b)))


def _fmt(ms):
    ms = max(0, ms)
    m, s = divmod(ms / 1000, 60)
    return f"{int(m)}:{s:06.3f}"


class SeekBar:
    """Song timeline: click anywhere to jump, drag to scrub, hover for the time.
    Shows note density, misses (red, click = jump just before it) and 100s / 50s."""

    PAD = 12
    MISS_LEAD = 1200   # clicking a miss mark lands this long before the miss

    def __init__(self, parent, on_seek):
        self.on_seek = on_seek
        self.c = tk.Canvas(parent, height=40, bg=BG, highlightthickness=0, cursor="hand2")
        self.t0, self.t1, self.t = 0.0, 1.0, 0.0
        self.obj_times, self.misses, self.marks = [], [], []
        self.bars = []          # (item, bin end time)
        self._played = 0        # number of density bars currently coloured as played
        self.c.bind("<Configure>", lambda e: self.redraw())
        self.c.bind("<Button-1>", self._press)
        self.c.bind("<B1-Motion>", lambda e: self._seek_x(e.x))
        self.c.bind("<Motion>", self._hover)
        self.c.bind("<Leave>", lambda e: self.c.delete("hover"))
        self.c.bind("<MouseWheel>", lambda e: self.on_seek(self.t + (-1000 if e.delta > 0 else 1000)))

    def set_data(self, t0, t1, obj_times, misses, marks):
        self.t0, self.t1 = t0, max(t1, t0 + 1)
        self.obj_times, self.misses, self.marks = obj_times, misses, marks
        self.redraw()

    # coordinates
    def _x(self, t):
        w = max(self.c.winfo_width(), 50) - 2 * self.PAD
        return self.PAD + (t - self.t0) / (self.t1 - self.t0) * w

    def _t(self, x):
        w = max(self.c.winfo_width(), 50) - 2 * self.PAD
        return self.t0 + min(max((x - self.PAD) / w, 0.0), 1.0) * (self.t1 - self.t0)

    def _miss_near(self, x):
        for m in self.misses:
            if abs(self._x(m) - x) <= 5:
                return m
        return None

    # drawing
    def redraw(self):
        c = self.c
        c.delete("all")
        W = max(c.winfo_width(), 50)
        top, bot = 6, 34
        round_rect(c, self.PAD, top, W - self.PAD, bot, 9, fill=PANEL, outline="")
        # note density
        n_bins = max(10, int((W - 2 * self.PAD) / 4))
        span = (self.t1 - self.t0) / n_bins
        counts = [0] * n_bins
        for t in self.obj_times:
            i = int((t - self.t0) / span)
            if 0 <= i < n_bins:
                counts[i] += 1
        peak = max(counts) or 1
        self.bars = []
        for i, n in enumerate(counts):
            if not n:
                continue
            x = self._x(self.t0 + i * span)
            h = 3 + (bot - top - 6) * n / peak
            item = c.create_rectangle(x + 0.5, bot - 1 - h, x + 3.5, bot - 1, fill="#4a4a62", outline="")
            self.bars.append((item, self.t0 + (i + 1) * span))
        self._played = 0
        for t, colour in self.marks:
            x = self._x(t)
            c.create_line(x, top + 1, x, top + 7, fill=colour, width=2)
        for m in self.misses:
            x = self._x(m)
            c.create_line(x, top - 3, x, bot + 3, fill=MISS_RED, width=2)
        c.create_line(0, 0, 0, 0, fill="#ffffff", width=2, tags="head")
        c.create_polygon(0, 0, 0, 0, 0, 0, fill="#ffffff", outline="", tags="knob")
        self.set_time(self.t, force=True)

    def set_time(self, t, force=False):
        self.t = t
        x = self._x(t)
        self.c.coords("head", x, 2, x, 38)
        self.c.coords("knob", x - 6, 0, x + 6, 0, x, 7)
        # recolour only the density bars that changed side of the playhead
        played = bisect.bisect_right([b[1] for b in self.bars], t) if self.bars else 0
        if force:
            lo, hi = 0, len(self.bars)
        else:
            lo, hi = min(played, self._played), max(played, self._played)
        for i in range(lo, hi):
            self.c.itemconfig(self.bars[i][0], fill=PINK if i < played else "#4a4a62")
        self._played = played

    # interaction
    def _press(self, e):
        m = self._miss_near(e.x)
        self.on_seek(m - self.MISS_LEAD if m is not None else self._t(e.x))

    def _seek_x(self, x):
        self.on_seek(self._t(x))

    def _hover(self, e):
        c = self.c
        c.delete("hover")
        m = self._miss_near(e.x)
        t = m if m is not None else self._t(e.x)
        x = self._x(t)
        label = f"miss  {_fmt(t)}  (click = 1.2 s before)" if m is not None else _fmt(t)
        c.create_line(x, 4, x, 36, fill=MISS_RED if m is not None else "#bbbbcc", width=1, tags="hover")
        item = c.create_text(0, 20, text=label, fill=FG, font=("Segoe UI Semibold", 9), tags="hover")
        x0, y0, x1, y1 = c.bbox(item)
        w = x1 - x0
        tx = min(max(x + 10 + w / 2, w / 2 + 2), max(c.winfo_width(), 50) - w / 2 - 2)
        if tx - w / 2 < x < tx + w / 2:          # would cover the line: put it on the left
            tx = max(w / 2 + 2, x - 10 - w / 2)
        c.coords(item, tx, 20)
        bx0, by0, bx1, by1 = c.bbox(item)
        bg = round_rect(c, bx0 - 7, by0 - 3, bx1 + 7, by1 + 3, 7, fill="#0b0b10", outline=BORDER, tags="hover")
        c.tag_raise(item, bg)


VOLUME_GAIN = 0.5   # slider at 100 % = half of full scale (full scale was too loud)
SPEED_OPTIONS = [(0.25, "0.25×"), (0.5, "0.5×"), (0.75, "0.75×"), (1.0, "1×"), (1.5, "1.5×"), (2.0, "2×")]


class ReplayViewer:
    """Replay viewer page, embedded in the app window (self.frame)."""

    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=BG)
        self.a = None
        self.analyses = []
        self.playing = False
        self.t = 0.0
        self.t0, self.t1 = 0.0, 1.0
        self._last = 0.0
        self.player = None
        self._audio_token = 0
        self._audio_q = queue.Queue()
        self._save_job = None
        self.speed_value = 1.0
        self._audio_text = ""
        self.bg_dim = core.load_settings().get("bg_dim", BG_DIM)

        header = tk.Frame(self.frame, bg=BG)
        header.pack(fill="x", padx=20, pady=(14, 0))
        self.title = tk.Label(header, bg=BG, fg=FG, font=("Segoe UI Semibold", 13), anchor="w")
        self.title.pack(side="left")
        self.subtitle = tk.Label(header, bg=BG, fg=MUTED, font=("Segoe UI", 10))
        self.subtitle.pack(side="left", padx=(12, 0), pady=(3, 0))
        self.picker = ttk.Combobox(header, state="readonly", width=52, style="Dark.TCombobox")
        self.picker.bind("<<ComboboxSelected>>", lambda e: (self._pick_from_combo(), self.canvas.focus_set()))

        self.canvas = tk.Canvas(self.frame, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.render())
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set())

        self.seekbar = SeekBar(self.frame, self.seek)
        self.seekbar.c.pack(fill="x", padx=8)

        controls = tk.Frame(self.frame, bg=BG)
        controls.pack(fill="x", padx=20, pady=(6, 2))
        FlatButton(controls, "‹  Miss", self.prev_miss, kind="ghost").pack(side="left")
        self.play_btn = PlayButton(controls, self.toggle)
        self.play_btn.pack(side="left", padx=10)
        FlatButton(controls, "Miss  ›", self.next_miss, kind="ghost").pack(side="left")
        self.time_now = tk.Label(controls, bg=BG, fg=FG, font=("Segoe UI Semibold", 13), text="0:00.000")
        self.time_now.pack(side="left", padx=(22, 0))
        self.time_total = tk.Label(controls, bg=BG, fg=MUTED, font=("Segoe UI", 11), text=" / 0:00.000")
        self.time_total.pack(side="left", pady=(2, 0))
        self.vol = VolumeSlider(controls, core.load_settings().get("volume", 0.5), self._on_volume, width=190)
        self.vol.pack(side="right")
        self.speed_pills = Segmented(controls, SPEED_OPTIONS, 1.0, self._speed_changed)
        self.speed_pills.pack(side="right", padx=(0, 24))

        foot = tk.Frame(self.frame, bg=BG)
        foot.pack(fill="x", padx=20, pady=(2, 10))
        tk.Label(foot, bg=BG, fg=MUTED, font=("Segoe UI", 9),
                 text="Space  play / pause      ← →  ±1 s      , .  frame by frame      "
                      "N / P  next / previous miss      M  mute").pack(side="left")
        self.audio_label = tk.Label(foot, bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.audio_label.pack(side="right")

        self._job = self.frame.after(15, self._tick)

    # ------------------------------------------------------------- loading --

    def handle_key(self, keysym):
        """Keyboard shortcuts, forwarded by the app while this page is shown."""
        if self.a is None:
            return False
        action = {
            "space": self.toggle,
            "Left": lambda: self.seek(self.t - 1000),
            "Right": lambda: self.seek(self.t + 1000),
            "comma": lambda: self.step(-1),
            "period": lambda: self.step(1),
            "n": self.next_miss,
            "p": self.prev_miss,
            "m": self.vol.toggle_mute,
        }.get(keysym)
        if action:
            action()
            return True
        return False

    def set_analyses(self, analyses, analysis=None, at=None):
        self.analyses = list(analyses)
        if not self.analyses:
            self.pause()
            self.a = None
            self._close_audio()
            self.render()
            return
        names = [f"{a.replay.player}  ·  {a.beatmap.artist} - {a.beatmap.title} [{a.beatmap.diff_name}]"
                 f"  +{a.replay.mod_string}" for a in self.analyses]
        if len(self.analyses) > 1:
            self.picker.config(values=names)
            self.picker.pack(side="right")
        else:
            self.picker.pack_forget()
        a = analysis if analysis in self.analyses else self.analyses[0]
        self.picker.set(names[self.analyses.index(a)])
        self.load(a, at)

    def _pick_from_combo(self):
        i = self.picker.current()
        if 0 <= i < len(self.analyses):
            self.load(self.analyses[i], None)

    def load(self, a, at=None):
        self.a = a
        bm, rp = a.beatmap, a.replay
        self.title.config(text=f"{bm.artist} - {bm.title} [{bm.diff_name}]")
        self.subtitle.config(text=f"{rp.player}   +{rp.mod_string}")
        self._bg_src, self._bg_key, self._bg_photo = None, None, None
        if bm.background and bm.background.exists():
            try:
                from PIL import Image
                im = Image.open(bm.background)
                im.draft("RGB", (1920, 1080))
                self._bg_src = im.convert("RGB")
            except Exception:  # noqa: BLE001 - unreadable image: plain background
                self._bg_src = None
        self.frames = rp.frames
        self.ftimes = [f[0] for f in self.frames]
        self.radius = a.radius
        self.preempt = core.preempt(bm.ar)
        self.fade_in = 400 * min(1.0, self.preempt / 450)
        self.w50 = a.windows[2]
        self.objs = bm.objects
        self.starts = [o.time - self.preempt for o in self.objs]
        self.max_len = max((o.end_time - o.time for o in self.objs), default=0)
        self.colours = bm.colours or DEFAULT_COMBO
        self._cum = {}

        playable = [o for o in self.objs if o.kind != "spinner"]
        self.head_done = {}   # id(object) -> time its head was judged
        events = []           # (time, kind, pos, label)
        for h in a.hits:
            t = h.time + h.error
            self.head_done[id(playable[h.index])] = t
            events.append((t, "hit", h.pos, h.judgement))
        for m in a.misses:
            t = m.time + (m.error if m.reason == "early" else self.w50)
            self.head_done[id(playable[m.index])] = t
            events.append((t, "miss", m.pos, None))
        events.sort(key=lambda e: e[0])
        self.events = events
        self.event_times = [e[0] for e in events]
        self.miss_times = [e[0] for e in events if e[1] == "miss"]
        self.count_times = {j: [e[0] for e in events if e[1] == "hit" and e[3] == j] for j in (300, 100, 50)}

        # Hit error bar: hits in the order they happened + running sums for the unstable rate
        self.hit_seq = sorted((h.time + h.error, h.error, h.judgement) for h in a.hits)
        self.hit_times = [hs[0] for hs in self.hit_seq]
        self.err_sum, self.err_sq = [0.0], [0.0]
        for _, e, _ in self.hit_seq:
            self.err_sum.append(self.err_sum[-1] + e)
            self.err_sq.append(self.err_sq[-1] + e * e)

        self.presses = []
        prev = 0
        for t, x, y, keys in self.frames:
            for mask in (core.KEY_LEFT, core.KEY_RIGHT):
                if keys & mask and not prev & mask:
                    self.presses.append((t, x, y))
            prev = keys
        self.press_times = [p[0] for p in self.presses]

        # Key timeline: (press, release) segments per key, and the result of every note
        self.key_segs = {}
        for mask in (core.KEY_LEFT, core.KEY_RIGHT):
            segs, down = [], None
            for t, _x, _y, keys in self.frames:
                if keys & mask and down is None:
                    down = t
                elif not keys & mask and down is not None:
                    segs.append((down, t))
                    down = None
            if down is not None:
                segs.append((down, self.ftimes[-1]))
            self.key_segs[mask] = (segs, [sg[0] for sg in segs],
                                   max((b - a for a, b in segs), default=0))
        self.obj_times = [o.time for o in self.objs]
        self.result = {}
        for h in a.hits:
            self.result[id(playable[h.index])] = h.judgement
        for m in a.misses:
            self.result[id(playable[m.index])] = 0

        first = self.objs[0].time if self.objs else 0
        last_frame = self.ftimes[-1] if self.ftimes else 0
        self.t0 = max(0.0, first - 2000)
        self.t1 = max(last_frame, self.objs[-1].end_time if self.objs else 0) + 500
        self.seekbar.t = self.t0
        self.seekbar.set_data(self.t0, self.t1, self.obj_times,
                              self.miss_times,
                              [(et, core.JUDGE_COLORS[j]) for et, _e, j in self.hit_seq if j != 300])
        self.time_total.config(text=" / " + _fmt(self.t1))
        self._load_audio(bm.audio)
        self.seek(at if at is not None else self.t0)

    # --------------------------------------------------------------- music --

    def _set_audio_text(self, text):
        if text != self._audio_text:
            self._audio_text = text
            self.audio_label.config(text=text)

    def _close_audio(self):
        if self.player:
            self.player.close()
            self.player = None
        self._audio_token += 1

    def _load_audio(self, path):
        self._close_audio()
        if not path or not path.exists():
            self._set_audio_text("♪ audio file not found")
            return
        self._set_audio_text("♪ loading music...")
        token = self._audio_token
        volume = self.vol.effective * VOLUME_GAIN

        def work():
            try:
                import audio
                self._audio_q.put((token, audio.AudioPlayer(path, volume), None))
            except Exception as e:  # noqa: BLE001 - no output device, unknown format...
                self._audio_q.put((token, None, e))

        threading.Thread(target=work, daemon=True).start()

    def _audio_ready(self, token, player, error):
        if token != self._audio_token:
            if player:
                player.close()
            return
        if error or not player:
            self._set_audio_text(f"♪ no sound ({error})")
            return
        self.player = player
        player.volume = self.vol.effective * VOLUME_GAIN
        self._speed_changed()
        if self.playing:
            player.play(self.t)

    def _speed_changed(self, value=None):
        if value is not None:
            self.speed_value = value
        if self.player and self.a:
            nc = bool(self.a.replay.mods & core.MOD_NC)
            self.player.set_rate(self.rate, keep_pitch=not nc)
            if self.playing:
                self.player.seek(self.t)

    def _on_volume(self, effective):
        if self.player:
            self.player.volume = effective * VOLUME_GAIN
        if self._save_job:
            self.frame.after_cancel(self._save_job)
        self._save_job = self.frame.after(600, lambda: core.save_settings(volume=self.vol.value))

    # ------------------------------------------------------------ controls --

    @property
    def rate(self):
        return self.a.replay.rate * self.speed_value

    def toggle(self):
        if self.a is None:
            return
        self.playing = not self.playing
        if self.playing and self.t >= self.t1 - 1:
            self.t = self.t0
        self._last = time.perf_counter()
        self.play_btn.set_playing(self.playing)
        if self.player:
            if self.playing:
                self.player.play(self.t)
            else:
                self.player.pause()

    def pause(self):
        if self.playing:
            self.toggle()

    def seek(self, t):
        if self.a is None:
            return
        self.t = min(max(self.t0, t), self.t1)
        if self.player:
            self.player.seek(self.t)
        self._sync_scale()
        self.render()

    def step(self, frames):
        self.pause()
        self.seek(self.t + frames * 1000 / 60 * self.a.replay.rate)

    def next_miss(self):
        if self.a is None:
            return
        i = bisect.bisect_right(self.miss_times, self.t + 1200 + 5)
        if i < len(self.miss_times):
            self.seek(self.miss_times[i] - 1200)

    def prev_miss(self):
        if self.a is None:
            return
        i = bisect.bisect_left(self.miss_times, self.t + 1200 - 5) - 1
        if i >= 0:
            self.seek(self.miss_times[i] - 1200)

    def play_from(self, t):
        self.seek(t)
        if not self.playing:
            self.toggle()

    def _sync_scale(self):
        self.seekbar.set_time(self.t)

    def _tick(self):
        try:
            while True:
                self._audio_ready(*self._audio_q.get_nowait())
        except queue.Empty:
            pass
        if self.playing and self.a is not None:
            now = time.perf_counter()
            if self.player and self.player.playing:
                self.t = self.player.position()   # the music is the clock
            else:
                self.t += (now - self._last) * 1000 * self.rate
            self._last = now
            if self.t >= self.t1:
                self.t = self.t1
                self.toggle()
            self._sync_scale()
            self.render()
        self._job = self.frame.after(15, self._tick)

    def shutdown(self):
        if self._job:
            self.frame.after_cancel(self._job)
        self._close_audio()

    # ------------------------------------------------------------- drawing --

    def _cursor(self, t):
        k = bisect.bisect_right(self.ftimes, t)
        if not self.frames:
            return 256, 192, 0
        if k <= 0:
            f = self.frames[0]
            return f[1], f[2], f[3]
        if k >= len(self.frames):
            f = self.frames[-1]
            return f[1], f[2], f[3]
        t0, x0, y0, keys = self.frames[k - 1]
        t1, x1, y1, _ = self.frames[k]
        f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f, keys

    def _ball(self, o, t):
        """Slider ball position (unstacked) at time t."""
        pts = o.path
        if id(o) not in self._cum:
            cum = [0.0]
            for i in range(len(pts) - 1):
                cum.append(cum[-1] + math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
            self._cum[id(o)] = cum
        cum = self._cum[id(o)]
        dur = max(1.0, o.end_time - o.time)
        p = min(max((t - o.time) / dur, 0.0), 1.0) * o.slides
        span = min(int(p), o.slides - 1)
        f = p - span
        if span % 2 == 1:
            f = 1 - f
        d = f * cum[-1]
        i = min(max(bisect.bisect_right(cum, d) - 1, 0), len(pts) - 2)
        seg = cum[i + 1] - cum[i]
        g = (d - cum[i]) / seg if seg > 0 else 0
        return pts[i][0] + (pts[i + 1][0] - pts[i][0]) * g, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * g

    def render(self):
        c = self.canvas
        if self.a is None:
            c.delete("all")
            W, H = c.winfo_width(), c.winfo_height()
            c.create_text(W / 2, H / 2 - 14, text="Replay Viewer", fill=PINK, font=("Segoe UI Semibold", 22))
            c.create_text(W / 2, H / 2 + 18, text="Pick a replay on the left", fill=MUTED, font=("Segoe UI", 12))
            return
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        # Leave a circle radius around the playfield, the HUD on top and the error bar below
        top, bottom = 100, 62
        if W - 40 < 100 or H - top - bottom < 100:
            return  # window not laid out yet (or tiny): <Configure> redraws once it has a size
        k = min((W - 40) / (512 + 2 * self.radius), (H - top - bottom) / (384 + 2 * self.radius))
        ox = (W - 512 * k) / 2
        oy = top + self.radius * k + ((H - top - bottom) - (384 + 2 * self.radius) * k) / 2

        def P(x, y):
            return ox + x * k, oy + y * k

        t = self.t
        r = self.radius * k
        bgc = _rgb(FIELD_BG)
        white = (255, 255, 255)
        self._draw_background(c, W, H)
        round_rect(c, *P(0, 0), *P(512, 384), 12, fill="", outline="#34344a", width=1)

        # Visible objects, collected latest first so earlier ones are drawn on top
        hi = bisect.bisect_right(self.starts, t)
        visible = []
        for i in range(hi - 1, -1, -1):
            o = self.objs[i]
            if o.time < t - self.max_len - 1000:
                break
            head_end = self.head_done.get(id(o), o.time + self.w50)
            end = max(head_end, o.end_time) + 150 if o.kind != "circle" else head_end + 150
            if o.kind == "spinner":
                end = o.end_time
            if t <= end:
                visible.append((o, head_end))

        font = ("Segoe UI Semibold", -max(8, int(r * 0.85)))
        for o, head_end in visible:
            alpha = min(1.0, (t - (o.time - self.preempt)) / self.fade_in)
            col = self.colours[o.combo_index % len(self.colours)]
            if o.kind == "spinner":
                if t >= o.time - self.preempt:
                    cx, cy = P(256, 192)
                    R = 170 * k
                    prog = min(max((t - o.time) / max(1, o.end_time - o.time), 0), 1)
                    c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=_mix(bgc, white, alpha * 0.6), width=3)
                    rr = R * (1 - prog)
                    c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=_mix(bgc, col, alpha), width=2)
                    c.create_text(cx, cy, text="spinner", fill=_mix(bgc, white, alpha * 0.7), font=font)
                continue

            sx, sy = o.stacked_pos[0] - o.pos[0], o.stacked_pos[1] - o.pos[1]
            ball = None
            if o.kind == "slider" and o.path and len(o.path) > 1:
                fade = alpha if t <= o.end_time else max(0.0, 1 - (t - o.end_time) / 150) * alpha
                flat = [v for x, y in o.path for v in P(x + sx, y + sy)]
                c.create_line(*flat, width=2 * r, fill=_mix(bgc, white, fade * 0.85),
                              capstyle="round", joinstyle="round")
                c.create_line(*flat, width=max(2, 2 * r - max(3, r * 0.18)),
                              fill=_mix(bgc, tuple(v * 0.35 for v in col), fade),
                              capstyle="round", joinstyle="round")
                if o.slides > 1 and t <= o.end_time:
                    ex, ey = P(o.path[-1][0] + sx, o.path[-1][1] + sy)
                    c.create_text(ex, ey, text="↺", fill=_mix(bgc, white, fade), font=font)
                if o.time <= t <= o.end_time:
                    bx, by = self._ball(o, t)
                    ball = P(bx + sx, by + sy)

            # Hit circle / slider head
            if t <= head_end + 150:
                a2 = alpha if t <= head_end else alpha * max(0.0, 1 - (t - head_end) / 150)
                cx, cy = P(*o.stacked_pos)
                c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=_mix(bgc, col, a2),
                              outline=_mix(bgc, white, a2), width=max(2, r * 0.1))
                c.create_text(cx, cy, text=str(o.combo_number), fill=_mix(bgc, white, a2), font=font)
                if t < o.time:
                    ar = r * (1 + 3 * (o.time - t) / self.preempt)
                    c.create_oval(cx - ar, cy - ar, cx + ar, cy + ar, outline=_mix(bgc, col, alpha),
                                  width=max(2, r * 0.07))
            if ball:  # slider ball + follow circle, above the fading head
                bx, by = ball
                c.create_oval(bx - r, by - r, bx + r, by + r, outline=_mix(bgc, white, 0.9),
                              width=2, fill=_hex(col))
                fr = r * 2.2
                c.create_oval(bx - fr, by - fr, bx + fr, by + fr, outline=_mix(bgc, col, 0.7), width=2)

        # Judgements
        lo = bisect.bisect_left(self.event_times, t - MISS_MS)
        hi = bisect.bisect_right(self.event_times, t)
        for et, kind, pos, label in self.events[lo:hi]:
            age = t - et
            x, y = P(*pos)
            if kind == "miss":
                f = 1 - age / MISS_MS
                s = r * 0.7
                col = _mix(bgc, _rgb(MISS_RED), f)
                c.create_line(x - s, y - s, x + s, y + s, fill=col, width=max(3, r * 0.2))
                c.create_line(x - s, y + s, x + s, y - s, fill=col, width=max(3, r * 0.2))
            elif age <= JUDGE_MS:
                f = 1 - age / JUDGE_MS
                c.create_text(x, y - r * 1.35, text=str(label),
                              fill=_mix(bgc, _rgb(core.JUDGE_COLORS[label]), f),
                              font=("Segoe UI Black", -max(9, int(r * 0.6))))

        # Where you clicked
        lo = bisect.bisect_left(self.press_times, t - CLICK_MARK_MS)
        hi = bisect.bisect_right(self.press_times, t)
        for pt, x, y in self.presses[lo:hi]:
            f = 1 - (t - pt) / CLICK_MARK_MS
            x, y = P(x, y)
            d = max(3, r * 0.14)
            c.create_oval(x - d, y - d, x + d, y + d, fill=_mix(bgc, _rgb(AVG), f), outline="")

        # Cursor trail + cursor
        lo = bisect.bisect_left(self.ftimes, t - TRAIL_MS)
        hi = bisect.bisect_right(self.ftimes, t)
        cx, cy, keys = self._cursor(t)
        trail = [P(f[1], f[2]) for f in self.frames[lo:hi]] + [P(cx, cy)]
        for i in range(1, len(trail)):
            f = i / len(trail)
            c.create_line(*trail[i - 1], *trail[i], fill=_mix(bgc, _rgb(PINK), f), width=max(2, 4 * f))
        x, y = P(cx, cy)
        cr = max(6, r * 0.28)
        pressed = keys & (core.KEY_LEFT | core.KEY_RIGHT)
        c.create_oval(x - cr, y - cr, x + cr, y + cr, fill=AVG if pressed else "#ffffff",
                      outline="#000000", width=2)

        self._draw_error_bar(c, W, H, t, bgc)
        self._draw_timeline(c, W, t, bgc)
        self.time_now.config(text=_fmt(t))
        if self.player:
            name = self.a.beatmap.audio.name
            self._set_audio_text(f"♪ {name}" + ("   ·   preparing pitch..." if not self.player.stretch_ready() else ""))

    def _draw_background(self, c, W, H):
        """Beatmap background, scaled to cover the canvas, blurred and darkened."""
        if self._bg_src is None or self.bg_dim <= 0:
            return
        if self._bg_key != (W, H):
            from PIL import Image, ImageEnhance, ImageFilter, ImageTk
            src = self._bg_src
            sc = max(W / src.width, H / src.height)
            img = src.resize((max(1, round(src.width * sc)), max(1, round(src.height * sc))), Image.BILINEAR)
            left, top = (img.width - W) // 2, (img.height - H) // 2
            img = img.crop((left, top, left + W, top + H)).filter(ImageFilter.GaussianBlur(3))
            img = ImageEnhance.Color(img).enhance(BG_COLOUR)
            img = ImageEnhance.Brightness(img).enhance(self.bg_dim)
            self._bg_photo = ImageTk.PhotoImage(img)
            self._bg_key = (W, H)
        c.create_image(0, 0, image=self._bg_photo, anchor="nw")

    def set_bg_dim(self, value):
        self.bg_dim = value
        self._bg_key = None
        self.render()

    def _draw_timeline(self, c, W, t, bgc):
        """Scrolling strip across the top: K1 presses / notes with their hit windows / K2 presses,
        with the K1 / K2 keys on its right."""
        w300, w100, w50 = self.a.windows
        win = TIMELINE_MS * self.a.replay.rate          # map-time half width
        keys_w = 78
        x0, x1 = 20.0, W - 20.0 - keys_w - 12
        cx = (x0 + x1) / 2
        pxms = (x1 - x0) / 2 / win
        y0 = 16
        lanes = {"ruler": (y0, y0 + 8), core.KEY_LEFT: (y0 + 10, y0 + 28),
                 "notes": (y0 + 30, y0 + 48), core.KEY_RIGHT: (y0 + 50, y0 + 68)}
        white = (255, 255, 255)
        strip = _mix(bgc, (0, 0, 0), 0.45)

        def X(ms):
            return min(x1 - 4, max(x0 + 4, cx + (ms - t) * pxms))

        round_rect(c, x0, y0 - 6, x1, y0 + 74, 12, fill=strip, outline="")
        for name, (a, b) in lanes.items():
            if name != "ruler":
                round_rect(c, x0 + 4, a, x1 - 4, b, 5, fill=_mix(bgc, white, 0.035), outline="")

        # Ruler: a tick every 100 ms of map time
        ra, rb = lanes["ruler"]
        first = math.ceil((t - win) / 100) * 100
        for ms in range(int(first), int(t + win) + 1, 100):
            x = X(ms)
            c.create_line(x, rb - (6 if ms % 500 == 0 else 3), x, rb, fill=_mix(bgc, white, 0.35))

        # Notes: 50 / 100 / 300 windows, outline = result, dark line = exact note time
        na, nb = lanes["notes"]
        lo = bisect.bisect_left(self.obj_times, t - win - w50 - self.max_len)
        hi = bisect.bisect_right(self.obj_times, t + win + w50)
        for o in self.objs[lo:hi]:
            if o.kind != "circle" and o.end_time >= t - win:
                round_rect(c, X(o.time), (na + nb) / 2 - 2, X(o.end_time), (na + nb) / 2 + 2, 2,
                           fill=_mix(bgc, white, 0.3), outline="")
            if o.kind == "spinner" or o.time + w50 < t - win:
                continue
            for wnd, shade in ((w50, 0.12), (w100, 0.25), (w300, 0.75)):
                round_rect(c, X(o.time - wnd), na, X(o.time + wnd), nb, 4,
                           fill=_mix(bgc, white, shade), outline="")
            res = self.result.get(id(o))
            if res is not None:
                round_rect(c, X(o.time - w300), na, X(o.time + w300), nb, 4, fill="",
                           outline=RESULT_COLOURS[res], width=2)
            c.create_line(X(o.time), na + 2, X(o.time), nb - 2, fill=_mix(bgc, (0, 0, 0), 0.6), width=1)

        # Key presses: bar while held + a tick at the press reaching into the note lane
        keys_now = self._cursor(t)[2]
        for i, (mask, colour, name) in enumerate(((core.KEY_LEFT, K1_COLOUR, "K1"),
                                                  (core.KEY_RIGHT, K2_COLOUR, "K2"))):
            segs, starts, longest = self.key_segs[mask]
            la, lb = lanes[mask]
            lo = bisect.bisect_left(starts, t - win - longest)
            hi = bisect.bisect_right(starts, t + win)
            for a, b in segs[lo:hi]:
                if b < t - win:
                    continue
                round_rect(c, X(a), la, X(b), lb, 5, fill=_hex(colour), outline="")
                if a >= t - win:
                    ta, tb = (la, nb) if mask == core.KEY_LEFT else (na, lb)
                    c.create_line(X(a), ta, X(a), tb, fill="#ffffff", width=2)

            # Key box on the right: K1 on top, K2 below, lit while held, with the press count
            kx0, kx1 = x1 + 12, W - 20
            ky0 = y0 - 6 + i * 41
            held = keys_now & mask
            round_rect(c, kx0, ky0, kx1, ky0 + 39, 10, fill=_hex(colour) if held else strip, outline="")
            c.create_text(kx0 + 14, ky0 + 20, anchor="w", text=name,
                          fill="#15151c" if held else FG, font=("Segoe UI Semibold", 11))
            c.create_text(kx1 - 12, ky0 + 20, anchor="e", text=str(bisect.bisect_right(starts, t)),
                          fill="#15151c" if held else MUTED, font=("Segoe UI", 9))

        # Now
        c.create_line(cx, y0 - 6, cx, y0 + 74, fill=AVG, width=2)

    def _draw_error_bar(self, c, W, H, t, bgc):
        """osu!-style hit error meter; judgement counts on its left, unstable rate on its right."""
        w300, w100, w50 = self.a.windows
        half = min(230.0, W * 0.2)
        bx, by = W / 2, H - 30
        sc = half / w50
        for win, colr in ((w50, core.JUDGE_COLORS[50]), (w100, core.JUDGE_COLORS[100]),
                          (w300, core.JUDGE_COLORS[300])):
            round_rect(c, bx - win * sc, by - 4, bx + win * sc, by + 4, 4,
                       fill=_mix(bgc, _rgb(colr), 0.6), outline="")
        lo = bisect.bisect_left(self.hit_times, t - UR_TICK_MS)
        n = bisect.bisect_right(self.hit_times, t)
        for et, err, j in self.hit_seq[lo:n]:
            f = 1 - (t - et) / UR_TICK_MS
            x = bx + max(-w50, min(w50, err)) * sc
            c.create_line(x, by - 12, x, by + 12, fill=_mix(bgc, _rgb(core.JUDGE_COLORS[j]), f),
                          width=2, capstyle="round")
        c.create_line(bx, by - 16, bx, by + 16, fill=FG, width=2, capstyle="round")
        recent = self.hit_seq[max(0, n - 20):n]
        if recent:
            m = sum(e for _, e, _ in recent) / len(recent)
            x = bx + max(-w50, min(w50, m)) * sc
            c.create_polygon(x, by - 17, x - 7, by - 27, x + 7, by - 27, fill=AVG, outline="")
        c.create_text(bx - half - 10, by, anchor="e", text="early", fill=MUTED, font=("Segoe UI", 9))
        c.create_text(bx + half + 10, by, anchor="w", text="late", fill=MUTED, font=("Segoe UI", 9))

        # Judgement counts, right-aligned on the left of the bar
        counts = {j: bisect.bisect_right(self.count_times[j], t) for j in (300, 100, 50)}
        x = bx - half - 64
        for label, val, colr in (("✕", bisect.bisect_right(self.miss_times, t), MISS_RED),
                                 ("50", counts[50], core.JUDGE_COLORS[50]),
                                 ("100", counts[100], core.JUDGE_COLORS[100]),
                                 ("300", counts[300], core.JUDGE_COLORS[300])):
            item = c.create_text(x, by, anchor="e", text=f"{label} {val}", fill=colr,
                                 font=("Segoe UI Semibold", 12))
            x = c.bbox(item)[0] - 18

        # Unstable rate on the right of the bar
        if n > 1:
            mean = self.err_sum[n] / n
            ur = 10 * math.sqrt(max(0.0, self.err_sq[n] / n - mean * mean)) / self.a.replay.rate
            ur_text, avg_text = f"UR {ur:.1f}", f"avg {mean:+.1f} ms"
        else:
            ur_text, avg_text = "UR -", ""
        item = c.create_text(bx + half + 52, by, anchor="w", text=ur_text, fill=FG,
                             font=("Segoe UI Semibold", 12))
        c.create_text(c.bbox(item)[2] + 14, by, anchor="w", text=avg_text, fill=MUTED,
                      font=("Segoe UI", 10))
