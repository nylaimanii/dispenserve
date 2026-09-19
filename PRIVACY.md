# dispenserve privacy

dispenserve needs to know one thing: *has this face been here in the last 24 hours?* It never needs to know who anyone is, so it doesn't. This page says exactly what is kept, where, for how long, and what leaves the machine.

## What is stored

| What | Where | How long |
|---|---|---|
| **One face vector per person served**: 512 numbers from the face model, averaged over the 3 second scan, plus the time it was stored | RAM of the `vision/main.py` process on the laptop | Until it's 24 hours old, the memory is cleared (`c` key), or the app quits, whichever comes first |
| Per-frame vectors and face landmarks during a scan | RAM, same process | About 3 seconds, discarded as soon as the decision is made |
| Camera frames | RAM, shown in the local preview window | One frame at a time, never saved |
| Counters: items dispensed today, unique people today, items left in the bay | RAM | Reset at midnight or when the app quits |
| Stage timings (`/metrics`) | RAM | The last 500 measurements per stage |

A face vector is not a photo. You can't view it and it contains no name. It's still biometric data, though: it's what lets the machine tell two faces apart, so we treat it as sensitive.

Stale vectors are purged before every scan. Purged and cleared vectors are overwritten with zeros before being released, not just dropped.

**Not stored anywhere:** images, video, names, ids, student numbers, or any link between a vector and a person. Nothing is written to disk and there is no database of people.

## What leaves the machine

Only anonymous counts. Each event is exactly four fields:

```json
{"machine_id": "library-2f", "bay": "Kit Kat", "event": "dispensed", "ts": "2026-09-19T14:03:11+00:00"}
```

`event` is one of `dispensed`, `already_served`, `restocked`. These go to the fleet database (Tiger Data) only if `TIGER_DATABASE_URL` is set; otherwise they're only printed in the laptop's terminal. There is no vector, image, similarity score or per-person id, and `telemetry.emit()` has no parameter that could carry one.

On the local network, the laptop serves the kiosk and dashboard: `/state` (idle/scanning/dispensed/already_served, progress, item name), `/stats` (counts and items left) and `/metrics` (timings). None of these contain face data. They are readable by anyone on the same Wi-Fi, which is fine for counts.

## What the system cannot do

- **It can't identify anyone.** There's nothing to compare a face against except other anonymous faces from the last 24 hours at this one machine.
- **It can't follow people between machines.** Each machine's memory is its own, and vectors are never sent anywhere.
- **It can't remember anyone past 24 hours or past a restart.** When the process exits, every vector is gone.
- **The fleet database can't be used to find a person.** It holds counts per bay per machine. Even with full access to it, there's no row that belongs to someone.
- **It can't be tricked into saving a face by a bug that's easy to miss.** `tests/test_privacy.py` runs a full fake session under Python audit hooks. The test fails if anything opens a file for writing, creates a directory, or connects anywhere off the machine. It also checks every telemetry event is exactly the four fields above.

## Honest caveats

- **Fails open.** If matching errors out, the person gets an item. And since memory is wiped on restart, a restart lets everyone take another item. We chose extra snacks over refusing someone because of a bug.
- **Swap.** Like any process, the operating system could page RAM to swap. On macOS, swap is encrypted by default.
- **Timestamps.** Telemetry timestamps are to the second. Someone who also had, say, CCTV of the machine could line up "an item was dispensed at 14:03" with a person on camera. If that matters for a deployment, round `ts` to the minute or hour in `vision/telemetry.py`.
- **Logs.** The terminal prints each scan's outcome and similarity score, e.g. `dispense (new, best score 0.12)`. A score is one number and can't be turned back into a face, but the app doesn't write logs to a file. If you redirect the output to a file, that file is yours to delete.
- **Liveness is basic.** The anti-spoof check (`--liveness`) catches a still photo held up to the camera. It is not certified against video replays or masks.
