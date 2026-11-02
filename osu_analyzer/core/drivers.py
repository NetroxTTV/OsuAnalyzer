"""Tablet drivers: each one shows the area its own way.

Everything is converted to edges (top, bottom, left, right) measured from the tablet's
top-left corner, in the driver's own unit, which is what the calibration works with."""

from ..settings import settings

AREA_KEYS = ("top", "bottom", "left", "right")


def fmt(x):
    """A number as a driver shows it: no trailing zeros, at most 2 decimals."""
    return f"{x:.2f}".rstrip("0").rstrip(".")


class Driver:
    key = name = ""
    fields = ()          # ((key, label), ...) in the driver's order
    unit = ""            # appended to lengths ("" = the driver's own points)
    mm = None            # millimetres per unit, None when unknown
    decimals = 0
    defaults = {}        # area fields + tablet_w / tablet_h
    hint = tablet_hint = stretch_note = ""
    axes = ()            # per axis: (position field, size field, tablet size field)

    def edges(self, v):
        raise NotImplementedError

    def values(self, edges):
        raise NotImplementedError

    def check(self, v):
        """{field: what is wrong} for values that can't be an area on this tablet."""
        errors = {k: "must be > 0" for k in ("tablet_w", "tablet_h") if v[k] <= 0}
        if not errors:
            for axis in self.axes:
                self._check_axis(v, *axis, errors)
        return errors

    def _check_axis(self, v, pos, size, tablet, errors):
        s, t = v[size], v[tablet]
        if s <= 0:
            errors[size] = "must be > 0"
        elif s > t + 1e-9:
            errors[size] = f"max {fmt(t)}"
        else:
            lo, hi = self._pos_range(s, t)
            if not lo - 1e-9 <= v[pos] <= hi + 1e-9:
                errors[pos] = f"{fmt(lo)} to {fmt(hi)}" if lo else f"max {fmt(hi)}"

    def _pos_range(self, size, tablet):
        return 0, tablet - size

    def length(self, x):
        return f"{fmt(x)} {self.unit}".rstrip()

    def copy_text(self, edges):
        v = self.values(edges)
        return "  ".join(f"{name} {fmt(v[k])}" for k, name in self.fields)

    # ---------------------------------------------------------- settings --

    def stored(self):
        """The values last entered for this driver (defaults for the missing ones)."""
        saved = settings.get(f"tablet_{self.key}")
        if saved is None and self.key == "wacom":   # before drivers existed: flat keys
            saved = {k: settings[k] for k in self.defaults if k in settings}
        return {**self.defaults, **(saved or {})}

    def store(self, values):
        settings.update(**{f"tablet_{self.key}": values, "tablet_driver": self.key})


class Wacom(Driver):
    key, name = "wacom", "Wacom"
    fields = (("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right"))
    mm = 0.01
    defaults = {"top": 2000, "bottom": 5000, "left": 1600, "right": 5000, "tablet_w": 15200, "tablet_h": 9500}
    hint = "As in Wacom Center, in tablet points (100 points = 1 mm)."
    tablet_hint = "Intuos S = 15200 × 9500"
    stretch_note = "\"Force proportions\" off"

    def edges(self, v):
        return tuple(v[k] for k in AREA_KEYS)

    def values(self, edges):
        return dict(zip(AREA_KEYS, edges))

    def check(self, v):
        errors = {k: "must be > 0" for k in ("tablet_w", "tablet_h") if v[k] <= 0}
        if errors:
            return errors
        for lo, hi, name, tablet in (("top", "bottom", "Top", "tablet_h"), ("left", "right", "Left", "tablet_w")):
            if v[hi] <= v[lo]:
                errors[hi] = f"must be > {name}"
            elif v[hi] > v[tablet]:
                errors[hi] = f"max {fmt(v[tablet])}"
        return errors


class OpenTabletDriver(Driver):
    key, name = "otd", "OpenTabletDriver"
    fields = (("width", "Width"), ("height", "Height"), ("x", "X"), ("y", "Y"))
    unit, mm, decimals = "mm", 1.0, 2
    defaults = {"width": 76, "height": 42.75, "x": 76, "y": 47.5, "tablet_w": 152, "tablet_h": 95}
    hint = ("As in OpenTabletDriver's Tablet area, in mm. X / Y = centre of the area. "
            "Rotation 0, display area = the whole screen.")
    tablet_hint = "Full tablet area in mm  ·  CTL-472 / CTL-4100 = 152 × 95"
    stretch_note = "\"Lock aspect ratio\" off"
    axes = (("x", "width", "tablet_w"), ("y", "height", "tablet_h"))

    def edges(self, v):
        w, h = v["width"], v["height"]
        return v["y"] - h / 2, v["y"] + h / 2, v["x"] - w / 2, v["x"] + w / 2

    def values(self, edges):
        t, b, l, r = edges
        return {"width": r - l, "height": b - t, "x": (l + r) / 2, "y": (t + b) / 2}

    def _pos_range(self, size, tablet):
        return size / 2, tablet - size / 2


class XPPen(Driver):
    key, name = "xppen", "XP-Pen"
    fields = (("x", "X"), ("y", "Y"), ("w", "W"), ("h", "H"))
    decimals = 2
    defaults = {"x": 38.1, "y": 25.4, "w": 76.2, "h": 50.8, "tablet_w": 152.4, "tablet_h": 101.6}
    hint = ("As in the XP-Pen driver (Work Area → Customize). X / Y = top-left corner of the area. "
            "Enter the tablet size in the same unit (the values shown with Full Area).")
    tablet_hint = "Full Area of your tablet  ·  Star G640 = 152.4 × 101.6 mm"
    stretch_note = "work area not set to \"Screen Ratio\""
    axes = (("x", "w", "tablet_w"), ("y", "h", "tablet_h"))

    def edges(self, v):
        return v["y"], v["y"] + v["h"], v["x"], v["x"] + v["w"]

    def values(self, edges):
        t, b, l, r = edges
        return {"x": l, "y": t, "w": r - l, "h": b - t}


DRIVERS = {d.key: d for d in (Wacom(), OpenTabletDriver(), XPPen())}


def current_driver():
    return DRIVERS.get(settings.get("tablet_driver"), DRIVERS["wacom"])


def current_tablet_area():
    """The tablet area entered on the Tablet Zone page as edges, or None."""
    d = current_driver()
    saved = settings.get(f"tablet_{d.key}")
    if saved is None and d.key == "wacom" and all(k in settings for k in AREA_KEYS):
        saved = {k: settings[k] for k in AREA_KEYS}
    if not saved or any(k not in saved for k, _ in d.fields):
        return None
    return [round(e, 4) for e in d.edges(saved)]
