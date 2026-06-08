/* mapgen — build a multi-step border animation, preview it live, render an MP4.
 *
 * The browser owns the BUILDER + live D3 preview. The MP4 is produced by the
 * Python render API (matplotlib + ffmpeg) from the very same storyboard, then
 * played back here in a <video>.
 */

const RENDER_API = `http://${location.hostname}:8799`;

const svg = d3.select("#map");
const stage = document.getElementById("stage");
let width = stage.clientWidth;
let height = stage.clientHeight;

const projection = d3.geoNaturalEarth1();
const path = d3.geoPath(projection);

const g = svg.append("g").attr("id", "zoomable");
const oceanLayer = g.append("path").attr("class", "sphere");
const gratLayer = g.append("path").attr("class", "graticule");
const countryLayer = g.append("g");
const biomeLayer = g.append("g");   // biome / ecoregion fills
const dataLayer = g.append("g");    // choropleth data overlay (US states)
const lakeLayer = g.append("g");    // lakes drawn as water (over land + overlays)
const gridLayer = g.append("g");    // coordinate graticule + degree labels
const selLayer = g.append("g");     // shows the currently-selected feature (pre-render)
const traceLayer = g.append("g");
const pinLayer = g.append("g");     // freeform coordinate pins (on top)
const overlayLayer = svg.append("g"); // screen-fixed labels (not zoomed)
const gridLabelLayer = svg.append("g"); // screen-fixed degree labels at the edges
const graticule = d3.geoGraticule10();

const zoom = d3.zoom().scaleExtent([1, 80]).on("zoom", (e) => { g.attr("transform", e.transform); onZoomed(e.transform); });
svg.call(zoom).on("dblclick.zoom", null);

// Grid labels live in a screen-fixed layer and are re-laid-out on every zoom so
// they sit along the viewport edges (no pile-up at the lon0/lat0 crossing).
function onZoomed() {
  if (_gridStep) layoutGridLabels();
}

// Screen position of a lon/lat through the current zoom transform.
function screenOf(lon, lat) {
  const p = projection([lon, lat]);
  if (!p) return null;
  const t = d3.zoomTransform(svg.node());
  return [t.applyX(p[0]), t.applyY(p[1])];
}
// lon/lat under a screen pixel (inverse of the above).
function lonlatAt(sx, sy) {
  const t = d3.zoomTransform(svg.node());
  return projection.invert([(sx - t.x) / t.k, (sy - t.y) / t.k]);
}

// Lay out degree labels. Longitude labels ride the equator and latitude labels
// ride the prime meridian — but each line is CLAMPED into the visible viewport,
// so when those lines scroll off-screen (zoomed in) the labels slide to the
// nearest visible edge instead of vanishing. The prime-meridian (lon 0) label
// is dropped from the longitude row and the two families are nudged apart, so
// nothing piles up at the lon0/lat0 crossing.
function layoutGridLabels() {
  gridLabelLayer.selectAll("*").remove();
  if (!_gridStep) return;
  const fmtLon = (v) => (v === 0 ? "0°" : `${Math.abs(v)}°${v < 0 ? "W" : "E"}`);
  const fmtLat = (v) => (v === 0 ? "0°" : `${Math.abs(v)}°${v < 0 ? "S" : "N"}`);
  const style = (sel) => sel.attr("font-size", "11px").attr("font-weight", "600")
    .attr("fill", "#33567d").attr("paint-order", "stroke").attr("stroke", "#eaf1f8")
    .attr("stroke-width", "2.6px").attr("pointer-events", "none");

  // visible lon/lat extent from the four viewport corners
  const corners = [[16, 16], [width - 16, 16], [16, height - 16], [width - 16, height - 16]]
    .map((p) => lonlatAt(p[0], p[1])).filter(Boolean);
  if (corners.length < 2) return;
  const lons = corners.map((c) => c[0]), lats = corners.map((c) => c[1]);
  const lonMin = Math.min(...lons), lonMax = Math.max(...lons);
  const latMin = Math.min(...lats), latMax = Math.max(...lats);
  const padLat = (latMax - latMin) * 0.07 + 1, padLon = (lonMax - lonMin) * 0.07 + 1;
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const labelLat = clamp(0, latMin + padLat, latMax - padLat);   // equator, else nearest edge
  const labelLon = clamp(0, lonMin + padLon, lonMax - padLon);   // prime meridian, else nearest edge

  for (let lon = -180; lon <= 180; lon += _gridStep) {
    if (lon === 0) continue;                                     // carried by the latitude row
    const s = screenOf(lon, labelLat);
    if (!s || s[0] < 8 || s[0] > width - 8 || s[1] < 12 || s[1] > height - 4) continue;
    style(gridLabelLayer.append("text").attr("x", s[0]).attr("y", s[1])
      .attr("text-anchor", "middle").attr("dominant-baseline", "hanging").attr("dy", "3").text(fmtLon(lon)));
  }
  for (let lat = -80; lat <= 80; lat += _gridStep) {
    const s = screenOf(labelLon, lat);
    if (!s || s[1] < 8 || s[1] > height - 8 || s[0] < 6 || s[0] > width - 6) continue;
    style(gridLabelLayer.append("text").attr("x", s[0]).attr("y", s[1])
      .attr("text-anchor", "start").attr("dominant-baseline", "central").attr("dx", "5").text(fmtLat(lat)));
  }
}

let countriesByName = new Map();
let statesByCountry = new Map();
let citiesByCountry = new Map();     // country name -> [city, ...] (sorted by pop)
let countyData = new Map();          // iso3 -> Map(county name -> feature)
let board = []; // [{action, level, country, state, county, name, lon, lat, mainland, duration}]
let runToken = 0;

const el = {
  action: document.getElementById("action"),
  level: document.getElementById("level"),
  country: document.getElementById("country"),
  state: document.getElementById("state"),
  county: document.getElementById("county"),
  city: document.getElementById("city"),
  river: document.getElementById("river"),
  riverList: document.getElementById("river-list"),
  riverHint: document.getElementById("river-hint"),
  fRiver: document.getElementById("f-river"),
  fRoadtypes: document.getElementById("f-roadtypes"),
  rtFreeway: document.getElementById("rt-freeway"),
  rtMajor: document.getElementById("rt-major"),
  rtLocal: document.getElementById("rt-local"),
  countyList: document.getElementById("county-list"),
  cityList: document.getElementById("city-list"),
  countyHint: document.getElementById("county-hint"),
  cityHint: document.getElementById("city-hint"),
  fLevel: document.getElementById("f-level"),
  fState: document.getElementById("f-state"),
  fCounty: document.getElementById("f-county"),
  fCity: document.getElementById("f-city"),
  fMainland: document.getElementById("f-mainland"),
  fShowLabel: document.getElementById("f-showlabel"),
  mainland: document.getElementById("mainland"),
  showLabel: document.getElementById("showlabel"),
  duration: document.getElementById("duration"),
  durVal: document.getElementById("dur-val"),
  add: document.getElementById("btn-add"),
  steps: document.getElementById("steps"),
  count: document.getElementById("board-count"),
  preview: document.getElementById("btn-preview"),
  render: document.getElementById("btn-render"),
  clear: document.getElementById("btn-clear"),
  status: document.getElementById("status"),
  videoWrap: document.getElementById("video-wrap"),
  video: document.getElementById("video"),
  vdownload: document.getElementById("vdownload"),
  vclose: document.getElementById("vclose"),
  overlay: document.getElementById("overlay"),
  overlayText: document.getElementById("overlay-text"),
  // new actions
  fPin: document.getElementById("f-pin"),
  pinLon: document.getElementById("pin-lon"),
  pinLat: document.getElementById("pin-lat"),
  pinLabel: document.getElementById("pin-label"),
  pinColor: document.getElementById("pin-color"),
  pinZoom: document.getElementById("pin-zoom"),
  pinHint: document.getElementById("pin-hint"),
  fData: document.getElementById("f-data"),
  dataMetric: document.getElementById("data-metric"),
  dataDesc: document.getElementById("data-desc"),
  fBiome: document.getElementById("f-biome"),
  biomeRegion: document.getElementById("biome-region"),
  biomeLabel: document.getElementById("biome-label"),
  fGrid: document.getElementById("f-grid"),
  gridStep: document.getElementById("grid-step"),
  gridVal: document.getElementById("grid-val"),
  gridOn: document.getElementById("grid-on"),
  // stage overlays
  coordReadout: document.getElementById("coord-readout"),
  coordLon: document.getElementById("coord-lon"),
  coordLat: document.getElementById("coord-lat"),
  legend: document.getElementById("legend"),
  legendTitle: document.getElementById("legend-title"),
  legendBar: document.getElementById("legend-bar"),
  legendScale: document.getElementById("legend-scale"),
  legendMin: document.getElementById("legend-min"),
  legendMax: document.getElementById("legend-max"),
  legendSwatches: document.getElementById("legend-swatches"),
};

