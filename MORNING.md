# Morning notes — overnight work

**Main was merged.** Everything below was verified after the merge. 102 tests pass.
**Roll back at any time:** `git checkout demo-safe` (tag pushed before any of this started).

## Kiosk fixes (the video problems)

- Headlines no longer smear: the sleep layer and the scanner never fade at the same time, and the headline block fades out, swaps words, fades back in. One headline on screen, always.
- The "time here" counter moved inside the ring, so it never sits on the headline.
- The grey dash in the middle of the ring is gone (it meant nothing). The tick on a dispense stays.
- Verified with Playwright at **1180×820 and 820×1180**, every state, English and Spanish: **no overlaps**. Screenshots in `docs/screenshots/`.

## What changed, per sponsor

| Sponsor | Change |
|---|---|
| **ElevenLabs** | Spanish added alongside English (30 cached clips), a spoken low-stock alert for volunteers, and an EN/ES toggle on the kiosk that switches the screen instantly and asks the laptop to switch the voice |
| **Gemini** | "Ask about this machine" box on the dashboard, answered from anonymous aggregates only; falls back to plain arithmetic if Gemini is down or rate-limited |
| **Tiger Data** | Hourly demand heatmap on the dashboard, drawn from the continuous aggregate, plus `/impact` computed in SQL over the hypertable |
| **Snowflake** | `IMPACT_DAILY` (people served, items, repeat visits turned away, restocks per day) and `DEMAND_FORECAST` (per-weekday average with 20% headroom) views, both live with real rows |
| **Solana** | "Verify on-chain" link in the new impact strip, pointing at the machine's devnet wallet |
| **DigitalOcean** | The fleet API now **serves the dashboard itself**, so judges open one URL with no query string, and the page talks to its own origin (no CORS, no mixed content). New `/impact` and `/ask` endpoints |
| **Bloomberg** | Impact strip at the top of the dashboard: people served today, people served all time, days the machine served someone, restocks by volunteers. Real numbers from the hypertable, nothing invented |

## Failed or skipped (and why)

- **Gemini hit its free-tier daily quota** at ~3am from overnight testing. The quota is *per model*, so I switched `GEMINI_MODEL` to `gemini-3.5-flash`, which has a fresh allowance; the insight card is live again. If it says "Estimate" during the demo, that's the fallback working, not a crash.
- **DigitalOcean per-machine heartbeat: skipped.** The laptop sits behind a phone hotspot and isn't reachable from the internet, so a heartbeat would have to be an outbound ping on a timer. "Last seen" already comes from the last real event, which is honest and needs no new event type. Not worth the risk this close to the demo.
- **Snowflake Cortex / ML forecast: skipped** in favour of plain SQL views. Cortex needs credits and a warehouse that may not be enabled on a trial account; the SQL version always works.
- **Liveness still untested against a phone photo**, so it stays log-only. Don't claim it as a working defence.
- **Ultrasonic sensor still not wired**; the board reports `nosensor` and the machine stays awake.

## Vercel 404, fixed and explained

The `dispenserve-dashboard.vercel.app` alias kept drifting off the newest production deployment, which is what produced the 404s. Every deploy now ends with an explicit `vercel alias set`, and it returns 200 with and without `?fleet=`. **If it 404s again**, one command fixes it:

```bash
./build_site.sh && npx vercel deploy --prod --yes --cwd dispenserve-dashboard
npx vercel alias set <the deployment url it prints> dispenserve-dashboard.vercel.app
```

Better still: the DigitalOcean URL now serves the same dashboard and has never drifted. Use it as the judge link.

## 60-second demo walkthrough (hits every sponsor)

1. **(0:00)** Walk up. Kiosk wakes, ring fills, item drops, voice says "here you go". → *ElevenLabs*
2. **(0:12)** Scan again: red light, "you've already got yours today." Tap **ES**, scan once more — the screen and the voice are both Spanish. → *ElevenLabs, accessibility*
3. **(0:25)** Point at the kiosk badge: *no photos, no names, forgets you in 24h*. → *the pitch*
4. **(0:32)** Open the dashboard. Impact strip: people served today and all time, restocks. → *Bloomberg*
5. **(0:40)** Hourly heatmap below it. "That's a Tiger Data continuous aggregate." → *Tiger Data*
6. **(0:46)** Type in the ask box: *"when should I restock tomorrow?"* → *Gemini*
7. **(0:52)** Click "Verify on-chain": a real devnet record of what this machine gave out. → *Solana*
8. **(0:57)** "Dashboard and API are one deploy on DigitalOcean, and the same events land in Snowflake for donor reporting." → *DigitalOcean, Snowflake*

## Morning startup

1. Arduino straight into the laptop (not a hub). Webcam in. 9V connected, disc at 0°.
2. Phone hotspot on; laptop **and** iPad joined. The IP changes on every reconnect.
3. `cd ~/dispenserve && ./start.sh` — it prints the iPad URL.
4. iPad: open that URL (Add to Home Screen for full screen).
5. Scan once (dispense), step away, scan again (already served). Press `r` after refilling.

**Live URLs**

| What | URL |
|---|---|
| Kiosk (iPad) | `http://<printed by start.sh>:8000/kiosk.html` |
| Judge dashboard (best link) | https://dispenserve-fleet-6txue.ondigitalocean.app/ |
| Same dashboard on Vercel | https://dispenserve-dashboard.vercel.app |
| Fleet API | https://dispenserve-fleet-6txue.ondigitalocean.app/fleet |
| Solana record | [explorer](https://explorer.solana.com/tx/5evYbxdsuERUZMWZpXQu8LMiYswa5yVRzHaanUW8X9k4spcPcCCHCv2B87bwb5vdhmBZ8V9wfQjk3S66gPAapLiG?cluster=devnet) |

**Fallbacks:** `./start.sh --camera 1` (built-in camera), `--no-camera` (scripted scans), `--no-serial` (no Arduino), `--mute` (silent).
