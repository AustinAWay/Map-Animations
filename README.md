# mapgen — code-driven, animatable maps

Generate map graphics entirely in code and animate them, using real
**Natural Earth** data. Two tracks live here:

### 1. Interactive web app (`web/`) — border-tracing animations
A full-earth D3 map with a control panel: pick a **country** and optionally a
**state/province**, then trigger animations that **zoom to the feature** and
**draw a line around its border** (SVG stroke sweep). Buttons:
*Trace country*, *Trace state*, *Country → State* (sequence), *Play all states*
(tour every province), *Reset*.

```bash
./sync_preview.sh                  # mirror web/ into /tmp (Desktop is sandboxed)
# then open http://127.0.0.1:8777/ in a real browser tab
```

> Note: D3 animations are driven by `requestAnimationFrame`, which browsers
> pause in **hidden/background tabs**. Keep the tab focused to see motion.

Data is preprocessed from the raw Natural Earth GeoJSON into slim files:

```bash
.venv/bin/python build_web_data.py   # -> web/data/{countries,states}.json
```

### 2. Rendered video pipeline (GeoPandas + Matplotlib)
Publication-style stills + animations that export to **MP4** (via a pip-bundled
ffmpeg, no Homebrew). One animation object exports two ways:

- an **interactive HTML player** (scrub/play in a browser)
- a **final MP4**

## Layout

| File | Role |
|------|------|
| `geomap.py` | Data toolkit: load/clip/project Natural Earth layers, select countries & US states, palette, view bounds. |
| `scene.py` | The *look* (composition) and *motion* (the intro animation) of the US map. Plus `export_html` / `export_mp4`. |
| `make.py` | Driver: renders the still + HTML, and `--mp4` for the video. |
| `data/` | Natural Earth GeoJSON (countries, states, rivers, lakes). |
| `output/` | Rendered PNG / HTML / MP4. |
| `preview_server.py` | Tiny static server used for browser preview. |

## Use

```bash
.venv/bin/python make.py          # still PNG + interactive HTML
.venv/bin/python make.py --mp4    # also render the MP4
open output/us_build.html         # play the animation in your browser
```

## Design notes

- **Projection:** North America Albers Equal Area (`TARGET_CRS` in `geomap.py`),
  so the lower-48 and Alaska both read well in one frame.
- **Clipping:** geometry is clipped in lon/lat *before* projecting to drop the
  far Aleutian islands that cross the antimeridian (they would smear the map).
- **Styling:** all colors live in `geomap.PALETTE` — change them in one place.
- **Adding features:** `geomap.layer("rivers")` / `layer("lakes")` are already
  projected & clipped; filter by name (e.g. river `name == "Mississippi"`) and
  plot onto the same Axes to highlight specific features.

## Storyboard actions

A storyboard is a list of steps; the same JSON drives the live D3 preview and
the matplotlib→MP4 render. Every action below works in **both**.

| Action | What it does |
|--------|--------------|
| `zoom` / `trace` | Ease the camera to a country / state / county, or draw its border. |
| `city` | Drop a marker for a place in the cities dataset (`zoom:false` pins it on the current view). |
| `pin` | **Drop a labeled marker at *any* lon/lat**, any color — no dataset needed. `{action:"pin", lon, lat, label, color, zoom}` |
| `grid` | **Toggle a lat/lon graticule** with degree labels — the coordinate system, made visible. `{action:"grid", step:15, on:true}` |
| `data` | **Choropleth the US states** by a metric, rank-colored, with a legend. `{action:"data", metric:"density"}` |
| `biome` | **Fill biome / ecoregion polygons** colored by class (14 WWF biomes), with a legend. `{action:"biome", region:"world"|"usa"}` |
| `streets` | Fade in OSM roads for a city, colored by class (freeway / major / local). |
| `river` | Trace a named river and label it along its curve. |
| `hold` / `reset` | Freeze the frame / clear everything and ease back to the world. |

A **live coordinate readout** (hover anywhere on the map) shows lon/lat through
the current zoom, so it's easy to read off coordinates for a `pin`.

### Data overlays (`data`)
Six real US-state metrics (2020 Census + ACS 2022), built by
`build_state_data.py` → `web/data/us_state_stats.json`:
population density, total population, median household income, land area,
poverty rate, and bachelor's-degree share. Each is **rank (quantile) colored**
so a single outlier (DC's density) doesn't crush every other state into one
shade. Add a metric by editing `METRICS`/`RAW` in `build_state_data.py`.

### Biomes (`biome`)
`web/data/biomes.json` is the RESOLVE Ecoregions 2017 dataset dissolved to the
14 WWF terrestrial biomes (cleaned to valid, antimeridian-safe, d3-wound
polygons). `web/data/biomes_meta.json` holds the biome names + colors.

## Showcase

`showcase.json` is a 46-step tour that exercises **every** capability at least
twice (coordinate grid + pins, biomes, the six data overlays, borders & city
markers, a state→county→street drill-down, and rivers). Render it:

```bash
.venv/bin/python storyboard_render.py showcase.json   # -> output/storyboard.mp4
```

The web app loads the same tour on boot — press **▶ Preview** or **🎬 Render MP4**.

## Next ideas

- World-wide choropleths (currently US-state only).
- Query the biome at a clicked point and label it.
- A camera that pans/zooms to a chosen region.
