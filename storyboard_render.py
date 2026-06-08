"""
storyboard_render — turn a storyboard (list of steps) into an MP4.

A storyboard is JSON:

    {
      "fps": 30, "width": 1280, "height": 720,
      "steps": [
        {"action": "zoom",  "country": "...", "state": "...", "duration": 1.2},
        {"action": "trace", "country": "...", "state": "...", "duration": 1.6},
        {"action": "hold",  "duration": 0.6},
        {"action": "reset", "duration": 1.0}
      ]
    }

Step actions:
    zoom   — ease the camera from its current window to the target feature
    trace  — "draw" a line around the target's border (sweep), camera held
    hold   — freeze the current frame
    reset  — ease back out to the whole world (and clear drawn borders)

Target = the state (if `state` given) else the country. Rendered with
matplotlib + the pip-bundled ffmpeg, so it needs no browser and is fully
reproducible. Same data files the web app uses (web/data/*.json).
"""

from __future__ import annotations

import json
import os

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DATA = os.path.join(HERE, "web", "data")

CRS = "+proj=natearth +lon_0=0 +datum=WGS84 +units=m +no_defs"

THEME = {
    "ocean": "#9cc0e6",
    "land": "#f4f6f8",
    "land_edge": "#8392a3",
    "land_sel": "#cfe0f4",
    "country_trace": "#1565d8",
    "state_trace": "#e8590c",
    "county_trace": "#6741d9",
    "city": "#e03131",
    "river": "#2389c9",
    "river_name": "#5cb3ec",
    "street_freeway": "#e8590c",
    "street_major": "#f59f00",
    "street_local": "#b6bcc4",
    "text": "#1c2733",
}

# What a country calls its ADM2 division — so a county label reads "Los Angeles
# County" (the division), distinct from the *city* "Los Angeles". Unknown
# countries keep the bare name (dedup still guards true collisions).
ADM2_TERM = {
    "USA": "County", "FRA": "Department", "GBR": "County", "IRL": "County",
    "ITA": "Province", "ESP": "Province", "PRT": "District",
}


# ---- data -------------------------------------------------------------------

_cache = {}


def _load():
    if _cache:
        return _cache
    countries = gpd.read_file(os.path.join(WEB_DATA, "countries.json")).set_crs(4326).to_crs(CRS)
    states = gpd.read_file(os.path.join(WEB_DATA, "states.json")).set_crs(4326).to_crs(CRS)
    _cache["countries"] = countries
    _cache["states"] = states
    _cache["by_country"] = {n: g for n, g in countries.set_index("name").geometry.items()}
    _cache["states_idx"] = states.groupby("country")
    _cache["iso3"] = dict(zip(countries["name"], countries["iso3"]))
    _cache["adm2"] = {}  # iso3 -> {county name: projected geom}
    return _cache


def _county_geom(country, county):
    """Projected geometry of an ADM2 (county) by name, fetching the country's
    county set from geoBoundaries on first use."""
    import geoboundaries
    from shapely.geometry import shape

    d = _load()
    iso3 = d["iso3"].get(country)
    if not iso3:
        return None
    if iso3 not in d["adm2"]:
        fc = geoboundaries.load_adm2(iso3)
        gdf = gpd.GeoDataFrame(
            {"name": [f["properties"]["name"] for f in fc["features"]]},
            geometry=[shape(f["geometry"]) for f in fc["features"]], crs=4326,
        ).to_crs(CRS)
        d["adm2"][iso3] = dict(zip(gdf["name"], gdf.geometry))
    return d["adm2"][iso3].get(county)


def _feature_geom(country, state):
    d = _load()
    if state:
        grp = d["states_idx"]
        if country in grp.groups:
            sub = grp.get_group(country)
            hit = sub[sub["name"] == state]
            if len(hit):
                return hit.geometry.iloc[0]
    return d["by_country"].get(country)


def _target_geom(step):
    """Resolve a step's border target: county > state > country."""
    if step.get("county"):
        return _county_geom(step.get("country"), step.get("county"))
    return _feature_geom(step.get("country"), step.get("state"))


def _label_text(step):
    """Display name for a border label: county names get their division type
    appended (e.g. 'Los Angeles' -> 'Los Angeles County')."""
    if step.get("county"):
        c = step["county"]
        term = ADM2_TERM.get(_load()["iso3"].get(step.get("country")), "")
        if term and not c.lower().endswith(term.lower()):
            return f"{c} {term}"
        return c
    return step.get("state") or step.get("country")


def _project_point(lon, lat):
    from shapely.geometry import Point
    return gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(CRS).iloc[0]


# ---- geometry helpers -------------------------------------------------------

def _main_geom(geom):
    """The largest contiguous polygon of a (Multi)Polygon."""
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda p: p.area)
    return geom


def _rings(geom, mainland=False):
    """All boundary rings of a (Multi)Polygon as Nx2 arrays (proj coords).

    `mainland` keeps only the largest landmass (drops scattered islands)."""
    if mainland:
        geom = _main_geom(geom)
    out = []
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    for p in polys:
        out.append(np.asarray(p.exterior.coords))
        for r in p.interiors:
            out.append(np.asarray(r.coords))
    return out


def _zoom_bounds(geom, mainland=True):
    """Framing bounds for a feature. With `mainland`, frame just the largest
    landmass (so a country with overseas territories frames its mainland, not a
    globe-spanning hull); otherwise frame the whole territory."""
    if mainland:
        return _main_geom(geom).bounds
    return geom.bounds


def _ring_len(ring):
    d = np.diff(ring, axis=0)
    return float(np.sum(np.hypot(d[:, 0], d[:, 1])))


def _cut_ring(ring, need):
    """The leading portion of a ring up to `need` arc-length."""
    if need <= 0:
        return ring[:1]
    seg = np.diff(ring, axis=0)
    seglen = np.hypot(seg[:, 0], seg[:, 1])
    run = 0.0
    pts = [ring[0]]
    for k, sl in enumerate(seglen):
        if run + sl <= need:
            pts.append(ring[k + 1])
            run += sl
        else:
            t = (need - run) / sl if sl else 0.0
            pts.append(ring[k] + t * (ring[k + 1] - ring[k]))
            break
    return np.asarray(pts)


def _partial_boundary(rings, lengths, total, frac):
    """Coords for the boundary with EVERY ring revealed to the same fraction.

    All rings grow together (the mainland and any islands draw simultaneously),
    so the on-screen outline is always actively drawing — no dead time spent
    tracing off-screen territories. NaN rows separate rings so matplotlib does
    not connect them.
    """
    f = max(0.0, min(1.0, frac))
    chunks = []
    for ring, L in zip(rings, lengths):
        if L <= 0:
            continue
        chunks.append(ring if f >= 1.0 else _cut_ring(ring, f * L))
    if not chunks:
        return np.array([]), np.array([])
    nan = np.array([[np.nan, np.nan]])
    parts = []
    for i, c in enumerate(chunks):
        if i:
            parts.append(nan)
        parts.append(c)
    allc = np.vstack(parts)
    return allc[:, 0], allc[:, 1]


