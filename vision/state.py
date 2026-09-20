"""Kiosk state and daily counters behind GET /state and GET /stats. Holds no face data."""

import datetime
import threading
import time

SLEEP = "sleep"  # nobody at the machine: the camera loop skips face processing entirely
IDLE = "idle"
SCANNING = "scanning"
DISPENSED = "dispensed"
ALREADY_SERVED = "already_served"
STATES = (SLEEP, IDLE, SCANNING, DISPENSED, ALREADY_SERVED)
LOW_STOCK = 3  # warn the operator at this many items left


class AppState:
    def __init__(self, bay_name, capacity, remaining=None):
        self._lock = threading.Lock()
        self._state = IDLE
        self._progress = 0.0
        self._item = bay_name
        self._bay = {"name": bay_name, "remaining": capacity if remaining is None else remaining, "capacity": capacity}
        self._day = datetime.date.today()
        self._dispensed_today = 0
        self._unique_today = 0
        self._closed_days = []  # (date, dispensed_total) for days that ended while running
        self._hourly = [0] * 24  # dispensed per local hour, today
        self._present = False    # someone is standing at the machine (face in frame, or the sensor)
        self._present_since = None

    def _roll_day(self):
        today = datetime.date.today()
        if today != self._day:
            self._closed_days.append((self._day, self._dispensed_today))
            self._day = today
            self._hourly = [0] * 24
            self._dispensed_today = 0
            self._unique_today = 0

    @property
    def bay_name(self):
        return self._bay["name"]

    @property
    def state(self):
        with self._lock:
            return self._state

    def set_state(self, state, progress=None):
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        with self._lock:
            self._state = state
            if progress is not None:
                self._progress = max(0.0, min(1.0, float(progress)))

    def set_progress(self, progress):
        with self._lock:
            self._progress = max(0.0, min(1.0, float(progress)))

    def set_presence(self, present):
        """Someone is at the machine. Drives the kiosk's ambient glow and "time here" counter."""
        with self._lock:
            if present and not self._present:
                self._present_since = time.monotonic()
            elif not present:
                self._present_since = None
            self._present = bool(present)

    def present_for(self):
        with self._lock:
            return 0.0 if self._present_since is None else time.monotonic() - self._present_since

    def set_item(self, item):
        with self._lock:
            self._item = item

    def record_dispense(self, new_person):
        """Count one dispense. new_person is False for forced dispenses."""
        with self._lock:
            self._roll_day()
            self._dispensed_today += 1
            self._hourly[datetime.datetime.now().hour] += 1
            if new_person:
                self._unique_today += 1
            self._bay["remaining"] = max(0, self._bay["remaining"] - 1)
            return self._bay["remaining"]

    def restock(self):
        """Refill to capacity. Returns how many items were added."""
        with self._lock:
            added = self._bay["capacity"] - self._bay["remaining"]
            self._bay["remaining"] = self._bay["capacity"]
            return added

    def hourly_today(self):
        """{hour: dispensed} for every hour of today so far."""
        with self._lock:
            self._roll_day()
            now_hour = datetime.datetime.now().hour
            return {h: self._hourly[h] for h in range(now_hour + 1)}

    def today(self):
        """(date, dispensed so far today)"""
        with self._lock:
            self._roll_day()
            return self._day, self._dispensed_today

    def pop_closed_days(self):
        """Days that ended since the last call, as (date, dispensed_total)."""
        with self._lock:
            self._roll_day()
            days, self._closed_days = self._closed_days, []
            return days

    def state_json(self):
        with self._lock:
            present_for = 0.0 if self._present_since is None else time.monotonic() - self._present_since
            return {
                "state": self._state,
                "progress": round(self._progress, 3),
                "item": self._item,
                "present": self._present,
                "present_for": round(present_for, 1),
            }

    def stats_json(self):
        with self._lock:
            self._roll_day()
            bay = dict(self._bay)
            bay["low"] = bay["remaining"] <= LOW_STOCK
            now_hour = datetime.datetime.now().hour
            return {
                "bays": [bay],
                "dispensed_today": self._dispensed_today,
                "unique_today": self._unique_today,
                "low_stock": bay["low"],
                "dispensed_per_hour": {f"{h:02d}:00": self._hourly[h] for h in range(now_hour + 1)},
            }