let stateStats = null;   // {metrics:[...], states:{name:{...}}}
let biomeData = null;    // FeatureCollection of 14 biomes
let biomeMeta = null;    // {biomes:[{code,name,color}]}
let lakeData = null;     // FeatureCollection of lakes (water bodies)

const setStatus = (html, err = false) => {
  el.status.innerHTML = html;
  el.status.classList.toggle("err", err);
};
const pause = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- map rendering ----------------------------------------------------------

function sizeToStage() {
  width = stage.clientWidth;
  height = stage.clientHeight;
  svg.attr("width", width).attr("height", height);
  projection.fitExtent([[12, 12], [width - 12, height - 12]], { type: "Sphere" });
  oceanLayer.attr("d", path({ type: "Sphere" }));
  gratLayer.attr("d", path(graticule));
  countryLayer.selectAll("path.country").attr("d", path);
  lakeLayer.selectAll("path.lake").attr("d", path);
  if (_gridStep) layoutGridLabels();
}

// Lakes drawn as water, above land and the data/biome overlays so the Great
// Lakes, Caspian, etc. always read as water.
function drawLakes(features) {
  lakeLayer.selectAll("path.lake").data(features).join("path")
    .attr("class", "lake").attr("d", path)
    .attr("fill", "var(--ocean)").attr("stroke", "var(--land-edge)")
    .attr("stroke-width", 0.3).attr("vector-effect", "non-scaling-stroke")
    .attr("pointer-events", "none");
}

function drawCountries(features) {
  countryLayer.selectAll("path.country").data(features, (d) => d.properties.name).join("path")
    .attr("class", "country").attr("d", path)
    .on("click", (_, d) => { el.country.value = d.properties.name; onCountryChange(); });
}

const highlightCountry = (name) =>
  countryLayer.selectAll("path.country").classed("sel", (d) => d.properties.name === name);

// ---- animation primitives ---------------------------------------------------

// Planar (shoelace) area of a lon/lat ring. Used instead of d3.geoArea because
// the spherical area of a polygon hugging the antimeridian (the US Aleutians,
// Russia's Chukotka, Fiji…) blows up to near-global and would be mis-picked as
// the "largest" landmass. Natural Earth splits rings at the antimeridian, so
// each polygon's coords stay in one hemisphere and the planar area is reliable.
function ringArea(ring) {
  let a = 0;
  for (let i = 0, n = ring.length, j = n - 1; i < n; j = i++) {
    a += ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1];
  }
  return Math.abs(a) / 2;
}

// Largest contiguous landmass of a feature — used for zoom framing so a
// country with overseas territories frames its mainland, not the whole globe.
function largestPolygon(feature) {
  const geom = feature.geometry;
  if (!geom || geom.type !== "MultiPolygon") return feature;
  let best = feature, bestArea = -1;
  for (const coordinates of geom.coordinates) {
    const a = ringArea(coordinates[0]);   // outer ring only
    if (a > bestArea) {
      bestArea = a;
      best = { type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates } };
    }
  }
  return best;
}

function transformFor(feature, mainland = true, maxScale = 60, pad = 0.82) {
  const framed = mainland ? largestPolygon(feature) : feature;
  const [[x0, y0], [x1, y1]] = path.bounds(framed);
  const dx = x1 - x0 || 1, dy = y1 - y0 || 1, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  const scale = Math.min(maxScale, pad / Math.max(dx / width, dy / height));
  return d3.zoomIdentity.translate(width / 2, height / 2).scale(scale).translate(-cx, -cy);
}

const zoomTo = (feature, durMs, mainland = true) =>
  svg.transition().duration(durMs).ease(d3.easeCubicInOut).call(zoom.transform, transformFor(feature, mainland)).end();

const resetZoom = (durMs) =>
  svg.transition().duration(durMs).ease(d3.easeCubicInOut).call(zoom.transform, d3.zoomIdentity).end();

const clearTraces = () => { traceLayer.selectAll("*").remove(); overlayLayer.selectAll("*").remove(); };

// All boundary rings of a feature (mainland + every island/hole).
function featureRings(feature) {
  const geom = feature.geometry;
  const polys = geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
  const rings = [];
  for (const poly of polys) for (const ring of poly) rings.push(ring);
  return rings;
}

// Draw the border by sweeping a stroke-dash on every ring at once, so the whole
// outline grows together over the duration (no ring-by-ring dead time).
// `mainland` restricts the trace to the largest contiguous landmass.
function trace(feature, color, durMs, mainland = true) {
  const target = mainland ? largestPolygon(feature) : feature;
  // translucent interior fill that fades in with the outline
  traceLayer.append("path").attr("d", path(target)).attr("fill", color)
    .attr("fill-opacity", 0).attr("stroke", "none").attr("pointer-events", "none")
    .transition().duration(durMs).attr("fill-opacity", 0.16);
  const proms = featureRings(target).map((ring) => {
    const p = traceLayer.append("path").attr("class", "trace")
      .attr("d", path({ type: "LineString", coordinates: ring }))
      .style("stroke", color).style("filter", `drop-shadow(0 0 3px ${color})`);
    const len = p.node().getTotalLength() || 1;
    p.attr("stroke-dasharray", len).attr("stroke-dashoffset", len);
    return p.transition().duration(durMs).ease(d3.easeSine).attr("stroke-dashoffset", 0).end();
  });
  return Promise.all(proms);
}

// ---- storyboard model + list ------------------------------------------------

const isoOf = (country) => {
  const f = countriesByName.get(country);
  return f && f.properties.iso3;
};

// What each country calls its ADM2 division (county label gets the type
// appended so "Los Angeles" the county reads "Los Angeles County").
const ADM2_TERM = { USA: "County", FRA: "Department", GBR: "County", IRL: "County", ITA: "Province", ESP: "Province", PRT: "District" };
function labelText(step) {
  if (step.county) {
    const term = ADM2_TERM[isoOf(step.country)] || "";
    if (term && !step.county.toLowerCase().endsWith(term.toLowerCase())) return `${step.county} ${term}`;
    return step.county;
  }
  return step.state || step.country;
}

// Fetch a country's county (ADM2) set on demand, caching by ISO3.
async function fetchCounties(country) {
  const iso = isoOf(country);
  if (!iso) return null;
  if (countyData.has(iso)) return countyData.get(iso);
  const res = await fetch(`${RENDER_API}/admin2?iso3=${iso}`);
  const data = await res.json();
  if (data.type !== "FeatureCollection") throw new Error(data.error || "no county data");
  const m = new Map();
  for (const f of data.features) if (f.properties.name) m.set(f.properties.name, f);
  countyData.set(iso, m);
  return m;
}

