"""Kiosk state and daily counters behind GET /state and GET /stats. Holds no face data."""

import datetime
import threading

SLEEP = "sleep"  # nobody at the machine: the camera loop skips face processing entirely
IDLE = "idle"
SCANNING = "scanning"
DISPENSED = "dispensed"
ALREADY_SERVED = "already_served"
STATES = (SLEEP, IDLE, SCANNING, DISPENSED, ALREADY_SERVED)


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

    def _roll_day(self):
        today = datetime.date.today()
        if today != self._day:
            self._day = today
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

    def set_item(self, item):
        with self._lock:
            self._item = item

    def record_dispense(self, new_person):
        """Count one dispense. new_person is False for forced dispenses."""
        with self._lock:
            self._roll_day()
            self._dispensed_today += 1
            if new_person:
                self._unique_today += 1
            self._bay["remaining"] = max(0, self._bay["remaining"] - 1)
            return self._bay["remaining"]

    def restock(self):
        with self._lock:
            self._bay["remaining"] = self._bay["capacity"]

    def state_json(self):
        with self._lock:
            return {"state": self._state, "progress": round(self._progress, 3), "item": self._item}

    def stats_json(self):
        with self._lock:
            self._roll_day()
            return {
                "bays": [dict(self._bay)],
                "dispensed_today": self._dispensed_today,
                "unique_today": self._unique_today,
            }
