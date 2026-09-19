"""
Mock backend for Dispenserve's UI, Job 1 (kiosk) and Job 3 (dashboard).

Stand-in for the laptop's real /state and /stats endpoints so both pages
can be built and tested before the vision/serial code is wired up. No
dependencies beyond the standard library -- nothing to install at the venue.

Run:
    python3 mock_server.py
    (or python mock_server.py on Windows)

Then open:
    http://localhost:8000/kiosk.html
    http://localhost:8000/dashboard.html

Drive it from another terminal, or a browser tab, with query params:
    http://localhost:8000/set?state=dispensed&item=Kit+Kat
    http://localhost:8000/set?state=already_served
    http://localhost:8000/set?state=idle
    http://localhost:8000/set?state=sleep
    http://localhost:8000/set?state=scanning&progress=0.5

With no manual /set calls, it free-runs through idle -> scanning ->
dispensed -> idle -> scanning -> already_served on a loop, so the kiosk
page has something to poll immediately.

Swap this file for the real laptop code without touching kiosk.html or
dashboard.html -- both only depend on the GET /state and GET /stats
JSON contracts below.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HOST = "0.0.0.0"
PORT = 8000

# ---- Shared mutable state, guarded by a lock -----------------------------
lock = threading.Lock()

state = {
    "state": "idle",
    "progress": 0.0,
    "item": "Kit Kat",
}

stats = {
    "bays": [
        {"name": "Kit Kat", "remaining": 18, "capacity": 24},
    ],
    "dispensed_today": 0,
    "unique_today": 0,
}

AUTO_DRIVE = True  # set False once /set is being called for real testing
SEQUENCE = ["sleep", "idle", "scanning", "dispensed", "idle", "scanning", "already_served"]
HOLD_SECONDS = {"sleep": 4.0, "idle": 2.5, "scanning": 3.0, "dispensed": 2.5, "already_served": 2.5}


def auto_driver():
    i = 0
    while True:
        with lock:
            drive = AUTO_DRIVE
        if drive:
            s = SEQUENCE[i % len(SEQUENCE)]
            i += 1
            with lock:
                state["state"] = s
                state["progress"] = 0.0
                if s == "dispensed":
                    stats["dispensed_today"] += 1
                    stats["unique_today"] += 1
                    bay = stats["bays"][0]
                    bay["remaining"] = max(0, bay["remaining"] - 1)
            if s == "scanning":
                steps = 15
                for _ in range(steps):
                    time.sleep(HOLD_SECONDS["scanning"] / steps)
                    with lock:
                        if state["state"] != "scanning":
                            break
                        state["progress"] = min(1.0, state["progress"] + 1 / steps)
                continue
            time.sleep(HOLD_SECONDS[s])
        else:
            time.sleep(0.2)


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload, code=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/state":
            with lock:
                self._json(dict(state))
            return

        if path == "/stats":
            with lock:
                self._json(dict(stats))
            return

        if path == "/set":
            global AUTO_DRIVE
            with lock:
                if "state" in qs:
                    AUTO_DRIVE = False
                    state["state"] = qs["state"][0]
                if "progress" in qs:
                    state["progress"] = float(qs["progress"][0])
                if "item" in qs:
                    state["item"] = qs["item"][0]
                if qs.get("auto", [""])[0] == "1":
                    AUTO_DRIVE = True
            self._json({"ok": True, "state": dict(state)})
            return

        if path in ("/", "/kiosk.html"):
            self._file("kiosk.html", "text/html")
            return
        if path == "/dashboard.html":
            self._file("dashboard.html", "text/html")
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet during the demo


if __name__ == "__main__":
    threading.Thread(target=auto_driver, daemon=True).start()
    print(f"Dispenserve mock server on http://localhost:{PORT}")
    print(f"  kiosk:     http://localhost:{PORT}/kiosk.html")
    print(f"  dashboard: http://localhost:{PORT}/dashboard.html")
    print(f"  drive it:  http://localhost:{PORT}/set?state=dispensed&item=Kit+Kat")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()