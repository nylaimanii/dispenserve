# Dispenserve privacy

Dispenserve needs to know one thing: *has this face been here in the last 24 hours?* It never needs to know who anyone is, so it doesn't. This page says exactly what is kept, where, for how long, and what every connected service receives.

## What stays on the laptop

| What | Where | How long |
|---|---|---|
| **One face vector per person served**: 512 numbers from the face model, averaged over the 3 second scan, plus the time it was stored | RAM of the `vision/main.py` process | Until it's 24 hours old, memory is cleared (`c`), or the app quits |
| Per-frame vectors and face landmarks during a scan | RAM | About 3 seconds, discarded once the decision is made |
| Camera frames | RAM, one at a time | Never saved. **While the machine is asleep they aren't even run through face detection.** |
| Counters: dispensed today, unique today, per-hour counts, items left | RAM | Reset at midnight or when the app quits |
| Stage timings (`/metrics`) | RAM | The last 500 measurements per stage |
| Spoken-line clips (`vision/audio/*.mp3`) | Disk | These are the twelve fixed kiosk lines, the same for everyone. Not user data. |

A face vector is not a photo. You can't view it and it contains no name. It is still biometric data, though (it's what tells two faces apart), so it never leaves RAM. Stale and cleared vectors are overwritten with zeros before being released.

**Stored nowhere:** images, video, names, student ids, or any link between a vector and a person.

## What every service receives

| Service | Receives | Never receives |
|---|---|---|
| **Kiosk iPad** (`GET /state`) | state (sleep / idle / scanning / dispensed / already_served), scan progress, item name | faces, vectors, scores |
| **Operator dashboard** (`/stats`, `/insights`, `/metrics`) | items left, dispensed today, unique count today, jam flag, restock advice, stage timings | faces, vectors, scores, per-visit data |
| **Arduino** (USB serial) | `d` (dispense), `x` (red light) | anything else |
| **Tiger Data** (fleet database) | `{machine_id, bay, event, ts}`, where event is dispensed / already_served / restocked | vectors, images, scores, any per-person id |
| **Snowflake** (analytics) | the same four fields as Tiger Data | vectors, images, scores, any per-person id |
| **Solana devnet** (public donor ledger) | restock `{machine_id, date, bay, restocked_qty}` and daily total `{machine_id, date, dispensed_total}` | anything per person or per visit, and no timestamps finer than a date |
| **Gemini** (restock advice) | items left per bay, dispensed per hour today, unique count today, local time | vectors, images, scores, individual visits |
| **ElevenLabs** (voice) | the twelve fixed kiosk lines, once, to make audio clips | anything about anyone: `voice.say()` only accepts a line name |
| **DigitalOcean** (fleet API host) | reads Tiger Data and the Solana ledger; serves counts | anything the database doesn't have (which is anything personal) |

Each row is checked by a test: `test_privacy.py` (full session: no disk writes, no off-machine connections, API responses contain no vectors), `test_telemetry.py` (Tiger Data and Snowflake rows), `test_solana.py` (memo contents; counts must be plain integers, so a vector can't be written), `test_insights.py` (the exact Gemini request), and `test_voice.py` (the exact ElevenLabs requests).

## What the system cannot do

- **Identify anyone.** There's nothing to compare a face against except other anonymous faces from the last 24 hours at this one machine.
- **Follow people between machines.** Each machine's memory is its own, and vectors are never sent anywhere.
- **Remember anyone past 24 hours or past a restart.** When the process exits, every vector is gone.
- **Let the cloud find a person.** Tiger Data, Snowflake, the Solana ledger and Gemini hold or see counts. Even with full access, no row belongs to someone.
- **Watch people who aren't using it.** Until the sensor says someone is standing within 80 cm, frames are ignored.

## Honest caveats

- **Fails open.** If matching errors out, the person gets an item. Memory is wiped on restart, so a restart lets everyone take another. We chose extra snacks over refusing someone because of a bug.
- **Timestamps.** Tiger Data and Snowflake events are timestamped to the second. Someone who also had CCTV of the machine could line up "an item was dispensed at 14:03" with a person on camera. If that matters for a deployment, round `ts` in `vision/telemetry.py`. The public Solana ledger only ever has dates.
- **Swap.** The OS could page RAM to swap. On macOS, swap is encrypted by default.
- **Logs.** The terminal prints each scan's outcome and similarity score, e.g. `dispense (new, best score 0.12)`. A score can't be turned back into a face, and the app never writes logs to a file.
- **Liveness is basic.** `--liveness` catches a still photo. It isn't certified against video replays or masks.
- **The sensor is presence, not identity.** "near" and "away" only mean something is within 80 cm of the front panel.