def _fit_window(bounds, aspect, pad):
    """A (xlim, ylim) window centered on bounds, matching frame aspect."""
    xmin, ymin, xmax, ymax = bounds
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    dx, dy = max(xmax - xmin, 1.0), max(ymax - ymin, 1.0)
    if dx / dy < aspect:
        dx = dy * aspect
    else:
        dy = dx / aspect
    dx *= pad
    dy *= pad
    return (cx - dx / 2, cx + dx / 2), (cy - dy / 2, cy + dy / 2)


def _ease(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def _lerp_win(a, b, f):
    (ax0, ax1), (ay0, ay1) = a
    (bx0, bx1), (by0, by1) = b
    return (
        (ax0 + (bx0 - ax0) * f, ax1 + (bx1 - ax1) * f),
        (ay0 + (by0 - ay0) * f, ay1 + (by1 - ay1) * f),
    )


# ---- render -----------------------------------------------------------------

def _point_window(px, py, aspect, half_h=6.0e5):
    """A regional window centered on a projected point (for city framing)."""
    hw = half_h * aspect
    return (px - hw, px + hw), (py - half_h, py + half_h)


def _overlaps(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _d2p(dx, dy, xlim, ylim, W, H):
    return (dx - xlim[0]) / (xlim[1] - xlim[0]) * W, H - (dy - ylim[0]) / (ylim[1] - ylim[0]) * H


def _p2d(qx, qy, xlim, ylim, W, H):
    return xlim[0] + qx / W * (xlim[1] - xlim[0]), ylim[0] + (H - qy) / H * (ylim[1] - ylim[0])


def _placed_to_px(placed, xlim, ylim, W, H):
    out = []
    for (bx0, by0, bx1, by1) in placed:
        a = _d2p(bx0, by1, xlim, ylim, W, H)
        b = _d2p(bx1, by0, xlim, ylim, W, H)
        out.append((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))
    return out


def _place_callout(name, ax_, ay_, win_px, placed_px, fontsize, dpi, prefer_center=False):
    """Pick an in-frame, non-overlapping label box for an anchor at (ax_,ay_) px.

    Returns (cx, cy, box, leader) where leader is True when the label had to be
    offset from the anchor (so a leader line should be drawn). `prefer_center`
    lets an area label sit on its own anchor (centroid); a point label (city)
    always offsets so it never covers the marker."""
    W, H = win_px
    ppc = fontsize * (dpi / 72.0)
    w = len(name) * ppc * 0.60 + 14
    h = ppc * 1.35 + 10
    M = 10
    anchor_box = (ax_ - 11, ay_ - 11, ax_ + 11, ay_ + 11)
    cands = ([(0, 0)] if prefer_center else []) + [
        (0, -46), (46, -32), (-46, -32), (62, 0), (-62, 0),
        (0, 46), (48, 36), (-48, 36), (0, -72), (0, 72)]
    for ox, oy in cands:
        cx, cy = ax_ + ox, ay_ + oy
        box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        if box[0] < M or box[1] < M or box[2] > W - M or box[3] > H - M:
            continue
        if (ox, oy) != (0, 0) and _overlaps(box, anchor_box):
            continue
        if any(_overlaps(box, pb) for pb in placed_px):
            continue
        return cx, cy, box, (ox, oy) != (0, 0)
    return None


def _render_city(ax, s, cur, aspect, n, setlims, writer, drawn, placed, width, height, shown):
    """Zoom to a city point, drop a marker, and place a leader-line callout
    label — unless that exact name was already labeled this scene (then the
    marker drops but the redundant label is skipped)."""
    from matplotlib.patches import Circle

    lon, lat, name = s.get("lon"), s.get("lat"), s.get("name", "")
    if lon is None or lat is None:
        for _ in range(n):
            setlims(cur)
            writer.grab_frame()
        return cur

    pt = _project_point(lon, lat)
    px, py = pt.x, pt.y
    # zoom:false drops a marker on the CURRENT view (e.g. to show cities
    # clustering on a country map) instead of zooming to the city.
    nozoom = s.get("zoom") is False
    half_h = 1.3e5  # ~260 km tall: a city/metro view, not a regional one
    target = cur if nozoom else _point_window(px, py, aspect, half_h)
    (xlim, ylim) = target
    xspan = xlim[1] - xlim[0]
    yspan = ylim[1] - ylim[0]
    col = THEME["city"]
    Rmax = yspan * 0.045
    fontsize, dpi = 14, 100

    def data_to_px(dx, dy):
        return (dx - xlim[0]) / xspan * width, height - (dy - ylim[0]) / yspan * height

    def px_to_data(qx, qy):
        return xlim[0] + qx / width * xspan, ylim[0] + (height - qy) / height * yspan

    mx, my = data_to_px(px, py)
    placed_px = []
    for (bx0, by0, bx1, by1) in placed:
        a = data_to_px(bx0, by1)
        b = data_to_px(bx1, by0)
        placed_px.append((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))

    want_label = bool(name) and name not in shown
    if want_label:
        shown.add(name)
    # Skip the marker if the city point sits on an existing label box (e.g. the
    # Paris city point lands on the "Paris Department" label) — the label box
    # already occupies that spot, so a dot would just overlap the text.
    pad = 8
    coincident = any(b[0] - pad <= mx <= b[2] + pad and b[1] - pad <= my <= b[3] + pad
                     for b in placed_px)
    draw_marker = not coincident

    marker = ring = leader = label = None
    _box = None
    if draw_marker:
        (marker,) = ax.plot([px], [py], marker="o", ms=0, color=col,
                            markeredgecolor="white", markeredgewidth=1.4, zorder=14)
        ring = Circle((px, py), 0, fill=False, edgecolor=col, lw=2.2, alpha=0.0, zorder=9)
        ax.add_patch(ring)
    if want_label:
        spot = _place_callout(name, mx, my, (width, height), placed_px, fontsize, dpi)
        if spot is None:
            spot = (mx, my - 46, None, True)
        cx, cy, _box, _leader = spot
        lx, ly = px_to_data(cx, cy)
        leader, = ax.plot([px, lx], [py, ly], color=col, lw=1.3, alpha=0.0, zorder=8)
        label = ax.text(lx, ly, name, ha="center", va="center", color=THEME["text"],
                        fontsize=fontsize, fontweight="bold", zorder=12, alpha=0.0,
                        bbox=dict(boxstyle="round,pad=0.32", fc="white", ec=col, lw=1.1))
        label.get_bbox_patch().set_alpha(0.0)

    start = cur
    for i in range(n):
        t = (i + 1) / n
        setlims(_lerp_win(start, target, _ease(min(1.0, t / 0.7))))
        if draw_marker:
            marker.set_markersize(11 * _ease(max(0.0, (t - 0.5) / 0.3)))
            pr = max(0.0, (t - 0.55) / 0.45)
            ring.set_radius(Rmax * _ease(pr))
            ring.set_alpha(max(0.0, 0.8 * (1 - pr)))
        if want_label:
            a = _ease(max(0.0, (t - 0.6) / 0.4))
            leader.set_alpha(a * 0.9)
            label.set_alpha(a)
            label.get_bbox_patch().set_alpha(a * 0.96)
        writer.grab_frame()

    if ring is not None:
        ring.remove()
    if marker is not None:
        drawn.append(marker)
    if want_label:
        if _box is not None:
            bx0, by0 = px_to_data(_box[0], _box[3])
            bx1, by1 = px_to_data(_box[2], _box[1])
            placed.append((min(bx0, bx1), min(by0, by1), max(bx0, bx1), max(by0, by1)))
        drawn.extend([label, leader])
    return target


def _make_label(ax, name, anchor_px, cur, placed, width, height, color,
                prefer_center=True, fontsize=14, dpi=100):
    """Create a (fading) name label near anchor_px, avoiding placed labels and
    the frame edges. Returns a set_alpha(a) callback; records its footprint."""
    (xlim, ylim) = cur
    ax_, ay_ = anchor_px
    placed_px = _placed_to_px(placed, xlim, ylim, width, height)
    spot = _place_callout(name, ax_, ay_, (width, height), placed_px, fontsize, dpi, prefer_center)
    if spot is None:
        cx = min(max(ax_, 60), width - 60)
        cy = min(max(ay_, 30), height - 30)
        box, leader_on = None, False
    else:
        cx, cy, box, leader_on = spot
    lx, ly = _p2d(cx, cy, xlim, ylim, width, height)

    leader = None
    if leader_on:
        a0 = _p2d(ax_, ay_, xlim, ylim, width, height)
        leader, = ax.plot([a0[0], lx], [a0[1], ly], color=color, lw=1.3, alpha=0.0, zorder=11)
    label = ax.text(lx, ly, name, ha="center", va="center", color=THEME["text"],
                    fontsize=fontsize, fontweight="bold", zorder=13, alpha=0.0,
                    bbox=dict(boxstyle="round,pad=0.32", fc="white", ec=color, lw=1.1))
    label.get_bbox_patch().set_alpha(0.0)
    if box is not None:
        p0 = _p2d(box[0], box[3], xlim, ylim, width, height)
        p1 = _p2d(box[2], box[1], xlim, ylim, width, height)
        placed.append((min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1])))

    artists = [label] + ([leader] if leader is not None else [])

    def set_alpha(a):
        label.set_alpha(a)
        label.get_bbox_patch().set_alpha(a * 0.96)
        if leader is not None:
            leader.set_alpha(a * 0.9)

    return set_alpha, artists


