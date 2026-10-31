"""Small rounded Tk widgets shared by the app: nav bar, buttons, segmented pills, panels,
text field, play button and volume slider."""

import tkinter as tk
from tkinter import font as tkfont

import osu_hit_analyzer as core

BG, PANEL, FG, MUTED, PINK = core.BG, core.PANEL, core.FG, core.MUTED, core.PINK
SIDEBAR = "#1a1a23"
BORDER = "#33334a"
HOVER = "#2a2a38"
DARK_TEXT = "#15151c"


def lighten(colour, t=0.22):
    r, g, b = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(round(v + (255 - v) * t) for v in (r, g, b))


ACCENT_HOVER = lighten(PINK)


def round_rect(c, x0, y0, x1, y1, r, **kw):
    """Rounded rectangle on a canvas (smoothed polygon)."""
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, splinesteps=12, **kw)


def bg_of(widget, default=BG):
    try:
        return widget.cget("bg")
    except tk.TclError:  # ttk widgets have no "bg"
        return default


class FlatButton(tk.Canvas):
    """Rounded flat button. kind: 'ghost' | 'panel' | 'accent'."""

    STYLES = {
        "ghost": (None, MUTED, HOVER, FG),
        "panel": (PANEL, FG, HOVER, FG),
        "accent": (PINK, DARK_TEXT, ACCENT_HOVER, DARK_TEXT),
    }

    def __init__(self, parent, text, command, kind="panel", font=("Segoe UI Semibold", 10),
                 padx=12, pady=6, radius=8):
        f = tkfont.Font(font=font)
        w, h = f.measure(text) + 2 * padx, f.metrics("linespace") + 2 * pady
        super().__init__(parent, width=w, height=h, bg=bg_of(parent), highlightthickness=0, cursor="hand2")
        self.text, self.font, self.command, self.radius = text, font, command, radius
        self.style = self.STYLES[kind]
        self._hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<Button-1>", lambda e: self.command and self.command())
        self._draw()

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    def _draw(self):
        self.delete("all")
        bg, fg, hbg, hfg = self.style
        w, h = int(self.cget("width")), int(self.cget("height"))
        fill = hbg if self._hover else bg
        if fill:
            round_rect(self, 0, 0, w, h, self.radius, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=self.text, font=self.font, fill=hfg if self._hover else fg)


class PlayButton(tk.Canvas):
    """Round pink play / pause button."""

    def __init__(self, parent, command, size=46):
        super().__init__(parent, width=size, height=size, bg=bg_of(parent), highlightthickness=0, cursor="hand2")
        self.size, self.command, self.playing, self._hover = size, command, False, False
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self._draw()

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    def set_playing(self, playing):
        if playing != self.playing:
            self.playing = playing
            self._draw()

    def _draw(self):
        s = self.size
        self.delete("all")
        self.create_oval(2, 2, s - 2, s - 2, fill=ACCENT_HOVER if self._hover else PINK, outline="")
        c = s / 2
        if self.playing:
            w, h = s * 0.09, s * 0.17
            for dx in (-s * 0.1, s * 0.1):
                round_rect(self, c + dx - w / 2 - 1, c - h, c + dx + w / 2 + 1, c + h, 2,
                           fill=DARK_TEXT, outline="")
        else:
            h = s * 0.18
            self.create_polygon(c - h * 0.7, c - h, c - h * 0.7, c + h, c + h * 1.05, c,
                                fill=DARK_TEXT, outline="")


