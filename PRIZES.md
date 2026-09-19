# Prize tracks

For each track: how Dispenserve uses it, and a 30 second demo script for a judge. Every demo assumes `vision/main.py` is running with the kiosk on the iPad and the dashboard open on the laptop.

## Bloomberg: Most Philanthropic Hack

Free food is one of the simplest ways to help students, and it fails in a predictable way: the first few people take everything, and the fix (swipe your ID, sign a sheet) keeps away exactly the students who most need help. Dispenserve makes a free-food table fair without asking anyone who they are. It's one item per person per day, the machine fails open so a bug never costs someone a meal, and no face ever leaves the laptop's RAM. On the donor side, every restock is published on a public ledger. A club, a department or an alum can see their money turn into snacks, and trust grows without turning students into data.

**Demo (30 s):**
1. "This is a free snack machine for students. No ID, no sign-up." Walk up; the kiosk wakes from its sleeping logo.
2. Hold still for 3 seconds. The item drops, the green light blinks, and the voice says "here you go."
3. Scan again. The red light comes on: "you've already got yours today." "One per person per day, and it still doesn't know who I am."
4. Point at the dashboard's lock line: "No names, faces, or images are ever stored. The face vector lives in RAM for 24 hours, then it's zeroed."
5. "Donors see every restock on a public ledger" (click one explorer link), "and no student is ever on it."

## Tiger Data

Every machine streams anonymous events (`{machine_id, bay, event, ts}`) into a TimescaleDB hypertable on Tiger Data. A continuous aggregate rolls up dispenses per bay per hour, and retention policies keep raw events for 30 days and the rollup for a year. The fleet API answers "what's running low across campus" with a couple of queries on the hypertable, and gets the recent dispense rate for the run-out forecast straight from the aggregate. A time-series database fits this well: the data is almost entirely `count(*)` over time buckets.

**Demo (30 s):**
1. Dispense one item: "that dispense just became one row in a Tiger Data hypertable."
2. Show `cloud/schema.sql`: the hypertable, the `dispensed_hourly` continuous aggregate with real-time mode on, and the two retention policies.
3. Open `/forecast`: "this run-out time is items left divided by the hourly rate from the continuous aggregate. It's plain math, and it updates the moment an event lands."
4. "Notice what the table doesn't have: no person, no face, no id. Just counts."

## DigitalOcean

The fleet API (FastAPI) is deployed on DigitalOcean App Platform from `.do/app.yaml` with one command (`doctl apps create --spec .do/app.yaml`). It rebuilds on every push to `main`, uses a health check on `/health`, and keeps secrets like the database URL out of the repo. It's the one place campus staff look: `/fleet` for stock and last-seen per machine, `/forecast` for run-out times, and `/ledger` for the donor record. With no database attached it serves clearly labeled demo data, so the deploy never shows an error page.

**Demo (30 s):**
1. Open the App Platform dashboard: "our fleet API, deployed from this spec file with one `doctl` command, redeploys on every push."
2. Open `https://<app>.ondigitalocean.app/fleet`: three machines, stock per bay, and one machine flagged offline.
3. Open the operator dashboard with `?fleet=<app url>`: "the dashboard reads the fleet from DigitalOcean. The forecast says student-union runs out of Kit Kats in [about 2.6 hours], so a staff member knows to go now."

## Snowflake

The same anonymous events are batched into Snowflake alongside Tiger Data, through one fan-out with no duplicated code. Each destination has its own background queue and retry. Tiger Data powers the live operational view; Snowflake is the analytics side for the people who fund and plan food programs. `cloud/snowflake_schema.sql` adds a `DAILY_BAY_SUMMARY` view (dispensed, repeat visits and restocks per machine, bay and day), which answers questions like "which building needs a second machine?" and "what do students actually take?"

**Demo (30 s):**
1. Dispense one item, then in a Snowflake worksheet run `SELECT * FROM EVENTS ORDER BY TS DESC LIMIT 5`: "there's the event, a few seconds later."
2. Run `SELECT * FROM DAILY_BAY_SUMMARY`: "per machine, per bay, per day. This is what a food program director plans with."
3. "Four columns, all anonymous. There's nothing in this warehouse about a student."

## Solana

Donor transparency without surveillance. Each restock (`{machine_id, date, bay, restocked_qty}`) and each day's total (`{machine_id, date, dispensed_total}`) is written to Solana devnet as a Memo-program transaction. We build and sign the transactions ourselves, verified against the `solders` parser and devnet's simulator. The fleet API's `/ledger` reads the records back straight from the chain with explorer links, so a donor doesn't have to trust us. The record builder only accepts plain integer counts and dates, so a face vector literally can't be written on chain.

**Demo (30 s):**
1. "A donor paid for 24 Kit Kats. Watch." Press `r` on the laptop to restock; the terminal prints an explorer link.
2. Open the link: a devnet transaction whose memo reads `dispenserve:{"bay":"Kit Kat","restocked_qty":24,...}`.
3. Show the dashboard's donor ledger: "every restock and every day's total, publicly verifiable, and not one student on chain."

## Gemini

`GET /insights` turns today's numbers into two sentences a staff member can act on, such as "Kit Kat is going at about 3 an hour and runs out around 2pm. Restock it before the lunch rush." Gemini only ever receives aggregates: items left per bay, dispenses per hour today, and today's unique count. The file opens with a comment saying individuals are never sent, and `tests/test_insights.py` checks the exact request. Answers are cached for 10 minutes and refreshed in the background, so a slow response never delays anything. Without a key, the same card shows the rule-based estimate.

**Demo (30 s):**
1. Point at the dashboard's Restock insight card with the Gemini badge: "this was written by Gemini from today's counts."
2. Open `vision/insights.py` at `aggregate_snapshot()`: "this is the entire input. Hourly counts, items left, one unique count. No faces, no people."
3. "If Gemini is down, the card falls back to plain math and says Estimate. The machine never waits on it."

## ElevenLabs

A machine that talks is friendlier than one that flashes, especially for someone being told "not today." Dispenserve has four moments (scanning, dispensed, already served, goodbye), each with three calm variations so it doesn't sound robotic. The lines are generated once with ElevenLabs and cached as mp3s. They're generic, the same for everyone, and `voice.say()` only accepts a line name, so nothing about a student can ever be spoken or sent. Playback is a background subprocess and never slows scanning. Without a key it falls back to macOS `say`.

**Demo (30 s):**
1. Walk up and hold still. "Hold still for a sec." The item drops: "Here you go, have a good one."
2. Scan again: "You've already got yours today. Come back tomorrow." "Notice how gentle that is. Being told no by a machine shouldn't feel bad."
3. Walk away: "See you tomorrow, thanks for stopping by."
4. Show `vision/audio/`: "twelve cached clips, generated once. ElevenLabs never hears about anyone."
