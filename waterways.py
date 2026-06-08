"""
waterways — fetch river/canal/stream geometry for a small area from OpenStreetMap.

Same Overpass pipeline as streets.py, but for `waterway` ways. Using OSM (rather
than the coarse Natural Earth river lines) means the water lines up exactly with
the OSM streets at city scale — e.g. the Thames sits where it really is.
Cached under web/data/water/.
"""

from __future__ import annotations

import hashlib
import json
import os

from streets import _bbox, _overpass        # reuse the Overpass helpers

HERE = os.path.dirname(os.path.abspath(__file__))
WATER_DIR = os.path.join(HERE, "web", "data", "water")

CLASSES = {
    "river": ["river", "canal"],
    "stream": ["stream", "ditch", "drain"],
}
_VALUE_CLASS = {v: c for c, vals in CLASSES.items() for v in vals}


def cache_path(lon, lat, radius_km, classes):
    key = f"{round(lon,4)}_{round(lat,4)}_{radius_km}_{'-'.join(sorted(classes))}"
    return os.path.join(WATER_DIR, f"{hashlib.md5(key.encode()).hexdigest()[:12]}.json")


def fetch_water(lon, lat, radius_km=2.0, classes=("river",)):
    """{lines:[{cls, coords:[[lon,lat],...]}]} for waterways of the given classes
    within radius_km of (lon,lat). Cached."""
    classes = [c for c in classes if c in CLASSES]
    path = cache_path(lon, lat, radius_km, classes)
    if os.path.exists(path):
        return json.load(open(path))

    os.makedirs(WATER_DIR, exist_ok=True)
    values = [v for c in classes for v in CLASSES[c]]
    s, w, n, e = _bbox(lon, lat, radius_km)
    rx = "|".join(values)
    q = (f'[out:json][timeout:60];'
         f'way["waterway"~"^({rx})$"]({s},{w},{n},{e});out geom;')
    res = _overpass(q)
    lines = []
    for el in res.get("elements", []):
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        cls = _VALUE_CLASS.get((el.get("tags") or {}).get("waterway"))
        if not cls:
            continue
        coords = [[round(p["lon"], 5), round(p["lat"], 5)] for p in el["geometry"]]
        if len(coords) >= 2:
            lines.append({"cls": cls, "coords": coords})
    out = {"lon": lon, "lat": lat, "radius_km": radius_km, "lines": lines}
    with open(path, "w") as fp:
        json.dump(out, fp, separators=(",", ":"))
    return out


if __name__ == "__main__":
    d = fetch_water(-0.118, 51.508, 2.5, ("river",))
    print(f"central London water: {len(d['lines'])} ways")
