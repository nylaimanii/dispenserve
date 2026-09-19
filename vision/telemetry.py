"""Anonymous fleet telemetry: the only data that ever leaves the machine.

Each event is exactly {machine_id, bay, event, ts}. No vector, no image, no score, no
per-person id; emit() has no way to accept anything else. Events queue in memory and a
background thread pushes them in batches to TIGER_DATABASE_URL (Tiger Data / Timescale
Postgres). Without a URL they're only logged. Nothing here ever blocks the camera loop:
emit() is an append, and when the queue is full the oldest events are dropped.
"""

import datetime
import logging
import threading
import time
from collections import deque

log = logging.getLogger("dispenserve.telemetry")

EVENTS = ("dispensed", "already_served", "restocked")
FIELDS = ("machine_id", "bay", "event", "ts")
MAX_QUEUE = 10_000
BATCH_SIZE = 50
FLUSH_INTERVAL_S = 5.0
RETRY_BACKOFF_S = 30.0
INSERT_SQL = "INSERT INTO events (machine_id, bay, event, ts) VALUES (%s, %s, %s, %s)"


class Telemetry:
    def __init__(self, machine_id, database_url=None, sink=None, batch_size=BATCH_SIZE, flush_interval=FLUSH_INTERVAL_S):
        """sink: optional callable(list[dict]) that replaces the database (used by tests)."""
        self.machine_id = str(machine_id)
        self.database_url = database_url
        self.sink = sink
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._queue = deque(maxlen=MAX_QUEUE)
        self._cond = threading.Condition()
        self._closed = False
        self._conn = None
        self._retry_at = 0.0
        self.sent = 0
        if database_url:
            log.info("telemetry → Tiger Data as machine %r", self.machine_id)
        elif sink is None:
            log.info("telemetry: TIGER_DATABASE_URL not set, events are only logged")
        self._thread = threading.Thread(target=self._worker, name="telemetry", daemon=True)
        self._thread.start()

    def emit(self, bay, event):
        """Queue one anonymous event. Returns the event dict, or None if it was invalid."""
        if event not in EVENTS or not isinstance(bay, str) or not bay or len(bay) > 64:
            log.warning("dropping invalid telemetry event %r for bay %r", event, bay)
            return None
        record = {
            "machine_id": self.machine_id,
            "bay": bay,
            "event": event,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }
        with self._cond:
            self._queue.append(record)
            if len(self._queue) >= self.batch_size:
                self._cond.notify()
        return record

    def close(self, timeout=5.0):
        """Try to flush what's queued, then stop."""
        with self._cond:
            self._closed = True
            self._cond.notify()
        self._thread.join(timeout)
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass

    def pending(self):
        with self._cond:
            return len(self._queue)

    # --- background ------------------------------------------------------------

    def _worker(self):
        while True:
            with self._cond:
                if not self._closed:
                    backoff = self._retry_at - time.monotonic()
                    if backoff > 0:
                        self._cond.wait(backoff)
                        continue
                    if len(self._queue) < self.batch_size:
                        self._cond.wait(self.flush_interval)
                closing = self._closed
                batch =[self._queue.popleft() for _ in range(min(self.batch_size, len(self._queue)))]
            if batch and not self._send(batch):
                with self._cond:
                    self._queue.extendleft(reversed(batch))  # keep order, retry later
                    self._retry_at = time.monotonic() + RETRY_BACKOFF_S
                if closing:
                    log.warning("telemetry: %d events not sent before exit", self.pending())
                    return
            if closing and self.pending() == 0:
                return

    def _send(self, batch):
        if self.sink is not None:
            self.sink([dict(r) for r in batch])
            self.sent += len(batch)
            return True
        if not self.database_url:
            for r in batch:
                log.info("telemetry (not sent): %s %s %s", r["bay"], r["event"], r["ts"])
            return True
        try:
            if self._conn is None or self._conn.closed:
                import psycopg

                self._conn = psycopg.connect(self.database_url, connect_timeout=5, autocommit=True)
            with self._conn.cursor() as cur:
                cur.executemany(INSERT_SQL, [tuple(r[f] for f in FIELDS) for r in batch])
            self.sent += len(batch)
            log.info("telemetry: sent %d events", len(batch))
            return True
        except Exception as e:
            log.warning("telemetry push failed, will retry in %.0fs: %s", RETRY_BACKOFF_S, e)
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return False
