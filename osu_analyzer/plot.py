"""Matplotlib version of the Hit Analyzer, used by the command line."""

from .core.stats import MISS_CAP, MISS_LABELS, MISS_REASONS, HitStats
from .palette import (BG, BORDER, CARD, DEFAULT_ACCENT, GOLD, JUDGE_COLORS, MISS_COLORS, MUTED, TEXT)


def plot(analyses, frame="screen", color_by="timing", save=None, accent=DEFAULT_ACCENT):
    import matplotlib
    if save:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(14, 9.5))
    if fig.canvas.manager:
        fig.canvas.manager.set_window_title("osu! Hit Analyzer")
    if not draw(fig, analyses, frame, color_by, accent):
        print("No hits to plot.")
    if save:
        fig.savefig(save, dpi=130, facecolor=BG)
        print(f"Saved plot to {save}")
    else:
        plt.show()


def stat_rows(s: HitStats):
    """(label, value) rows of the stats panel; value None = section title."""
    mx, my = s.mean
    miss_split, hit_split = s.aim_splits()
    cnt, reasons = s.counts, s.misses_by_reason
    rows = [
        ("AVERAGE HIT", None),
        ("offset", f"{s.offset * 100:.1f}% of radius  ({s.offset_px:.1f} px)"),
        ("direction", s.direction),
        ("x / y", f"{mx * 100:+.1f}%  /  {my * 100:+.1f}%"),
        ("SPREAD", None),
        ("mean distance", f"{s.mean_distance * 100:.1f}% of radius"),
        ("std x / y", f"{s.std[0] * 100:.1f}%  /  {s.std[1] * 100:.1f}%"),
        ("inside 50% radius", f"{s.inside_half * 100:.1f}%"),
        ("OVER / UNDER AIM", None),
        ("misses", f"{miss_split.over} over / {miss_split.under} under"
                   + (f"  ({miss_split.over_pct:.0f}% over)" if miss_split.total else "")),
        ("hits", f"{hit_split.over_pct:.0f}% over / {100 - hit_split.over_pct:.0f}% under"
                 if hit_split.total else "-"),
        ("TIMING", None),
        ("mean error", f"{s.mean_error:+.1f} ms ({'late' if s.mean_error > 0 else 'early'})"),
        ("unstable rate", f"{s.unstable_rate:.1f}"),
        ("HITS", None),
        ("analysed", f"{len(s.hits)}" + (f"  ({s.skipped} skipped)" if s.skipped else "")),
        ("300 / 100 / 50", f"{cnt[300]} / {cnt[100]} / {cnt[50]}"),
        ("misses (detected)", f"{s.total_misses}"),
        ("outside / early / no click", " / ".join(str(reasons[r]) for r in MISS_REASONS)),
    ]
    if len(s.analyses) == 1:
        r = s.analyses[0].replay
        rows.append(("replay header", f"{r.n300}/{r.n100}/{r.n50}/{r.nmiss}x"))
    return rows