function targetFeature(step) {
  if (step.county) {
    const m = countyData.get(isoOf(step.country));
    return (m && m.get(step.county)) || null;
  }
  if (step.state) return (statesByCountry.get(step.country) || []).find((f) => f.properties.name === step.state) || null;
  return countriesByName.get(step.country) || null;
}

// Append a leader-line callout label (marker -> white label box) into `layer`,
// avoiding already-placed boxes in `placedPx` (screen px). Returns its box.
function calloutLabel(layer, px, py, name, k, color, placedPx) {
  const ppc = 13;                                 // px per char at k=1 scale baseline
  const wpx = name.length * ppc * 0.6 + 14;
  const hpx = 22;
  const mb = [px * k - 11, py * k - 11, px * k + 11, py * k + 11]; // marker box (screen)
  let cxk = px * k, cyk = py * k - 46;
  for (const [ox, oy] of [[0, -46], [46, -32], [-46, -32], [62, 0], [-62, 0], [0, 46], [48, 36], [-48, 36]]) {
    const c = [px * k + ox, py * k + oy];
    const box = [c[0] - wpx / 2, c[1] - hpx / 2, c[0] + wpx / 2, c[1] + hpx / 2];
    const hit = (a, b) => !(a[2] <= b[0] || b[2] <= a[0] || a[3] <= b[1] || b[3] <= a[1]);
    if (hit(box, mb)) continue;
    if (placedPx.some((p) => hit(box, p))) continue;
    cxk = c[0]; cyk = c[1];
    placedPx.push(box);
    break;
  }
  const lx = cxk / k, ly = cyk / k;
  const grp = layer.append("g").attr("opacity", 0);
  grp.append("line").attr("x1", px).attr("y1", py).attr("x2", lx).attr("y2", ly)
    .attr("stroke", color).attr("stroke-width", 1.2 / k);
  const txt = grp.append("text").attr("x", lx).attr("y", ly).attr("text-anchor", "middle")
    .attr("dominant-baseline", "central").attr("font-size", `${13 / k}px`)
    .attr("font-weight", "bold").attr("fill", "#1c2733").text(name);
  const bb = txt.node().getBBox();
  const pad = 4 / k;
  grp.insert("rect", "text").attr("x", bb.x - pad).attr("y", bb.y - pad)
    .attr("width", bb.width + 2 * pad).attr("height", bb.height + 2 * pad)
    .attr("rx", 3 / k).attr("fill", "#fff").attr("stroke", color).attr("stroke-width", 1 / k);
  return grp;
}

// A centered white name-label box for an area, at projected point (px,py).
function areaLabel(layer, px, py, name, k, color) {
  const grp = layer.append("g").attr("opacity", 0);
  const txt = grp.append("text").attr("x", px).attr("y", py).attr("text-anchor", "middle")
    .attr("dominant-baseline", "central").attr("font-size", `${13 / k}px`)
    .attr("font-weight", "bold").attr("fill", "#1c2733").text(name);
  const bb = txt.node().getBBox();
  const pad = 4 / k;
  grp.insert("rect", "text").attr("x", bb.x - pad).attr("y", bb.y - pad)
    .attr("width", bb.width + 2 * pad).attr("height", bb.height + 2 * pad)
    .attr("rx", 3 / k).attr("fill", "#fff").attr("stroke", color).attr("stroke-width", 1 / k);
  // remember the box (projection coords) so city markers can avoid sitting on it
  _placedAreas.push({ x0: bb.x - pad, y0: bb.y - pad, x1: bb.x + bb.width + pad, y1: bb.y + bb.height + pad });
  return grp;
}

let _placedPx = [];     // screen-space callout boxes placed during the current run
let _placedAreas = [];  // area-label boxes (projection coords) for marker avoidance

// Zoom to a city point, drop a marker, and (optionally) a leader-line callout.
function markCity(lon, lat, name, durMs, withLabel, nozoom) {
  const [px, py] = projection([lon, lat]);
  const curK = d3.zoomTransform(svg.node()).k || 1;
  const k = nozoom ? curK : 40;
  const t = d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-px, -py);
  // Skip the dot if the city point sits on an existing area label (e.g. Paris
  // city on the "Paris Department" box).
  const onArea = _placedAreas.some((b) => px >= b.x0 && px <= b.x1 && py >= b.y0 && py <= b.y1);
  const move = nozoom ? Promise.resolve() : svg.transition().duration(durMs * 0.6).ease(d3.easeCubicInOut).call(zoom.transform, t).end();
  return move.then(() => {
    if (!withLabel && onArea) return Promise.resolve();
    if (!onArea) {
      const dot = traceLayer.append("circle").attr("cx", px).attr("cy", py).attr("r", 5 / k)
        .attr("fill", "#e03131").attr("stroke", "#fff").attr("stroke-width", 1.4 / k).attr("opacity", 0);
      dot.transition().duration(durMs * 0.25).attr("opacity", 1);
    }
    if (!withLabel) return Promise.resolve();
    // city callout must avoid both other callouts AND area labels
    const areaPx = _placedAreas.map((b) => [b.x0 * k, b.y0 * k, b.x1 * k, b.y1 * k]);
    const grp = calloutLabel(traceLayer, px, py, name, k, "#e03131", _placedPx.concat(areaPx));
    return grp.transition().duration(durMs * 0.35).attr("opacity", 1).end();
  });
}

let _riverId = 0;

// Fetch a river by name, zoom to it, trace its course, and label it with light
// blue text that follows the curve via an SVG <textPath>.
async function traceRiver(country, name, durMs) {
  let data;
  try {
    const res = await fetch(`${RENDER_API}/river?country=${encodeURIComponent(country)}&name=${encodeURIComponent(name)}`);
    data = await res.json();
  } catch (e) { setStatus(`River fetch failed: ${e.message}`, true); return; }
  if (!data.ok) { setStatus(`River "${name}" not found in ${country}.`, true); return; }
  const lines = (data.lines || []).filter((l) => l.length >= 2);
  if (!lines.length) { setStatus(`River "${name}" had no geometry.`, true); return; }

  const feat = { type: "Feature", geometry: { type: "MultiLineString", coordinates: lines } };
  await zoomTo(feat, durMs * 0.5, false);
  const k = d3.zoomTransform(svg.node()).k || 1;
  const gen = d3.line().x((d) => projection(d)[0]).y((d) => projection(d)[1]);

  const proms = lines.map((l) => {
    const p = traceLayer.append("path").attr("d", gen(l)).attr("fill", "none")
      .attr("stroke", "#2389c9").attr("stroke-width", 2.4 / k).attr("stroke-linecap", "round")
      .attr("vector-effect", "non-scaling-stroke");
    const len = p.node().getTotalLength() || 1;
    p.attr("stroke-dasharray", len).attr("stroke-dashoffset", len);
    return p.transition().duration(durMs * 0.7).ease(d3.easeSine).attr("stroke-dashoffset", 0).end();
  });

  // curved name label via <textPath> on the longest segment
  const longest = lines.reduce((a, b) => (a.length >= b.length ? a : b));
  const id = `riverpath-${_riverId++}`;
  traceLayer.append("path").attr("id", id).attr("d", gen(longest)).attr("fill", "none").attr("stroke", "none");
  const txt = traceLayer.append("text").attr("fill", "#2f86c9").attr("font-weight", "bold")
    .attr("font-size", `${12 / k}px`).attr("dy", `${-3 / k}px`).attr("opacity", 0)
    .attr("paint-order", "stroke").attr("stroke", "#fff").attr("stroke-width", `${2.4 / k}px`);
  txt.append("textPath").attr("href", `#${id}`).attr("startOffset", "32%").text(data.name);

  await Promise.all(proms);
  await txt.transition().duration(durMs * 0.3).attr("opacity", 1).end();
}