class Segmented(tk.Canvas):
    """Rounded group of pills, one selected. options: list of (value, label)."""

    def __init__(self, parent, options, value, command=None, font=("Segoe UI Semibold", 9),
                 padx=11, pady=4, gap=2, inset=3):
        f = tkfont.Font(font=font)
        self.font, self.inset = font, inset
        h = f.metrics("linespace") + 2 * pady
        x = inset
        self.cells = []
        for val, label in options:
            w = f.measure(label) + 2 * padx
            self.cells.append((val, label, x, x + w))
            x += w + gap
        super().__init__(parent, width=x - gap + inset, height=h + 2 * inset, bg=bg_of(parent),
                         highlightthickness=0, cursor="hand2")
        self.command, self.value, self.h, self._hover = command, value, h, None
        self.bind("<Button-1>", lambda e: self._hit(e.x) is not None and self.set(self._hit(e.x), notify=True))
        self.bind("<Motion>", lambda e: self._set_hover(self._hit(e.x)))
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self._draw()

    def _hit(self, x):
        for val, _label, x0, x1 in self.cells:
            if x0 <= x <= x1:
                return val
        return None

    def _set_hover(self, val):
        if val != self._hover:
            self._hover = val
            self._draw()

    def set(self, value, notify=False):
        changed = value != self.value
        self.value = value
        self._draw()
        if notify and changed and self.command:
            self.command(value)

    def _draw(self):
        self.delete("all")
        w, h, i = int(self.cget("width")), int(self.cget("height")), self.inset
        round_rect(self, 0, 0, w, h, h / 2, fill=PANEL, outline="")
        for val, label, x0, x1 in self.cells:
            if val == self.value:
                round_rect(self, x0, i, x1, i + self.h, self.h / 2, fill=PINK, outline="")
                colour = DARK_TEXT
            else:
                if val == self._hover:
                    round_rect(self, x0, i, x1, i + self.h, self.h / 2, fill=HOVER, outline="")
                colour = FG if val == self._hover else MUTED
            self.create_text((x0 + x1) / 2, i + self.h / 2, text=label, font=self.font, fill=colour)


class RoundedPanel(tk.Canvas):
    """Rounded background with a normal Frame inside (put children in .inner)."""

    def __init__(self, parent, fill=PANEL, outline="", radius=14, padx=16, pady=12, stretch=False):
        # Start big enough that the inner frame is inside the visible area: Tk does not map
        # canvas windows outside it, and then the panel could never measure its content.
        super().__init__(parent, bg=bg_of(parent), highlightthickness=0, height=200, width=400)
        self.fill, self.outline, self.radius, self.padx, self.pady = fill, outline, radius, padx, pady
        self.stretch = stretch
        self.inner = tk.Frame(self, bg=fill)
        self._win = self.create_window(padx, pady, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self._fit())
        self.bind("<Configure>", lambda e: self._paint())
        self.after_idle(self._fit)

    def _fit(self):
        self.config(height=self.inner.winfo_reqheight() + 2 * self.pady)
        if not self.stretch:
            self.config(width=self.inner.winfo_reqwidth() + 2 * self.padx)

    def _paint(self):
        w, h = self.winfo_width(), self.winfo_height()
        if self.stretch:
            self.itemconfig(self._win, width=max(10, w - 2 * self.padx))
        self.delete("bg")
        round_rect(self, 1, 1, w - 1, h - 1, self.radius, fill=self.fill,
                   outline=self.outline, width=1.5 if self.outline else 0, tags="bg")
        self.tag_lower("bg")


class RoundedEntry(tk.Canvas):
    """Rounded text field with a placeholder."""

    def __init__(self, parent, textvariable, placeholder="", height=36, radius=10):
        super().__init__(parent, height=height, bg=bg_of(parent), highlightthickness=0, cursor="xterm")
        self.var, self.placeholder, self.radius, self.h = textvariable, placeholder, radius, height
        self.entry = tk.Entry(self, textvariable=textvariable, bg=PANEL, fg=FG, insertbackground=FG,
                              relief="flat", bd=0, highlightthickness=0, font=("Segoe UI", 10))
        self._win = self.create_window(14, height / 2, window=self.entry, anchor="w")
        self._focused = False
        self.entry.bind("<FocusIn>", lambda e: self._set_focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._set_focus(False))
        self.entry.bind("<Escape>", lambda e: self.var.set(""))
        self.bind("<Button-1>", lambda e: self._activate())
        self.bind("<Configure>", lambda e: self._paint())
        textvariable.trace_add("write", lambda *_: self._paint())

    def _activate(self):
        self.itemconfig(self._win, state="normal")
        self.entry.focus_set()

    def _set_focus(self, on):
        self._focused = on
        self._paint()

    def _paint(self):
        w = self.winfo_width()
        self.delete("bg")
        round_rect(self, 1, 1, w - 1, self.h - 1, self.radius, fill=PANEL,
                   outline=PINK if self._focused else PANEL, width=1.5, tags="bg")
        self.tag_lower("bg")
        self.itemconfig(self._win, width=max(10, w - 28))
        empty = not self.var.get()
        self.delete("ph")
        if empty and not self._focused:
            self.itemconfig(self._win, state="hidden")
            self.create_text(15, self.h / 2, anchor="w", text=self.placeholder, fill=MUTED,
                             font=("Segoe UI", 10), tags="ph")
        else:
            self.itemconfig(self._win, state="normal")