def _curved_text(ax, pts, text, color, win, width, height, fontsize=15):
    """Place `text` character-by-character along a polyline, each rotated to the
    local tangent — a name that follows the flow of a river. Returns the artists."""
    import math

    pts = np.asarray(pts, float)
    if len(pts) < 2 or not text:
        return []
    if pts[-1, 0] < pts[0, 0]:          # keep text reading left-to-right
        pts = pts[::-1]
    seg = np.diff(pts, axis=0)
    seglen = np.hypot(seg[:, 0], seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    total = float(cum[-1])
    if total <= 0:
        return []

    (xlim, _ylim) = win
    char_data = fontsize * (100 / 72) * 0.62 * (xlim[1] - xlim[0]) / width
    start = max(0.0, (total - len(text) * char_data) / 2)

    def at(d):
        d = min(max(d, 0.0), total)
        i = min(max(int(np.searchsorted(cum, d) - 1), 0), len(seg) - 1)
        f = (d - cum[i]) / (seglen[i] or 1.0)
        p = pts[i] + f * (pts[i + 1] - pts[i])
        return p, math.degrees(math.atan2(seg[i, 1], seg[i, 0]))

    arts = []
    for j, ch in enumerate(text):
        p, ang = at(start + (j + 0.5) * char_data)
        arts.append(ax.text(p[0], p[1], ch, color=color, fontsize=fontsize, fontweight="bold",
                            ha="center", va="center", rotation=ang, rotation_mode="anchor",
                            zorder=12, alpha=0.0,
                            path_effects=[__import__("matplotlib.patheffects", fromlist=["withStroke"])
                                          .withStroke(linewidth=2.4, foreground="white")]))
    return arts


def _render_river(ax, s, cur, aspect, n, setlims, writer, drawn, width, height):
    """Zoom to a river, trace its course, and label it with curved light-blue text."""
    from shapely.geometry import LineString
    import rivers

    def hold():
        for _ in range(n):
            setlims(cur)
            writer.grab_frame()
        return cur

    try:
        data = rivers.load_river(s.get("country"), s.get("name"))
    except Exception:  # noqa: BLE001 — river not found / API down: just hold
        return hold()

    raw = [l for l in data["lines"] if len(l) >= 2]
    if not raw:
        return hold()
    gs = gpd.GeoSeries([LineString(l) for l in raw], crs=4326).to_crs(CRS)
    proj = [np.asarray(g.coords) for g in gs if len(g.coords) >= 2]
    if not proj:
        return hold()

    allp = np.vstack(proj)
    bounds = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
    target = _fit_window(bounds, aspect, pad=1.3)
    lengths = [_ring_len(a) for a in proj]
    total = sum(lengths) or 1.0

    (line,) = ax.plot([], [], color=THEME["river"], lw=2.6, solid_capstyle="round",
                      solid_joinstyle="round", zorder=6)
    longest = max(proj, key=len)
    label_arts = _curved_text(ax, longest, data["name"], THEME["river_name"], target, width, height)

    start = cur
    for i in range(n):
        t = (i + 1) / n
        setlims(_lerp_win(start, target, _ease(min(1.0, t / 0.55))))
        x, y = _partial_boundary(proj, lengths, total, _ease(t))
        line.set_data(x, y)
        la = _ease(max(0.0, (t - 0.6) / 0.4))
        for a in label_arts:
            a.set_alpha(la)
        writer.grab_frame()

    drawn.append(line)
    drawn.extend(label_arts)
    return target


def _render_streets(ax, s, cur, aspect, n, setlims, writer, drawn, width, height):
    """Zoom into a small area and fade in OSM roads, colored by class (freeway /
    major / local). The step's `classes` selects which to show."""
    from matplotlib.collections import LineCollection
    from shapely.geometry import LineString, Point
    import streets as st

    lon, lat = s.get("lon"), s.get("lat")
    radius = s.get("radius_km", 3.0)
    classes = s.get("classes", ["freeway", "major", "local"])

    def hold():
        for _ in range(n):
            setlims(cur)
            writer.grab_frame()
        return cur

    if lon is None:
        return hold()
    if s.get("clear"):                 # start this city's view clean
        for art in list(drawn):
            try:
                art.remove()
            except Exception:  # noqa: BLE001
                pass
        drawn.clear()
    try:
        data = st.fetch_streets(lon, lat, radius, classes)
    except Exception:  # noqa: BLE001
        return hold()

    by = {}
    for ln in data["lines"]:
        by.setdefault(ln["cls"], []).append(ln["coords"])
    if not by:
        return hold()

    sb, wb, nb, eb = st._bbox(lon, lat, radius)
    cs = gpd.GeoSeries([Point(wb, sb), Point(eb, nb)], crs=4326).to_crs(CRS)
    xs = [cs.iloc[0].x, cs.iloc[1].x]
    ys = [cs.iloc[0].y, cs.iloc[1].y]
    target = _fit_window((min(xs), min(ys), max(xs), max(ys)), aspect, pad=1.04)

    # Clean land background — the world base map is too simplified to be reliable
    # at street zoom (it leaves slivers of water over inland cities).
    from matplotlib.patches import Rectangle
    (tx0, tx1), (ty0, ty1) = target
    cx, cy, w2, h2 = (tx0 + tx1) / 2, (ty0 + ty1) / 2, (tx1 - tx0) * 4, (ty1 - ty0) * 4
    landrect = Rectangle((cx - w2 / 2, cy - h2 / 2), w2, h2, facecolor=THEME["land"],
                         edgecolor="none", zorder=3, alpha=0.0)
    ax.add_patch(landrect)
    drawn.append(landrect)

    style = {"local": (THEME["street_local"], 0.6, 6),
             "major": (THEME["street_major"], 1.4, 7),
             "freeway": (THEME["street_freeway"], 2.6, 8)}
    colls = []
    for cls in ["local", "major", "freeway"]:
        if cls not in by:
            continue
        col, lw, z = style[cls]
        gs = gpd.GeoSeries([LineString(c) for c in by[cls]], crs=4326).to_crs(CRS)
        lc = LineCollection([list(g.coords) for g in gs], colors=col, linewidths=lw,
                            zorder=z, alpha=0.0, capstyle="round")
        ax.add_collection(lc)
        colls.append(lc)
        drawn.append(lc)

    label = None
    if s.get("name"):
        for t in list(ax.texts):       # one street label at a time
            if t.get_gid() == "streetlabel":
                t.remove()
                if t in drawn:
                    drawn.remove(t)
        label = ax.text(0.5, 0.94, s["name"], transform=ax.transAxes, ha="center", va="center",
                        fontsize=22, fontweight="bold", color=THEME["text"], zorder=20, alpha=0.0,
                        gid="streetlabel",
                        bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#c8ccd0", lw=1.2))
        label.get_bbox_patch().set_alpha(0.0)
        drawn.append(label)

    start = cur
    for i in range(n):
        t = (i + 1) / n
        setlims(_lerp_win(start, target, _ease(min(1.0, t / 0.5))))
        landrect.set_alpha(_ease(min(1.0, t / 0.4)))   # land fills in as we arrive
        a = _ease(max(0.0, (t - 0.4) / 0.6))
        for lc in colls:
            lc.set_alpha(a)
        if label is not None:
            label.set_alpha(a)
            label.get_bbox_patch().set_alpha(a * 0.95)
        writer.grab_frame()
    return target


# ---- data layers (biomes, US-state choropleth, coordinate grid, pins) -------

def _load_stats():
    if "stats" not in _cache:
        _cache["stats"] = json.load(open(os.path.join(WEB_DATA, "us_state_stats.json")))
    return _cache["stats"]


def _load_biomes():
    if "biomes" not in _cache:
        gdf = gpd.read_file(os.path.join(WEB_DATA, "biomes.json")).set_crs(4326).to_crs(CRS)
        meta = json.load(open(os.path.join(WEB_DATA, "biomes_meta.json")))
        _cache["biomes"] = gdf
        _cache["biome_meta"] = meta["biomes"]
    return _cache["biomes"], _cache["biome_meta"]


def _us_states_gdf():
    if "us_states" not in _cache:
        s = _load()["states"]
        _cache["us_states"] = s[s["country"] == "United States of America"].copy()
    return _cache["us_states"]


def _load_lakes():
    if "lakes" not in _cache:
        path = os.path.join(WEB_DATA, "lakes.json")
        _cache["lakes"] = (gpd.read_file(path).set_crs(4326).to_crs(CRS)
                           if os.path.exists(path) else None)
    return _cache["lakes"]


def _rank_positions(values):
    """value -> quantile position in [0,1] (matches the web app's rank coloring,
    so one outlier doesn't crush every state into a single shade)."""
    sv = sorted(values)
    n = len(sv)
    pos = {}
    for i, v in enumerate(sv):
        if v not in pos:
            pos[v] = i / (n - 1) if n > 1 else 0.5
    return pos


def _fmt_value(v, fmt):
    if v is None:
        return "—"
    if fmt == "usd":
        return "$" + format(int(round(v)), ",")
    if fmt == "pct":
        return f"{v:.1f}%"
    if fmt == "int":
        return format(int(round(v)), ",")
    return str(v)


def _legend_gradient(ax, title, lo, hi, scheme, fmt):
    """A bottom-right gradient legend (title + color strip + min/max), in axes
    coords so it stays fixed while the map zooms. Returns its artists."""
    from matplotlib.patches import FancyBboxPatch, Rectangle

    cmap = plt.get_cmap(scheme)
    arts = []
    x0, y0, w, h = 0.685, 0.045, 0.285, 0.115
    bg = FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0.012", transform=ax.transAxes,
                        fc="white", ec="#d4dae1", lw=1.0, alpha=0.95, zorder=18)
    ax.add_patch(bg); arts.append(bg)
    arts.append(ax.text(x0 + 0.014, y0 + h - 0.028, title, transform=ax.transAxes,
                        fontsize=10.5, fontweight="bold", color=THEME["text"], zorder=19, va="center"))
    bx, bw, by, bh = x0 + 0.012, w - 0.024, y0 + 0.040, 0.022
    nseg = 64
    for i in range(nseg):
        r = ax.add_patch(Rectangle((bx + bw * i / nseg, by), bw / nseg + 0.001, bh,
                         transform=ax.transAxes, fc=cmap(i / (nseg - 1)), ec="none", zorder=19))
        arts.append(r)
    arts.append(ax.text(bx, by - 0.012, _fmt_value(lo, fmt), transform=ax.transAxes,
                        fontsize=9.5, color=THEME["text"], ha="left", va="top", zorder=19))
    arts.append(ax.text(bx + bw, by - 0.012, _fmt_value(hi, fmt), transform=ax.transAxes,
                        fontsize=9.5, color=THEME["text"], ha="right", va="top", zorder=19))
    return arts


def _legend_swatches(ax, title, items):
    """A right-side swatch legend (one colored chip + label per item)."""
    from matplotlib.patches import FancyBboxPatch, Rectangle

    arts = []
    rowh = 0.052
    n = len(items)
    h = 0.045 + n * rowh
    x0, w = 0.70, 0.295
    y0 = max(0.03, 0.95 - h)
    bg = FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0.012", transform=ax.transAxes,
                        fc="white", ec="#d4dae1", lw=1.0, alpha=0.95, zorder=18)
    ax.add_patch(bg); arts.append(bg)
    arts.append(ax.text(x0 + 0.014, y0 + h - 0.028, title, transform=ax.transAxes,
                        fontsize=11, fontweight="bold", color=THEME["text"], zorder=19, va="center"))
    for i, b in enumerate(items):
        yy = y0 + h - 0.058 - i * rowh
        arts.append(ax.add_patch(Rectangle((x0 + 0.016, yy - 0.012), 0.022, 0.026, transform=ax.transAxes,
                    fc=b["color"], ec="#00000022", lw=0.5, zorder=19)))
        nm = b["name"]
        if len(nm) > 34:
            nm = nm[:33] + "…"
        arts.append(ax.text(x0 + 0.05, yy, nm, transform=ax.transAxes, fontsize=8.6,
                    color=THEME["text"], va="center", zorder=19))
    return arts


