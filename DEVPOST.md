# Dispenserve

**A free snack dispenser for college students: one item per person per day, and it never learns who anyone is.**

## Inspiration

Free food on campus disappears fast, and usually to the same few people. Food pantries, club events and late-night study tables all hit the same problem: the first people through clear the table, and the students who most needed a snack leave with nothing. The usual fixes are to swipe an ID, sign a sheet or scan a QR code. All of them ask students to identify themselves to get a granola bar, and many of the students who most need free food would rather go without than do that.

We wanted a machine that is fair without tracking anyone. It only needs to know one thing: has this face been here in the last 24 hours? It never needs to know who the person is.

## What it does

Walk up to the machine. An ultrasonic sensor notices you and the kiosk fades from a sleeping logo into a face scanner. Look at the camera for 3 seconds while a ring fills and a calm voice says "hold still for a sec."

- **First time today:** the servo turns a slotted disc, your snack drops, the green light blinks, and you hear "here you go, have a good one."
- **Already had one:** the red light comes on and the kiosk kindly says "you've already got yours today, come back tomorrow."
- **Walk away:** "see you tomorrow, thanks for stopping by." The machine goes back to sleep.

Around the machine:

- **Staff** get an operator dashboard with stock per bay, jam and low-stock alerts, a Gemini-written restock recommendation, and a fleet view. The fleet view shows every machine on campus and a forecast of when each bay runs out.
- **Donors** get a public ledger on Solana. Every restock and every day's total is written on chain with an explorer link, so they can watch their money turn into snacks. No student ever appears in it.
- **Students** get a snack without handing over a name, an ID, or a photo.

## How we built it

**Hardware.** An Arduino Uno runs off a 9V battery. A 9g servo sweeps a slotted disc: each 0→180→0 sweep drops one item. The servo is only attached during the sweep, so it draws no power while idle. An HC-SR04 ultrasonic sensor on the front panel reports `near` (someone within 80 cm for half a second) and `away` (nobody for 3 seconds). A green LED blinks on a dispense and a red LED lights on a repeat visit. The laptop sends `d` and the Arduino sweeps, blinks and answers `ok`. A full cycle takes **4.87 s** (0 misses in [N] consecutive test dispenses). A hardware watchdog resets the board if it ever freezes.

**Privacy by design.**
- Face vectors live **only in RAM**. They are purged after 24 hours and overwritten with zeros, and they're gone when the app quits.
- While the machine is asleep, camera frames aren't even run through face detection.
- It **fails open**: any error while matching means the student gets the snack.
- A test runs a whole session under Python audit hooks. It fails if anything writes a file or connects off the laptop. Every cloud integration has its own test proving exactly what it sends.

**Vision.** Python with insightface (`buffalo_l`): SCRFD finds faces and ArcFace makes a 512-number embedding. A scan only starts when **exactly one** face is in frame, and it restarts if a second face appears or someone swaps in. The embeddings from the 3 second hold are averaged into one normalized vector, which is steadier than any single frame. We match it by cosine similarity against everyone in memory, with a threshold of **0.42**.

