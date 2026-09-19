# dispenserve

A dispenser that gives one item per person per day. A laptop camera does face matching in Python (`vision/`), and an Arduino Uno (`dispenser/`) drives a 9g servo that sweeps a slotted disc to drop an item. Machines report anonymous counts to a fleet database (`cloud/`).

## Layout

- `dispenser/dispenser.ino` — Arduino sketch. Servo on pin 9, serial at 9600 baud. Prints `ready` on boot; on `d` it runs one dispense sweep and prints `ok`.
- `vision/` — the machine. Venv lives in `.venv` (`requirements.txt` at the repo root). Scripts use flat imports (`import memory`), run as `.venv/bin/python vision/<file>.py`.
  - `main.py` — the app: camera loop, 3s hold (`HoldTracker`), `Dispenserve` (decision side effects), `--no-camera` fake scans, `--no-serial`, `--liveness`. Keys f/c/r/q.
  - `memory.py` — `MemoryStore` (vectors in RAM) and `decide()`. No camera needed, so tests use it directly.
  - `server.py` — HTTP on port 8000, same routes as `ui/mockserver.py` (`/state`, `/stats`, `/set`, pages) plus `/metrics`. Serves `ui/` pages read-only.
  - `state.py` — kiosk state and daily counters. `serial_link.py` — Arduino link, missing hardware is non-fatal.
  - `liveness.py` — blink + depth (affine residual of 5 keypoints) anti-spoof. `metrics.py` — per-stage timings.
  - `telemetry.py` — anonymous `{machine_id, bay, event, ts}` batches to `TIGER_DATABASE_URL`.
  - `tune.py` — threshold tuning from (score, label) pairs. `config.py` — env + `.env` loading.
  - `test_serial.py`, `focus_test.py`, `face_test.py` — hardware check scripts.
- `cloud/schema.sql` — TimescaleDB hypertable, hourly continuous aggregate, retention. `cloud/api/` — FastAPI fleet service (`/fleet`, `/forecast`, `--fake`), Dockerfile. `.do/app.yaml` — DigitalOcean App Platform spec.
- `tests/` — pytest (`.venv/bin/pytest`). `tests/test_privacy.py` guards the privacy rules below; keep it passing.
- `ui/` — kiosk + dashboard pages and a mock server (`mockserver.py`). **Owned by a teammate: do not edit anything in `ui/`.**
- Docs: `README.md`, `PRIVACY.md`, `DEVPOST.md`.

## Privacy and matching rules

- Face vectors live in memory only. They must never be written to disk (no files, databases, logs, caches, or pickles) and never sent anywhere. Same for images and landmarks.
- Entries are purged after 24 hours.
- Match threshold: cosine similarity 0.42 (strictly greater is a match).
- The system fails open: any error during matching or liveness → dispense rather than refuse. (A lost camera reconnects; it does not dispense, since nobody was scanned.)
- Telemetry is only `{machine_id, bay, event, ts}` with event in dispensed / already_served / restocked. Never add fields to it.
- Secrets (`TIGER_DATABASE_URL`) come from the environment or the gitignored `.env`; everything must run without them.

## API the web pages depend on

The kiosk reads:

```
GET /state -> { "state": "idle" | "scanning" | "dispensed" | "already_served", "progress": 0-1, "item": ... }
```

The dashboard reads:

```
GET /stats -> { "bays": [{ "name": ..., "remaining": ..., "capacity": ... }], "dispensed_today": ..., "unique_today": ... }
```

Keep these shapes stable; the pages in `ui/` depend on them.
