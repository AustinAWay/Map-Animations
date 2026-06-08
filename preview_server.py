"""Minimal static file server for the mapgen/output dir (preview only).

Avoids `python -m http.server`, whose argparse default calls os.getcwd() at
import time — which the preview sandbox denies. We pin an absolute directory
instead and never touch the process cwd.
"""

import functools
import http.server
import socketserver

DIRECTORY = "/Users/austinway/Desktop/AudinceRating/mapgen/output"
PORT = 8777

Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DIRECTORY)

with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"serving {DIRECTORY} at http://127.0.0.1:{PORT}")
    httpd.serve_forever()
