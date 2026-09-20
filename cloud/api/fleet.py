"""Fleet math: items left, today's counts, and run-out forecasts. Plain arithmetic, no AI.

Both data sources (Tiger Data and --fake) produce BayStats rows; everything the API
returns is computed here from those rows.
"""

import datetime
import math
from dataclasses import dataclass, field

LOW_ITEMS = 3  # matches the machine's own low-stock warning (vision/state.py)
LOW_HOURS = 4.0
ONLINE_MINUTES = 30  # machines only report on events, so "last seen" is the last event


@dataclass
class BayStats:
    machine_id: str
    bay: str
    last_restocked: datetime.datetime | None
    dispensed_since_restock: int
    dispensed_today: int
    dispensed_in_window: int  # dispenses in the last `window_hours` full hours


@dataclass
class MachineStats:
    machine_id: str
    last_seen: datetime.datetime
    bays: list = field(default_factory=list)


def iso(dt):
    return None if dt is None else dt.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")


def remaining(bay, capacity):
    return max(0, capacity - bay.dispensed_since_restock)


def build_fleet(machines, capacity, now):
    out = []
    for m in sorted(machines, key=lambda m: m.machine_id):
        minutes = (now - m.last_seen).total_seconds() / 60
        out.append(
            {
                "machine_id": m.machine_id,
                "last_seen": iso(m.last_seen),
                "minutes_since_seen": round(minutes, 1),
                "online": minutes <= ONLINE_MINUTES,
                "dispensed_today": sum(b.dispensed_today for b in m.bays),
                "bays": [
                    {
                        "name": b.bay,
                        "remaining": remaining(b, capacity),
                        "capacity": capacity,
                        "dispensed_today": b.dispensed_today,
                        "last_restocked": iso(b.last_restocked),
                    }
                    for b in sorted(m.bays, key=lambda b: b.bay)
                ],
            }
        )
    return out


def forecast_bay(bay, capacity, now, window_hours):
    """Run-out estimate from the recent dispense rate: remaining / (items per hour)."""
    left = remaining(bay, capacity)
    rate = bay.dispensed_in_window / window_hours if window_hours > 0 else 0.0
    if left == 0:
        hours_left, runs_out_at, status = 0.0, now, "empty"
    elif rate <= 0:
        hours_left, runs_out_at, status = None, None, "idle"
    else:
        hours_left = left / rate
        runs_out_at = now + datetime.timedelta(hours=hours_left)
        status = "low" if hours_left < LOW_HOURS or left <= LOW_ITEMS else "ok"
    return {
        "machine_id": bay.machine_id,
        "bay": bay.bay,
        "remaining": left,
        "capacity": capacity,
        "rate_per_hour": round(rate, 2),
        "window_hours": window_hours,
        "hours_left": None if hours_left is None else round(hours_left, 1),
        "runs_out_at": iso(runs_out_at),
        "status": status,
    }


def build_forecast(machines, capacity, now, window_hours):
    rows = [forecast_bay(b, capacity, now, window_hours) for m in machines for b in m.bays]
    # soonest to run out first; idle bays (no recent dispenses) last
    return sorted(rows, key=lambda r: (r["hours_left"] is None, r["hours_left"] if r["hours_left"] is not None else math.inf))
