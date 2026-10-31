"""
osu! analyzer - desktop app.

Left: your replays. Top: Replay Viewer / Hit Analyzer / Tablet Zone.
Ctrl/Shift-click several replays to combine them.
"""

import math
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

import osu_hit_analyzer as core
import viewer
from widgets import (FlatButton, NavBar, Segmented, RoundedEntry, RoundedPanel, ReplayList, Swatches,
                     round_rect, SIDEBAR, BORDER, HOVER)

BG, PANEL, FG, MUTED, PINK = core.BG, core.PANEL, core.FG, core.MUTED, core.PINK
FONT = ("Segoe UI", 10)
PAGES = [("viewer", "Replay Viewer"), ("analyzer", "Hit Analyzer"), ("tablet", "Tablet Zone")]


def resource(name):
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / name


_REPLAY_NAME = re.compile(
    r"^(?P<player>.+?) - (?P<map>.+) \((?P<date>\d{4}-\d{2}-\d{2})\) \w+(?:-(?P<n>\d+))?$")


def _display_name(path):
    """'Player - Artist - Title [Diff] (2026-10-15) Osu-3.osr'
    -> ('Artist - Title', 'Diff  ·  Player', '10-15 #4')."""
    stem = path.name[:-4] if path.name.lower().endswith(".osr") else path.name
    m = _REPLAY_NAME.match(stem)
    if not m:
        return stem, "", ""
    date = m.group("date")[5:]
    if m.group("n"):
        date += f" #{int(m.group('n')) + 1}"
    md = re.match(r"^(.*) \[(.*)\]$", m.group("map"))
    title, diff = (md.group(1), md.group(2)) if md else (m.group("map"), "")
    return title, "  ·  ".join(x for x in (diff, m.group("player")) if x), date


