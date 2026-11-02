"""Slider path geometry (bezier, catmull, perfect circle, linear)."""

import math

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _bezier(points):
    """Sample a single bezier segment."""
    if len(points) == 1:
        return [points[0]]
    poly_len = sum(dist(points[i], points[i + 1]) for i in range(len(points) - 1))
    steps = int(min(1000, max(16, poly_len / 2)))
    out = []
    for s in range(steps + 1):
        t = s / steps
        pts = list(points)
        while len(pts) > 1:
            pts = [(pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t,
                    pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t) for i in range(len(pts) - 1)]
        out.append(pts[0])
    return out


def _bezier_path(points):
    """Bezier with red anchors (repeated points split segments)."""
    out, seg = [], [points[0]]
    for p in points[1:]:
        if p == seg[-1]:
            out += _bezier(seg)
            seg = [p]
        else:
            seg.append(p)
    out += _bezier(seg)
    return out


def _catmull_path(points):
    out = []
    n = len(points)
    for i in range(n - 1):
        v1 = points[i - 1] if i > 0 else points[i]
        v2 = points[i]
        v3 = points[i + 1] if i + 1 < n else (2 * v2[0] - v1[0], 2 * v2[1] - v1[1])
        v4 = points[i + 2] if i + 2 < n else (2 * v3[0] - v2[0], 2 * v3[1] - v2[1])
        for c in range(50):
            t = c / 50
            t2, t3 = t * t, t * t * t
            out.append(tuple(
                0.5 * (2 * v2[k] + (-v1[k] + v3[k]) * t
                       + (2 * v1[k] - 5 * v2[k] + 4 * v3[k] - v4[k]) * t2
                       + (-v1[k] + 3 * v2[k] - 3 * v3[k] + v4[k]) * t3)
                for k in (0, 1)))
    out.append(points[-1])
    return out


def _circle_path(a, b, c):
    d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
    if abs(d) < 1e-3:
        return None
    asq, bsq, csq = a[0] ** 2 + a[1] ** 2, b[0] ** 2 + b[1] ** 2, c[0] ** 2 + c[1] ** 2
    cx = (asq * (b[1] - c[1]) + bsq * (c[1] - a[1]) + csq * (a[1] - b[1])) / d
    cy = (asq * (c[0] - b[0]) + bsq * (a[0] - c[0]) + csq * (b[0] - a[0])) / d
    r = math.hypot(a[0] - cx, a[1] - cy)
    t0 = math.atan2(a[1] - cy, a[0] - cx)
    t1 = math.atan2(c[1] - cy, c[0] - cx)
    while t1 < t0:
        t1 += 2 * math.pi
    direction, rng = 1, t1 - t0
    ortho = (c[1] - a[1], -(c[0] - a[0]))
    if ortho[0] * (b[0] - a[0]) + ortho[1] * (b[1] - a[1]) < 0:
        direction, rng = -1, 2 * math.pi - rng
    if r > 0.1:
        n = int(min(1000, max(2, math.ceil(rng / (2 * math.acos(max(-1.0, 1 - 0.1 / r)))))))
    else:
        n = 2
    return [(cx + r * math.cos(t0 + direction * rng * i / (n - 1)),
             cy + r * math.sin(t0 + direction * rng * i / (n - 1))) for i in range(n)]


def _point_at_length(poly, length):
    """Point at `length` along the polyline (extends the last segment if needed)."""
    if len(poly) == 1:
        return poly[0]
    walked = 0.0
    for i in range(len(poly) - 1):
        seg = dist(poly[i], poly[i + 1])
        if walked + seg >= length and seg > 0:
            f = (length - walked) / seg
            return (poly[i][0] + (poly[i + 1][0] - poly[i][0]) * f,
                    poly[i][1] + (poly[i + 1][1] - poly[i][1]) * f)
        walked += seg
    a, b = poly[-2], poly[-1]
    seg = dist(a, b)
    if seg == 0:
        return b
    f = (length - walked) / seg
    return (b[0] + (b[0] - a[0]) * f, b[1] + (b[1] - a[1]) * f)


def slider_path(curve_type, points, length):
    """Slider body as a polyline, cut (or extended) to the slider's pixel length."""
    if curve_type == "P" and len(points) == 3:
        poly = _circle_path(*points) or _bezier_path(points)
    elif curve_type == "L":
        poly = list(points)
    elif curve_type == "C":
        poly = _catmull_path(points)
    else:
        poly = _bezier_path(points)
    if length is None or length <= 0 or len(poly) < 2:
        return poly
    out, walked = [poly[0]], 0.0
    for i in range(len(poly) - 1):
        seg = dist(poly[i], poly[i + 1])
        if walked + seg >= length and seg > 0:
            f = (length - walked) / seg
            out.append((poly[i][0] + (poly[i + 1][0] - poly[i][0]) * f,
                        poly[i][1] + (poly[i + 1][1] - poly[i][1]) * f))
            return out
        walked += seg
        out.append(poly[i + 1])
    out[-1] = _point_at_length(poly, length)  # path shorter than the length: extend
    return out


def slider_path_end(curve_type, points, length):
    return slider_path(curve_type, points, length)[-1]
