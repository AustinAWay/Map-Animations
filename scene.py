"""
scene — compose the US base map and drive its animation.

This module owns the *look* of the map and the *motion*. It exposes:

    build_static(ax)          -> draw the full US map onto an Axes (no motion)
    make_animation(...)       -> a matplotlib FuncAnimation (intro build-in)
    export_html(anim, path)   -> self-contained interactive page (dev preview)
    export_mp4(anim, path)    -> final delivery video (bundled ffmpeg)

The animation and the still share one composition, so what you scrub in the
browser is exactly what renders to MP4.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless; we export files, never open a window

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

import geomap as gm


def _ease(t: float) -> float:
    """Smooth ease-in-out on t in [0, 1]."""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _draw_neighbors(ax):
    """Greyed-out Canada & Mexico bodies (context, not focus)."""
    neighbors = gm.countries_named("Canada", "Mexico")
    neighbors.plot(
        ax=ax,
        facecolor=gm.PALETTE["neighbor_fill"],
        edgecolor=gm.PALETTE["neighbor_edge"],
        linewidth=0.6,
        zorder=1,
    )


def _draw_water(ax):
    """Lakes (incl. Great Lakes) and major river centerlines."""
    lakes = gm.layer("lakes")
    if not lakes.empty:
        lakes.plot(
            ax=ax,
            facecolor=gm.PALETTE["lake"],
            edgecolor=gm.PALETTE["river"],
            linewidth=0.3,
            zorder=3,
        )
    rivers = gm.layer("rivers")
    if not rivers.empty:
        rivers.plot(
            ax=ax,
            color=gm.PALETTE["river"],
            linewidth=0.5,
            alpha=0.8,
            zorder=4,
        )


def _draw_us(ax):
    """US states on top; returns the PathCollection so motion can fade it."""
    states = gm.us_states()
    states.plot(
        ax=ax,
        facecolor=gm.PALETTE["us_fill"],
        edgecolor=gm.PALETTE["us_edge"],
        linewidth=0.5,
        zorder=5,
    )
    return ax.collections[-1]


def _frame_axes(ax):
    ax.set_facecolor(gm.PALETTE["ocean"])
    ax.set_aspect("equal")
    ax.axis("off")


def build_static(ax):
    """Draw the complete US map (no animation) and return key handles."""
    _frame_axes(ax)
    _draw_neighbors(ax)
    _draw_water(ax)
    us_coll = _draw_us(ax)
    bounds = gm.view_bounds(gm.us_states(), pad=0.04)
    ax.set_xlim(bounds[0], bounds[1])
    ax.set_ylim(bounds[2], bounds[3])
    return {"us": us_coll, "bounds": bounds}


def _zoomed(bounds, factor):
    """Scale a (xmin,xmax,ymin,ymax) window about its center by `factor`."""
    xmin, xmax, ymin, ymax = bounds
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    hw, hh = (xmax - xmin) / 2 * factor, (ymax - ymin) / 2 * factor
    return cx - hw, cx + hw, cy - hh, cy + hh


def make_animation(fig=None, frames=72, title="The United States"):
    """Intro build-in: greyed neighbors sit, the US fades up, camera eases in."""
    if fig is None:
        fig = plt.figure(figsize=(11, 7), dpi=110)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1])

    handles = build_static(ax)
    us_coll = handles["us"]
    final_bounds = handles["bounds"]
    start_bounds = _zoomed(final_bounds, 1.16)

    txt = ax.text(
        0.5, 0.06, title, transform=ax.transAxes, ha="center", va="center",
        fontsize=26, fontweight="bold", color=gm.PALETTE["text"], alpha=0.0,
    )

    def update(i):
        t = i / (frames - 1)
        # US fades in over the first 65% of the timeline.
        us_coll.set_alpha(_ease(t / 0.65))
        # Camera eases from slightly-out to the framed bounds.
        f = _ease(t)
        xmin, xmax, ymin, ymax = (
            s + (e - s) * f for s, e in zip(start_bounds, final_bounds)
        )
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        # Title fades in over the last 40%.
        txt.set_alpha(_ease((t - 0.6) / 0.4))
        return us_coll, txt

    anim = FuncAnimation(fig, update, frames=frames, interval=1000 / 30, blit=False)
    return fig, anim


def export_html(anim, path):
    """Write a self-contained interactive HTML player (dev preview)."""
    html = anim.to_jshtml(fps=30, default_mode="loop")
    with open(path, "w") as f:
        f.write(
            "<!doctype html><meta charset='utf-8'>"
            "<title>US map — preview</title>"
            "<style>body{margin:0;background:#11151a;display:flex;"
            "justify-content:center;align-items:center;min-height:100vh;}"
            "</style>" + html
        )
    return path


def export_mp4(anim, path, fps=30):
    """Render the final MP4 using the pip-bundled ffmpeg."""
    import imageio_ffmpeg
    from matplotlib.animation import FFMpegWriter

    plt.rcParams["animation.ffmpeg_path"] = imageio_ffmpeg.get_ffmpeg_exe()
    writer = FFMpegWriter(fps=fps, bitrate=4000, codec="libx264")
    anim.save(path, writer=writer, dpi=110)
    return path