class VolumeSlider(tk.Canvas):
    """Speaker icon (click = mute) + draggable track + percentage. Wheel adjusts by 5 %."""

    def __init__(self, parent, value, command, width=170):
        super().__init__(parent, width=width, height=30, bg=bg_of(parent), highlightthickness=0)
        self.value, self.command, self.muted = value, command, False
        self.x0, self.x1 = 34, width - 46
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", lambda e: self._drag(e.x))
        self.bind("<MouseWheel>", lambda e: self.set(self.value + (0.05 if e.delta > 0 else -0.05), True))
        self.bind("<Motion>", lambda e: self.config(cursor="hand2" if e.x < self.x1 + 8 else ""))
        self._draw()

    @property
    def effective(self):
        return 0.0 if self.muted else self.value

    def set(self, value, notify=False):
        self.value = min(1.0, max(0.0, value))
        if self.value > 0:
            self.muted = False
        self._draw()
        if notify:
            self.command(self.effective)

    def toggle_mute(self):
        self.muted = not self.muted
        self._draw()
        self.command(self.effective)

    def _press(self, e):
        if e.x < self.x0 - 6:
            self.toggle_mute()
        else:
            self._drag(e.x)

    def _drag(self, x):
        if x >= self.x0 - 6:
            self.muted = False
            self.set((x - self.x0) / (self.x1 - self.x0), notify=True)

    def _draw(self):
        self.delete("all")
        y = 15
        col = MUTED if self.muted or self.value == 0 else FG
        self.create_polygon(6, y - 4, 11, y - 4, 17, y - 9, 17, y + 9, 11, y + 4, 6, y + 4,
                            fill=col, outline="")
        if self.muted or self.value == 0:
            self.create_line(20, y - 5, 28, y + 5, fill=col, width=2)
            self.create_line(28, y - 5, 20, y + 5, fill=col, width=2)
        else:
            self.create_arc(13, y - 6, 25, y + 6, start=-50, extent=100, style="arc", outline=col, width=2)
            if self.value > 0.5:
                self.create_arc(13, y - 10, 29, y + 10, start=-50, extent=100, style="arc",
                                outline=col, width=2)
        self.create_line(self.x0, y, self.x1, y, fill=HOVER, width=5, capstyle="round")
        xv = self.x0 + (self.x1 - self.x0) * self.effective
        if self.effective > 0:
            self.create_line(self.x0, y, xv, y, fill=PINK, width=5, capstyle="round")
        self.create_oval(xv - 7, y - 7, xv + 7, y + 7, fill="#ffffff", outline="")
        self.create_text(self.x1 + 12, y, anchor="w", fill=MUTED, font=("Segoe UI", 9),
                         text="muted" if self.muted else f"{round(self.value * 100)}%")


