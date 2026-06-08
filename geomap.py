"""
geomap — a tiny reusable toolkit for code-driven, animatable maps.

Built on GeoPandas + Matplotlib + real Natural Earth data. The whole point:
every map is defined in code, every map can be animated, and the *same*
animation object exports to an interactive browser page (for fast iteration)
or to a final MP4 (for delivery).

Layers available (Natural Earth 1:50m, in ./data):
    countries  - admin_0 country polygons (US, Canada, Mexico, ...)
    states     - admin_1 state/province polygons
    rivers     - named river + lake centerlines
    lakes      - lake polygons (incl. the Great Lakes)

Conventions:
    * All geometry is reprojected to TARGET_CRS (North America Albers Equal
      Area) so distances/areas look right and the US sits flat and centered.
    * Coordinates are clipped in lon/lat *before* projecting to drop the
      trans-antimeridian Aleutian sliver that would otherwise smear the map.
"""

from __future__ import annotations

import os
from functools import lru_cache

import geopandas as gpd
from shapely.geometry import box

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
OUTPUT_DIR = os.path.join(HERE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# North America Albers Equal Area. Standard parallels chosen to keep both the
# lower-48 and Alaska looking reasonable in one frame.
TARGET_CRS = (
    "+proj=aea +lat_1=20 +lat_2=60 +lat_0=40 +lon_0=-100 "
    "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
)

# Lon/lat clip window applied before projecting. Keeps mainland US + Alaska +
# the near Aleutians; drops the far Aleutians that cross the antimeridian.
CLIP_LONLAT = (-179.0, 14.0, -52.0, 72.0)  # (minx, miny, maxx, maxy)

# A shared, tweakable palette so every map looks consistent.
PALETTE = {
    "ocean": "#dfeaf2",
    "us_fill": "#3b6ea5",
    "us_edge": "#ffffff",
    "neighbor_fill": "#cdd3d8",
    "neighbor_edge": "#aeb6bd",
    "country_edge": "#2c4257",
    "lake": "#dfeaf2",
    "river": "#7fa8cc",
    "text": "#1c2b3a",
}

_LAYER_FILES = {
    "countries": "ne_50m_admin_0_countries.geojson",
    "states": "ne_50m_admin_1_states_provinces.geojson",
    "rivers": "ne_50m_rivers_lake_centerlines.geojson",
    "lakes": "ne_50m_lakes.geojson",
}


@lru_cache(maxsize=None)
def _raw_layer(name: str) -> gpd.GeoDataFrame:
    """Load one Natural Earth layer in its native lon/lat CRS (cached)."""
    path = os.path.join(DATA_DIR, _LAYER_FILES[name])
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        gdf = gdf.set_crs(4326)
    return gdf


@lru_cache(maxsize=None)
def layer(name: str) -> gpd.GeoDataFrame:
    """A layer clipped to the working window and projected to TARGET_CRS."""
    gdf = _raw_layer(name)
    clip_box = box(*CLIP_LONLAT)
    gdf = gdf.clip(clip_box)
    return gdf.to_crs(TARGET_CRS)


def _country_field(countries: gpd.GeoDataFrame) -> str:
    for f in ("ADMIN", "admin", "NAME", "name", "SOVEREIGNT"):
        if f in countries.columns:
            return f
    raise KeyError("No country-name field found in countries layer")


def countries_named(*names: str) -> gpd.GeoDataFrame:
    """Country polygons selected by name, e.g. countries_named('Canada')."""
    c = layer("countries")
    field = _country_field(c)
    return c[c[field].isin(names)]


def _state_country_field(states: gpd.GeoDataFrame) -> str:
    for f in ("admin", "ADMIN", "sov_a3", "iso_a2"):
        if f in states.columns:
            return f
    raise KeyError("No country field found in states layer")


def us_states() -> gpd.GeoDataFrame:
    """The 50 US states + DC (excluding territories), projected & clipped."""
    s = layer("states")
    field = _state_country_field(s)
    if field in ("admin", "ADMIN"):
        return s[s[field] == "United States of America"]
    return s[s[field] == "US"]


def view_bounds(gdf: gpd.GeoDataFrame, pad: float = 0.04):
    """(xmin, xmax, ymin, ymax) bounding a layer, padded by a fraction."""
    minx, miny, maxx, maxy = gdf.total_bounds
    dx, dy = (maxx - minx) * pad, (maxy - miny) * pad
    return minx - dx, maxx + dx, miny - dy, maxy + dy
