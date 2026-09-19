# dispenserve

**One snack per person per day. The machine never learns who you are.**

## Inspiration

Free food on campus disappears fast, and usually to the same few people. Food pantries, club events and study-night snack tables all run into it: the fastest people clear the table and the people who needed it most get nothing. The usual fixes are to swipe an ID, sign a sheet or scan a QR code. All of them make people identify themselves to get a granola bar, and many people who need free food would rather not.

We wanted a machine that is fair without tracking anyone. It only needs to know whether a face has been here in the last 24 hours. It doesn't need to know who the person is.

## What it does

Walk up to the kiosk and look at the camera for 3 seconds. A ring on the iPad fills as it scans.

- **New today?** The servo turns, your item drops, and the kiosk shows what you got.
- **Already had one?** The kiosk tells you kindly. No alarm, no name.

Behind the scenes:

- Your face becomes a 512-number vector that exists **only in the laptop's RAM** and is purged after 24 hours. No photos, no names, no database of people.
- If anything goes wrong while matching, it **fails open**: you get the item.
- Each machine reports only anonymous counts (`machine, bay, dispensed, time`) to a fleet database. Campus staff get a dashboard showing every machine's stock, plus a forecast of when each bay will run out, so they can restock before it's empty.

## How we built it

**Hardware.** An Arduino Uno drives a 9g servo that sweeps a slotted disc: each 0→180→0 sweep drops one item. The servo runs on a 4×AA pack with a ground shared with the Uno. The laptop sends `d` over serial; the Arduino sweeps and answers `ok`. A full cycle takes [~3.1 s].

**Vision.** Python with insightface (`buffalo_l`): an SCRFD detector finds faces and ArcFace makes a 512-d embedding. The kiosk only starts a scan when **exactly one** face stays in frame, and it restarts if a second face appears or someone swaps in mid-scan. Every frame's embedding over the 3 second hold is averaged into one normalized vector, which is steadier than a single frame. We match it by cosine similarity against everyone in memory, with a threshold of **0.42**.

**Timing.** Each stage is timed and served at `GET /metrics`. On our laptop's CPU: detection [38] ms, embedding [23] ms and landmarks [2] ms per frame, so a frame takes about [65] ms. After the 3 second hold, the decision takes [~1] ms. From the end of the hold to the item dropping takes [___] ms.

**Anti-spoofing.** A simple liveness check on the landmarks insightface already gives us:
1. **Blink**: eye openness (from the 106-point landmarks) dips during the hold.
2. **Depth**: a flat photo waved in front of the camera only moves its 5 keypoints by a 2D affine transform. A real head is 3D, so the nose shifts relative to the eyes and mouth in a way an affine fit can't explain. That leftover is our depth score.

It sits behind a `--liveness` flag and only logs by default, so it can never refuse a real person during a demo.

**Threshold tuning.** `tune.py` records only similarity **scores** and a yes/no label from user testing, never vectors. It prints false match and missed match rates for thresholds from 0.30 to 0.60. With [N] people and [M] labeled scans, the best threshold was [0.xx]: [x]% false match, [y]% missed match.

**Fleet.** Anonymous events go into a **Tiger Data** (TimescaleDB) hypertable. A continuous aggregate rolls up dispenses per bay per hour, and retention policies drop raw events after 30 days. A FastAPI service on **DigitalOcean App Platform** serves `/fleet` (stock and last-seen time per machine) and `/forecast`. Forecasting is deliberately plain math: *items left ÷ items per hour over the last 3 hours*. The machine batches telemetry in a background thread, so a slow network never blocks the camera.

**Kiosk and dashboard.** Plain HTML pages that poll `/state` and `/stats` from the laptop over Wi-Fi, so any iPad on the network can be the kiosk.

## Challenges we ran into

- **The USB hub that hid the Arduino.** The Uno's power light was on, but macOS never showed a serial port, so there was nothing to upload to. The hub was passing power but not data. Plugging straight into the laptop fixed it instantly. Along the way we also found that newer macOS lists USB devices under `system_profiler SPUSBHostDataType`, not the older `SPUSBDataType`.
- **Servo brownout on USB power.** Powered from the Arduino's 5V pin, the servo pulled enough current at the start of a sweep to reset the Uno mid-dispense. Moving the servo to its own 4×AA pack with a shared ground fixed it.
- **The Arduino compiler on Apple Silicon.** The AVR toolchain `arduino-cli` downloads is an Intel binary, so compiling failed with `bad CPU type in executable` until we installed Rosetta.
- **Proving we don't save faces.** It's easy to say. To prove it, we wrote a test that runs a whole fake session under Python audit hooks. It fails if *anything* opens a file for writing or connects off the machine. [Anything it caught?]
- **Detector jitter vs. real motion.** Keypoints jitter by about a pixel from frame to frame, which is about as big as a small natural head movement. Smoothing over 3 frames helped, but the depth signal only really separates a photo from a real head when the head moves around [8]° or more. That's why blink is part of the check and why liveness is off by default.

## Accomplishments that we're proud of

- A privacy promise that's **enforced by a test**, not just written in a doc.
- It never refuses on error: every failure path we could find ends in a dispense.
- Real, measured latency: [~65 ms per frame; ~1 ms decision].
- An end-to-end fleet pipeline, from a laptop at a snack table to a hypertable to a cloud forecast, that never handles personal data at any stage.
- [___ people served / ___ items dispensed during testing.]

## What we learned

- Averaging embeddings across a short hold makes matching much more stable than trusting a single frame.
- Hardware debugging is mostly power and cables.
- Deciding "fail open" early made every other design choice simpler.
- Time-series databases make "what's running low" a small SQL query rather than a separate pipeline.

## What's next

- Measure accuracy with more people and publish the false match / missed match curve.
- Stronger liveness: a challenge-response ("turn your head") or depth from a second camera.
- Multiple bays per machine, one servo each, and let people choose their item.
- Restock alerts pushed to staff phones from the forecast.
- Run the face model on-device on a small board so there's no laptop at all.

## Built with

arduino · c++ · python · insightface · onnxruntime · opencv · numpy · pyserial · fastapi · uvicorn · postgresql · timescaledb · tiger-data · digitalocean · docker · html · javascript · pytest
