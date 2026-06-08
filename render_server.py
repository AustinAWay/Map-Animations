"""
render_server — tiny HTTP API that turns a posted storyboard into an MP4.

Runs in the project venv (needs geopandas/matplotlib/ffmpeg), so it is started
from a normal shell, NOT from the sandboxed preview server. It writes the MP4
into the preview's static dir so the web app can play it back same-origin.

    POST /render   body: storyboard JSON  ->  {ok, url, frames, seconds}
    GET  /health   ->  {ok: true}

CORS is open so the browser app (served on :8777) can call this on :8799.
"""

from __future__ import annotations

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import storyboard_render

PORT = 8799
OUT_DIR = "/tmp/mapgen_preview/output"
os.makedirs(OUT_DIR, exist_ok=True)

_counter = {"n": 0}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/health"):
            return self._json(200, {"ok": True})
        if self.path.startswith("/admin2"):
            from urllib.parse import parse_qs, urlparse
            iso3 = (parse_qs(urlparse(self.path).query).get("iso3") or [""])[0]
            try:
                import geoboundaries
                data = geoboundaries.load_adm2(iso3)
                self.log_message("admin2 %s -> %d counties", iso3, len(data["features"]))
                return self._json(200, data)  # FeatureCollection
            except Exception as e:  # noqa: BLE001
                return self._json(200, {"ok": False, "error": str(e)})
        if self.path.startswith("/rivers"):  # list rivers in a country (for the picker)
            from urllib.parse import parse_qs, urlparse
            country = (parse_qs(urlparse(self.path).query).get("country") or [""])[0]
            try:
                import rivers
                names = rivers.river_names(country)
                return self._json(200, {"ok": True, "names": names})
            except Exception as e:  # noqa: BLE001
                return self._json(200, {"ok": False, "error": str(e)})
        if self.path.startswith("/streets"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            try:
                import streets
                lon = float((q.get("lon") or ["0"])[0])
                lat = float((q.get("lat") or ["0"])[0])
                radius = float((q.get("radius") or ["3"])[0])
                classes = (q.get("classes") or ["freeway,major,local"])[0].split(",")
                data = streets.fetch_streets(lon, lat, radius, tuple(classes))
                self.log_message("streets %.3f,%.3f r%s -> %d roads", lon, lat, radius, len(data["lines"]))
                return self._json(200, {"ok": True, **data})
            except Exception as e:  # noqa: BLE001
                return self._json(200, {"ok": False, "error": str(e)})
        if self.path.startswith("/river"):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(self.path).query)
            country = (q.get("country") or [""])[0]
            name = (q.get("name") or [""])[0]
            try:
                import rivers
                data = rivers.load_river(country, name)
                self.log_message("river %s/%s -> %d lines", country, name, len(data["lines"]))
                return self._json(200, {"ok": True, **data})
            except Exception as e:  # noqa: BLE001
                return self._json(200, {"ok": False, "error": str(e)})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/render"):
            return self._json(404, {"ok": False, "error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            board = json.loads(self.rfile.read(n) or b"{}")
            steps = board.get("steps", [])
            if not steps:
                return self._json(400, {"ok": False, "error": "storyboard has no steps"})

            _counter["n"] += 1
            name = f"animation_{_counter['n']}.mp4"
            path = os.path.join(OUT_DIR, name)
            storyboard_render.render(board, path)

            fps = int(board.get("fps", 30))
            frames = sum(max(1, round(s.get("duration", 1.0) * fps)) for s in steps)
            self.log_message("rendered %s (%d frames)", name, frames)
            return self._json(200, {
                "ok": True,
                "url": f"/output/{name}",
                "frames": frames,
                "seconds": round(frames / fps, 2),
            })
        except Exception as e:  # noqa: BLE001 — report any render failure to the client
            traceback.print_exc()
            return self._json(500, {"ok": False, "error": str(e)})


if __name__ == "__main__":
    print(f"render API on http://127.0.0.1:{PORT}  (out -> {OUT_DIR})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