class NavBar(tk.Frame):
    """Top navigation: app name + tabs; the active tab gets a rounded pink underline."""

    def __init__(self, parent, tabs, active, command, right_tabs=()):
        super().__init__(parent, bg=SIDEBAR, height=54)
        self.pack_propagate(False)
        self.command, self.active, self.tabs = command, active, {}
        tk.Label(self, text="osu!", fg=PINK, bg=SIDEBAR, font=("Segoe UI Black", 15)).pack(side="left", padx=(20, 2))
        tk.Label(self, text="analyzer", fg=FG, bg=SIDEBAR, font=("Segoe UI Semibold", 13)).pack(side="left", padx=(0, 28))
        for side, items in (("left", tabs), ("right", list(reversed(right_tabs)))):
            for key, label in items:
                box = tk.Frame(self, bg=SIDEBAR)
                box.pack(side=side, fill="y", padx=(4, 16) if side == "right" else 4)
                lbl = tk.Label(box, text=label, bg=SIDEBAR, font=("Segoe UI Semibold", 11), padx=12,
                               cursor="hand2")
                lbl.pack(fill="both", expand=True)
                bar = tk.Canvas(box, height=5, width=1, bg=SIDEBAR, highlightthickness=0)
                bar.pack(fill="x", side="bottom")
                bar.bind("<Configure>", lambda e: self._paint())
                lbl.bind("<Button-1>", lambda e, k=key: self.select(k, notify=True))
                lbl.bind("<Enter>", lambda e, k=key: self._paint(hover=k))
                lbl.bind("<Leave>", lambda e: self._paint())
                self.tabs[key] = (lbl, bar)
        self._paint()

    def select(self, key, notify=False):
        self.active = key
        self._paint()
        if notify:
            self.command(key)

    def _paint(self, hover=None):
        for key, (lbl, bar) in self.tabs.items():
            on = key == self.active
            lbl.config(fg=FG if on or key == hover else MUTED)
            bar.delete("all")
            if on:
                w = bar.winfo_width()
                bar.create_line(14, 2, max(15, w - 14), 2, fill=PINK, width=3, capstyle="round")


