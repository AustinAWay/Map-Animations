"""
rivers — named rivers from Natural Earth 10m, selectable per country.

Uses the local NE 1:10m rivers layer (reliable, detailed, no external API). A
river is selected by name from the list of rivers that pass through a country,
then its segments are returned as polylines for tracing.
"""

from __future__ import annotations

import os

import geopandas as gpd
from shapely.geometry import box

HERE = os.path.dirname(os.path.abspath(__file__))
RIVERS_FILE = os.path.join(HERE, "data", "ne_10m_rivers_lake_centerlines.geojson")
COUNTRIES = os.path.join(HERE, "web", "data", "countries.json")

_rivers = None
_bbox_cache = {}


def _load():
    global _rivers
    if _rivers is None:
        g = gpd.read_file(RIVERS_FILE)
        col = next(c for c in g.columns if c.lower() in ("name", "name_en"))
        g = g[g[col].notna()].rename(columns={col: "name"})
        _rivers = g[["name", "geometry"]].reset_index(drop=True)
    return _rivers


def _ring_bbox(ring):
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _country_bbox(country):
    """(south, west, north, east) of a country's largest landmass."""
    if not _bbox_cache:
        import json
        for f in json.load(open(COUNTRIES))["features"]:
            geom = f["geometry"]
            polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
            best, area = None, -1
            for poly in polys:
                minx, miny, maxx, maxy = _ring_bbox(poly[0])
                a = (maxx - minx) * (maxy - miny)
                if a > area:
                    area, best = a, (miny, minx, maxy, maxx)
            _bbox_cache[f["properties"]["name"]] = best
    return _bbox_cache.get(country)


def _country_box(country):
    bb = _country_bbox(country)
    if not bb:
        return None
    s, w, n, e = bb
    return box(w, s, e, n)


def river_names(country):
    """Sorted distinct names of rivers passing through a country."""
    g = _load()
    b = _country_box(country)
    sub = g[g.intersects(b)] if b is not None else g
    return sorted(sub["name"].dropna().unique().tolist())


def _to_lines(gdf):
    lines = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "LineString":
            lines.append([[round(x, 5), round(y, 5)] for x, y in geom.coords])
        elif geom.geom_type == "MultiLineString":
            for ls in geom.geoms:
                lines.append([[round(x, 5), round(y, 5)] for x, y in ls.coords])
    lines.sort(key=len, reverse=True)
    return lines


def load_river(country, name):
    """{name, lines:[[[lon,lat],...], ...]} for a named river within a country."""
    g = _load()
    hit = g[g["name"].str.lower() == name.strip().lower()]
    b = _country_box(country)
    if b is not None:
        inside = hit[hit.intersects(b)]
        if len(inside):
            hit = inside
    if not len(hit):
        raise ValueError(f'no river named "{name}" in {country}')
    return {"name": name, "lines": _to_lines(hit)}


if __name__ == "__main__":
    import sys

    country = sys.argv[1] if len(sys.argv) > 1 else "United States of America"
    name = sys.argv[2] if len(sys.argv) > 2 else "Mississippi"
    names = river_names(country)
    print(f"{country}: {len(names)} rivers (e.g. {names[:6]})")
    d = load_river(country, name)
    print(f'{name}: {len(d["lines"])} polylines, longest {len(d["lines"][0])} pts')