// Zoom into a small area and fade in OSM roads colored by class (preview).
async function traceStreets(lon, lat, radius, classes, durMs, cityName, clearPrev) {
  if (clearPrev) clearTraces();
  let data;
  try {
    const res = await fetch(`${RENDER_API}/streets?lon=${lon}&lat=${lat}&radius=${radius}&classes=${classes.join(",")}`);
    data = await res.json();
  } catch (e) { setStatus(`Streets fetch failed: ${e.message}`, true); return; }
  if (!data.ok) { setStatus(`Streets unavailable: ${data.error}`, true); return; }

  const by = { freeway: [], major: [], local: [] };
  data.lines.forEach((l) => by[l.cls] && by[l.cls].push(l.coords));

  const dlat = radius / 111, dlon = radius / (111 * Math.cos(lat * Math.PI / 180));
  const ring = [[lon - dlon, lat - dlat], [lon + dlon, lat - dlat], [lon + dlon, lat + dlat], [lon - dlon, lat + dlat], [lon - dlon, lat - dlat]];
  const feat = { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] } };
  // clean land background (base map is too coarse at street zoom)
  const bg = [[lon - 4 * dlon, lat - 4 * dlat], [lon + 4 * dlon, lat - 4 * dlat], [lon + 4 * dlon, lat + 4 * dlat], [lon - 4 * dlon, lat + 4 * dlat], [lon - 4 * dlon, lat - 4 * dlat]];
  const land = traceLayer.append("path").attr("d", "M" + bg.map((p) => projection(p).join(",")).join("L") + "Z")
    .attr("fill", "#f4f6f8").attr("stroke", "none").attr("opacity", 0);
  await zoomTo(feat, durMs * 0.5, false);
  land.transition().duration(durMs * 0.3).attr("opacity", 1);

  const style = { local: ["#b6bcc4", 0.6], major: ["#f59f00", 1.3], freeway: ["#e8590c", 2.4] };
  const paths = [];
  for (const cls of ["local", "major", "freeway"]) {
    if (!by[cls].length) continue;
    const d = by[cls].map((line) => "M" + line.map((p) => { const q = projection(p); return `${q[0]},${q[1]}`; }).join("L")).join("");
    const [col, lw] = style[cls];
    paths.push(traceLayer.append("path").attr("d", d).attr("fill", "none").attr("stroke", col)
      .attr("stroke-width", lw).attr("stroke-linecap", "round").attr("stroke-linejoin", "round")
      .attr("vector-effect", "non-scaling-stroke").attr("opacity", 0));
  }
  // fixed city-name label (screen overlay, not zoomed)
  let lbl = null;
  if (cityName) {
    overlayLayer.selectAll("*").remove(); // one street label at a time
    lbl = overlayLayer.append("g").attr("opacity", 0).attr("transform", `translate(${width / 2}, 34)`);
    const t = lbl.append("text").attr("text-anchor", "middle").attr("dominant-baseline", "central")
      .attr("font-size", "20px").attr("font-weight", "bold").attr("fill", "#1c2733").text(cityName);
    const bb = t.node().getBBox();
    lbl.insert("rect", "text").attr("x", bb.x - 10).attr("y", bb.y - 6).attr("width", bb.width + 20)
      .attr("height", bb.height + 12).attr("rx", 7).attr("fill", "#fff").attr("stroke", "#c8ccd0");
  }
  await Promise.all(paths.map((p) => p.transition().duration(durMs * 0.4).attr("opacity", 1).end()));
  if (lbl) await lbl.transition().duration(durMs * 0.3).attr("opacity", 1).end();
}

// ---- coordinate grid + readout ---------------------------------------------

let _gridStep = 0;  // current grid spacing in degrees (0 = off)

// Draw a lat/lon graticule at `step`-degree spacing with edge degree labels.
function drawGrid(step) {
  gridLayer.selectAll("*").remove();
  _gridStep = step;
  if (!step) { gridLabelLayer.selectAll("*").remove(); return; }
  const k = d3.zoomTransform(svg.node()).k || 1;
  const mkLine = (pts) => gridLayer.append("path").attr("class", "grid-ln-p")
    .attr("d", path({ type: "LineString", coordinates: pts }))
    .attr("fill", "none").attr("stroke", "#5b86b3").attr("stroke-opacity", 0.5)
    .attr("stroke-width", 0.7 / k).attr("vector-effect", "non-scaling-stroke");
  for (let lon = -180; lon <= 180; lon += step) {
    mkLine(d3.range(-80, 80.1, 2).map((lat) => [lon, lat]));
  }
  for (let lat = -80; lat <= 80; lat += step) {
    mkLine(d3.range(-180, 180.1, 3).map((lon) => [lon, lat]));
  }
  layoutGridLabels();
}

async function runGrid(step, on, durMs) {
  if (!on) {
    gridLabelLayer.transition().duration(durMs * 0.6).attr("opacity", 0);
    await gridLayer.transition().duration(durMs * 0.6).attr("opacity", 0).end().catch(() => {});
    gridLayer.selectAll("*").remove();
    gridLabelLayer.selectAll("*").remove();
    gridLayer.attr("opacity", 1);
    gridLabelLayer.attr("opacity", 1);
    _gridStep = 0;
    return;
  }
  gridLayer.attr("opacity", 0);
  gridLabelLayer.attr("opacity", 0);
  drawGrid(step);
  gridLabelLayer.transition().duration(durMs * 0.8).attr("opacity", 1);
  await gridLayer.transition().duration(durMs * 0.8).attr("opacity", 1).end().catch(() => {});
}

// Live hover readout — converts cursor pixels back to lon/lat through the
// current zoom transform, so the coordinate system is always legible.
function initCoordReadout() {
  svg.on("mousemove.coord", (e) => {
    const [mx, my] = d3.pointer(e, svg.node());
    const t = d3.zoomTransform(svg.node());
    const inv = projection.invert([(mx - t.x) / t.k, (my - t.y) / t.k]);
    if (!inv || !isFinite(inv[0])) { el.coordReadout.classList.add("hidden"); return; }
    el.coordReadout.classList.remove("hidden");
    const [lon, lat] = inv;
    el.coordLon.textContent = `${Math.abs(lon).toFixed(2)}°${lon < 0 ? "W" : "E"}`;
    el.coordLat.textContent = `${Math.abs(lat).toFixed(2)}°${lat < 0 ? "S" : "N"}`;
  });
  svg.on("mouseleave.coord", () => el.coordReadout.classList.add("hidden"));
}

// ---- freeform coordinate pin ------------------------------------------------

// Drop a labeled marker at an arbitrary lon/lat with a custom color. Unlike a
// "city" pin this needs no dataset — any coordinate the storyboard names.
function markPin(lon, lat, label, color, durMs, doZoom) {
  const [px, py] = projection([lon, lat]);
  const curK = d3.zoomTransform(svg.node()).k || 1;
  const k = doZoom ? 24 : curK;
  color = color || "#e8590c";
  const t = d3.zoomIdentity.translate(width / 2, height / 2).scale(k).translate(-px, -py);
  const move = doZoom
    ? svg.transition().duration(durMs * 0.55).ease(d3.easeCubicInOut).call(zoom.transform, t).end()
    : Promise.resolve();
  return move.then(() => {
    const kk = d3.zoomTransform(svg.node()).k || 1;
    const dot = pinLayer.append("circle").attr("cx", px).attr("cy", py).attr("r", 5.5 / kk)
      .attr("fill", color).attr("stroke", "#fff").attr("stroke-width", 1.6 / kk).attr("opacity", 0);
    const ring = pinLayer.append("circle").attr("cx", px).attr("cy", py).attr("r", 5.5 / kk)
      .attr("fill", "none").attr("stroke", color).attr("stroke-width", 2 / kk).attr("opacity", 0.9);
    dot.transition().duration(durMs * 0.3).attr("opacity", 1);
    ring.transition().duration(durMs * 0.6).attr("r", 22 / kk).attr("opacity", 0).remove();
    if (!label) return Promise.resolve();
    const grp = calloutLabel(pinLayer, px, py, label, kk, color, _placedPx);
    return grp.transition().duration(durMs * 0.4).attr("opacity", 1).end();
  });
}