def draw(fig, analyses, frame="screen", color_by="timing", accent=DEFAULT_ACCENT):
    """Draw the analysis onto a matplotlib Figure (cleared first). Returns False if no hits."""
    import matplotlib.colors as mcolors
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm
    from matplotlib.lines import Line2D
    from matplotlib.patches import Circle, Ellipse, FancyBboxPatch

    from .palette import EARLY_BLUE, LATE_RED

    fig.clear()
    fig.set_facecolor(BG)
    s = HitStats.compute(analyses, frame)
    if s.empty:
        fig.text(0.5, 0.5, "No hits found in this replay", color=MUTED, ha="center", fontsize=14)
        return False
    xs, ys = s.xs, s.ys
    mean_x, mean_y = s.mean
    mxs, mys, pinned = s.pinned_misses()

    ax = fig.add_axes([0.03, 0.07, 0.60, 0.80])
    ax.set_facecolor(BG)
    ax.set_aspect("equal")
    lim = max(1.15, float(np.max(np.abs(np.concatenate([xs, ys])))) + 0.05)
    if len(s.misses):
        lim = max(lim, float(s.miss_dists.max(initial=0).clip(max=MISS_CAP)) + 0.12)
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.axis("off")

    ax.add_patch(Circle((0, 0), 1, facecolor=accent, alpha=0.07, zorder=0))
    ax.add_patch(Circle((0, 0), 1, fill=False, edgecolor=accent, lw=3, zorder=1))
    for r in (0.25, 0.5, 0.75):
        ax.add_patch(Circle((0, 0), r, fill=False, edgecolor="#ffffff", alpha=0.12,
                            lw=1, ls=(0, (3, 4)), zorder=1))
        ax.text(r * 0.707 + 0.01, r * 0.707 + 0.01, f"{int(r * 100)}%", color=MUTED,
                fontsize=8, alpha=0.7, zorder=1)
    ax.plot([-1, 1], [0, 0], color="#ffffff", alpha=0.08, lw=1, zorder=1)
    ax.plot([0, 0], [-1, 1], color="#ffffff", alpha=0.08, lw=1, zorder=1)
    if frame == "movement":
        ax.annotate("", xy=(0.95, -1.08), xytext=(0.55, -1.08),
                    arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.5))
        ax.text(0.5, -1.08, "movement direction", color=MUTED, ha="right", va="center", fontsize=9)
        ax.text(1.04, 0, "overshoot", color=MUTED, rotation=-90, va="center", fontsize=9)
        ax.text(-1.04, 0, "undershoot", color=MUTED, rotation=90, va="center", ha="right", fontsize=9)

    size = 26 if len(s.hits) < 600 else 14
    if color_by == "judgement":
        ax.scatter(xs, ys, c=[JUDGE_COLORS[h.judgement] for h in s.hits], s=size, alpha=0.8,
                   linewidths=0, zorder=3)
    else:
        w300 = s.windows[0]
        cmap = LinearSegmentedColormap.from_list("timing", [EARLY_BLUE, "#e6e6ee", LATE_RED])
        sc = ax.scatter(xs, ys, c=np.clip(s.errors, -w300, w300), cmap=cmap,
                        norm=TwoSlopeNorm(0, -w300, w300), s=size, alpha=0.85, linewidths=0, zorder=3)
        cax = fig.add_axes([0.08, 0.05, 0.50, 0.015])
        cb = fig.colorbar(sc, cax=cax, orientation="horizontal")
        cb.set_label("timing error (ms, scale = 300 window)   ← early  |  late →", color=TEXT, fontsize=9)
        cb.ax.tick_params(colors=MUTED, labelsize=8)
        cb.outline.set_edgecolor(MUTED)

    ell = s.ellipse()
    if ell:
        centre, (w, h), angle = ell
        for k, ls in ((1, "-"), (2, "--")):
            ax.add_patch(Ellipse(centre, k * w, k * h, angle=angle, fill=False, edgecolor=TEXT,
                                 alpha=0.55, lw=1.3, ls=ls, zorder=4))

    ax.plot([0, mean_x], [0, mean_y], color=GOLD, lw=2, alpha=0.9, zorder=5)
    ax.scatter([0], [0], marker="+", s=120, color=TEXT, alpha=0.6, zorder=5)
    ax.scatter([mean_x], [mean_y], marker="X", s=320, color=GOLD, edgecolors="#000000",
               linewidths=1.5, zorder=6)

    if len(s.misses):
        if pinned.any():
            ax.add_patch(Circle((0, 0), MISS_CAP, fill=False, edgecolor=MUTED, alpha=0.35,
                                lw=1, ls=(0, (2, 4)), zorder=1))
        rgba = [mcolors.to_rgba(MISS_COLORS[m.reason], 0.55 if p else 0.95)
                for m, p in zip(s.misses, pinned)]
        ax.scatter(mxs, mys, marker="x", s=80, c=rgba, linewidths=2.4, zorder=7)

    handles = [Line2D([], [], marker="X", ls="", color=GOLD, markeredgecolor="#000000",
                      markersize=11, label="average hit")]
    for reason in MISS_REASONS:
        n = sum(1 for m in s.misses if m.reason == reason)
        if n:
            handles.append(Line2D([], [], marker="x", ls="", color=MISS_COLORS[reason],
                                  markeredgewidth=2.4, markersize=9,
                                  label=f"miss: {MISS_LABELS[reason]} ({n})"))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.025, 0.915), ncol=len(handles),
               frameon=False, fontsize=9, labelcolor=TEXT, columnspacing=1.6, handletextpad=0.4)

    fig.text(0.03, 0.965, s.title, color=TEXT, fontsize=14, weight="bold")
    fig.text(0.03, 0.935, s.subtitle, color=MUTED, fontsize=10)

    # Stats panel
    sx = 0.66
    pane = fig.add_axes([sx, 0.05, 0.31, 0.86])
    pane.set_facecolor("none")
    pw, ph = fig.get_figwidth() * 0.31, fig.get_figheight() * 0.86
    pane.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.045",
                                  mutation_aspect=pw / ph, transform=pane.transAxes,
                                  facecolor=CARD, edgecolor="none", clip_on=False, zorder=-1))
    pane.set_xticks([])
    pane.set_yticks([])
    for sp in pane.spines.values():
        sp.set_visible(False)
    y = 0.965
    for label, value in stat_rows(s):
        if value is None:
            if y < 0.96:
                y -= 0.012
            pane.text(0.06, y, label, color=accent, fontsize=10, weight="bold", transform=pane.transAxes)
            y -= 0.033
            continue
        pane.text(0.06, y, label, color=MUTED, fontsize=9.5, transform=pane.transAxes)
        pane.text(0.94, y, value, color=TEXT, fontsize=9.5, ha="right", transform=pane.transAxes)
        y -= 0.031

    hax = fig.add_axes([sx + 0.025, 0.08, 0.26, 0.12])
    hax.set_facecolor(CARD)
    w100 = s.windows[1]
    hax.hist(np.clip(s.errors, -w100, w100), bins=np.linspace(-w100, w100, 41), color=accent, alpha=0.8)
    hax.axvline(0, color=TEXT, alpha=0.4, lw=1)
    hax.axvline(s.mean_error, color=GOLD, lw=1.5)
    hax.set_title("timing distribution (ms)", color=MUTED, fontsize=9)
    hax.tick_params(colors=MUTED, labelsize=8)
    for sp in hax.spines.values():
        sp.set_color(BORDER)

    fig.text(0.63, 0.935, f"view: {frame}" + ("  (screen axes, up = up)" if frame == "screen" else
             "  (rotated so movement → right)"), color=MUTED, fontsize=8, ha="right")
    return True