**Measured performance** (on our laptop's CPU, from `GET /metrics`):
- **62 ms per frame** with a face in view: detection 36.5 ms and embedding 25.1 ms, over about 1,800 frames.
- **1.1 ms** from the end of the hold to the decision (p95 1.5 ms).
- In live testing, the same person's repeat scans matched with **cosine similarity 0.77 to 0.93**, far above the 0.42 threshold. [Across N different people, the highest similarity between two different people was X.]

**Anti-spoofing.** A liveness check built from the landmarks insightface already returns. It counts a blink (eye openness dips) or real 3D motion: a photo waved in front of the camera only moves its keypoints in flat 2D, while a real head's nose shifts relative to its eyes. All 10 of our real scans passed, scoring 1.5 and up (1.0 passes); [a phone photo scored X]. It only logs by default, so it can't turn anyone away during a demo.

**Fleet telemetry (Tiger Data + Snowflake).** Each event is exactly `{machine_id, bay, event, ts}`. It fans out on background threads to a Tiger Data hypertable, which has an hourly continuous aggregate and retention policies, and to a Snowflake table with a daily-per-bay view. Each destination has its own queue and retry, so one slow service never blocks the other or the camera.

**Fleet API (DigitalOcean).** FastAPI on App Platform serves `/fleet` (stock and last-seen time per machine), `/forecast` and `/ledger`. The forecast is plain arithmetic: *items left ÷ items per hour over the last 3 hours*.

**Donor ledger (Solana).** A restock (`r` on the laptop) and each day's total are written to devnet as Memo-program transactions. We build and sign the transactions ourselves, about 40 lines, and verified them against the `solders` parser and devnet's own simulator. `/ledger` reads them back straight from the chain, so a donor doesn't have to trust our server. Records can only hold plain integer counts, so a vector literally can't be written.

**Restock advice (Gemini).** `/insights` sends Gemini hourly counts, items left and today's unique count. It asks for two sentences staff can act on and caches the answer for 10 minutes. Without a key it falls back to the same arithmetic as the forecast.

**Voice (ElevenLabs).** Three variations of four fixed lines, generated once and cached as mp3s. Playback runs as a subprocess and never blocks. Without a key it uses macOS `say`.

**Kiosk and dashboard.** Plain HTML on any iPad on the same Wi-Fi, polling the laptop. The kiosk is a black screen with a softly pulsing logo while asleep, then fades into a large, high-contrast scanner that's readable from 6 feet.

## Challenges we ran into

- **The USB hub that hid the Arduino.** The Uno's power light was on, but macOS never showed a serial port. The hub passed power but not data. Plugging straight into the laptop fixed it instantly.
- **Power.** On USB power, the servo's current draw browned out the Uno mid-sweep. On the 9V battery, one test run froze the board after three sweeps with no clean reset. We attach the servo only while it moves, added a hardware watchdog so a freeze recovers in 2 seconds, and show a jam alert when a dispense doesn't answer.
- **The Arduino compiler on Apple Silicon.** The AVR toolchain `arduino-cli` downloads is an Intel binary (`bad CPU type in executable`) until Rosetta is installed.
- **A sensor that isn't there looks like an empty room.** If the ultrasonic sensor were unplugged, the machine would sleep forever. The Arduino now pings once at boot with a 4 m range and reports `nosensor` if nothing ever echoes. The laptop then stays awake.
- **Proving we don't save faces.** Saying it is easy. Our test runs a full session under Python audit hooks and fails if *anything* opens a file for writing or connects off the machine. We checked that it catches a plain write, a `numpy.save` and an outgoing socket.
- **Detector jitter vs. real motion.** Keypoints jitter about a pixel between frames, which is about as big as a small natural head movement. Smoothing over 3 frames helped, and blink detection covers the rest.
- **Rate-limited faucets.** The devnet faucet returned 429s, so we validated our hand-built transactions with devnet's `simulateTransaction` (signature verified) before funding the wallet from the web faucet.

## Accomplishments that we're proud of

- A privacy promise that's **enforced by tests**, down to what each sponsor API receives.
- Six cloud integrations that each **degrade gracefully**: pull any key and the machine keeps dispensing.
- Real, measured numbers: **62 ms per frame, 1.1 ms to decide, 4.87 s per dispense**.
- A donor ledger that proves impact publicly without putting a single student on chain.
- [___ students served / ___ items dispensed during testing.]

## What we learned

- Averaging embeddings over a short hold makes matching far more stable than trusting one frame.
- Hardware debugging is mostly power and cables.
- Deciding to fail open early made every other design choice simpler.
- Privacy is easier to build in than to bolt on. If the cloud only ever gets counts, there's nothing to leak.

## What's next

- Measure accuracy with many more people and publish the false match / missed match curve (`tune.py` already does the math).
- Multiple bays per machine, one servo each, and let students choose.
- Push restock alerts to staff phones from the forecast.
- Put the face model on a small on-device board so there's no laptop.
- Partner with a campus food pantry for a real pilot.

## Built with

arduino · c++ · python · insightface · onnxruntime · opencv · numpy · pyserial · fastapi · uvicorn · postgresql · timescaledb · tiger-data · snowflake · solana · gemini · elevenlabs · digitalocean · docker · html · javascript · pytest