// ---- data overlay (US states choropleth) ------------------------------------

function metricExtent(metric) {
  const vals = Object.values(stateStats.states).map((s) => s[metric]).filter((v) => v != null);
  return [Math.min(...vals), Math.max(...vals)];
}

// Rank (quantile) position of each value in [0,1] — keyed by value. This spreads
// color evenly across states so a single outlier (e.g. DC's density) doesn't
// crush everyone into one shade. Endpoints still map to true min/max.
function rankPositions(values) {
  const sorted = [...values].sort((a, b) => a - b);
  const n = sorted.length;
  const pos = new Map();
  sorted.forEach((v, i) => { if (!pos.has(v)) pos.set(v, n > 1 ? i / (n - 1) : 0.5); });
  return pos;
}

async function applyData(metricKey, durMs) {
  if (!stateStats) { setStatus("State data not loaded.", true); return; }
  const meta = stateStats.metrics.find((m) => m.key === metricKey);
  if (!meta) { setStatus(`Unknown metric: ${metricKey}`, true); return; }
  const usStates = statesByCountry.get("United States of America") || [];
  if (!usStates.length) { setStatus("US states not loaded yet.", true); return; }
  const [lo, hi] = metricExtent(metricKey);
  const ranks = rankPositions(Object.values(stateStats.states).map((s) => s[metricKey]).filter((v) => v != null));

  dataLayer.selectAll("*").remove();
  // frame the lower-48 (+ keep it readable): zoom to the US mainland
  const usFeat = countriesByName.get("United States of America");
  if (usFeat) zoomTo(usFeat, durMs * 0.5, true);

  usStates.forEach((f) => {
    const rec = stateStats.states[f.properties.name];
    const fill = rec ? cmapSample(meta.scheme, ranks.get(rec[metricKey]) ?? 0) : "#e9edf1";
    dataLayer.append("path").attr("d", path(f)).attr("fill", fill)
      .attr("stroke", "#ffffff").attr("stroke-width", 0.5).attr("vector-effect", "non-scaling-stroke")
      .attr("opacity", 0).transition().duration(durMs * 0.7).attr("opacity", 0.92);
  });
  showLegendGradient(meta, lo, hi);
  await pause(durMs * 0.7);
}

function clearData() { dataLayer.selectAll("*").remove(); }

// ---- biome / ecoregion layer ------------------------------------------------

async function showBiomes(region, withLegend, durMs) {
  if (!biomeData) {
    try {
      [biomeData, biomeMeta] = await Promise.all([d3.json("data/biomes.json"), d3.json("data/biomes_meta.json")]);
    } catch (e) { setStatus(`Biome data failed: ${e.message}`, true); return; }
  }
  const colorByCode = new Map(biomeMeta.biomes.map((b) => [b.code, b.color]));
  biomeLayer.selectAll("*").remove();
  if (region === "usa") {
    const usFeat = countriesByName.get("United States of America");
    if (usFeat) zoomTo(usFeat, durMs * 0.5, true);
  } else {
    resetZoom(durMs * 0.5);
  }
  biomeData.features.forEach((f) => {
    biomeLayer.append("path").attr("d", path(f)).attr("fill", colorByCode.get(f.properties.code) || "#cccccc")
      .attr("stroke", "#ffffff").attr("stroke-width", 0.25).attr("vector-effect", "non-scaling-stroke")
      .attr("opacity", 0).transition().duration(durMs * 0.7).attr("opacity", 0.82);
  });
  if (withLegend) showLegendSwatches("Biomes", biomeMeta.biomes);
  await pause(durMs * 0.7);
}

function clearBiomes() { biomeLayer.selectAll("*").remove(); }

// ---- legend -----------------------------------------------------------------

function showLegendGradient(meta, lo, hi) {
  el.legend.classList.remove("hidden");
  el.legendSwatches.classList.add("hidden");
  el.legendBar.style.display = "";
  el.legendScale.style.display = "";
  el.legendTitle.textContent = `${meta.label}${meta.unit ? ` (${meta.unit})` : ""}`;
  el.legendBar.style.background = cmapGradient(meta.scheme);
  el.legendMin.textContent = fmtValue(lo, meta.fmt);
  el.legendMax.textContent = fmtValue(hi, meta.fmt);
}

function showLegendSwatches(title, items) {
  el.legend.classList.remove("hidden");
  el.legendBar.style.display = "none";
  el.legendScale.style.display = "none";
  el.legendSwatches.classList.remove("hidden");
  el.legendTitle.textContent = title;
  el.legendSwatches.innerHTML = items.map((b) =>
    `<div class="sw"><i style="background:${b.color}"></i><span>${b.name}</span></div>`).join("");
}

function hideLegend() { el.legend.classList.add("hidden"); }

// Highlight (and frame) whatever is currently selected in the composer.
function showSelection() {
  selLayer.selectAll("*").remove();
  highlightCountry(null);
  const a = el.action.value;
  if (a === "hold" || a === "reset") return;

  if (a === "city") {
    const c = resolveCity();
    if (!c) return;
    highlightCountry(el.country.value);
    const [px, py] = projection([c.lon, c.lat]);
    selLayer.append("circle").attr("cx", px).attr("cy", py).attr("r", 0.35)
      .attr("fill", "#e03131").attr("stroke", "#fff").attr("stroke-width", 0.12)
      .attr("vector-effect", "non-scaling-stroke");
    svg.transition().duration(650).ease(d3.easeCubicInOut)
      .call(zoom.transform, d3.zoomIdentity.translate(width / 2, height / 2).scale(20).translate(-px, -py));
    return;
  }

  const country = el.country.value;
  if (!country) return;
  const level = el.level.value;
  let feat = null, color = "#1565d8", mainland = el.mainland.checked;
  if (level === "county" && el.county.value) {
    const m = countyData.get(isoOf(country));
    feat = m && m.get(el.county.value); color = "#6741d9"; mainland = false;
  } else if (level === "state" && el.state.value) {
    feat = (statesByCountry.get(country) || []).find((f) => f.properties.name === el.state.value);
    color = "#e8590c";
  } else {
    feat = countriesByName.get(country); color = "#1565d8";
  }
  if (!feat) { highlightCountry(country); return; }
  selLayer.append("path").attr("d", path(feat)).attr("fill", color).attr("fill-opacity", 0.28)
    .attr("stroke", color).attr("stroke-width", 1.6).attr("vector-effect", "non-scaling-stroke");
  svg.transition().duration(650).ease(d3.easeCubicInOut).call(zoom.transform, transformFor(feat, mainland));
}

function stepLabel(step) {
  const A = { zoom: "Zoom to", trace: "Trace", hold: "Hold", reset: "Reset to world", city: "📍 Mark", river: "🌊 River", streets: "🛣 Streets", pin: "🎯 Pin", data: "📊 Data", biome: "🌿 Biome", grid: "🧭 Grid" }[step.action] || step.action;
  let where = "";
  if (step.action === "streets") where = (step.classes || ["all"]).join(", ");
  else if (step.action === "city" || step.action === "river") where = step.name;
  else if (step.action === "pin") where = step.label || `${step.lon}, ${step.lat}`;
  else if (step.action === "data") where = step.metric;
  else if (step.action === "biome") where = step.region || "world";
  else if (step.action === "grid") where = step.on === false ? "off" : `${step.step || 15}°`;
  else if (step.action === "zoom" || step.action === "trace") {
    where = step.county ? `${step.country} / ${step.county}`
      : step.state ? `${step.country} / ${step.state}` : step.country;
  }
  const mainland = (step.action === "zoom" || step.action === "trace") && !step.county && step.mainland !== false;
  return { a: A, where, t: `${step.duration}s`, mainland };
}