class Swatches(tk.Canvas):
    """Row of round colour swatches; the selected one gets a ring."""

    def __init__(self, parent, colours, value, command, size=30, gap=12):
        super().__init__(parent, width=len(colours) * (size + gap), height=size + 8, bg=bg_of(parent),
                         highlightthickness=0, cursor="hand2")
        self.colours, self.value, self.command, self.size, self.gap = colours, value, command, size, gap
        self.bind("<Button-1>", self._click)
        self._draw()

    def _click(self, e):
        i = int(e.x // (self.size + self.gap))
        if 0 <= i < len(self.colours):
            self.value = self.colours[i]
            self._draw()
            self.command(self.value)

    def _draw(self):
        self.delete("all")
        for i, colour in enumerate(self.colours):
            x = 4 + i * (self.size + self.gap)
            if colour.lower() == self.value.lower():
                self.create_oval(x - 3, 1, x + self.size + 3, self.size + 7, outline=FG, width=2)
            self.create_oval(x + 1, 5, x + self.size - 1, self.size + 3, fill=colour, outline="")


class ReplayList(tk.Canvas):
    """Clean, rounded, virtualised list. items: (title, subtitle, right_text).
    Click / Ctrl+click / Shift+click, arrows, wheel and a slim scrollbar."""

    ROW = 52

    def __init__(self, parent, on_select):
        super().__init__(parent, bg=bg_of(parent, SIDEBAR), highlightthickness=0, takefocus=1)
        self.on_select = on_select
        self.items, self.selected, self.anchor, self.hover = [], set(), None, None
        self.offset = 0.0
        self._drag_from = None
        self._fit_cache = {}
        self.f_title = tkfont.Font(family="Segoe UI Semibold", size=10)
        self.f_sub = tkfont.Font(family="Segoe UI", size=9)
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<MouseWheel>", lambda e: self.scroll(-e.delta / 120 * self.ROW * 2))
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Button-1>", self._click)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag_from", None))
        for key, step in (("Up", -1), ("Down", 1), ("Prior", -8), ("Next", 8)):
            self.bind(f"<{key}>", lambda e, d=step: self._key_move(d, e.state & 0x1))
        self.bind("<Home>", lambda e: self._key_move(-len(self.items), e.state & 0x1))
        self.bind("<End>", lambda e: self._key_move(len(self.items), e.state & 0x1))

    # data
    def set_items(self, items, selected=()):
        self.items = items
        self.selected = set(i for i in selected if i < len(items))
        self.anchor = min(self.selected) if self.selected else None
        self._fit_cache.clear()
        self.scroll(0)

    def see(self, i):
        H = self.winfo_height()
        top, bottom = i * self.ROW, (i + 1) * self.ROW
        if top < self.offset:
            self.offset = top
        elif bottom > self.offset + H:
            self.offset = bottom - H
        self.scroll(0)

    # geometry
    def _max_offset(self):
        return max(0.0, len(self.items) * self.ROW - self.winfo_height())

    def scroll(self, dy):
        self.offset = min(max(0.0, self.offset + dy), self._max_offset())
        self.draw()

    def _index_at(self, y):
        i = int((y + self.offset) // self.ROW)
        return i if 0 <= i < len(self.items) else None

    def _on_scrollbar(self, x):
        return x >= self.winfo_width() - 12 and self._max_offset() > 0

    # interaction
    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            self.draw()

    def _motion(self, e):
        self.config(cursor="" if self._on_scrollbar(e.x) else "hand2")
        self._set_hover(None if self._on_scrollbar(e.x) else self._index_at(e.y))

    def _click(self, e):
        self.focus_set()
        if self._on_scrollbar(e.x):
            self._drag_from = (e.y, self.offset)
            return
        i = self._index_at(e.y)
        if i is None:
            return
        if e.state & 0x4:                     # Ctrl: toggle
            self.selected ^= {i}
            self.anchor = i
        elif e.state & 0x1 and self.anchor is not None:   # Shift: range
            a, b = sorted((self.anchor, i))
            self.selected = set(range(a, b + 1))
        else:
            self.selected = {i}
            self.anchor = i
        self.draw()
        self.on_select(sorted(self.selected))

    def _drag(self, e):
        if self._drag_from is None:
            return
        y0, off0 = self._drag_from
        H = self.winfo_height()
        total = len(self.items) * self.ROW
        self.offset = off0
        self.scroll((e.y - y0) * total / max(H, 1))

    def _key_move(self, d, shift):
        if not self.items:
            return "break"
        cur = self.anchor if self.anchor is not None else 0
        if shift and self.selected:
            far = max(self.selected) if d > 0 else min(self.selected)
            i = min(max(far + d, 0), len(self.items) - 1)
            self.selected |= set(range(min(far, i), max(far, i) + 1))
        else:
            i = min(max(cur + d, 0), len(self.items) - 1)
            self.selected = {i}
            self.anchor = i
        self.see(i)
        self.on_select(sorted(self.selected))
        return "break"

    # drawing
    def _fit(self, text, font, width):
        key = (text, str(font), int(width))
        if key not in self._fit_cache:
            if font.measure(text) <= width:
                out = text
            else:
                lo, hi = 0, len(text)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    if font.measure(text[:mid] + "…") <= width:
                        lo = mid
                    else:
                        hi = mid - 1
                out = text[:lo].rstrip() + "…"
            self._fit_cache[key] = out
        return self._fit_cache[key]

    def draw(self):
        self.delete("all")
        W, H = self.winfo_width(), self.winfo_height()
        if W < 50:
            return
        bar_space = 14 if self._max_offset() > 0 else 6
        x0, x1 = 6, W - bar_space
        first = int(self.offset // self.ROW)
        last = min(len(self.items), int((self.offset + H) // self.ROW) + 1)
        for i in range(first, last):
            title, sub, right = self.items[i]
            y = i * self.ROW - self.offset
            sel = i in self.selected
            if sel or i == self.hover:
                round_rect(self, x0, y + 3, x1, y + self.ROW - 3, 12,
                           fill=PINK if sel else HOVER, outline="")
            main = DARK_TEXT if sel else FG
            muted = "#3b2230" if sel else MUTED
            rw = self.f_sub.measure(right) + 10 if right else 0
            self.create_text(x0 + 14, y + 17, anchor="w", text=self._fit(title, self.f_title, x1 - x0 - 28 - rw),
                             fill=main, font=self.f_title)
            self.create_text(x0 + 14, y + 35, anchor="w", text=self._fit(sub, self.f_sub, x1 - x0 - 28),
                             fill=muted, font=self.f_sub)
            if right:
                self.create_text(x1 - 12, y + 17, anchor="e", text=right, fill=muted, font=self.f_sub)
        if not self.items:
            self.create_text(W / 2, 40, text="No replays", fill=MUTED, font=self.f_sub)
        # slim rounded scrollbar
        total = len(self.items) * self.ROW
        if total > H > 0:
            th = max(30.0, H * H / total)
            ty = (H - th) * self.offset / (total - H)
            round_rect(self, W - 9, ty + 2, W - 4, ty + th - 2, 3, fill="#3a3a50", outline="")
