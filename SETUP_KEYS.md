# Setting up keys

Do these in order. Each one is optional: skip any and that feature falls back (the startup log says which). Paste values into `.env` at the repo root (`cp .env.example .env` first). `.env` is gitignored. Free tiers and coupons below were right when this was written; check each sponsor's hackathon page for current credits.

- [ ] **1. Gemini** (2 minutes)
  - Go to https://aistudio.google.com/apikey, sign in with Google, and click **Create API key**. The free tier is plenty for one request every 10 minutes.
  - `.env`: `GEMINI_API_KEY=...`
  - Check: run the app, then poll `http://localhost:8000/insights` for ~15s. The first call answers instantly with `"source": "rules"` while Gemini is asked in the background; once it answers, the source becomes `"gemini"`.
  - Leave `GEMINI_MODEL` unset. The default `gemini-flash-latest` works; `gemini-2.5-flash` is 404 for new keys ("no longer available to new users").

- [ ] **2. ElevenLabs** (3 minutes)
  - Sign up at https://elevenlabs.io. The coupon for extra credits is in the **HopHacks Discord, #coupon-codes**. The free tier alone covers our 12 lines (under 500 characters).
  - Profile (bottom left) → **API Keys** → create one. Give it text-to-speech access.
  - `.env`: `ELEVENLABS_API_KEY=...`
  - **Voice ids:** a free account can't use Voice Library voices through the API (`402 paid_plan_required`). The built-in ones work: Sarah `EXAVITQu4vr4xnSDxMaL` (the default), Lily `pFZP5JQG7iQjIQuC4Bku`, George `JBFqnCBsd6RMkjVDRZzb`, Adam `pNInz6obpgDQGcFmaJgB`. Set `ELEVENLABS_VOICE_ID` to switch; the clips regenerate on the next start.
  - The key only needs text-to-speech permission. A scoped key can't list voices or read the account, which is fine.
  - Check: start the app; the log says `generated 12 ElevenLabs clips` and `vision/audio/` fills with mp3s.

- [ ] **3. Solana devnet** (5 minutes, no account needed)
  - `.venv/bin/python vision/ledger.py --new-keypair ~/.config/dispenserve/devnet.json`
  - `.env`: `SOLANA_KEYPAIR_PATH=~/.config/dispenserve/devnet.json`
  - Fund it (devnet SOL is free and worthless): `.venv/bin/python vision/ledger.py --airdrop`. If that's rate-limited, go to https://faucet.solana.com, choose **devnet**, and paste the address that `--balance` prints.
  - `.env` (for the fleet API): `SOLANA_LEDGER_ADDRESSES=<that address>`
  - Check: run the app, press `r`, and open the explorer link it logs.

- [ ] **4. Tiger Data** (5 minutes)
  - Sign up at https://console.cloud.timescale.com (Tiger Cloud; there's a free trial). Create a service; the default settings are fine.
  - Copy the service's connection string (`postgres://tsdbadmin:...@...tsdb.cloud.timescale.com:.../tsdb?sslmode=require`).
  - `.env`: `TIGER_DATABASE_URL=...`
  - Create the tables once: `psql "$TIGER_DATABASE_URL" -f cloud/schema.sql` (install psql with `brew install libpq` if needed).
  - Check: dispense once. The log says `sent 1 events to tiger`.

- [ ] **5. Snowflake** (10 minutes)
  - Sign up for the free trial at https://signup.snowflake.com (30 days, with credits).
  - In a worksheet:
    ```sql
    CREATE WAREHOUSE IF NOT EXISTS DISPENSERVE_WH WAREHOUSE_SIZE = XSMALL AUTO_SUSPEND = 60;
    CREATE DATABASE IF NOT EXISTS DISPENSERVE;
    CREATE SCHEMA IF NOT EXISTS DISPENSERVE.TELEMETRY;
    USE SCHEMA DISPENSERVE.TELEMETRY;
    ```
    Then paste and run `cloud/snowflake_schema.sql`.
  - Account identifier: bottom-left menu → your account → **Copy account identifier**, then use the `orgname-accountname` form (dash, not dot).
  - `.env`: `SNOWFLAKE_ACCOUNT=orgname-accountname`, `SNOWFLAKE_USER=`, `SNOWFLAKE_PASSWORD=`, `SNOWFLAKE_WAREHOUSE=DISPENSERVE_WH`, `SNOWFLAKE_DATABASE=DISPENSERVE`, `SNOWFLAKE_SCHEMA=TELEMETRY`
  - If your account requires MFA for password logins, create a separate user for the machine, or expect a login prompt error in the log.
  - Check: dispense once, then `SELECT * FROM EVENTS` in the worksheet.

- [ ] **6. DigitalOcean** (10 minutes)
  - Sign up at https://cloud.digitalocean.com. New accounts and MLH hackathons usually come with free credits (check the MLH / hackathon sponsor page for the link).
  - `brew install doctl`, then API → **Generate New Token** (read + write), then `doctl auth init` and paste it.
  - The spec deploys from GitHub, so connect DigitalOcean to GitHub when it asks (Apps → Create → GitHub → authorize `nylaimanii/dispenserve`).
  - `doctl apps create --spec .do/app.yaml`
  - In the app's **Settings → Environment variables**, set `TIGER_DATABASE_URL` (as a secret) and `SOLANA_LEDGER_ADDRESSES`.
  - Check: open `https://<your-app>.ondigitalocean.app/fleet`, then open the dashboard with `?fleet=https://<your-app>.ondigitalocean.app`.

After all six, restart `vision/main.py`. Its first log lines list which integrations are on.
