"""Where fleet numbers come from: Tiger Data (Timescale Postgres), or generated fake data."""

import datetime
import hashlib
import math
import random

from fleet import BayStats, MachineStats

UTC = datetime.timezone.utc


def hour_floor(dt):
    return dt.replace(minute=0, second=0, microsecond=0)


class TigerSource:
    """Reads the events hypertable and the dispensed_hourly continuous aggregate."""

    name = "tiger"

    BAYS_SQL = """
        WITH bays AS (
            SELECT machine_id, bay, max(ts) AS last_seen,
                   max(ts) FILTER (WHERE event = 'restocked') AS last_restocked
            FROM events
            GROUP BY machine_id, bay
        )
        SELECT b.machine_id, b.bay, b.last_seen, b.last_restocked,
               (SELECT count(*) FROM events e
                 WHERE e.machine_id = b.machine_id AND e.bay = b.bay AND e.event = 'dispensed'
                   AND e.ts > coalesce(b.last_restocked, '-infinity')) AS since_restock,
               (SELECT count(*) FROM events e
                 WHERE e.machine_id = b.machine_id AND e.bay = b.bay AND e.event = 'dispensed'
                   AND e.ts >= %(today_start)s) AS today
        FROM bays b
    """

    HOURLY_SQL = """
        SELECT bucket, machine_id, bay, sum(dispensed)::int
        FROM dispensed_hourly
        WHERE bucket >= %(from_hour)s
        GROUP BY bucket, machine_id, bay
        ORDER BY bucket
    """

    WINDOW_SQL = """
        SELECT machine_id, bay, sum(dispensed)::int
        FROM dispensed_hourly
        WHERE bucket >= %(window_start)s AND bucket < %(window_end)s
        GROUP BY machine_id, bay
    """

    def __init__(self, database_url):
        self.database_url = database_url

    def machines(self, now, today_start, window_hours):
        import psycopg

        window_end = hour_floor(now)
        params = {
            "today_start": today_start,
            "window_start": window_end - datetime.timedelta(hours=window_hours),
            "window_end": window_end,
        }
        with psycopg.connect(self.database_url, connect_timeout=5) as conn:
            bay_rows = conn.execute(self.BAYS_SQL, params).fetchall()
            window = {(m, b): n for m, b, n in conn.execute(self.WINDOW_SQL, params).fetchall()}

        machines = {}
        for machine_id, bay, last_seen, last_restocked, since_restock, today in bay_rows:
            m = machines.setdefault(machine_id, MachineStats(machine_id, last_seen))
            m.last_seen = max(m.last_seen, last_seen)
            m.bays.append(BayStats(machine_id, bay, last_restocked, since_restock, today, window.get((machine_id, bay), 0)))
        return list(machines.values())


    IMPACT_SQL = """
        SELECT
            count(*) FILTER (WHERE event = 'dispensed')                          AS items_all_time,
            count(*) FILTER (WHERE event = 'dispensed' AND ts >= %(today)s)      AS items_today,
            count(*) FILTER (WHERE event = 'already_served')                     AS repeat_visits,
            count(*) FILTER (WHERE event = 'restocked')                          AS restocks,
            count(DISTINCT machine_id)                                           AS machines,
            count(DISTINCT date_trunc('day', ts)) FILTER (WHERE event = 'dispensed') AS days_serving,
            min(ts)                                                              AS first_event
        FROM events
    """

    def impact(self, now, today_start):
        import psycopg

        with psycopg.connect(self.database_url, connect_timeout=5) as conn:
            row = conn.execute(self.IMPACT_SQL, {"today": today_start}).fetchone()
        items_all, items_today, repeats, restocks, machines, days, first = row
        return {
            "items_today": items_today, "items_all_time": items_all,
            "people_today": items_today,          # one item per person per day, so these are the same
            "people_all_time": items_all,
            "repeat_visits_turned_away": repeats, "restocks": restocks,
            "machines": machines, "days_serving": days,
            "first_event": None if first is None else first.astimezone(UTC).isoformat(timespec="seconds"),
        }

    def hourly(self, now, hours):
        import psycopg

        from_hour = hour_floor(now) - datetime.timedelta(hours=hours - 1)
        with psycopg.connect(self.database_url, connect_timeout=5) as conn:
            rows = conn.execute(self.HOURLY_SQL, {"from_hour": from_hour}).fetchall()
        return [{"hour": b.astimezone(UTC).isoformat(timespec="minutes"), "machine_id": m, "bay": bay, "dispensed": n}
                for b, m, bay, n in rows]


