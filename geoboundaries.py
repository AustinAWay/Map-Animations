"""
geoboundaries — fetch county-equivalent (ADM2) borders on demand.

Natural Earth has no global county layer, so we pull ADM2 per country from
geoBoundaries (open data, CC BY), slim it, and cache it under web/data/adm2/.
Fetched lazily because global ADM2 is hundreds of MB; one country at a time is
a few MB. Both the web app (via the render server) and the MP4 renderer read
the same cache.
"""

from __future__ import annotations

import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ADM2_DIR = os.path.join(HERE, "web", "data", "adm2")
API = "https://www.geoboundaries.org/api/current/gbOpen/{iso3}/ADM2/"


def _round(x, nd):
    if isinstance(x, (list, tuple)):
        if x and isinstance(x[0], (int, float)):
            return [round(float(c), nd) for c in x]
        return [_round(i, nd) for i in x]
    return x


def cache_path(iso3):
    return os.path.join(ADM2_DIR, f"{iso3.upper()}.json")


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "mapgen/1.0"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch_adm2(iso3, ndigits=3):
    """Path to the slim ADM2 cache for a country, downloading+caching if needed.

    Raises ValueError if geoBoundaries has no ADM2 for the country."""
    iso3 = iso3.upper()
    path = cache_path(iso3)
    if os.path.exists(path):
        return path
    os.makedirs(ADM2_DIR, exist_ok=True)

    meta = json.loads(_get(API.format(iso3=iso3), timeout=60))
    if isinstance(meta, list):  # API returns a list for some queries
        meta = meta[0] if meta else {}
    gj_url = meta.get("simplifiedGeometryGeoJSON") or meta.get("gjDownloadURL")
    if not gj_url:
        raise ValueError(f"no ADM2 (county-level) data for {iso3}")

    raw = json.loads(_get(gj_url, timeout=180))
    feats = []
    for f in raw.get("features", []):
        g = f.get("geometry")
        if not g:
            continue
        feats.append({
            "type": "Feature",
            "properties": {"name": f.get("properties", {}).get("shapeName")},
            "geometry": {"type": g["type"], "coordinates": _round(g["coordinates"], ndigits)},
        })
    with open(path, "w") as fp:
        json.dump({"type": "FeatureCollection", "features": feats}, fp, separators=(",", ":"))
    return path


def load_adm2(iso3):
    """The slim ADM2 FeatureCollection for a country (fetches if not cached)."""
    return json.load(open(fetch_adm2(iso3)))


if __name__ == "__main__":
    import sys

    iso = sys.argv[1] if len(sys.argv) > 1 else "BEL"
    p = fetch_adm2(iso)
    d = json.load(open(p))
    print(f"{iso}: {len(d['features'])} counties -> {p} ({os.path.getsize(p)/1e6:.2f} MB)")
    print("example:", d["features"][0]["properties"]["name"])