function renderBoard() {
  el.count.textContent = board.length;
  el.steps.innerHTML = "";
  if (!board.length) {
    el.steps.innerHTML = '<li class="empty">No steps yet. Build your sequence above.</li>';
  } else {
    board.forEach((step, i) => {
      const { a, where, t, mainland } = stepLabel(step);
      const li = document.createElement("li");
      li.className = "step";
      li.dataset.i = i;
      li.innerHTML =
        `<span class="idx">${i + 1}</span>` +
        `<span class="desc"><span class="a">${a}</span> ${where ? `<span>${where}</span> ` : ""}<span class="t">· ${t}</span>${mainland ? ' <span class="m">· mainland</span>' : ""}</span>` +
        `<span class="ctrls">` +
        `<button data-act="up" title="Move up">▲</button>` +
        `<button data-act="down" title="Move down">▼</button>` +
        `<button data-act="del" title="Delete">✕</button></span>`;
      el.steps.appendChild(li);
    });
  }
  const has = board.length > 0;
  el.preview.disabled = !has;
  el.render.disabled = !has;
  el.clear.disabled = !has;
}

function addStep() {
  const action = el.action.value;
  const duration = parseFloat(el.duration.value);

  if (action === "hold") board.push({ action: "hold", duration });
  else if (action === "reset") board.push({ action: "reset", duration });
  else if (action === "city") {
    const c = resolveCity();
    if (!c) return;
    board.push({ action: "city", country: el.country.value, name: c.name, lon: c.lon, lat: c.lat, duration });
  } else if (action === "streets") {
    const c = resolveCity();
    if (!c) return;
    const classes = [];
    if (el.rtFreeway.checked) classes.push("freeway");
    if (el.rtMajor.checked) classes.push("major");
    if (el.rtLocal.checked) classes.push("local");
    if (!classes.length) return;
    board.push({ action: "streets", country: el.country.value, name: c.name, lon: c.lon, lat: c.lat, radius_km: 3, classes, duration });
  } else if (action === "river") {
    if (!el.country.value || !el.river.value.trim()) return;
    board.push({ action: "river", country: el.country.value, name: el.river.value.trim(), duration });
  } else if (action === "pin") {
    const lon = parseFloat(el.pinLon.value), lat = parseFloat(el.pinLat.value);
    if (!isFinite(lon) || !isFinite(lat)) return;
    board.push({ action: "pin", lon, lat, label: el.pinLabel.value.trim(), color: el.pinColor.value, zoom: el.pinZoom.checked, duration });
  } else if (action === "data") {
    board.push({ action: "data", metric: el.dataMetric.value, duration });
  } else if (action === "biome") {
    board.push({ action: "biome", region: el.biomeRegion.value, label: el.biomeLabel.checked, duration });
  } else if (action === "grid") {
    board.push({ action: "grid", step: parseInt(el.gridStep.value, 10), on: el.gridOn.checked, duration });
  } else {
    const t = borderTarget();
    if (!t) return;
    if (action === "zoomtrace") {
      board.push({ action: "zoom", ...t, duration });
      board.push({ action: "trace", ...t, duration });
    } else board.push({ action, ...t, duration });
  }

  renderBoard();
  setStatus(`Added step. ${board.length} total.`);
}

el.steps.addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const i = +btn.closest("li.step").dataset.i;
  const act = btn.dataset.act;
  if (act === "del") board.splice(i, 1);
  else if (act === "up" && i > 0) [board[i - 1], board[i]] = [board[i], board[i - 1]];
  else if (act === "down" && i < board.length - 1) [board[i + 1], board[i]] = [board[i], board[i + 1]];
  renderBoard();
});

// ---- preview runner ---------------------------------------------------------

function cancelRuns() {
  runToken += 1;
  svg.interrupt();
  traceLayer.selectAll("path").interrupt();
  return runToken;
}

function markActive(i) {
  el.steps.querySelectorAll("li.step").forEach((li) => li.classList.toggle("active", +li.dataset.i === i));
}

async function runStoryboard() {
  const token = cancelRuns();
  clearTraces();
  clearData();
  clearBiomes();
  pinLayer.selectAll("*").remove();
  gridLayer.selectAll("*").remove();
  gridLabelLayer.selectAll("*").remove();
  gridLayer.attr("opacity", 1);
  gridLabelLayer.attr("opacity", 1);
  _gridStep = 0;
  hideLegend();
  selLayer.selectAll("*").remove();
  _placedPx = [];
  _placedAreas = [];
  const shown = new Set(); // names labeled this scene (cleared on reset) — no dupes
  highlightCountry(null);
  showVideo(false);

  // Pre-fetch county data for any county steps so the preview never stalls.
  for (const c of new Set(board.filter((s) => s.county).map((s) => s.country))) {
    try { await fetchCounties(c); } catch (_) { /* shown when the step runs */ }
  }

  for (let i = 0; i < board.length; i++) {
    if (token !== runToken) return;
    markActive(i);
    const step = board[i];
    const dur = Math.max(120, step.duration * 1000);
    const where = step.county || step.state || step.country;
    try {
      const mainland = step.mainland !== false;
      if (step.action === "zoom") {
        const f = targetFeature(step);
        if (step.country) highlightCountry(step.country);
        if (f) { setStatus(`Zooming to <b>${where}</b>`); await zoomTo(f, dur, mainland); }
      } else if (step.action === "trace") {
        const f = targetFeature(step);
        const color = step.county ? "#6741d9" : step.state ? "#e8590c" : "#1565d8";
        if (f) {
          setStatus(`Tracing <b>${where}</b>`);
          await trace(f, color, dur, mainland);
          if (token !== runToken) return;
          const labelTxt = labelText(step);
          if (step.label !== false && !shown.has(labelTxt)) {
            shown.add(labelTxt);
            const k = d3.zoomTransform(svg.node()).k || 1;
            const [cx, cy] = path.centroid(mainland ? largestPolygon(f) : f);
            if (isFinite(cx) && isFinite(cy)) {
              const lg = areaLabel(traceLayer, cx, cy, labelTxt, k, color);
              await lg.transition().duration(Math.max(180, dur * 0.3)).attr("opacity", 1).end();
            }
          }
        }
      } else if (step.action === "city") {
        setStatus(`Marking <b>${step.name}</b>`);
        await markCity(step.lon, step.lat, step.name, dur, !shown.has(step.name), step.zoom === false);
        shown.add(step.name);
      } else if (step.action === "river") {
        setStatus(`Tracing river <b>${step.name}</b>`);
        await traceRiver(step.country, step.name, dur);
      } else if (step.action === "streets") {
        setStatus(`Loading streets (${(step.classes || []).join(", ")})…`);
        await traceStreets(step.lon, step.lat, step.radius_km || 3, step.classes || ["freeway", "major", "local"], dur, step.name, step.clear);
      } else if (step.action === "pin") {
        setStatus(`Pinning <b>${step.label || `${step.lon}, ${step.lat}`}</b>`);
        await markPin(step.lon, step.lat, step.label || "", step.color, dur, step.zoom === true);
      } else if (step.action === "data") {
        setStatus(`Data overlay: <b>${step.metric}</b>`);
        await applyData(step.metric, dur);
      } else if (step.action === "biome") {
        setStatus(`Biomes (${step.region || "world"})`);
        await showBiomes(step.region || "world", step.label !== false, dur);
      } else if (step.action === "grid") {
        setStatus(step.on === false ? "Hiding grid" : `Coordinate grid (${step.step || 15}°)`);
        await runGrid(step.step || 15, step.on !== false, dur);
      } else if (step.action === "reset") {
        setStatus("Resetting view"); clearTraces(); clearData(); clearBiomes(); pinLayer.selectAll("*").remove();
        gridLayer.selectAll("*").remove(); gridLabelLayer.selectAll("*").remove();
        gridLayer.attr("opacity", 1); gridLabelLayer.attr("opacity", 1); _gridStep = 0; hideLegend();
        _placedPx = []; _placedAreas = []; shown.clear(); highlightCountry(null); await resetZoom(dur);
      } else { setStatus("Holding"); await pause(dur); }
    } catch (_) { return; /* interrupted */ }
  }
  if (token === runToken) { markActive(-1); setStatus("Preview complete."); }
}