class FakeSource:
    """Three made-up campus machines with believable, stable numbers.

    Hourly dispense counts are seeded by (machine, bay, hour), so refreshing the page
    gives the same history and the numbers only move as real time passes.
    """

    name = "fake"

    MACHINES = {
        # machine_id: (bays, busyness, minutes since last seen)
        "library-2f": (["Kit Kat", "Granola Bar"], 1.0, 1),
        "student-union": (["Kit Kat", "Pretzels", "Fruit Snacks"], 1.6, 3),
        "rec-center": (["Protein Bar"], 0.6, 95),  # quiet and stale, so the dashboard has something to flag
    }
    RESTOCK_HOURS_AGO = {"Kit Kat": 6, "Granola Bar": 11, "Pretzels": 3, "Fruit Snacks": 8, "Protein Bar": 14}
    HISTORY_HOURS = 48

    def __init__(self, capacity):
        self.capacity = capacity

    @staticmethod
    def _hourly_rate(hour_utc, busyness):
        # campus day: quiet overnight, lunch and afternoon peaks (in UTC-4 local time)
        local = (hour_utc - 4) % 24
        base = 0.5 if local < 8 or local >= 22 else 1.2 + 1.3 * math.exp(-((local - 12.5) ** 2) / 4) + 0.8 * math.exp(-((local - 16) ** 2) / 3)
        return base * busyness

    def _count(self, machine_id, bay, hour_start, busyness):
        seed = int(hashlib.sha256(f"{machine_id}|{bay}|{hour_start.isoformat()}".encode()).hexdigest()[:12], 16)
        rng = random.Random(seed)
        lam = self._hourly_rate(hour_start.hour, busyness)
        # Poisson draw by inversion
        k, p, threshold = 0, 1.0, math.exp(-lam)
        while True:
            p *= rng.random()
            if p <= threshold:
                return k
            k += 1

    def impact(self, now, today_start):
        machines = self.machines(now, today_start, 3)
        today = sum(b.dispensed_today for m in machines for b in m.bays)
        hourly = self.hourly(now, self.HISTORY_HOURS)
        all_time = sum(b["dispensed"] for b in hourly)
        return {
            "items_today": today, "items_all_time": all_time,
            "people_today": today, "people_all_time": all_time,
            "repeat_visits_turned_away": round(all_time * 0.22), "restocks": len(self.RESTOCK_HOURS_AGO),
            "machines": len(self.MACHINES), "days_serving": 2,
            "first_event": (now - datetime.timedelta(hours=self.HISTORY_HOURS)).isoformat(timespec="seconds"),
        }

    def hourly(self, now, hours):
        current_hour = hour_floor(now)
        out = []
        for machine_id, (bays, busyness, _) in self.MACHINES.items():
            for bay in bays:
                for h in range(hours - 1, -1, -1):
                    hour_start = current_hour - datetime.timedelta(hours=h)
                    n = self._count(machine_id, bay, hour_start, busyness)
                    if h == 0:
                        n = round(n * (now - hour_start).total_seconds() / 3600)
                    out.append({"hour": hour_start.isoformat(timespec="minutes"), "machine_id": machine_id, "bay": bay, "dispensed": n})
        return out

    def machines(self, now, today_start, window_hours):
        current_hour = hour_floor(now)
        out = []
        for machine_id, (bays, busyness, minutes_ago) in self.MACHINES.items():
            m = MachineStats(machine_id, now - datetime.timedelta(minutes=minutes_ago))
            for bay in bays:
                restocked = current_hour - datetime.timedelta(hours=self.RESTOCK_HOURS_AGO[bay])
                since_restock = today = in_window = 0
                for h in range(self.HISTORY_HOURS, -1, -1):
                    hour_start = current_hour - datetime.timedelta(hours=h)
                    n = self._count(machine_id, bay, hour_start, busyness)
                    if h == 0:  # the current hour only counts the part that has happened
                        n = round(n * (now - hour_start).total_seconds() / 3600)
                    if hour_start >= restocked:
                        n = min(n, self.capacity - since_restock)  # an empty bay can't dispense
                        since_restock += n
                    if hour_start >= hour_floor(today_start):
                        today += n
                    if 1 <= h <= window_hours:
                        in_window += n
                m.bays.append(BayStats(machine_id, bay, restocked, since_restock, today, in_window))
            out.append(m)
        return out