def _us_target(aspect):
    geom = _feature_geom("United States of America", None)
    if geom is None:
        return None
    return _fit_window(_zoom_bounds(geom, True), aspect, pad=1.18)


def _render_data(ax, s, cur, aspect, n, setlims, writer, layers, width, height):
    """Choropleth the US states by a metric (rank-colored) + a gradient legend."""
    for a in layers["data"]:        # replace any prior data overlay
        try:
            a.remove()
        except Exception:  # noqa: BLE001
            pass
    layers["data"].clear()

    stats = _load_stats()
    meta = next((m for m in stats["metrics"] if m["key"] == s.get("metric")), None)
    us = _us_states_gdf()
    if meta is None or not len(us):
        return _hold(cur, n, setlims, writer)

    vals = [v[meta["key"]] for v in stats["states"].values() if v.get(meta["key"]) is not None]
    lo, hi = min(vals), max(vals)
    ranks = _rank_positions(vals)
    cmap = plt.get_cmap(meta["scheme"])

    target = _us_target(aspect) or cur
    patches = []
    for _, row in us.iterrows():
        rec = stats["states"].get(row["name"])
        color = cmap(ranks.get(rec[meta["key"]], 0.0)) if rec else "#e9edf1"
        gpd.GeoSeries([row.geometry], crs=CRS).plot(
            ax=ax, facecolor=color, edgecolor="white", linewidth=0.5, zorder=3, alpha=0.0)
        coll = ax.collections[-1]
        patches.append(coll)
        layers["data"].append(coll)

    title = f'{meta["label"]}' + (f' ({meta["unit"]})' if meta["unit"] else "")
    legend = _legend_gradient(ax, title, lo, hi, meta["scheme"], meta["fmt"])
    layers["data"].extend(legend)

    start = cur
    for i in range(n):
        t = (i + 1) / n
        setlims(_lerp_win(start, target, _ease(min(1.0, t / 0.55))))
        a = 0.92 * _ease(t)
        for c in patches:
            c.set_alpha(a)
        for art in legend:
            art.set_alpha(min(1.0, a + 0.08))
        writer.grab_frame()
    return target


