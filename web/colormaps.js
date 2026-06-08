/* colormaps — sequential color scales that match matplotlib's built-ins, so the
 * D3 web preview and the matplotlib MP4 render shade choropleths identically.
 * Each scale is a list of evenly-spaced hex stops; sample() interpolates. */

const COLORMAPS = {
  viridis: ["#440154", "#482878", "#3e4a89", "#31688e", "#26828e", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"],
  plasma:  ["#0d0887", "#41049d", "#6a00a8", "#8f0da4", "#b12a90", "#cc4778", "#e16462", "#f2844b", "#fca636", "#f0f921"],
  cividis: ["#00224e", "#123570", "#3b496c", "#575d6d", "#707173", "#8a8779", "#a59c74", "#c3b369", "#e1cc55", "#fee838"],
  magma:   ["#000004", "#1c1044", "#4f127b", "#812581", "#b5367a", "#e55064", "#fb8761", "#fec287", "#fcfdbf"],
  YlGn:    ["#ffffe5", "#f7fcb9", "#d9f0a3", "#addd8e", "#78c679", "#41ab5d", "#238443", "#006837", "#004529"],
  GnBu:    ["#f7fcf0", "#e0f3db", "#ccebc5", "#a8ddb5", "#7bccc4", "#4eb3d3", "#2b8cbe", "#0868ac", "#084081"],
};

function _hex(c) {
  return [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)];
}

// Sample a colormap at t in [0,1] -> "rgb(r,g,b)".
function cmapSample(name, t) {
  const stops = COLORMAPS[name] || COLORMAPS.viridis;
  t = Math.max(0, Math.min(1, t));
  const x = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x));
  const f = x - i;
  const a = _hex(stops[i]), b = _hex(stops[i + 1]);
  const r = Math.round(a[0] + (b[0] - a[0]) * f);
  const g = Math.round(a[1] + (b[1] - a[1]) * f);
  const bl = Math.round(a[2] + (b[2] - a[2]) * f);
  return `rgb(${r},${g},${bl})`;
}

// A CSS linear-gradient string for a colormap (left=low, right=high).
function cmapGradient(name) {
  const stops = COLORMAPS[name] || COLORMAPS.viridis;
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

// Format a metric value per its fmt code.
function fmtValue(v, fmt) {
  if (v == null || isNaN(v)) return "—";
  if (fmt === "usd") return "$" + Math.round(v).toLocaleString();
  if (fmt === "pct") return v.toFixed(1) + "%";
  if (fmt === "int") return Math.round(v).toLocaleString();
  return "" + v;
}
