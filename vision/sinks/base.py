"""Shared plumbing for telemetry sinks: one queue + background thread per sink.

A sink only implements send(batch) (raise on failure) and optionally close().
SinkWorker handles batching, flushing on a timer, retry with backoff, and dropping
the oldest events if a sink stays down, so no sink can ever block the camera loop.
"""

import logging
import threading
import time
from collections import deque

log = logging.getLogger("dispenserve.telemetry")

FIELDS = ("machine_id", "bay", "event", "ts")  # the only fields any sink ever receives
MAX_QUEUE = 10_000
BATCH_SIZE = 50
FLUSH_INTERVAL_S = 5.0
RETRY_BACKOFF_S = 30.0


class Sink:
    name = "sink"

    def send(self, batch):
        """batch: list of {machine_id, bay, event, ts} dicts. Raise on failure."""
        raise NotImplementedError

    def close(self):
        pass


class LogSink(Sink):
    """Used when no real sink is configured: events are only printed."""

    name = "log"

    def send(self, batch):
        for r in batch:
            log.info("telemetry (not sent): %s %s %s", r["bay"], r["event"], r["ts"])


class CallbackSink(Sink):
    """Hands batches to a function. Used by tests to see exactly what would leave."""

    name = "callback"

    def __init__(self, fn):
        self.fn = fn

    def send(self, batch):
        self.fn([dict(r) for r in batch])


class SinkWorker:
    def __init__(self, sink, batch_size=BATCH_SIZE, flush_interval=FLUSH_INTERVAL_S, retry_backoff=RETRY_BACKOFF_S):
        self.sink = sink
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.retry_backoff = retry_backoff
        self.sent = 0
        self._queue = deque(maxlen=MAX_QUEUE)
        self._cond = threading.Condition()
        self._closed = False
        self._retry_at = 0.0
        self._thread = threading.Thread(target=self._run, name=f"telemetry-{sink.name}", daemon=True)
        self._thread.start()

    def put(self, record):
        with self._cond:
            self._queue.append(record)
            if len(self._queue) >= self.batch_size:
                self._cond.notify()

    def pending(self):
        with self._cond:
            return len(self._queue)

    def close(self, timeout=5.0):
        with self._cond:
            self._closed = True
            self._cond.notify()
        self._thread.join(timeout)
        try:
            self.sink.close()
        except Exception:
            pass

    def _run(self):
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
                batch = [self._queue.popleft() for _ in range(min(self.batch_size, len(self._queue)))]
            if batch:
                try:
                    self.sink.send(batch)
                    self.sent += len(batch)
                    if not isinstance(self.sink, LogSink):
                        log.info("telemetry: sent %d events to %s", len(batch), self.sink.name)
                except Exception as e:
                    with self._cond:
                        self._queue.extendleft(reversed(batch))  # keep order, retry later
                        self._retry_at = time.monotonic() + self.retry_backoff
                    log.warning("telemetry: %s push failed, retrying in %.0fs: %s", self.sink.name, self.retry_backoff, e)
                    if closing:
                        log.warning("telemetry: %d events for %s not sent before exit", self.pending(), self.sink.name)
                        return
            if closing and self.pending() == 0:
                return
