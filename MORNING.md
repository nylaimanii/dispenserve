# Morning notes

All six parts are done, and each one is committed and pushed. The camera and the Arduino were not touched overnight.

## What got built

1. **`vision/main.py`**, the real app. 3s single-face hold, averaged vector, `decide()` in `vision/memory.py`, serial dispense (waits up to 5s for `ok`), fail-open, `/state` `/stats` `/metrics` on port 8000 with CORS, and it serves `ui/` pages read-only. Keys f/c/r/q, plus `--no-camera`, `--no-serial` and `--liveness`.
2. **Tests**: 48, all passing (`.venv/bin/pytest`). The privacy test uses Python audit hooks to catch any file write or off-machine connection during a full fake session. I checked that it really catches a write, a `numpy.save` and an outgoing connection.
3. **`liveness.py`** (blink + depth, logs only by default), **`tune.py`** (try `--demo`), and per-stage timings at `/metrics`.
4. **Telemetry**, only `{machine_id, bay, event, ts}`. Plus `cloud/schema.sql`, the `cloud/api` FastAPI service (`/fleet`, `/forecast`, `--fake`), a Dockerfile and `.do/app.yaml`.
5. **README** (with a mermaid diagram), **PRIVACY.md**, **DEVPOST.md** ([brackets] mark where real numbers go).
6. `.env` is gitignored, CLAUDE.md is updated, and I added a root `requirements.txt`.

## Verified beyond the unit tests

- The real face models ran on insightface's bundled sample photo, cropped in memory. Same person gave `already_served` (1.00), a different person gave `dispense` (0.06), and the mirrored photo still matched (0.96).
- Frame timing: detect ~38 ms, embed ~23 ms, landmarks ~2 ms; decision ~1 ms. Re-measure with the real camera for Devpost.
- **Tiger Data path, end to end, against a real TimescaleDB 2.30 in Docker.** The schema applies and can be re-run. `telemetry.py` pushed events, the continuous aggregate picked them up, and `/fleet` and `/forecast` returned exactly the expected numbers.
- The API Docker image builds and runs in both fake and database modes. This caught a startup crash inside Docker, which is now fixed.

## Needs a key or URL

- `TIGER_DATABASE_URL` in `.env`, for both the laptop and the fleet API. Then run once: `psql "$TIGER_DATABASE_URL" -f cloud/schema.sql`. Without it, the laptop only logs events and the API serves fake data.
- DigitalOcean: `doctl auth init`, then `doctl apps create --spec .do/app.yaml`, then set `TIGER_DATABASE_URL` as a secret in the app settings. I didn't validate the spec with `doctl`, since it isn't installed; it parses as YAML.
- Set `MACHINE_ID` per laptop, and `FLEET_TZ` (defaults to UTC) for the fleet API.

## Test first

1. `.venv/bin/python vision/main.py` with the webcam and Arduino plugged in directly, not through the hub. Do a full scan → dispense, then scan again → already_served.
2. Open `http://<laptop-ip>:8000/kiosk.html` on the iPad. Stop `ui/mockserver.py` first, because both use port 8000.
3. Run `vision/tune.py` with a few people, and put the best threshold into `MATCH_THRESHOLD` if it differs from 0.42.
4. Read the logged liveness scores for a real face and for a phone photo before ever turning on `--liveness`.

## Weak spots, and things for your teammate

- **Liveness depth is weak.** On synthetic data it only separates a photo from a real head when the head moves about 8° or more; blinks carry the rest. The thresholds are guesses, and that's why it stays log-only.
- **The dashboard's privacy blurb (in `ui/`, not edited) is inaccurate.** It says the machine keeps "a numeric match value and a timestamp". It actually keeps a 512-number face vector and a timestamp. Worth fixing before judges read it.
- **Fleet on the dashboard:** fetch `GET <fleet-url>/fleet` and `GET <fleet-url>/forecast` (CORS is open). Each machine in `/fleet` has `bays: [{name, remaining, capacity}]`, the same shape the dashboard already renders, plus `last_seen`, `online` and `dispensed_today`. `/forecast` gives per-bay `hours_left`, `runs_out_at` and `status` (ok/low/empty/idle), soonest first. Locally: `cd cloud/api && ../../.venv/bin/python app.py --fake` serves it on :8080.
- Nothing is failing right now. Docker images are still on disk: `timescale/timescaledb:latest-pg17` and `dispenserve-fleet:test`. Remove them with `docker rmi` if you need the space.