def _render_biome(ax, s, cur, aspect, n, setlims, writer, layers, width, height, world_win):
    """Fill biome (ecoregion) polygons colored by class + a swatch legend."""
    for a in layers["biome"]:
        try:
            a.remove()
        except Exception:  # noqa: BLE001
            pass
    layers["biome"].clear()

    gdf, meta = _load_biomes()
    color_by = {b["code"]: b["color"] for b in meta}
    region = s.get("region", "world")
    target = (_us_target(aspect) or cur) if region == "usa" else world_win

    patches = []
    for _, row in gdf.iterrows():
        gpd.GeoSeries([row.geometry], crs=CRS).plot(
            ax=ax, facecolor=color_by.get(row["code"], "#cccccc"),
            edgecolor="white", linewidth=0.2, zorder=2, alpha=0.0)
        coll = ax.collections[-1]
        patches.append(coll)
        layers["biome"].append(coll)

    legend = []
    if s.get("label", True):
        legend = _legend_swatches(ax, "Biomes", meta)
        layers["biome"].extend(legend)

    start = cur
    for i in range(n):
        t = (i + 1) / n
        setlims(_lerp_win(start, target, _ease(min(1.0, t / 0.55))))
        a = 0.85 * _ease(t)
        for c in patches:
            c.set_alpha(a)
        for art in legend:
            art.set_alpha(min(1.0, a + 0.1))
        writer.grab_frame()
    return target


