"""dispenserve fleet API: what's running low across every machine on campus.

Reads only anonymous events ({machine_id, bay, event, ts}) from Tiger Data. There is
nothing about people in the database, so there is nothing about people to serve.

    GET /fleet     every machine: items left per bay, dispensed today, last seen
    GET /forecast  per bay: estimated run-out time from the last few hours' dispense rate
    GET /ledger    public donor ledger: restocks and daily totals from Solana devnet memos
    GET /health

Run:
    python app.py --fake              # generated data for 3 machines, no database needed
    python app.py                     # reads TIGER_DATABASE_URL (falls back to fake if unset)
    uvicorn app:app --port 8080       # same, as an ASGI app (FLEET_FAKE=1 forces fake data)
"""

import argparse
import datetime
import logging
import os
import zoneinfo
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from fleet import build_fleet, build_forecast
from ledger_reader import DEVNET_RPC, LedgerReader, example_records
from sources import FakeSource, TigerSource

log = logging.getLogger("fleet")


def load_dotenv():
    """Reads KEY=VALUE lines from the repo's gitignored .env, if there is one."""
    here = Path(__file__).resolve()
    repo_root = here.parents[2] if len(here.parents) > 2 else here.parent  # in Docker it's just /app
    for path in (repo_root / ".env", Path.cwd() / ".env"):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip().removeprefix("export ").strip(), value.strip().strip("\"'"))
        return


def settings():
    load_dotenv()
    return {
        "database_url": os.environ.get("TIGER_DATABASE_URL", "").strip() or None,
        "fake": os.environ.get("FLEET_FAKE", "").strip().lower() in ("1", "true", "yes"),
        "capacity": int(os.environ.get("BAY_CAPACITY", "24")),
        "window_hours": int(os.environ.get("FORECAST_WINDOW_HOURS", "3")),
        "timezone": os.environ.get("FLEET_TZ", "UTC"),
        "ledger_addresses": [a for a in os.environ.get("SOLANA_LEDGER_ADDRESSES", "").split(",") if a.strip()],
        "solana_rpc": os.environ.get("SOLANA_RPC_URL", "").strip() or DEVNET_RPC,
    }


def create_app(fake=None):
    cfg = settings()
    use_fake = cfg["fake"] if fake is None else fake
    if not use_fake and not cfg["database_url"]:
        log.warning("TIGER_DATABASE_URL not set, serving fake data")
        use_fake = True
    source = FakeSource(cfg["capacity"]) if use_fake else TigerSource(cfg["database_url"])
    tz = zoneinfo.ZoneInfo(cfg["timezone"])
    ledger = LedgerReader(cfg["ledger_addresses"], cfg["solana_rpc"]) if cfg["ledger_addresses"] else None

    app = FastAPI(title="dispenserve fleet", description="Anonymous inventory telemetry for dispenserve machines.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

    def load():
        now = datetime.datetime.now(datetime.timezone.utc)
        today_start = datetime.datetime.combine(now.astimezone(tz).date(), datetime.time(), tz)
        return now, source.machines(now, today_start, cfg["window_hours"])

    def unavailable(e):
        log.exception("database query failed")
        return JSONResponse({"error": "database unavailable", "detail": type(e).__name__}, status_code=503)

    @app.get("/health")
    def health():
        return {"ok": True, "source": source.name}

    @app.get("/fleet")
    def fleet():
        try:
            now, machines = load()
        except Exception as e:
            return unavailable(e)
        return {"generated_at": now.isoformat(timespec="seconds"), "source": source.name, "machines": build_fleet(machines, cfg["capacity"], now)}

    @app.get("/forecast")
    def forecast():
        try:
            now, machines = load()
        except Exception as e:
            return unavailable(e)
        return {
            "generated_at": now.isoformat(timespec="seconds"),
            "source": source.name,
            "window_hours": cfg["window_hours"],
            "bays": build_forecast(machines, cfg["capacity"], now, cfg["window_hours"]),
        }

    @app.get("/ledger")
    def ledger_records():
        now = datetime.datetime.now(datetime.timezone.utc)
        if ledger is not None:
            try:
                records = ledger.records()
            except Exception as e:
                log.exception("solana query failed")
                return JSONResponse({"error": "solana unavailable", "detail": type(e).__name__}, status_code=503)
            return {"generated_at": now.isoformat(timespec="seconds"), "source": "solana-devnet", "addresses": ledger.addresses, "records": records}
        if use_fake:
            return {"generated_at": now.isoformat(timespec="seconds"), "source": "example", "records": example_records(now.date()),
                    "note": "example records; set SOLANA_LEDGER_ADDRESSES to read the real devnet ledger"}
        return {"generated_at": now.isoformat(timespec="seconds"), "source": "none", "records": [],
                "note": "set SOLANA_LEDGER_ADDRESSES to the machines' devnet wallet addresses"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="dispenserve fleet API")
    parser.add_argument("--fake", action="store_true", help="serve generated data for 3 machines")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(fake=True if args.fake else None), host=args.host, port=args.port)
