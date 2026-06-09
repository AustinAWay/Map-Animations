# Animation style — "fast, high-motion" (preferred)

The house style for mapgen videos. Energetic and cinematic: the camera is almost
always moving, builds are quick, then each shot holds ~2s so it lands. Codified
from the John Snow cholera explainer (`../cholera-video`).

## Principles
1. **Fast, punchy builds.** Zooms/draw-ons are snappy — `focus` ≈ 0.7–1.0s, not
   slow drifts. Get to the payoff quickly.
2. **Never static.** Every shot keeps moving — a slow Ken-Burns push/pull fills
   any "hold" instead of freezing. Static frames feel dead.
3. **Build, then land.** After the quick build, hold the finished state ~1.5–2s
   (often as a slow continued push) so the viewer can read it before the cut.
4. **Get close.** Prefer building/street scale over wide overviews — close-ups on
   real detail read far better than "zoomed out and hard to follow."
5. **Motion carries meaning.** Reveal data progressively (staggered dots, draw-on
   borders, a walker leaving a wake) rather than popping it in all at once.
6. **Time it to the words.** Cue events to the narration to the exact second.

## Signature moves (all in mapgen core)
- **Follow-cam** — `walk` with `follow:true, follow_km:~0.15`: track a moving
  marker at close zoom (e.g. John Snow walking the real streets, deaths in his
  wake). Pair with `sat_bounds` so the camera can pan without leaving the tiles.
- **Match cut** — end a vector clip framed on a place, then hard-cut to the SAME
  framing in satellite (`basemap:"satellite"`): "the map becomes real."
- **Scale reveal** — open CLOSE on detail (a corner, a pump) while data builds,
  then `focus` PULL-BACK to reveal the whole pattern (or the reverse).
- **Draw-on / fly-in** — `trace` a border that draws itself, then `focus`
  straight into the subject. Quick, no dead air on empty space.
- **Progressive plot** — `dots` with `reveal:"stagger"` so points plot in.

## Concrete defaults
- focus (camera move): **0.7–1.0s** quick, **1.5–2.5s** for a slow reveal/hold push
- hold-to-land tail: **~2s** (as motion, not a freeze)
- follow-cam window: **follow_km 0.13–0.18** (building scale)
- satellite: `sat_zoom 18` (19 for max crispness), `sat_bounds` padded ~0.005°
- dots: `radius ~4.5`, `glow:true`, white edge — pop on imagery
- segment pacing: animation runs a beat past its narration phrase so it can hold

## Look
- **Cinematic polish:** vignette + graded imagery (contrast/saturation) on
  satellite; soft glow on data dots.
- **Vector palette:** warm "1854 map" parchment land, bold orange/sepia roads,
  blue water; vivid red/cyan data that pops.
- **No redundant captions:** if the narration says it, don't print it.

## Accuracy (non-negotiable)
- Streets & waterways from **OpenStreetMap** (they line up); coastlines from the
  hi-res countries file; data from real georeferenced sources.
