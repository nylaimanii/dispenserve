# Status

All parts built, committed and pushed. **98 tests pass** (`.venv/bin/pytest`), no hardware or keys needed.

## Live right now

- **Machine:** `./start.sh` runs the camera loop (C270 on `CAMERA_INDEX=0`), kiosk + dashboard server on port 8000, Arduino connected. Sleep/wake is off (`--no-sensor`) until the HC-SR04 is wired.
- **Kiosk:** camera-free by design. Geometric node/line field that reacts to presence, glowing ring, "time here" counter, burst on dispense, calm amber for already-served, privacy badge in the corner.
- **Dashboard:** operator console with inventory bars, dispensed today, per-hour chart, run-out forecast, fleet list, donor ledger and the Gemini insight. Works locally from `/stats` or as a static site against the public fleet API.
- **Inventory:** capacity 20, low-stock warning at 3, `remaining` / `dispensed_today` / `dispensed_per_hour` on `/stats`. `r` restocks to full and emits a `restocked` event.
- **Gemini:** live. First `/insights` call answers instantly with the estimate, Gemini text follows ~10-15s later, cached 10 min. A failed call now retries after 60s instead of holding the estimate for the full cache.
- **ElevenLabs:** live, 12 clips cached in `vision/audio/` (voice "Sarah"). Library voices need a paid plan; built-in voices work.
- **Snowflake:** live. `EVENTS` table and `DAILY_BAY_SUMMARY` view created, and real events verified landing in both.

## Blocked, and exactly what unblocks each

- **Tiger Data: password rejected.** `FATAL: password authentication failed for user "tsdbadmin"`, with the URL parsed correctly (13-char password). Reset the service password in the Tiger console and update `TIGER_DATABASE_URL` in `.env`. Telemetry queues and retries meanwhile, so nothing breaks. Then run `cloud/schema.sql` once.
- **Solana: wallet created, no funds.** `AmEVPvxvZx4PgJCSjZtSEhU3PT9xCfbgNKqzEN1A9xFN` (keypair at `~/.config/solana/dispenserve.json`). The public faucet rate-limited every airdrop (429). Fund it at https://faucet.solana.com (devnet, paste the address), then press `r` and the restock writes on chain.
- **Vercel: deployed but private.** https://dispenserve-dashboard.vercel.app returns 404/302 because Deployment Protection is on. Vercel project → Settings → Deployment Protection → turn off Vercel Authentication, then redeploy with `./build_site.sh && npx vercel deploy --prod --cwd dispenserve-dashboard`.
- **DigitalOcean: waiting on the token.** Then `doctl auth init`, `doctl apps create --spec .do/app.yaml`, and set `TIGER_DATABASE_URL` + `SOLANA_LEDGER_ADDRESSES` in the app's settings.

## Test first

1. `./start.sh`, open the kiosk on the iPad, and do a real scan: dispense, then scan again for already-served.
2. Watch the dashboard chart fill as you dispense, and check the low-stock warning at 3 left.
3. Wire the HC-SR04 (trig 3, echo 4) and drop `--no-sensor` from the last line of `start.sh` for sleep/wake.
4. Fill the [brackets] in DEVPOST.md with real numbers.

## Notes

- Keys live in `.env` (gitignored, chmod 600): Gemini, ElevenLabs, Tiger, Snowflake, Solana keypair path. Rotate them after the hackathon, since several were pasted in chat.
- `ui/mockserver.py` and `main.py` both want port 8000. Run one at a time.
