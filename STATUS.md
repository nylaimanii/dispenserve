# Dispenserve — live status (checked, not guessed)

Every row below was verified by running it on demo morning. **98 tests pass.**

## 1. What works

| Piece | Status | Why |
|---|---|---|
| Arduino serial (`d` → `ok`) | **WORKS** | Replied `ok` in 5.51 s on the last check |
| Servo dispense (sweep, hold, 3 shakes) | **WORKS** | Same check; item drops free |
| Watchdog auto-reset | **WORKS** | On the board; added after one freeze |
| Camera + face match | **WORKS** | C270 opens at index 0, 1280×720; live scans matched 0.59–0.93 vs the 0.42 threshold |
| Kiosk page (iPad URL) | **WORKS** | HTTP 200 over the hotspot |
| Local dashboard `:8000` | **WORKS** | HTTP 200 |
| Vercel dashboard | **WORKS** | HTTP 200 (if it ever 404s, redeploy: see below) |
| Gemini insights | **WORKS** | Direct API call returns text; app falls back to arithmetic during Google 503s and retries after 60 s |
| ElevenLabs voice | **WORKS** | 12 cached mp3s in `vision/audio/` |
| Snowflake | **WORKS** | 5 rows in `EVENTS`, `DAILY_BAY_SUMMARY` shows 4 dispensed / 1 restock |
| Tiger Data | **WORKS** | Schema applied; 3 event rows; hourly continuous aggregate populated |
| Solana devnet | **WORKS** | Record written by the machine and read back: [tx](https://explorer.solana.com/tx/5evYbxdsuERUZMWZpXQu8LMiYswa5yVRzHaanUW8X9k4spcPcCCHCv2B87bwb5vdhmBZ8V9wfQjk3S66gPAapLiG?cluster=devnet) |
| DigitalOcean fleet API | **WORKS** | Deployed; `/health` reports `"source":"tiger"`, `/fleet` and `/ledger` return real data |
| Inventory + low-stock warning | **WORKS** | Capacity 20, decrements per dispense, warns at 3; seen live at 17/20 |
| 24h purge / no images on disk | **WORKS** | Audit-hook test passes; no image or vector file exists anywhere in the repo |
| Ultrasonic sleep/wake | **NOT SET UP** | Sensor not wired; board reports `nosensor`, machine stays awake (safe fallback) |
| Liveness anti-spoof | **PARTIAL** | Built and logging scores; never tested against a phone photo, so it stays log-only |

## 2. Prizes to submit for

**All eight are live:** Bloomberg philanthropy · Best overall · ElevenLabs · Gemini · Tiger Data · Snowflake · Solana · DigitalOcean.

**Don't mention:** the ultrasonic sleep/wake sensor (not wired) and the liveness check as a *working defence* (it only logs, and a phone photo was never tested). Describe liveness as "built, off by default" if it comes up.

## 3. Live URLs

| What | URL |
|---|---|
| Kiosk (iPad) | `http://172.20.10.2:8000/kiosk.html` — IP changes with the hotspot |
| Operator dashboard (laptop) | `http://172.20.10.2:8000/dashboard.html?fleet=https://dispenserve-fleet-6txue.ondigitalocean.app` |
| Public dashboard (judges) | https://dispenserve-dashboard.vercel.app |
| Fleet API (DigitalOcean) | https://dispenserve-fleet-6txue.ondigitalocean.app/fleet |
| Solana record | [explorer.solana.com/tx/5evYbx…](https://explorer.solana.com/tx/5evYbxdsuERUZMWZpXQu8LMiYswa5yVRzHaanUW8X9k4spcPcCCHCv2B87bwb5vdhmBZ8V9wfQjk3S66gPAapLiG?cluster=devnet) |

## 4. Morning startup

1. Arduino straight into the laptop (not a hub). Webcam in. 9V connected, disc at 0°.
2. Phone hotspot on; laptop **and** iPad joined to it.
3. `cd ~/dispenserve && ./start.sh` — it prints the new iPad URL.
4. On the iPad, open the printed URL. Add to Home Screen for full screen.
5. Scan once (dispense), step away, scan again (already served). Press `r` after refilling.
6. Optional fleet view: the dashboard URL above with `?fleet=https://dispenserve-fleet-6txue.ondigitalocean.app`.

**If something fails**
- Camera won't open → `./start.sh --camera 1`, or `./start.sh --no-camera` (scripted scans, kiosk and servo still run).
- Arduino missing → `./start.sh --no-serial`; everything runs, nothing drops.
- Voice too loud → `./start.sh --mute`.
- Vercel URL 404s → `./build_site.sh && npx vercel deploy --prod --yes --cwd dispenserve-dashboard`.
- No internet → kiosk and dashboard still work from the laptop; Gemini falls back to arithmetic, and cloud events queue and retry.

## 5. Video shots

**Shot 1 — the camera window (idle → recognized → already served)**
The window titled "dispenserve" opens with `./start.sh`. Film the screen: stand out of frame (idle), step in and hold still 3 s (ring fills, dispense, green LED), step away, then step back and hold again (already served, red LED). Record the iPad next to it for the kiosk view.

**Shot 2 — the box.** Yours to film.

**Shot 3 — the dashboard with real numbers.** Open `http://172.20.10.2:8000/dashboard.html?fleet=https://dispenserve-fleet-6txue.ondigitalocean.app`. It already has data: 3 dispenses are in Tiger Data and Snowflake, so the Fleet section and the hourly chart are populated. The "This machine" tiles start at 0 each time the app restarts and fill as you scan, so film this **after** shot 1.