def _render_grid(ax, s, cur, n, setlims, writer, layers, width, height):
    """Draw (or remove) a lat/lon graticule with degree labels."""
    from shapely.geometry import LineString, Point
    import matplotlib.patheffects as pe

    if s.get("on", True) is False:
        arts = list(layers["grid"])
        for i in range(n):
            a = max(0.0, 1.0 - (i + 1) / n)
            for art in arts:
                art.set_alpha(a * (0.55 if art.__class__.__name__ == "Line2D" else 1.0))
            setlims(cur)
            writer.grab_frame()
        for art in arts:
            try:
                art.remove()
            except Exception:  # noqa: BLE001
                pass
        layers["grid"].clear()
        return cur

    for a in layers["grid"]:
        try:
            a.remove()
        except Exception:  # noqa: BLE001
            pass
    layers["grid"].clear()

    step = int(s.get("step", 15))
    stroke = [pe.withStroke(linewidth=2.2, foreground="#eaf1f8")]
    arts = []

    # graticule lines
    for lon in range(-180, 181, step):
        pts = [(lon, lat) for lat in range(-80, 81, 2)]
        gs = gpd.GeoSeries([LineString(pts)], crs=4326).to_crs(CRS).iloc[0]
        xy = np.asarray(gs.coords)
        (ln,) = ax.plot(xy[:, 0], xy[:, 1], color="#5b86b3", lw=0.6, alpha=0.0, zorder=4)
        arts.append(ln)
    for lat in range(-80, 81, step):
        pts = [(lon, lat) for lon in range(-180, 181, 3)]
        gs = gpd.GeoSeries([LineString(pts)], crs=4326).to_crs(CRS).iloc[0]
        xy = np.asarray(gs.coords)
        (ln,) = ax.plot(xy[:, 0], xy[:, 1], color="#5b86b3", lw=0.6, alpha=0.0, zorder=4)
        arts.append(ln)

    # Labels: longitude rides the equator, latitude rides the prime meridian,
    # each CLAMPED into the visible window so they slide to the nearest edge when
    # their line scrolls off — and the lon0 label is dropped so nothing piles up
    # at the lon0/lat0 crossing.
    (xlim, ylim) = cur
    cg = gpd.GeoSeries([Point(xlim[0], ylim[0]), Point(xlim[1], ylim[0]),
                        Point(xlim[0], ylim[1]), Point(xlim[1], ylim[1])], crs=CRS).to_crs(4326)
    lons = [p.x for p in cg]
    lats = [p.y for p in cg]
    lon_lo, lon_hi, lat_lo, lat_hi = min(lons), max(lons), min(lats), max(lats)
    pad_lat = (lat_hi - lat_lo) * 0.07 + 1
    pad_lon = (lon_hi - lon_lo) * 0.07 + 1

    def clamp(v, lo, hi):
        return max(lo, min(hi, v))

    label_lat = clamp(0, lat_lo + pad_lat, lat_hi - pad_lat)
    label_lon = clamp(0, lon_lo + pad_lon, lon_hi - pad_lon)
    anchors = []
    for lon in range(-180, 181, step):
        if lon == 0:
            continue
        anchors.append((lon, label_lat, f"{abs(lon)}°{'W' if lon < 0 else 'E'}", "center", "top"))
    for lat in range(-80, 81, step):
        anchors.append((label_lon, lat, f"{abs(lat)}°{'S' if lat < 0 else 'N' if lat > 0 else ''}",
                        "left", "center"))
    pg = gpd.GeoSeries([Point(lo, la) for lo, la, *_ in anchors], crs=4326).to_crs(CRS)
    mx, my = (xlim[1] - xlim[0]) * 0.012, (ylim[1] - ylim[0]) * 0.012
    for (lo, la, txt, ha, va), p in zip(anchors, pg):
        if not (xlim[0] + mx <= p.x <= xlim[1] - mx and ylim[0] + my <= p.y <= ylim[1] - my):
            continue
        arts.append(ax.text(p.x, p.y, txt, fontsize=9.5, color="#33567d", ha=ha, va=va,
                            zorder=16, alpha=0.0, path_effects=stroke))

    layers["grid"].extend(arts)
    for i in range(n):
        a = (i + 1) / n
        for art in arts:
            art.set_alpha(0.55 * a if art.__class__.__name__ == "Line2D" else a)
        setlims(cur)
        writer.grab_frame()
    return cur


def _render_pin(ax, s, cur, aspect, n, setlims, writer, drawn, placed, width, height):
    """Drop a labeled marker at an arbitrary lon/lat with a custom color."""
    from matplotlib.patches import Circle

    lon, lat = s.get("lon"), s.get("lat")
    if lon is None or lat is None:
        return _hold(cur, n, setlims, writer)
    pt = _project_point(lon, lat)
    px, py = pt.x, pt.y
    color = s.get("color") or THEME["state_trace"]
    label = s.get("label") or ""
    do_zoom = bool(s.get("zoom"))
    half_m = float(s.get("zoom_km", 800.0)) * 1000.0   # half-height of the zoom window
    target = _point_window(px, py, aspect, half_m) if do_zoom else cur
    (xlim, ylim) = target
    yspan = ylim[1] - ylim[0]
    Rmax = yspan * 0.05

    def data_to_px(dx, dy):
        return (dx - xlim[0]) / (xlim[1] - xlim[0]) * width, height - (dy - ylim[0]) / (ylim[1] - ylim[0]) * height

    def px_to_data(qx, qy):
        return xlim[0] + qx / width * (xlim[1] - xlim[0]), ylim[0] + (height - qy) / height * (ylim[1] - ylim[0])

    mx, my = data_to_px(px, py)
    placed_px = []
    for (bx0, by0, bx1, by1) in placed:
        a = data_to_px(bx0, by1)
        b = data_to_px(bx1, by0)
        placed_px.append((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])))

    (marker,) = ax.plot([px], [py], marker="o", ms=0, color=color,
                        markeredgecolor="white", markeredgewidth=1.6, zorder=15)
    ring = Circle((px, py), 0, fill=False, edgecolor=color, lw=2.4, alpha=0.0, zorder=10)
    ax.add_patch(ring)

    lbl = leader = None
    _box = None
    if label:
        spot = _place_callout(label, mx, my, (width, height), placed_px, 14, 100)
        if spot is None:
            spot = (mx, my - 46, None, True)
        cx, cy, _box, _leader = spot
        lx, ly = px_to_data(cx, cy)
        leader, = ax.plot([px, lx], [py, ly], color=color, lw=1.4, alpha=0.0, zorder=9)
        lbl = ax.text(lx, ly, label, ha="center", va="center", color=THEME["text"],
                      fontsize=14, fontweight="bold", zorder=13, alpha=0.0,
                      bbox=dict(boxstyle="round,pad=0.32", fc="white", ec=color, lw=1.2))
        lbl.get_bbox_patch().set_alpha(0.0)

    start = cur
    for i in range(n):
        t = (i + 1) / n
        if do_zoom:
            setlims(_lerp_win(start, target, _ease(min(1.0, t / 0.6))))
        marker.set_markersize(11 * _ease(max(0.0, (t - 0.35) / 0.3)))
        pr = max(0.0, (t - 0.4) / 0.5)
        ring.set_radius(Rmax * _ease(pr))
        ring.set_alpha(max(0.0, 0.85 * (1 - pr)))
        if label:
            a = _ease(max(0.0, (t - 0.5) / 0.4))
            leader.set_alpha(a * 0.9)
            lbl.set_alpha(a)
            lbl.get_bbox_patch().set_alpha(a * 0.96)
        writer.grab_frame()

    ring.remove()
    drawn.append(marker)
    if label:
        if _box is not None:
            bx0, by0 = px_to_data(_box[0], _box[3])
            bx1, by1 = px_to_data(_box[2], _box[1])
            placed.append((min(bx0, bx1), min(by0, by1), max(bx0, bx1), max(by0, by1)))
        drawn.extend([lbl, leader])
    return target


