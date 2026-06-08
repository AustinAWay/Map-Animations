"""
satellite — Esri World Imagery basemap tiles for a lon/lat bounding box.

Fetches and stitches Web Mercator (EPSG:3857) tiles so a render can sit on real
aerial imagery. Tiles are cached on disk. Free Esri World Imagery service
(attribution: "Imagery © Esri"); no API key.
"""

from __future__ import annotations

import io
import math
import os
import urllib.request

import numpy as np
from PIL import Image, ImageEnhance

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "web", "data", "sat_tiles")
R = 6378137.0
HALF = math.pi * R
URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ATTRIBUTION = "Imagery © Esri"


def _tilexy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _pick_zoom(west, east, target=7, zmax=18, zmin=10):
    for z in range(zmax, zmin - 1, -1):
        xw, _ = _tilexy(west, 0, z)
        xe, _ = _tilexy(east, 0, z)
        if (xe - xw) <= target:
            return z
    return zmin


def _get_tile(z, x, y):
    p = os.path.join(CACHE, str(z), str(x), f"{y}.jpg")
    if os.path.exists(p):
        return Image.open(p).convert("RGB")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    req = urllib.request.Request(URL.format(z=z, x=x, y=y),
                                 headers={"User-Agent": "Mozilla/5.0 mapgen/1.0"})
    data = urllib.request.urlopen(req, timeout=30).read()
    with open(p, "wb") as f:
        f.write(data)
    return Image.open(io.BytesIO(data)).convert("RGB")


def fetch(west, south, east, north, zoom=None):
    """RGB mosaic + its EPSG:3857 extent [xmin, xmax, ymin, ymax] covering the
    lon/lat bbox. Pass zoom to force a tile level (else auto by width)."""
    z = zoom or _pick_zoom(west, east)
    x0, y0 = _tilexy(west, north, z)        # top-left
    x1, y1 = _tilexy(east, south, z)        # bottom-right
    xa, xb = int(math.floor(x0)), int(math.floor(x1))
    ya, yb = int(math.floor(y0)), int(math.floor(y1))
    cols, rows = xb - xa + 1, yb - ya + 1
    mosaic = Image.new("RGB", (cols * 256, rows * 256))
    for ix in range(xa, xb + 1):
        for iy in range(ya, yb + 1):
            try:
                t = _get_tile(z, ix, iy)
            except Exception:  # noqa: BLE001 — missing tile -> neutral fill
                t = Image.new("RGB", (256, 256), (28, 28, 32))
            mosaic.paste(t, ((ix - xa) * 256, (iy - ya) * 256))
    # gentle grade so the imagery reads richer, not flat
    mosaic = ImageEnhance.Contrast(mosaic).enhance(1.12)
    mosaic = ImageEnhance.Color(mosaic).enhance(1.18)
    arr = np.asarray(mosaic)
    size = (2 * HALF) / (2 ** z)
    xmin = -HALF + xa * size
    xmax = -HALF + (xb + 1) * size
    ymax = HALF - ya * size
    ymin = HALF - (yb + 1) * size
    return arr, [xmin, xmax, ymin, ymax]


if __name__ == "__main__":
    a, ext = fetch(-0.142, 51.510, -0.131, 51.516)
    print("mosaic", a.shape, "extent3857", [round(v) for v in ext])