class App:
    def __init__(self, root, initial_files):
        self.root = root
        root.title(f"osu! analyzer {core.__version__}")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{int(sw * 0.9)}x{int(sh * 0.85)}+{int(sw * 0.05)}+{int(sh * 0.04)}")
        root.minsize(1100, 700)
        try:
            root.state("zoomed")
        except tk.TclError:
            pass
        root.configure(bg=BG)
        try:
            root.iconbitmap(str(resource("assets/icon.ico")))
        except tk.TclError:
            pass

        self.osu_dir = core.find_osu_dir()
        self.songs_dir = core.find_songs_dir(self.osu_dir) if self.osu_dir else None
        self.replays_dir = self.osu_dir / "Replays" if self.osu_dir else None

        self.cache = {}        # replay path -> (Replay, Beatmap)
        self.entries = []      # Paths shown in the sidebar
        self.shown = []        # entries currently visible after filtering
        self.current = []      # replay paths currently analysed
        self.analyses = []
        self.busy = False
        self.pending = None
        self.queue = queue.Queue()
        self._select_job = None
        self._started = 0.0
        self.page = None
        self._dirty = set()    # pages that need a redraw when shown

        self.auto_load = core.load_settings().get("auto_load", True)
        self._dir_mtime = None
        self._announce = None

        self.frame_mode = "screen"
        self.color_mode = "timing"
        self.heads = True
        self.filter_var = tk.StringVar()

        self._style()
        self._layout()
        self._bind_keys()
        self.refresh_list()
        self._welcome()
        self.show_page("viewer")
        self.root.after(50, self._poll)
        self.root.after(1500, self._watch)
        if initial_files:
            self.root.after(100, lambda: self.analyse_paths(initial_files))

    # ------------------------------------------------------------------ UI --

    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=FG, font=FONT)
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", foreground=MUTED, font=("Segoe UI", 9))
        s.configure("Title.TLabel", font=("Segoe UI Semibold", 13), foreground=PINK)
        s.configure("Card.TLabel", background=PANEL, foreground=FG, font=("Segoe UI Semibold", 12))
        s.configure("CardMuted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        s.configure("TEntry", fieldbackground=PANEL, foreground=FG, bordercolor=BORDER,
                    lightcolor=PANEL, darkcolor=PANEL, insertcolor=FG, padding=7)
        s.map("TEntry", bordercolor=[("focus", PINK)])
        s.configure("Dark.TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG,
                    arrowcolor=MUTED, bordercolor=BORDER, lightcolor=PANEL, darkcolor=PANEL, padding=5)
        s.map("Dark.TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)],
              selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", FG)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", PINK)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#15151c")
        s.configure("Pink.Horizontal.TProgressbar", troughcolor=BG, background=PINK,
                    bordercolor=PANEL, lightcolor=PINK, darkcolor=PINK)
        s.configure("Vertical.TScrollbar", background=PANEL, troughcolor=SIDEBAR,
                    bordercolor=SIDEBAR, arrowcolor=MUTED, lightcolor=PANEL, darkcolor=PANEL)
        s.map("Vertical.TScrollbar", background=[("active", HOVER)])
        s.configure("Treeview", background=SIDEBAR, fieldbackground=SIDEBAR, foreground=FG,
                    bordercolor=SIDEBAR, lightcolor=SIDEBAR, darkcolor=SIDEBAR, rowheight=28,
                    font=("Segoe UI", 9))
        s.map("Treeview", background=[("selected", PINK)], foreground=[("selected", "#15151c")])
        s.configure("Treeview.Heading", background=SIDEBAR, foreground=MUTED, bordercolor=SIDEBAR,
                    lightcolor=SIDEBAR, darkcolor=SIDEBAR, relief="flat", font=("Segoe UI", 9))
        s.map("Treeview.Heading", background=[("active", SIDEBAR)])
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])  # no border

    def _layout(self):
        # Sidebar: the replay list, nothing else
        side = tk.Frame(self.root, bg=SIDEBAR, width=400)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        head = tk.Frame(side, bg=SIDEBAR)
        head.pack(fill="x", padx=16, pady=(16, 10))
        tk.Label(head, text="Replays", bg=SIDEBAR, fg=FG, font=("Segoe UI Semibold", 14)).pack(side="left")
        self.count_label = tk.Label(head, bg=SIDEBAR, fg=MUTED, font=("Segoe UI", 10))
        self.count_label.pack(side="left", padx=(8, 0), pady=(3, 0))
        FlatButton(head, "＋", self.open_files, kind="ghost", font=("Segoe UI Semibold", 13),
                   padx=6, pady=0).pack(side="right")
        FlatButton(head, "⟳", self.refresh_list, kind="ghost", font=("Segoe UI Semibold", 12),
                   padx=6, pady=0).pack(side="right")

        self.filter_box = RoundedEntry(side, self.filter_var, "Filter by map, difficulty, player...")
        self.filter_box.pack(fill="x", padx=16, pady=(0, 10))
        self.filter_var.trace_add("write", lambda *_: self._fill_list())

        self.list = ReplayList(side, self._on_select)
        self.list.pack(fill="both", expand=True, padx=(10, 6))

        self.side_foot = tk.Frame(side, bg=SIDEBAR)
        self.side_foot.pack(fill="x", padx=16, pady=(8, 12))
        tk.Label(self.side_foot, text="Click a replay  ·  Ctrl/Shift+click to combine", bg=SIDEBAR,
                 fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        self.folder_btn = FlatButton(self.side_foot, "Choose your osu! folder", self.choose_osu_dir,
                                     kind="accent")

        tk.Frame(self.root, width=1, bg=BORDER).pack(side="left", fill="y")

        # Main: nav bar + pages
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.nav = NavBar(main, PAGES, "viewer", self.show_page, right_tabs=[("settings", "⚙  Settings")])
        self.nav.pack(fill="x")
        tk.Frame(main, height=1, bg=BORDER).pack(fill="x")
        self.status = tk.Label(main, bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w", padx=20, pady=4)
        self.status.pack(fill="x", side="bottom")
        self.pages_box = tk.Frame(main, bg=BG)
        self.pages_box.pack(fill="both", expand=True)

        self.viewer = viewer.ReplayViewer(self.pages_box)
        self.analyzer = self._build_analyzer(self.pages_box)
        self.tablet = TabletPage(self, self.pages_box)
        self.settings = SettingsPage(self, self.pages_box)
        self.pages = {"viewer": self.viewer.frame, "analyzer": self.analyzer, "tablet": self.tablet.frame,
                      "settings": self.settings.frame}
        for frame in self.pages.values():
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Loading card (placed over the pages while working)
        self.loading = RoundedPanel(self.pages_box, outline=BORDER, radius=16, padx=28, pady=22)
        self.loading_title = ttk.Label(self.loading.inner, text="Analysing...", style="Card.TLabel")
        self.loading_title.pack(anchor="w")
        self.loading_text = ttk.Label(self.loading.inner, text="", style="CardMuted.TLabel")
        self.loading_text.pack(anchor="w", pady=(4, 12))
        self.progress = ttk.Progressbar(self.loading.inner, length=340, mode="indeterminate",
                                        style="Pink.Horizontal.TProgressbar")
        self.progress.pack()

    def _build_analyzer(self, parent):
        page = tk.Frame(parent, bg=BG)
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", padx=20, pady=(14, 0))
        for label, seg in (
            ("View", Segmented(bar, [("screen", "Screen"), ("movement", "Movement")], self.frame_mode,
                               lambda v: self._set_option("frame_mode", v))),
            ("Colour", Segmented(bar, [("timing", "Timing"), ("judgement", "300 / 100 / 50")],
                                 self.color_mode, lambda v: self._set_option("color_mode", v))),
            ("Slider heads", Segmented(bar, [(True, "On"), (False, "Off")], self.heads,
                                       lambda v: self._set_option("heads", v))),
        ):
            tk.Label(bar, text=label, bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(side="left", padx=(0, 8))
            seg.pack(side="left", padx=(0, 22))
        FlatButton(bar, "Save image", self.save_image, kind="panel").pack(side="right")
        self.fig = Figure(figsize=(14, 9.5), facecolor=BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=page)
        self.canvas.get_tk_widget().configure(bg=BG, highlightthickness=0)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        return page

    def _bind_keys(self):
        r = self.root
        r.bind_all("<Key>", self._on_key)
        r.bind_all("<Control-o>", lambda e: self.open_files())
        r.bind_all("<Control-s>", lambda e: self.save_image())
        r.bind_all("<F5>", lambda e: self.refresh_list())
        for i, (key, _label) in enumerate(PAGES, 1):
            r.bind_all(f"<Control-Key-{i}>", lambda e, k=key: self.show_page(k))

    def _on_key(self, e):
        if self.page != "viewer" or e.state & 0x4:   # Ctrl shortcuts are handled above
            return
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox)):  # typing in the filter
            return
        self.viewer.handle_key(e.keysym)

    def show_page(self, key):
        if key == self.page:
            return
        if self.page == "viewer":
            self.viewer.pause()
        self.page = key
        self.pages[key].tkraise()
        if self.loading.winfo_ismapped():
            tk.Misc.tkraise(self.loading)  # (Canvas.tkraise raises items, not the widget)
        self.nav.select(key)
        if key in self._dirty:
            self._dirty.discard(key)
            if key == "analyzer":
                self.redraw()
            elif key == "tablet":
                self.tablet.refresh()
        if key == "viewer":
            self.viewer.canvas.focus_set()

    def _set_option(self, name, value):
        setattr(self, name, value)
        if name == "heads":
            self.reanalyse()
        else:
            self.redraw()

    def _welcome(self):
        self.fig.clear()
        self.fig.set_facecolor(BG)
        self.fig.text(0.5, 0.53, "Hit Analyzer", color=PINK, ha="center", fontsize=24, weight="bold")
        self.fig.text(0.5, 0.47, "Pick a replay on the left  ·  Ctrl/Shift+click to combine several",
                      color=MUTED, ha="center", fontsize=12)
        self.canvas.draw_idle()

    # ------------------------------------------------------- replay list --

    def refresh_list(self):
        if self.replays_dir and self.replays_dir.is_dir():
            files = sorted(self.replays_dir.glob("*.osr"), key=lambda p: p.stat().st_mtime,
                           reverse=True)
            self.folder_btn.pack_forget()
        else:
            files = []
            self.folder_btn.pack(fill="x", pady=(8, 0))
        extra = [p for p in self.entries if p not in files and p.exists()
                 and (not self.replays_dir or p.parent != self.replays_dir)]
        self.entries = extra + files
        self.count_label.config(text=str(len(self.entries)))
        self._fill_list()

    def _fill_list(self):
        words = self.filter_var.get().lower().split()
        self.shown = [p for p in self.entries if all(w in p.name.lower() for w in words)]
        current = {str(p) for p in self.current}
        selected = [i for i, p in enumerate(self.shown) if str(p) in current]
        self.list.set_items([_display_name(p) for p in self.shown], selected)
        if selected:
            self.list.see(selected[0])

    def _on_select(self, _indices):
        if self._select_job:
            self.root.after_cancel(self._select_job)
        self._select_job = self.root.after(250, self._commit_selection)

    def _commit_selection(self):
        self._select_job = None
        paths = [self.shown[i] for i in sorted(self.list.selected)]
        if paths and [str(p) for p in paths] != [str(p) for p in self.current]:
            self.analyse_paths(paths)

    def open_files(self):
        init = str(self.replays_dir) if self.replays_dir and self.replays_dir.is_dir() else None
        files = filedialog.askopenfilenames(
            title="Choose osu! replay(s)", initialdir=init,
            filetypes=[("osu! replay", "*.osr"), ("All files", "*.*")])
        if files:
            paths = [Path(f) for f in files]
            for p in paths:
                if p not in self.entries:
                    self.entries.insert(0, p)
            self.filter_var.set("")
            self.count_label.config(text=str(len(self.entries)))
            self.analyse_paths(paths)

    def _watch(self):
        """Notice replays osu! saves while the app is open (F2, replay export) and load them."""
        try:
            if self.replays_dir and self.replays_dir.is_dir():
                m = self.replays_dir.stat().st_mtime_ns
                if self._dir_mtime is not None and m != self._dir_mtime:
                    known = {str(p) for p in self.entries}
                    self.refresh_list()
                    new = [p for p in self.entries if str(p) not in known]
                    if new and self.auto_load:
                        newest = max(new, key=lambda q: q.stat().st_mtime)
                        self._wait_until_written(newest, -1, 0)
                self._dir_mtime = m
        except OSError:
            pass
        self.root.after(1500, self._watch)

    def _wait_until_written(self, path, last_size, tries):
        try:
            size = path.stat().st_size
        except OSError:
            return
        if (size == last_size and size > 0) or tries > 25:
            self._announce = path
            self.filter_var.set("")
            self.analyse_paths([path])
        else:
            self.root.after(300, lambda: self._wait_until_written(path, size, tries + 1))

    def set_auto_load(self, value):
        self.auto_load = value
        core.save_settings(auto_load=value)

    def refresh_all(self):
        """Rescan everything: osu! folder, replay list, beatmaps, current analysis."""
        if not (self.osu_dir and self.osu_dir.exists()):
            self.osu_dir = core.find_osu_dir()
            self.songs_dir = core.find_songs_dir(self.osu_dir) if self.osu_dir else None
            self.replays_dir = self.osu_dir / "Replays" if self.osu_dir else None
        self.cache.clear()
        self.refresh_list()
        if self.current:
            self.analyse_paths(self.current)
        self.status.config(text="Refreshed", fg=MUTED)

    def close(self):
        self.viewer.shutdown()
        self.root.destroy()

    def restart(self):
        if getattr(sys, "frozen", False):
            args = [sys.executable]
        else:
            args = [sys.executable, str(Path(__file__).resolve())]
        # A fresh exe instance must not reuse this one's unpacked files
        env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
        subprocess.Popen(args, env=env, close_fds=True)
        self.close()

    def choose_osu_dir(self):
        d = filedialog.askdirectory(title="Choose your osu! folder")
        if not d:
            return
        self.osu_dir = Path(d)
        self.songs_dir = core.find_songs_dir(self.osu_dir)
        self.replays_dir = self.osu_dir / "Replays"
        self._dir_mtime = None
        self.refresh_list()
        self.settings.update_folder()

    # ---------------------------------------------------------- analysis --

    def analyse_paths(self, paths, overrides=None):
        paths = [Path(p) for p in paths]
        if self.busy:
            self.pending = (paths, overrides)
            return
        self.busy = True
        self._started = time.perf_counter()
        self.current = paths
        self._fill_list()
        self._show_loading("Analysing..." if len(paths) == 1 else f"Analysing {len(paths)} replays...")
        threading.Thread(target=self._worker, args=(paths, self.heads, overrides or {}),
                         daemon=True).start()

    def _on_pick(self, analysis, obj):
        """Click on a dot / X in the Hit Analyzer: watch that note in the viewer."""
        self.show_page("viewer")
        if self.viewer.a is not analysis:
            self.viewer.set_analyses(self.analyses, analysis)
        self.viewer.play_from(obj.time - 1500)

    def reanalyse(self):
        if self.current:
            self.analyse_paths(self.current)

    def _worker(self, paths, heads, overrides):
        post = self.queue.put
        analyses, missing, errors = [], [], []
        for n, p in enumerate(paths, 1):
            tag = f"[{n}/{len(paths)}]  " if len(paths) > 1 else ""
            key = str(p)
            try:
                if key in self.cache:
                    replay, bm = self.cache[key]
                else:
                    post(("status", f"{tag}Reading replay  {p.name}"))
                    replay = core.read_replay(p)
                    if replay.mode != 0:
                        errors.append(f"{p.name}: not an osu!standard replay")
                        continue
                    bpath = overrides.get(key)
                    if not bpath and self.songs_dir and self.songs_dir.is_dir():
                        post(("status", f"{tag}Looking for the beatmap..."))
                        bpath = core.find_beatmap(
                            replay.beatmap_md5, self.songs_dir,
                            progress=lambda d, t: post(("progress", f"Indexing your beatmaps (first time only)  {d:,} / {t:,}", d, t)))
                    if not bpath:
                        missing.append(p)
                        continue
                    post(("status", f"{tag}Loading beatmap  {Path(bpath).name}"))
                    bm = core.read_beatmap(bpath, hard_rock=bool(replay.mods & core.MOD_HR),
                                           easy=bool(replay.mods & core.MOD_EZ))
                    self.cache[key] = (replay, bm)
                post(("status", f"{tag}Calculating hits and cursor offsets..."))
                analyses.append(core.analyse(replay, bm, include_slider_heads=heads))
            except Exception as e:  # noqa: BLE001 - shown to the user
                errors.append(f"{p.name}: {e}")
                traceback.print_exc()
        post(("done", paths, analyses, missing, errors))

    def _poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "status":
                    self._set_indeterminate()
                    self.loading_text.config(text=msg[1])
                elif kind == "progress":
                    _, text, done, total = msg
                    if str(self.progress.cget("mode")) != "determinate":
                        self.progress.stop()
                        self.progress.config(mode="determinate")
                    self.progress.config(maximum=max(total, 1), value=done)
                    self.loading_text.config(text=text)
                elif kind == "done":
                    self._finish(*msg[1:])
        except queue.Empty:
            pass
        self.root.after(40, self._poll)

    def _finish(self, paths, analyses, missing, errors):
        self.busy = False
        # Beatmaps that could not be found automatically: ask for the .osu file
        overrides = {}
        for p in missing:
            f = filedialog.askopenfilename(
                title=f"Beatmap not found for {p.name} - choose the .osu file",
                initialdir=str(self.songs_dir) if self.songs_dir else None,
                filetypes=[("osu! beatmap", "*.osu"), ("All files", "*.*")])
            if f:
                overrides[str(p)] = f
        if overrides:
            self.analyse_paths([p for p in paths if p not in missing or str(p) in overrides],
                               overrides)
            return

        if self.pending:
            nxt, ov = self.pending
            self.pending = None
            self.analyse_paths(nxt, ov)
            return

        self.analyses = analyses
        self.loading_text.config(text="Drawing...")
        self._set_indeterminate()
        self.root.update_idletasks()
        self.viewer.set_analyses(analyses)
        self._dirty = {"analyzer", "tablet"} - {self.page}
        if self.page == "analyzer":
            self.redraw()
        elif self.page == "tablet":
            self.tablet.refresh()
        self._hide_loading()

        elapsed = time.perf_counter() - self._started
        if analyses:
            hits = sum(len(a.hits) for a in analyses)
            misses = sum(len(a.misses) for a in analyses)
            what = (f"{analyses[0].beatmap.artist} - {analyses[0].beatmap.title} "
                    f"[{analyses[0].beatmap.diff_name}]" if len(analyses) == 1
                    else f"{len(analyses)} replays")
            text = f"{what}   ·   {hits} hits, {misses} misses   ·   loaded in {elapsed:.1f} s"
        else:
            text = "Nothing to show"
        if self._announce:
            text = f"New replay loaded   ·   {text}"
            self._announce = None
        if errors:
            text += "   ·   skipped: " + "; ".join(errors)
        self.status.config(text=text, fg=MUTED if not errors else "#ffb347")

    def redraw(self):
        if not self.analyses:
            self._welcome()
            return
        core.draw(self.fig, self.analyses, frame=self.frame_mode,
                  color_by=self.color_mode, on_pick=self._on_pick)
        self.canvas.draw_idle()

    # ------------------------------------------------------------ helpers --

    def _set_indeterminate(self):
        if str(self.progress.cget("mode")) != "indeterminate":
            self.progress.config(mode="indeterminate", value=0)
        self.progress.start(12)

    def _show_loading(self, title):
        self.loading_title.config(text=title)
        self.loading_text.config(text="Starting...")
        self._set_indeterminate()
        self.loading.place(relx=0.5, rely=0.45, anchor="center")
        tk.Misc.tkraise(self.loading)  # (Canvas.tkraise raises items, not the widget)

    def _hide_loading(self):
        self.progress.stop()
        self.loading.place_forget()

    def save_image(self):
        if not self.analyses:
            self.status.config(text="Pick a replay first.")
            return
        if self.page != "analyzer":
            self.show_page("analyzer")
        a = self.analyses[0]
        default = (f"{a.replay.player} - {a.beatmap.title} [{a.beatmap.diff_name}].png"
                   if len(self.analyses) == 1 else "combined.png")
        default = "".join(c for c in default if c not in '\\/:*?"<>|')
        f = filedialog.asksaveasfilename(defaultextension=".png", initialfile=default,
                                         filetypes=[("PNG image", "*.png")])
        if f:
            self.fig.savefig(f, dpi=130, facecolor=BG)
            self.status.config(text=f"Saved {f}", fg=MUTED)


def selftest(out_png, replay):
    """Headless check of the packaged app: analyse a replay and save the plot, no window."""
    root = tk.Tk()
    root.withdraw()
    fig = Figure(figsize=(14, 9.5), facecolor=BG)
    FigureCanvasTkAgg(fig, master=root)
    osu_dir = core.find_osu_dir()
    r = core.read_replay(replay)
    bpath = core.find_beatmap(r.beatmap_md5, core.find_songs_dir(osu_dir), progress=lambda *_: None)
    bm = core.read_beatmap(bpath, hard_rock=bool(r.mods & core.MOD_HR), easy=bool(r.mods & core.MOD_EZ))
    a = core.analyse(r, bm)
    core.draw(fig, [a])
    fig.savefig(out_png, dpi=100, facecolor=BG)
    Path(out_png).with_suffix(".txt").write_text(f"{len(a.hits)} hits, {len(a.misses)} misses\n")
    root.destroy()


def close_splash():
    try:
        import pyi_splash  # only exists inside the PyInstaller exe
        pyi_splash.close()
    except ImportError:
        pass


AREA_DEFAULTS = {"top": 2000, "bottom": 5000, "left": 1600, "right": 5000,
                 "tablet_w": 15200, "tablet_h": 9500}


def screen_size(osu_dir, root):
    """osu! fullscreen resolution from its config, else the monitor size."""
    if osu_dir:
        for cfg in osu_dir.glob("osu!.*.cfg"):
            try:
                kv = dict(line.split(" = ", 1) for line in
                          cfg.read_text(encoding="utf-8", errors="replace").splitlines() if " = " in line)
                w, h = int(kv["WidthFullscreen"]), int(kv["HeightFullscreen"])
                if w > 0 and h > 0:
                    return w, h
            except (OSError, KeyError, ValueError):
                continue
    return root.winfo_screenwidth(), root.winfo_screenheight()


class TabletPage:
    """Suggests a tablet area from where you over / underaim on the playfield."""

    FIELDS = (("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right"))
    SIDES = {"top": "top notes", "bottom": "bottom notes", "left": "left notes", "right": "right notes"}

    def __init__(self, app, parent):
        self.app = app
        self._job = None
        self.frame = tk.Frame(parent, bg=BG)

        settings = {**AREA_DEFAULTS, **core.load_settings()}
        self.vars = {k: tk.StringVar(value=str(settings[k])) for k in AREA_DEFAULTS}

        left = ttk.Frame(self.frame, padding=(20, 16, 10, 16))
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(self.frame, padding=(10, 16, 20, 16))
        right.pack(side="left", fill="both", expand=True)

        # Left: current area, tablet drawing, suggestion
        ttk.Label(left, text="Your tablet area", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="As in Wacom Center, in points  (Haut / Bas / Gauche / Droite)",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        grid = ttk.Frame(left)
        grid.pack(fill="x")
        for i, (key, label) in enumerate(self.FIELDS):
            r, c = divmod(i, 2)
            ttk.Label(grid, text=label).grid(row=r, column=c * 2, sticky="e",
                                              padx=(0 if c == 0 else 30, 8), pady=3)
            ttk.Entry(grid, textvariable=self.vars[key], width=9).grid(row=r, column=c * 2 + 1,
                                                                       sticky="w", pady=3)
        ttk.Label(grid, text="Tablet").grid(row=2, column=0, sticky="e", padx=(0, 8), pady=(10, 3))
        tf = ttk.Frame(grid)
        tf.grid(row=2, column=1, columnspan=3, sticky="w", pady=(10, 3))
        ttk.Entry(tf, textvariable=self.vars["tablet_w"], width=7).pack(side="left")
        ttk.Label(tf, text=" × ").pack(side="left")
        ttk.Entry(tf, textvariable=self.vars["tablet_h"], width=7).pack(side="left")
        ttk.Label(tf, text="   Intuos S = 15200 × 9500  (100 points = 1 mm)",
                  style="Muted.TLabel").pack(side="left")
        for v in self.vars.values():
            v.trace_add("write", lambda *_: self._schedule())

        self.tablet_canvas = tk.Canvas(left, height=200, bg=BG, highlightthickness=0)
        self.tablet_canvas.pack(fill="x", pady=(14, 10))
        self.tablet_canvas.bind("<Configure>", lambda e: self._schedule())
        self.result = ttk.Frame(left)
        self.result.pack(fill="both", expand=True)

        # Right: where you over / underaim on the playfield
        ttk.Label(right, text="Where you miss on the playfield", style="Title.TLabel").pack(anchor="w")
        ttk.Label(right, text="overaim = the cursor goes past the note in the jump's direction  ·  "
                              "underaim = it stops before", style="Muted.TLabel",
                  wraplength=560).pack(anchor="w", pady=(2, 8))
        self.aim_text = ttk.Frame(right)
        self.aim_text.pack(fill="x")
        self.field_canvas = tk.Canvas(right, bg=BG, highlightthickness=0)
        self.field_canvas.pack(fill="both", expand=True, pady=(10, 6))
        self.field_canvas.bind("<Configure>", lambda e: self._schedule())
        ttk.Label(right, text="Arrow = where your cursor lands on average for notes in that area "
                              "(drawn 4× bigger).  Numbers = overaim / underaim misses.",
                  style="Muted.TLabel", wraplength=560).pack(anchor="w")
        self.refresh()

    def _schedule(self):
        if self._job:
            self.frame.after_cancel(self._job)
        self._job = self.frame.after(250, self.refresh)

    def _row(self, parent, text, style="TLabel", **pack):
        lbl = ttk.Label(parent, text=text, style=style, wraplength=560, justify="left")
        lbl.pack(anchor="w", **({"pady": 2} | pack))
        return lbl

    def refresh(self):
        self._job = None
        for frame in (self.result, self.aim_text):
            for child in frame.winfo_children():
                child.destroy()
        try:
            vals = {k: int(float(v.get())) for k, v in self.vars.items()}
        except ValueError:
            self._row(self.result, "Invalid values.", "Muted.TLabel")
            return
        area = (vals["top"], vals["bottom"], vals["left"], vals["right"])
        tablet = (vals["tablet_w"], vals["tablet_h"])
        if area[1] <= area[0] or area[3] <= area[2] or min(tablet) <= 0:
            self._row(self.result, "Bottom must be > Top and Right > Left.", "Muted.TLabel")
            return
        core.save_settings(**vals)

        analyses = self.app.analyses
        if not analyses:
            self._draw_tablet(tablet, area, None)
            self._draw_field(None)
            self._row(self.result, "Pick one or more replays on the left (Ctrl+click to combine "
                      "several: the more notes, the more reliable the result).", "Muted.TLabel")
            return

        screen = screen_size(self.app.osu_dir, self.app.root)
        s = core.suggest_tablet_area(analyses, area, tablet, screen)
        self._draw_tablet(tablet, area, s.suggested)
        self._draw_field(s)
        self._fill_aim_text(s)
        self._fill_result(s, area, len(analyses), screen)

    def _fill_aim_text(self, s):
        ms, hs = s.miss_split, s.hit_split
        if ms.total:
            self._row(self.aim_text, f"Misses (clicked next to the note):  {ms.over} overaim  ·  "
                                     f"{ms.under} underaim   ({ms.over_pct:.0f}% overaim)")
        else:
            self._row(self.aim_text, "No misses where you clicked next to the note.")
        if hs.total:
            self._row(self.aim_text, f"Hits:  {hs.over_pct:.0f}% overaim  ·  "
                                     f"{100 - hs.over_pct:.0f}% underaim")

    def _fill_result(self, s, area, n, screen):
        self._row(self.result, f"Based on {n} replay{'s' if n > 1 else ''}  ·  {s.n_samples} clicks",
                  "Muted.TLabel", pady=(0, 6))

        panel = RoundedPanel(self.result, outline=PINK, radius=14, padx=18, pady=14, stretch=True)
        panel.pack(fill="x")
        box = panel.inner
        tk.Label(box, text="SUGGESTED AREA", bg=PANEL, fg=PINK,
                 font=("Segoe UI Semibold", 10)).grid(row=0, column=0, columnspan=4, sticky="w")
        for i, (key, label) in enumerate(self.FIELDS):
            r, c = divmod(i, 2)
            old, new = area[i], s.suggested[i]
            delta = f"  ({new - old:+d})" if new != old else ""
            tk.Label(box, text=label, bg=PANEL, fg=MUTED, font=FONT).grid(
                row=r + 1, column=c * 2, sticky="e", padx=(0 if c == 0 else 30, 8), pady=2)
            tk.Label(box, text=f"{new}{delta}", bg=PANEL, fg=FG if new == old else core.AVG,
                     font=("Segoe UI Semibold", 12)).grid(row=r + 1, column=c * 2 + 1, sticky="w")
        ow, oh = (area[3] - area[2]) / 100, (area[1] - area[0]) / 100
        nw = (s.suggested[3] - s.suggested[2]) / 100
        nh = (s.suggested[1] - s.suggested[0]) / 100
        tk.Label(box, text=f"{nw:.1f} × {nh:.1f} mm   (was {ow:.1f} × {oh:.1f} mm)", bg=PANEL,
                 fg=MUTED, font=("Segoe UI", 9)).grid(row=3, column=0, columnspan=4, sticky="w",
                                                      pady=(6, 0))
        FlatButton(box, "Copy", lambda: self._copy(s.suggested), kind="accent").grid(
            row=1, column=4, rowspan=2, padx=(30, 0))

        for key, label in self.FIELDS:
            self._row(self.result, f"{label}:  {self._describe_edge(key, s.edges[key])}",
                      pady=(6 if key == 'top' else 1, 1))

        self._row(self.result, f"Estimated misses on {'this replay' if n == 1 else 'these replays'}:  "
                               f"{s.misses_now}  →  {s.misses_after}", pady=(10, 2))
        if s.suggested == area:
            self._row(self.result, "Your area is already well calibrated: no edge shows a measurable "
                      "overaim or underaim.", "Muted.TLabel")
        if s.misses_now and s.misses_now - s.misses_after <= max(1, s.misses_now // 10):
            self._row(self.result, "Most of your misses come from aim scatter, not from an area bias: "
                      "the area only fixes the systematic offset.", "Muted.TLabel")
        if s.clamped:
            self._row(self.result, "Large bias: change limited to ±15% per edge. Analyse again after a "
                      "few maps with the new area.", "Muted.TLabel")
        sw, sh = screen
        zr, sr = (area[3] - area[2]) / (area[1] - area[0]), sw / sh
        if abs(zr / sr - 1) > 0.05:
            self._row(self.result, f"Computed for an area stretched over the whole {sw}×{sh} screen "
                      f"(\"Force proportions\" off). Your area ratio ({zr:.2f}) differs from the "
                      f"screen's ({sr:.2f}).", "Muted.TLabel", pady=(8, 2))
        self._row(self.result, "Apply it, play a few maps, then analyse again: adjust in small steps.",
                  "Muted.TLabel", pady=(4, 2))

    def _describe_edge(self, key, e):
        side = self.SIDES[key]
        if e.stderr is None:
            return "not enough notes to measure."
        d = e.suggested - e.current
        if d == 0:
            return f"no clear bias on {side}, unchanged."
        outward = d > 0 if key in ("bottom", "right") else d < 0
        if outward:
            return f"you overaim {side}  →  edge moved out by {abs(d)} (bigger on that side)."
        return f"you underaim {side}  →  edge moved in by {abs(d)} (smaller on that side)."

    def _copy(self, area):
        t, b, l, r = area
        self.frame.clipboard_clear()
        self.frame.clipboard_append(f"Top {t}  Bottom {b}  Left {l}  Right {r}")
        self.app.status.config(text="Suggested area copied to the clipboard", fg=MUTED)

    def _draw_tablet(self, tablet, area, suggested):
        c = self.tablet_canvas
        c.delete("all")
        cw, ch = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        round_rect(c, 0, 0, cw, ch, 14, fill=PANEL, outline="")
        pad = 14
        k = min((cw - 2 * pad) / tablet[0], (ch - 2 * pad - 18) / tablet[1])
        ox, oy = (cw - tablet[0] * k) / 2, pad

        def rect(a, **kw):
            t, b, l, r = a
            return c.create_rectangle(ox + l * k, oy + t * k, ox + r * k, oy + b * k, **kw)

        t0, b0, l0, r0 = 0, tablet[1], 0, tablet[0]
        round_rect(c, ox + l0 * k, oy + t0 * k, ox + r0 * k, oy + b0 * k, 12, outline=BORDER, width=2,
                   fill="#18181f")
        if suggested:
            rect(suggested, outline=PINK, width=2, fill="#3a2433")
        rect(area, outline=FG, width=1, dash=(4, 3))
        y = oy + tablet[1] * k + 11
        c.create_text(ox, y, text="- - -  current area", fill=FG, anchor="w", font=("Segoe UI", 9))
        if suggested:
            c.create_text(ox + 150, y, text="▬  suggested area", fill=PINK, anchor="w",
                          font=("Segoe UI", 9))

    def _draw_field(self, s):
        c = self.field_canvas
        c.delete("all")
        cw, ch = max(c.winfo_width(), 100), max(c.winfo_height(), 100)
        round_rect(c, 0, 0, cw, ch, 14, fill=PANEL, outline="")
        pad = 16
        k = min((cw - 2 * pad) / 512, (ch - 2 * pad) / 384)
        ox, oy = (cw - 512 * k) / 2, (ch - 384 * k) / 2
        cell_w, cell_h = 512 * k / 3, 384 * k / 3
        c.create_rectangle(ox, oy, ox + 512 * k, oy + 384 * k, outline=BORDER, width=2, fill="#18181f")
        if not s:
            c.create_text(cw / 2, ch / 2, text="(no replay)", fill=MUTED, font=FONT)
            return
        most = max((r.misses.total for r in s.regions), default=0) or 1
        for r in s.regions:
            x0, y0 = ox + r.col * cell_w, oy + r.row * cell_h
            heat = r.misses.total / most
            fill = _mix("#18181f", "#5a2440", heat) if r.misses.total else "#18181f"
            c.create_rectangle(x0, y0, x0 + cell_w, y0 + cell_h, outline=BORDER, fill=fill)
            cx, cy = x0 + cell_w / 2, y0 + cell_h / 2
            if r.n >= 15:
                ex, ey = r.mean_err
                scale = min(cell_w, cell_h) * 0.9  # 1 radius of error = 0.9 cell (×4 visually)
                ax, ay = cx + ex * scale, cy + ey * scale
                lim = min(cell_w, cell_h) * 0.42
                d = math.hypot(ax - cx, ay - cy)
                if d > lim:
                    ax, ay = cx + (ax - cx) * lim / d, cy + (ay - cy) * lim / d
                c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=MUTED, outline="")
                if d > 2:
                    c.create_line(cx, cy, ax, ay, fill=core.AVG, width=3, arrow="last",
                                  arrowshape=(10, 12, 4))
                c.create_text(x0 + 6, y0 + 4, anchor="nw", fill=MUTED, font=("Segoe UI", 8),
                              text=f"{math.hypot(ex, ey) * 100:.0f}% r")
            c.create_text(cx, y0 + cell_h - 8, anchor="s", fill=FG, font=("Segoe UI", 9),
                          text=f"{r.misses.over} over / {r.misses.under} under")
            c.create_text(x0 + cell_w - 6, y0 + 4, anchor="ne", fill=MUTED, font=("Segoe UI", 8),
                          text=f"{r.n} clicks")


ACCENTS = ["#ff66aa", "#5ac8fa", "#7ed957", "#ffb347", "#b48cff", "#ff5c6c"]
BG_LEVELS = [(0.0, "Off"), (0.1, "Darker"), (0.16, "Dark"), (0.26, "Dim")]


class SettingsPage:
    def __init__(self, app, parent):
        self.app = app
        self.frame = tk.Frame(parent, bg=BG)
        col = tk.Frame(self.frame, bg=BG)
        col.pack(fill="x", padx=60, pady=(26, 16), anchor="n")
        tk.Label(col, text="Settings", bg=BG, fg=FG, font=("Segoe UI Semibold", 18)).pack(anchor="w", pady=(0, 16))

        self._card(col, "Refresh", "Rescan your replays, reload the beatmaps and analyse the current "
                   "selection again.",
                   lambda box: FlatButton(box, "Refresh everything", app.refresh_all, kind="accent"))
        self._card(col, "New replays", "Load a replay automatically as soon as osu! saves it "
                   "(F2 after a play, or exporting a replay).",
                   lambda box: Segmented(box, [(True, "On"), (False, "Off")], app.auto_load,
                                         app.set_auto_load))

        def accent(box):
            f = tk.Frame(box, bg=PANEL)
            Swatches(f, ACCENTS, core.PINK, self._accent_changed).pack(side="left")
            self.restart_btn = FlatButton(f, "Restart to apply", app.restart, kind="panel")
            return f
        self._card(col, "Accent colour", "Colour used for highlights, buttons and the analyzer.", accent)

        dim = app.viewer.bg_dim
        nearest = min(BG_LEVELS, key=lambda lv: abs(lv[0] - dim))[0]
        self._card(col, "Viewer background", "How visible the beatmap background is behind the replay.",
                   lambda box: Segmented(box, BG_LEVELS, nearest, self._bg_changed))

        def folder(box):
            f = tk.Frame(box, bg=PANEL)
            FlatButton(f, "Change...", app.choose_osu_dir, kind="panel").pack(side="right")
            return f
        self.folder_text = self._card(col, "osu! folder", "", folder)
        self.update_folder()

    def _card(self, parent, title, text, make_control):
        panel = RoundedPanel(parent, radius=14, padx=22, pady=16, stretch=True)
        panel.pack(fill="x", pady=(0, 12))
        box = panel.inner
        box.columnconfigure(0, weight=1)
        tk.Label(box, text=title, bg=PANEL, fg=FG, font=("Segoe UI Semibold", 11)).grid(row=0, column=0, sticky="w")
        desc = tk.Label(box, text=text, bg=PANEL, fg=MUTED, font=("Segoe UI", 9), justify="left",
                        wraplength=620)
        desc.grid(row=1, column=0, sticky="w", pady=(3, 0))
        make_control(box).grid(row=0, column=1, rowspan=2, sticky="e", padx=(24, 0))
        return desc

    def update_folder(self):
        d = self.app.osu_dir
        self.folder_text.config(text=str(d) if d else "Not found - choose it with Change...")

    def _accent_changed(self, colour):
        core.save_settings(accent=colour)
        if colour.lower() != core.PINK.lower():
            self.restart_btn.pack(side="left", padx=(16, 0))
        else:
            self.restart_btn.pack_forget()

    def _bg_changed(self, value):
        core.save_settings(bg_dim=value)
        self.app.viewer.set_bg_dim(value)


def _mix(a, b, t):
    """Blend two #rrggbb colours."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "--selftest":
        close_splash()
        selftest(sys.argv[2], sys.argv[3])
        return
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()

    def report(exc, val, tb):
        messagebox.showerror("Error", "".join(traceback.format_exception(exc, val, tb))[-2000:])
    root.report_callback_exception = report

    files = [a for a in sys.argv[1:] if a.lower().endswith(".osr")]
    app = App(root, files)
    close_splash()

    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()
