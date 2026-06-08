"""
build_web_data — turn the heavy Natural Earth GeoJSON into slim files the
browser can load fast.

For each layer we: keep only the few properties we use, simplify the geometry,
and round coordinates. The 39 MB world states file drops to a few MB.

Outputs -> web/data/
    countries.json   one FeatureCollection, props: {name, iso2, continent}
    states.json      one FeatureCollection, props: {name, country, iso2}
"""

from __future__ import annotations

import json
import os

import geopandas as gpd
from shapely.geometry import mapping

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "web", "data")
os.makedirs(OUT, exist_ok=True)


def _round_geom(geom, ndigits):
    """Recursively round every coordinate in a GeoJSON geometry mapping."""
    def r(x):
        if isinstance(x, (list, tuple)):
            if x and isinstance(x[0], (int, float)):
                return [round(float(c), ndigits) for c in x]
            return [r(i) for i in x]
        return x

    g = mapping(geom)
    return {"type": g["type"], "coordinates": r(g["coordinates"])}


def _features(gdf, prop_map, simplify_tol, ndigits):
    feats = []
    geoms = gdf.geometry.simplify(simplify_tol, preserve_topology=True)
    for (_, row), geom in zip(gdf.iterrows(), geoms):
        if geom.is_empty:
            continue
        props = {out: row[src] for out, src in prop_map.items()}
        feats.append(
            {"type": "Feature", "properties": props,
             "geometry": _round_geom(geom, ndigits)}
        )
    return feats


def _write(path, feats):
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": feats}, f,
                  separators=(",", ":"))
    return os.path.getsize(path)


def main():
    # All admin layers come from Natural Earth 10m so country/state/county share
    # boundaries. States are simplified once; the country base map is the DISSOLVE
    # of those simplified states, so the base and the state borders nest exactly.
    TOL = 0.006

    print("reading states (10m)...")
    s = gpd.read_file(os.path.join(DATA, "ne_10m_admin_1_states_provinces.geojson"))
    s = s.copy()
    s["geometry"] = s.geometry.simplify(TOL, preserve_topology=True)
    s_feats = _features(s, {"name": "name", "country": "admin", "iso2": "iso_a2"},
                        simplify_tol=0.0, ndigits=4)
    n = _write(os.path.join(OUT, "states.json"), s_feats)
    print(f"  states.json     {len(s_feats):4d} feats  {n/1e6:5.2f} MB")

    # The base WORLD map is drawn all at once (258 shapes), so it must stay
    # light or the browser hangs painting the SVG. Simplify it hard — a faint
    # backdrop doesn't need 10m detail (state/county traces carry the detail).
    print("reading countries (10m admin_0, simplified for a light base)...")
    a0 = gpd.read_file(os.path.join(DATA, "ne_10m_admin_0_countries.geojson"))
    c_feats = _features(
        a0, {"name": "ADMIN", "iso2": "ISO_A2", "iso3": "ADM0_A3", "continent": "CONTINENT"},
        simplify_tol=0.08, ndigits=2)
    n = _write(os.path.join(OUT, "countries.json"), c_feats)
    print(f"  countries.json  {len(c_feats):4d} feats  {n/1e6:5.2f} MB")

    print("building US counties (10m, nests with states)...")
    c2 = gpd.read_file(os.path.join(DATA, "ne_10m_admin_2_counties.geojson"))
    c2 = c2[c2["ADMIN"] == "United States of America"]
    cty_feats = _features(c2, {"name": "NAME"}, simplify_tol=TOL, ndigits=4)
    os.makedirs(os.path.join(OUT, "adm2"), exist_ok=True)
    _write(os.path.join(OUT, "adm2", "USA.json"), cty_feats)
    print(f"  adm2/USA.json   {len(cty_feats):4d} feats")

    print("reading cities (Natural Earth populated places)...")
    pp_path = os.path.join(DATA, "ne_10m_populated_places_simple.geojson")
    p = gpd.read_file(pp_path)
    cities = []
    for _, row in p.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        cities.append({
            "name": row.get("name"),
            "country": row.get("adm0name"),
            "state": row.get("adm1name"),
            "pop": int(row.get("pop_max") or 0),
            "rank": int(row.get("scalerank") or 10),
            "lon": round(float(geom.x), 3),
            "lat": round(float(geom.y), 3),
        })
    cities.sort(key=lambda c: -c["pop"])
    cpath = os.path.join(OUT, "cities.json")
    with open(cpath, "w") as f:
        json.dump({"cities": cities}, f, separators=(",", ":"))
    print(f"  cities.json     {len(cities):4d} pts    {os.path.getsize(cpath)/1e6:5.2f} MB")


if __name__ == "__main__":
    main()
