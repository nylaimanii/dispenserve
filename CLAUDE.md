# dispenserve

A dispenser that gives one item per person per day. A laptop camera does face matching in Python (`vision/`), and an Arduino Uno (`dispenser/`) drives a 9g servo that sweeps a slotted disc to drop an item.

## Layout

- `dispenser/` — Arduino sketch. Servo on pin 9, serial at 9600 baud. Prints `ready` on boot; on `d` it runs one dispense sweep and prints `ok`.
- `vision/` — Python face matching + serial control of the Arduino. Venv lives in `.venv` (pyserial, opencv-python, numpy).
- `web/` — kiosk + dashboard pages. **Owned by a teammate: do not edit anything in `web/`.**

## Privacy and matching rules

- Face vectors live in memory only. They must never be written to disk (no files, databases, logs, caches, or pickles).
- Entries are purged after 24 hours.
- Match threshold: cosine similarity 0.42.
- The system fails open: if matching or the camera errors out, dispense rather than refuse.

## API the web pages depend on

The kiosk reads:

```
GET /state -> { "state": "idle" | "scanning" | "dispensed" | "already_served", "progress": 0-1, "item": ... }
```

The dashboard reads:

```
GET /stats -> { "bays": [{ "name": ..., "remaining": ... }], "dispensed_today": ..., "unique_today": ... }
```

Keep these shapes stable; the pages in `web/` depend on them.