// ---- MP4 render -------------------------------------------------------------

function showVideo(on) { el.videoWrap.classList.toggle("hidden", !on); }
function showOverlay(on, text) { el.overlay.classList.toggle("hidden", !on); if (text) el.overlayText.textContent = text; }

async function renderMP4() {
  cancelRuns();
  const storyboard = { fps: 30, width: 1280, height: 720, steps: board };
  showOverlay(true, "Rendering MP4…");
  setStatus("Rendering MP4 on the server…");
  try {
    const res = await fetch(`${RENDER_API}/render`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(storyboard),
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "render failed");
    const url = `${location.origin}${data.url}?t=${Date.now()}`;
    el.video.src = url;
    el.vdownload.href = url;
    showOverlay(false);
    showVideo(true);
    el.video.play().catch(() => {});
    setStatus(`Rendered <b>${data.seconds}s</b> (${data.frames} frames).`);
  } catch (err) {
    showOverlay(false);
    setStatus(
      `Render failed: ${err.message}. Is the render server running? ` +
      `Run <b>mapgen/.venv/bin/python mapgen/render_server.py</b>.`, true);
  }
}

// ---- selection wiring -------------------------------------------------------

const show = (node, on) => node.classList.toggle("hidden", !on);

function borderTarget() {
  const country = el.country.value;
  if (!country) return null;
  const level = el.level.value;
  const label = el.showLabel.checked;
  if (level === "state") return el.state.value ? { country, state: el.state.value, mainland: el.mainland.checked, label } : null;
  if (level === "county") return el.county.value ? { country, county: el.county.value, label } : null;
  return { country, mainland: el.mainland.checked, label };
}

const resolveCity = () => (citiesByCountry.get(el.country.value) || []).find((c) => c.name === el.city.value) || null;

function updateComposer() {
  const a = el.action.value;
  const border = a === "zoom" || a === "trace" || a === "zoomtrace";
  const city = a === "city";
  const river = a === "river";
  const streets = a === "streets";
  const level = el.level.value;
  show(el.fLevel, border);
  document.getElementById("f-country").classList.toggle("hidden", !(border || city || river || streets));
  show(el.fState, (border && level === "state") || city || streets);
  show(el.fCity, city || streets);
  show(el.fCounty, border && level === "county");
  show(el.fRiver, river);
  show(el.fRoadtypes, streets);
  show(el.fPin, a === "pin");
  show(el.fData, a === "data");
  show(el.fBiome, a === "biome");
  show(el.fGrid, a === "grid");
  show(el.fMainland, border && level !== "county");
  show(el.fShowLabel, border);
  updateAddEnabled();
}

function updateAddEnabled() {
  const a = el.action.value;
  if (a === "hold" || a === "reset" || a === "data" || a === "biome" || a === "grid") { el.add.disabled = false; return; }
  if (a === "city") { el.add.disabled = !resolveCity(); return; }
  if (a === "streets") { el.add.disabled = !(resolveCity() && (el.rtFreeway.checked || el.rtMajor.checked || el.rtLocal.checked)); return; }
  if (a === "river") { el.add.disabled = !(el.country.value && el.river.value.trim()); return; }
  if (a === "pin") { el.add.disabled = !(isFinite(parseFloat(el.pinLon.value)) && isFinite(parseFloat(el.pinLat.value))); return; }
  el.add.disabled = !borderTarget();
}

function onCountryChange() {
  const name = el.country.value;
  const states = statesByCountry.get(name) || [];
  el.state.innerHTML = '<option value="">— whole country —</option>';
  for (const f of states.slice().sort((a, b) => a.properties.name.localeCompare(b.properties.name))) {
    const o = document.createElement("option");
    o.value = o.textContent = f.properties.name;
    el.state.appendChild(o);
  }
  el.state.disabled = !name || states.length === 0;
  populateCounties();
  populateCities();
  populateRivers();
  updateAddEnabled();
  showSelection();
}

async function populateCounties() {
  el.countyList.innerHTML = ""; el.county.value = ""; el.countyHint.textContent = "";
  if (el.action.value === "city" || el.level.value !== "county" || !el.country.value) return;
  if (!isoOf(el.country.value)) { el.countyHint.textContent = "(no data)"; return; }
  el.countyHint.textContent = "loading…";
  try {
    const m = await fetchCounties(el.country.value);
    const names = [...m.keys()].sort((a, b) => a.localeCompare(b));
    el.countyList.innerHTML = names.map((n) => `<option value="${n.replace(/"/g, "&quot;")}"></option>`).join("");
    el.countyHint.textContent = `(${names.length})`;
  } catch (e) { el.countyHint.textContent = `— ${e.message}`; }
  updateAddEnabled();
}

function populateCities() {
  el.cityList.innerHTML = ""; el.city.value = ""; el.cityHint.textContent = "";
  if ((el.action.value !== "city" && el.action.value !== "streets") || !el.country.value) return;
  let list = citiesByCountry.get(el.country.value) || [];
  if (el.state.value) list = list.filter((c) => c.state === el.state.value);
  el.cityList.innerHTML = list.slice(0, 800).map((c) => `<option value="${c.name.replace(/"/g, "&quot;")}"></option>`).join("");
  el.cityHint.textContent = `(${list.length})`;
  updateAddEnabled();
}

async function populateRivers() {
  el.riverList.innerHTML = ""; el.river.value = ""; el.riverHint.textContent = "";
  if (el.action.value !== "river" || !el.country.value) return;
  el.riverHint.textContent = "loading…";
  try {
    const res = await fetch(`${RENDER_API}/rivers?country=${encodeURIComponent(el.country.value)}`);
    const data = await res.json();
    if (!data.ok) throw new Error(data.error || "no rivers");
    el.riverList.innerHTML = data.names.map((n) => `<option value="${n.replace(/"/g, "&quot;")}"></option>`).join("");
    el.riverHint.textContent = `(${data.names.length})`;
  } catch (e) { el.riverHint.textContent = `— ${e.message}`; }
  updateAddEnabled();
}

// ---- boot -------------------------------------------------------------------

