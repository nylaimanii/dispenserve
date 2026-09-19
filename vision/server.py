"""HTTP server for the kiosk and dashboard. Same routes and port as ui/mockserver.py.

Serves the ui/ pages read-only, so the kiosk can load from this laptop and fetch
/state and /stats from the same origin.
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from config import REPO_ROOT

log = logging.getLogger("dispenserve.server")

HOST = "0.0.0.0"
PORT = 8000
UI_DIR = REPO_ROOT / "ui"
PAGES = {"/": "kiosk.html", "/kiosk.html": "kiosk.html", "/dashboard.html": "dashboard.html"}


def make_handler(app):
    """app provides app_state (AppState) and metrics_json() -> dict."""

    class Handler(BaseHTTPRequestHandler):
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "*")

        def _json(self, payload, code=200):
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self._cors()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _page(self, name):
            try:
                body = (UI_DIR / name).read_bytes()
            except OSError:
                self._json({"error": f"ui/{name} not found"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/state":
                self._json(app.app_state.state_json())
            elif path == "/stats":
                self._json(app.stats_json())
            elif path == "/metrics":
                self._json(app.metrics_json())
            elif path == "/insights":
                self._json(app.insights_json())
            elif path == "/set":
                self._set(parse_qs(parsed.query))
            elif path == "/flush-solana":
                # only from this laptop (python vision/main.py --flush-solana), not the network
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    self._json({"ok": False, "error": "local only"}, 403)
                else:
                    self._json(app.flush_solana())
            elif path in PAGES:
                self._page(PAGES[path])
            else:
                self._json({"error": "not found"}, 404)

        def _set(self, qs):
            # manual kiosk override for demos, same as the mock server
            try:
                if "state" in qs:
                    app.app_state.set_state(qs["state"][0], qs.get("progress", [None])[0])
                elif "progress" in qs:
                    app.app_state.set_progress(qs["progress"][0])
                if "item" in qs:
                    app.app_state.set_item(qs["item"][0])
            except ValueError as e:
                self._json({"ok": False, "error": str(e)}, 400)
                return
            self._json({"ok": True, "state": app.app_state.state_json()})

        def log_message(self, fmt, *args):
            pass  # keep the terminal quiet during the demo

    return Handler


def start_server(app, host=HOST, port=PORT):
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    log.info("serving on http://localhost:%d (kiosk: /kiosk.html, dashboard: /dashboard.html)", server.server_address[1])
    return server
