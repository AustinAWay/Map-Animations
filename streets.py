"""
streets — fetch classified road geometry for a small area from OpenStreetMap.

Roads come from OSM's `highway` tag, grouped into a few classes so they can be
shown selectively (just freeways, just major roads, etc.). Bounded to a small
radius around a point (a city/downtown), cached under web/data/streets/.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STREETS_DIR = os.path.join(HERE, "web", "data", "streets")

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# OSM highway value -> our class. Order matters for display (freeways on top).
CLASSES = {
    "freeway": ["motorway", "motorway_link", "trunk", "trunk_link"],
    "major": ["primary", "primary_link", "secondary", "secondary_link"],
    "local": ["tertiary", "tertiary_link", "residential", "unclassified", "living_street"],
}
_VALUE_CLASS = {v: c for c, vals in CLASSES.items() for v in vals}


def _overpass(query):
    data = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for ep in ENDPOINTS:
        try:
            req = urllib.request.Request(ep, data=data, headers={"User-Agent": "mapgen/1.0"})
            return json.loads(urllib.request.urlopen(req, timeout=70).read())
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def _bbox(lon, lat, radius_km):
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(0.2, math.cos(math.radians(lat))))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)  # s, w, n, e


def cache_path(lon, lat, radius_km, classes):
    key = f"{round(lon,4)}_{round(lat,4)}_{radius_km}_{'-'.join(sorted(classes))}"
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return os.path.join(STREETS_DIR, f"{h}.json")


def fetch_streets(lon, lat, radius_km=3.0, classes=("freeway", "major", "local")):
    """{lines:[{cls, coords:[[lon,lat],...]}, ...]} for roads of the given
    classes within radius_km of (lon,lat). Cached."""
    classes = [c for c in classes if c in CLASSES]
    path = cache_path(lon, lat, radius_km, classes)
    if os.path.exists(path):
        return json.load(open(path))

    os.makedirs(STREETS_DIR, exist_ok=True)
    values = [v for c in classes for v in CLASSES[c]]
    s, w, n, e = _bbox(lon, lat, radius_km)
    rx = "|".join(values)
    q = (f'[out:json][timeout:60];'
         f'way["highway"~"^({rx})$"]({s},{w},{n},{e});out geom;')
    res = _overpass(q)
    lines = []
    for el in res.get("elements", []):
        if el.get("type") != "way" or not el.get("geometry"):
            continue
        cls = _VALUE_CLASS.get((el.get("tags") or {}).get("highway"))
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
    import collections

    d = fetch_streets(-118.243, 34.052, 3.0, ("freeway", "major", "local"))
    c = collections.Counter(l["cls"] for l in d["lines"])
    print(f"downtown LA: {len(d['lines'])} roads -> {dict(c)}")