// Showcase storyboard — a tour of the United States that exercises EVERY
// capability at least twice: the coordinate system, the land (biomes), the
// people (data), borders & cities, the state→county→street drill-down, and
// rivers. Acts are separated by resets so each scene starts on a clean map.
function seedTour() {
  const us = "United States of America";
  const pin = (lon, lat, label, color, zoom, d = 1.5) => ({ action: "pin", lon, lat, label, color, zoom, duration: d });
  const mark = (name, lon, lat, d = 0.9) => ({ action: "city", country: us, name, lon, lat, zoom: false, duration: d });
  const streets = (name, lon, lat, d = 2.4) => ({ action: "streets", country: us, name, lon, lat, radius_km: 3, classes: ["freeway", "major", "local"], duration: d });
  board = [
    // ── ACT 1 · The coordinate system (grid ×2, pins ×2) ──
    { action: "grid", step: 30, on: true, duration: 1.4 },
    pin(0, 0, "0°,0° · Null Island", "#e8590c", true, 1.6),
    { action: "hold", duration: 0.7 },
    pin(-157.86, 21.31, "Honolulu · 21°N", "#1565d8", true, 1.5),
    { action: "hold", duration: 0.7 },
    { action: "grid", step: 15, on: true, duration: 1.0 },           // grid #2 — finer spacing
    { action: "hold", duration: 0.8 },
    { action: "reset", duration: 1.2 },

    // ── ACT 2 · The land (biomes ×2) ──
    { action: "biome", region: "world", label: true, duration: 2.0 },
    { action: "hold", duration: 1.6 },
    { action: "biome", region: "usa", label: true, duration: 1.8 },  // biome #2
    { action: "hold", duration: 1.6 },
    { action: "reset", duration: 1.2 },

    // ── ACT 3 · The people (data overlays ×3) ──
    { action: "data", metric: "density", duration: 2.0 },
    { action: "hold", duration: 1.6 },
    { action: "data", metric: "income", duration: 1.8 },             // data #2
    { action: "hold", duration: 1.6 },
    { action: "data", metric: "bachelors", duration: 1.8 },          // data #3
    { action: "hold", duration: 1.6 },
    { action: "reset", duration: 1.2 },

    // ── ACT 4 · Borders & cities (zoom, trace country, city markers ×3) ──
    { action: "zoom", country: us, mainland: true, duration: 1.4 },
    { action: "trace", country: us, mainland: true, label: true, duration: 1.8 },
    mark("New York", -74.006, 40.713),
    mark("Chicago", -87.632, 41.884),
    mark("Houston", -95.369, 29.760),
    { action: "hold", duration: 1.6 },
    { action: "reset", duration: 1.2 },

    // ── ACT 5 · Drill down: state → county → streets (county ×2, streets ×2) ──
    { action: "zoom", country: us, state: "California", duration: 1.2 },
    { action: "trace", country: us, state: "California", label: true, duration: 1.4 },
    { action: "trace", country: us, county: "Los Angeles", duration: 1.4 },   // county #1
    pin(-118.243, 34.052, "Los Angeles", "#6741d9", true, 1.2),
    streets("Los Angeles", -118.243, 34.052),
    { action: "hold", duration: 1.0 },
    { action: "reset", duration: 1.2 },
    { action: "zoom", country: us, state: "Illinois", duration: 1.2 },
    { action: "trace", country: us, state: "Illinois", label: true, duration: 1.3 },
    { action: "trace", country: us, county: "Cook", duration: 1.3 },          // county #2
    streets("Chicago", -87.632, 41.884),
    { action: "hold", duration: 1.0 },
    { action: "reset", duration: 1.2 },

    // ── ACT 6 · Rivers & a final grid (river ×2, grid ×3) ──
    { action: "river", country: us, name: "Mississippi", duration: 2.6 },
    { action: "hold", duration: 1.0 },
    { action: "river", country: us, name: "Colorado", duration: 2.2 },        // river #2
    { action: "grid", step: 10, on: true, duration: 1.0 },                    // grid #3
    { action: "hold", duration: 1.2 },
    { action: "reset", duration: 1.4 },
  ];
  renderBoard();
}

async function boot() {
  sizeToStage();
  setStatus("Loading map…");

  // 1) Base map first — so it appears fast and survives if the bigger region
  //    files are slow or fail to load.
  let countries;
  try {
    countries = await d3.json("data/countries.json");
  } catch (e) {
    setStatus(`Couldn't load the map (${e.message}). Is the server running?`, true);
    return;
  }
  countriesByName = new Map(countries.features.map((f) => [f.properties.name, f]));
  drawCountries(countries.features);
  for (const name of countries.features.map((f) => f.properties.name).sort((a, b) => a.localeCompare(b))) {
    const o = document.createElement("option");
    o.value = o.textContent = name;
    el.country.appendChild(o);
  }
  setStatus("Loading regions & cities…");

  // Lakes (water bodies) — small file, draw as soon as it arrives.
  d3.json("data/lakes.json").then((l) => { lakeData = l; drawLakes(l.features); }).catch(() => {});

  // State stats power the data-overlay dropdown; load early (tiny file).
  d3.json("data/us_state_stats.json").then((s) => {
    stateStats = s;
    el.dataMetric.innerHTML = s.metrics.map((m) => `<option value="${m.key}">${m.label}</option>`).join("");
    el.dataDesc.textContent = s.metrics[0].desc;
  }).catch(() => { el.dataDesc.textContent = "(state data unavailable)"; });

  // 2) States + cities load in the background (they're large); the seed tour is
  //    built once cities are available.
  Promise.all([d3.json("data/states.json"), d3.json("data/cities.json")])
    .then(([states, cityData]) => {
      for (const f of states.features) {
        const k = f.properties.country;
        if (!statesByCountry.has(k)) statesByCountry.set(k, []);
        statesByCountry.get(k).push(f);
      }
      for (const c of cityData.cities) {
        if (!citiesByCountry.has(c.country)) citiesByCountry.set(c.country, []);
        citiesByCountry.get(c.country).push(c);
      }
      seedTour();
      setStatus("Showcase tour loaded — press ▶ Preview or 🎬 Render MP4.");
    })
    .catch((e) => setStatus(`Map loaded, but regions/cities failed: ${e.message}`, true));

  el.action.addEventListener("change", () => { updateComposer(); populateCounties(); populateCities(); populateRivers(); showSelection(); });
  el.level.addEventListener("change", () => { updateComposer(); populateCounties(); showSelection(); });
  el.country.addEventListener("change", onCountryChange);
  el.state.addEventListener("change", () => { populateCities(); updateAddEnabled(); showSelection(); });
  el.county.addEventListener("input", updateAddEnabled);
  el.county.addEventListener("change", showSelection);
  el.city.addEventListener("input", updateAddEnabled);
  el.city.addEventListener("change", showSelection);
  el.river.addEventListener("input", updateAddEnabled);
  [el.rtFreeway, el.rtMajor, el.rtLocal].forEach((c) => c.addEventListener("change", updateAddEnabled));
  [el.pinLon, el.pinLat].forEach((c) => c.addEventListener("input", updateAddEnabled));
  el.dataMetric.addEventListener("change", () => {
    const m = stateStats && stateStats.metrics.find((x) => x.key === el.dataMetric.value);
    if (m) el.dataDesc.textContent = m.desc;
  });
  el.gridStep.addEventListener("input", () => (el.gridVal.textContent = el.gridStep.value));
  el.duration.addEventListener("input", () => (el.durVal.textContent = parseFloat(el.duration.value).toFixed(1)));
  el.add.addEventListener("click", addStep);
  el.preview.addEventListener("click", runStoryboard);
  el.render.addEventListener("click", renderMP4);
  el.clear.addEventListener("click", () => {
    board = []; renderBoard(); cancelRuns(); clearTraces(); clearData(); clearBiomes();
    pinLayer.selectAll("*").remove(); gridLayer.selectAll("*").remove(); gridLabelLayer.selectAll("*").remove();
    gridLayer.attr("opacity", 1); gridLabelLayer.attr("opacity", 1);
    _gridStep = 0; hideLegend(); selLayer.selectAll("*").remove(); _placedPx = []; highlightCountry(null); setStatus("Cleared.");
  });
  el.vclose.addEventListener("click", () => { el.video.pause(); showVideo(false); });
  initCoordReadout();

  window.addEventListener("resize", () => { cancelRuns(); sizeToStage(); svg.call(zoom.transform, d3.zoomIdentity); });

  updateComposer();
  renderBoard();

  // Verification hook (the preview tab backgrounds rAF, freezing tweens).
  window.mapgenDebug = {
    static(country, state) {
      cancelRuns(); clearTraces();
      const f = state ? (statesByCountry.get(country) || []).find((x) => x.properties.name === state) : countriesByName.get(country);
      if (!f) return "not found";
      highlightCountry(country);
      svg.call(zoom.transform, transformFor(f));
      traceLayer.append("path").attr("class", "trace").attr("d", path(f)).style("stroke", state ? "#e8590c" : "#1565d8");
      return "ok";
    },
    api: RENDER_API,
  };
}

boot();