def _hold(cur, n, setlims, writer):
    for _ in range(n):
        setlims(cur)
        writer.grab_frame()
    return cur


def _render_dots(ax, s, cur, aspect, n, setlims, writer, drawn, width, height):
    """Plot many points as small dots — a scatter layer (e.g. John Snow's cholera
    deaths). reveal:'stagger' makes them appear progressively (a "plotting"
    effect); reveal:'all' fades them in together. frame:true frames the points."""
    from shapely.geometry import Point
    import matplotlib.colors as mcolors

    pts = s.get("points", [])
    if not pts:
        return _hold(cur, n, setlims, writer)
    gs = gpd.GeoSeries([Point(p[0], p[1]) for p in pts], crs=4326).to_crs(CRS)
    xy = np.array([[g.x, g.y] for g in gs])
    color = s.get("color", "#c0392b")
    radius = float(s.get("radius", 2.6))
    reveal = s.get("reveal", "stagger")

    if s.get("frame"):
        bounds = (xy[:, 0].min(), xy[:, 1].min(), xy[:, 0].max(), xy[:, 1].max())
        target = _fit_window(bounds, aspect, pad=float(s.get("pad", 1.3)))
    else:
        target = cur

    N = len(xy)
    if reveal == "stagger" and N > 1:
        rng = np.random.default_rng(1854)
        t_reveal = np.linspace(0.0, 0.72, N)[rng.permutation(N)]
    else:
        t_reveal = np.zeros(N)

    rgb = mcolors.to_rgb(color)
    fc = np.tile([rgb[0], rgb[1], rgb[2], 0.0], (N, 1))
    sizes = np.full(N, (radius * 2) ** 2)
    sc = ax.scatter(xy[:, 0], xy[:, 1], s=sizes, facecolors=fc.copy(),
                    edgecolors="white", linewidths=0.3, zorder=12)

    start = cur
    fade = 0.13
    for i in range(n):
        t = (i + 1) / n
        setlims(_lerp_win(start, target, _ease(min(1.0, t / 0.5))))
        a = np.clip((t - t_reveal) / fade, 0.0, 1.0)
        fc[:, 3] = a * 0.92
        sc.set_facecolors(fc.copy())
        sc.set_edgecolors(np.tile([1, 1, 1, 1], (N, 1)) * a[:, None])
        writer.grab_frame()
    drawn.append(sc)
    return target


def _render_caption(ax, s, cur, n, setlims, writer, layers, width, height):
    """A screen-fixed title card (caption + optional subtitle) that fades in and
    persists until the next caption or a reset. Use for narration cues."""
    for a in layers["caption"]:
        try:
            a.remove()
        except Exception:  # noqa: BLE001
            pass
    layers["caption"].clear()

    text = s.get("text", "")
    sub = s.get("sub", "")
    if not text and not sub:
        return _hold(cur, n, setlims, writer)
    pos = s.get("pos", "lower")
    y = {"top": 0.90, "center": 0.52, "lower": 0.13}.get(pos, 0.13)

    arts = []
    if text:
        t1 = ax.text(0.5, y, text, transform=ax.transAxes, ha="center", va="center",
                     fontsize=30, fontweight="bold", color="#12283f", zorder=30, alpha=0.0,
                     bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#c7d0d9", lw=1.2))
        t1.get_bbox_patch().set_alpha(0.0)
        arts.append(t1)
    if sub:
        t2 = ax.text(0.5, y - 0.07, sub, transform=ax.transAxes, ha="center", va="center",
                     fontsize=15, color="#41566b", zorder=30, alpha=0.0,
                     bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="none"))
        t2.get_bbox_patch().set_alpha(0.0)
        arts.append(t2)
    layers["caption"].extend(arts)

    for i in range(n):
        t = (i + 1) / n
        a = _ease(min(1.0, t / 0.6))
        for art in arts:
            art.set_alpha(a)
            if art.get_bbox_patch() is not None:
                art.get_bbox_patch().set_alpha(a * (0.92 if art is arts[0] else 0.0))
        setlims(cur)
        writer.grab_frame()
    return cur


