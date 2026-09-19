# Status

All 9 parts are done, and each one is committed and pushed. **90 tests pass** (`.venv/bin/pytest`), none needing hardware or keys.

## What works (tested)

- **Arduino (uploaded):** the new sketch is on the board. Servo attaches only while sweeping at 1°/10ms, green and red LEDs, sensor logic, watchdog. `d` → `ok` in **4.87 s**, 20/20 on the last two runs. One earlier run **froze the board after 3 sweeps** (power, most likely the 9V feeding the servo through the 5V pin). I added a watchdog that resets a frozen board within 2s, a longer 8s timeout on the laptop, and a jam alert on the dashboard.
- **Sleep / wake:** tested with fakes and the real board. The ultrasonic sensor isn't wired yet: the board reported `nosensor`, and the app correctly stayed awake. **`near` / `away` haven't been tested on real hardware.** While asleep, the camera loop does zero face detection (checked).
- **Kiosk sleep screen:** a pulsing slotted-disc logo on black, with a smooth fade into the scanner (checked in Chrome).
- **Dashboard:** machine stats, jam and low-stock alerts, insight, fleet, donor ledger with explorer links, and the "no names, faces, or images" line (checked in Chrome).
- **Tiger Data:** the new sink wrote to a real local TimescaleDB.
- **Snowflake:** the code is tested against a fake connection only.
- **Solana:** transactions were verified by the `solders` parser and devnet's simulator. `/ledger` reads real devnet. No real transaction was sent: the faucet rate-limited me.
- **Gemini:** tested with a fake transport.
- **ElevenLabs:** tested with a fake transport. The macOS `say` fallback voice is present.
- **Fleet API:** Docker image builds and serves `/fleet`, `/forecast` and `/ledger`.

## Needs a key (follow SETUP_KEYS.md, in order)

`GEMINI_API_KEY`, `ELEVENLABS_API_KEY` (coupon in HopHacks Discord #coupon-codes), `SOLANA_KEYPAIR_PATH` (+ fund it at faucet.solana.com, then `SOLANA_LEDGER_ADDRESSES`), `TIGER_DATABASE_URL`, the `SNOWFLAKE_*` six, and `doctl auth init` for DigitalOcean. Without them everything falls back, and the startup log lists what's off.

## Test first

1. **Wire the HC-SR04** (trig 3, echo 4, 5V, GND) and the LEDs (6, 7 through 220Ω), then run `.venv/bin/python vision/main.py --camera 0`. Walk up: the log should say "waking up". Walk away for 3s: "going to sleep".
2. **Do 10 real dispenses.** If you see "jam" alerts, the 9V is sagging: use a fresh battery, or give the servo a 4×AA pack with a shared ground.
3. **Add the Gemini and ElevenLabs keys first** (fastest). Restart, and the log should say "generated 12 ElevenLabs clips".
4. **Solana:** keypair → fund → press `r` → open the explorer link.
5. **Fill the [brackets] in DEVPOST.md** with real numbers.

## Notes

- `ui/mockserver.py` and `main.py` both use port 8000. Run one at a time.
- A throwaway devnet keypair from testing lives in my scratch folder, not the repo. Docker images `timescale/timescaledb:latest-pg17` and `dispenserve-fleet:test` are still on disk (`docker rmi` them if you need space).
