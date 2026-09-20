# Status

All 9 parts are done, and each one is committed and pushed. **90 tests pass** (`.venv/bin/pytest`), none needing hardware or keys.

## What works (tested)

- **Arduino (uploaded):** the current sketch is on the board. Servo attaches only while sweeping (full 500-2500µs range, 1°/10ms), holds 600ms at the top and shakes 3× so the item drops free, green and red LEDs, sensor logic, watchdog. `d` → `ok` in **5.51 s**, and the last 21 dispenses all answered. One earlier run **froze the board after 3 sweeps** (power, most likely the 9V feeding the servo through the 5V pin). I added a watchdog that resets a frozen board within 2s, a longer 8s timeout on the laptop, and a jam alert on the dashboard.
- **Sleep / wake:** tested with fakes and the real board. The ultrasonic sensor isn't wired yet: the board reported `nosensor`, and the app correctly stayed awake. **`near` / `away` haven't been tested on real hardware.** While asleep, the camera loop does zero face detection (checked).
- **Kiosk sleep screen:** a pulsing slotted-disc logo on black, with a smooth fade into the scanner (checked in Chrome).
- **Dashboard:** machine stats, jam and low-stock alerts, insight, fleet, donor ledger with explorer links, and the "no names, faces, or images" line (checked in Chrome).
- **Tiger Data:** the new sink wrote to a real local TimescaleDB.
- **Snowflake:** the code is tested against a fake connection only.
- **Solana:** transactions were verified by the `solders` parser and devnet's simulator. `/ledger` reads real devnet. No real transaction was sent: the faucet rate-limited me.
- **Gemini: live and working** with a real key in `.env`. The dashboard's insight card shows the Gemini badge. Notes: `gemini-2.5-flash` is 404 for new keys ("no longer available to new users"), so leave `GEMINI_MODEL` unset and let it use `gemini-flash-latest`. One call came back 503 (transient overload), so a failed call now retries once after 2s before falling back to the estimate, with a 30s timeout for hotspot speeds. Expect the first `/insights` call to answer instantly with the estimate and switch to Gemini's text 10-15s later, then stay cached for 10 minutes.
- **ElevenLabs:** tested with a fake transport. The macOS `say` fallback voice is present.
- **Fleet API:** Docker image builds and serves `/fleet`, `/forecast` and `/ledger`.

## Needs a key (follow SETUP_KEYS.md, in order)

`ELEVENLABS_API_KEY` (coupon in HopHacks Discord #coupon-codes), `SOLANA_KEYPAIR_PATH` (+ fund it at faucet.solana.com, then `SOLANA_LEDGER_ADDRESSES`), `TIGER_DATABASE_URL`, the `SNOWFLAKE_*` six, and `doctl auth init` for DigitalOcean. Without them everything falls back, and the startup log lists what's off.

## Test first

1. **Wire the HC-SR04** (trig 3, echo 4, 5V, GND), then run `./start.sh` **without** `--no-sensor` (edit the script's last line) . Walk up: the log should say "waking up". Walk away for 3s: "going to sleep". LEDs on pins 6 and 7 can be checked any time by sending `g` (green blinks 3×) or `x` (red on 3s).
2. **Do 10 real dispenses.** If you see "jam" alerts, the 9V is sagging: use a fresh battery, or give the servo a 4×AA pack with a shared ground.
3. **Add the ElevenLabs key** (fastest one left). Restart, and the log should say "generated 12 ElevenLabs clips".
4. **Solana:** keypair → fund → press `r` → open the explorer link.
5. **Fill the [brackets] in DEVPOST.md** with real numbers.

## Running it

`./start.sh` is the one command: it checks port 8000, prints the iPad URL from this Mac's Wi-Fi address, and starts the app with `--no-sensor`. The USB webcam is `CAMERA_INDEX=0` in `.env` (the built-in camera is 1). Extra flags pass through, e.g. `./start.sh --no-camera`.

## Notes

- `ui/mockserver.py` and `main.py` both use port 8000. Run one at a time.
- A throwaway devnet keypair from testing lives in my scratch folder, not the repo. Docker images `timescale/timescaledb:latest-pg17` and `dispenserve-fleet:test` are still on disk (`docker rmi` them if you need space).