def render(storyboard, out_path, progress=None):
    fps = int(storyboard.get("fps", 30))
    width = int(storyboard.get("width", 1280))
    height = int(storyboard.get("height", 720))
    aspect = width / height
    steps = storyboard.get("steps", [])

    d = _load()
    countries = d["countries"]

    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi)
    fig.patch.set_facecolor(THEME["ocean"])
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(THEME["ocean"])
    ax.set_aspect("auto")
    ax.axis("off")

    countries.plot(ax=ax, facecolor=THEME["land"], edgecolor=THEME["land_edge"],
                   linewidth=0.7, zorder=1)

    # Lakes as water, drawn ABOVE the land and the data/biome fills (zorder 3.6)
    # so the Great Lakes, Caspian, etc. read as water everywhere.
    lakes = _load_lakes()
    if lakes is not None and len(lakes):
        lakes.plot(ax=ax, facecolor=THEME["ocean"], edgecolor=THEME["land_edge"],
                   linewidth=0.3, zorder=3.6)

    world_win = _fit_window(countries.total_bounds, aspect, pad=1.03)
    cur = world_win
    # Optional initial camera so a clip can begin already framed (no fly-in from
    # the world): start = {bounds:[w,s,e,n]} or {lon, lat, km}.
    start_spec = storyboard.get("start")
    if start_spec:
        from shapely.geometry import Point as _Pt
        if "bounds" in start_spec:
            w, s, e, nn = start_spec["bounds"]
            gg = gpd.GeoSeries([_Pt(w, s), _Pt(e, nn)], crs=4326).to_crs(CRS)
            cur = _fit_window((min(gg.iloc[0].x, gg.iloc[1].x), min(gg.iloc[0].y, gg.iloc[1].y),
                               max(gg.iloc[0].x, gg.iloc[1].x), max(gg.iloc[0].y, gg.iloc[1].y)),
                              aspect, pad=start_spec.get("pad", 1.1))
        elif "lon" in start_spec:
            p = _project_point(start_spec["lon"], start_spec["lat"])
            half = start_spec.get("km", 0.4) * 1000.0
            cur = _point_window(p.x, p.y, aspect, half)
    ax.set_xlim(*cur[0])
    ax.set_ylim(*cur[1])

    drawn = []   # persistent fully-drawn trace lines / markers
    placed = []  # label boxes already placed (data coords) for collision avoidance
    shown = set()  # names already labeled this scene (cleared on reset) — no dupes
    # replaceable overlay layers (a new data/biome step swaps the old one)
    layers = {"data": [], "biome": [], "grid": [], "caption": []}

    import imageio_ffmpeg
    from matplotlib.animation import FFMpegWriter

    plt.rcParams["animation.ffmpeg_path"] = imageio_ffmpeg.get_ffmpeg_exe()
    # yuv420p + faststart so it plays everywhere (QuickTime, Safari, <video>).
    writer = FFMpegWriter(
        fps=fps, bitrate=6000, codec="libx264",
        extra_args=["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-preset", "medium"],
    )

    total_frames = sum(max(1, int(round(s.get("duration", 1.0) * fps))) for s in steps) or 1
    done = 0

    def setlims(win):
        ax.set_xlim(*win[0])
        ax.set_ylim(*win[1])

    with writer.saving(fig, out_path, dpi):
        for s in steps:
            action = s.get("action")
            n = max(1, int(round(s.get("duration", 1.0) * fps)))

            if action == "zoom":
                geom = _target_geom(s)
                mainland = s.get("mainland", True)
                target = _fit_window(_zoom_bounds(geom, mainland), aspect, pad=1.18) if geom is not None else world_win
                start = cur
                for i in range(n):
                    setlims(_lerp_win(start, target, _ease(i / max(1, n - 1))))
                    writer.grab_frame()
                    done += 1
                cur = target

            elif action == "city":
                cur = _render_city(ax, s, cur, aspect, n, setlims, writer, drawn, placed,
                                   width, height, shown)
                done += n

            elif action == "river":
                cur = _render_river(ax, s, cur, aspect, n, setlims, writer, drawn, width, height)
                done += n

            elif action == "streets":
                cur = _render_streets(ax, s, cur, aspect, n, setlims, writer, drawn, width, height)
                done += n

            elif action == "pin":
                cur = _render_pin(ax, s, cur, aspect, n, setlims, writer, drawn, placed, width, height)
                done += n

            elif action == "dots":
                cur = _render_dots(ax, s, cur, aspect, n, setlims, writer, drawn, width, height)
                done += n

            elif action == "caption":
                cur = _render_caption(ax, s, cur, n, setlims, writer, layers, width, height)
                done += n

            elif action == "data":
                cur = _render_data(ax, s, cur, aspect, n, setlims, writer, layers, width, height)
                done += n

            elif action == "biome":
                cur = _render_biome(ax, s, cur, aspect, n, setlims, writer, layers, width, height, world_win)
                done += n

            elif action == "grid":
                cur = _render_grid(ax, s, cur, n, setlims, writer, layers, width, height)
                done += n

            elif action == "trace":
                geom = _target_geom(s)
                if s.get("county"):
                    color = THEME["county_trace"]
                elif s.get("state"):
                    color = THEME["state_trace"]
                else:
                    color = THEME["country_trace"]
                if geom is None:
                    for i in range(n):
                        writer.grab_frame(); done += 1
                else:
                    mainland = s.get("mainland", True)
                    rings = _rings(geom, mainland)
                    lengths = [_ring_len(r) for r in rings]
                    total = sum(lengths) or 1.0

                    # translucent interior fill (fades in with the trace)
                    fill_coll = None
                    if s.get("fill", True):
                        sub = gpd.GeoSeries([_main_geom(geom) if mainland else geom], crs=CRS)
                        sub.plot(ax=ax, facecolor=color, edgecolor="none", zorder=4)
                        fill_coll = ax.collections[-1]
                        fill_coll.set_alpha(0.0)
                        drawn.append(fill_coll)

                    (line,) = ax.plot([], [], color=color, lw=2.4, solid_capstyle="round",
                                      solid_joinstyle="round", zorder=5)
                    line.set_path_effects([])

                    set_label_alpha = None
                    if s.get("label", True):
                        nm = _label_text(s)
                        if nm and nm not in shown:
                            shown.add(nm)
                            rp = (_main_geom(geom) if mainland else geom).representative_point()
                            apx = _d2p(rp.x, rp.y, cur[0], cur[1], width, height)
                            set_label_alpha, arts = _make_label(
                                ax, nm, apx, cur, placed, width, height, color, prefer_center=True)
                            drawn.extend(arts)

                    for i in range(n):
                        t = (i + 1) / n
                        x, y = _partial_boundary(rings, lengths, total, t)
                        line.set_data(x, y)
                        if fill_coll is not None:
                            fill_coll.set_alpha(0.16 * _ease(t))
                        if set_label_alpha:
                            set_label_alpha(_ease(max(0.0, (t - 0.45) / 0.45)))
                        setlims(cur)
                        writer.grab_frame()
                        done += 1
                    drawn.append(line)

            elif action == "reset":
                for ln in list(drawn) + layers["data"] + layers["biome"] + layers["grid"] + layers["caption"]:
                    try:
                        ln.remove()
                    except (ValueError, NotImplementedError):
                        pass
                drawn.clear()
                layers["data"].clear()
                layers["biome"].clear()
                layers["grid"].clear()
                layers["caption"].clear()
                placed.clear()
                shown.clear()
                start = cur
                for i in range(n):
                    setlims(_lerp_win(start, world_win, _ease(i / max(1, n - 1))))
                    writer.grab_frame()
                    done += 1
                cur = world_win

            else:  # hold (or unknown -> hold)
                for i in range(n):
                    setlims(cur)
                    writer.grab_frame()
                    done += 1

            if progress:
                progress(done, total_frames)

    plt.close(fig)
    return out_path


def _demo_storyboard():
    us = "United States of America"
    return {
        "fps": 30, "width": 1280, "height": 720,
        "steps": [
            {"action": "zoom", "country": us, "duration": 1.3},
            {"action": "trace", "country": us, "duration": 1.6},
            {"action": "hold", "duration": 0.4},
            {"action": "zoom", "country": us, "state": "California", "duration": 1.1},
            {"action": "trace", "country": us, "state": "California", "duration": 1.4},
            {"action": "hold", "duration": 0.6},
            {"action": "reset", "duration": 1.1},
        ],
    }


if __name__ == "__main__":
    import sys

    # usage: storyboard_render.py [board.json|--demo] [out.mp4]
    board = _demo_storyboard()
    if len(sys.argv) > 1 and sys.argv[1] != "--demo":
        board = json.load(open(sys.argv[1]))
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "output", "storyboard.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    render(board, out, progress=lambda d, t: print(f"\r  {d}/{t} frames", end="", flush=True))
    print("\n->", out)
