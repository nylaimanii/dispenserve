"""Anonymous fleet telemetry: the only per-event data that ever leaves the machine.

Each event is exactly {machine_id, bay, event, ts}. No vector, no image, no score, no
per-person id; emit() has no way to accept anything else. Every event fans out to every
enabled sink (Tiger Data, Snowflake), each with its own in-memory queue and background
thread (vision/sinks/base.py), so nothing here ever blocks the camera loop.
With no sink configured, events are only logged.
"""

import datetime
import logging

from sinks.base import BATCH_SIZE, FIELDS, FLUSH_INTERVAL_S, LogSink, SinkWorker

log = logging.getLogger("dispenserve.telemetry")

EVENTS = ("dispensed", "already_served", "restocked")
__all__ = ["EVENTS", "FIELDS", "Telemetry", "build_sinks"]


class Telemetry:
    def __init__(self, machine_id, sinks=None, batch_size=BATCH_SIZE, flush_interval=FLUSH_INTERVAL_S):
        self.machine_id = str(machine_id)
        sinks = list(sinks or [])
        if not sinks:
            sinks = [LogSink()]
        self.workers = [SinkWorker(s, batch_size=batch_size, flush_interval=flush_interval) for s in sinks]

    @property
    def sink_names(self):
        return [w.sink.name for w in self.workers]

    def emit(self, bay, event):
        """Queue one anonymous event for every sink. Returns the event dict, or None if invalid."""
        if event not in EVENTS or not isinstance(bay, str) or not bay or len(bay) > 64:
            log.warning("dropping invalid telemetry event %r for bay %r", event, bay)
            return None
        record = {
            "machine_id": self.machine_id,
            "bay": bay,
            "event": event,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }
        for worker in self.workers:
            worker.put(dict(record))
        return record

    def pending(self):
        return sum(w.pending() for w in self.workers)

    def close(self, timeout=5.0):
        for worker in self.workers:
            worker.close(timeout)


def build_sinks(env, disabled=()):
    """Every sink whose settings are present and that isn't turned off with --no-<name>.

    env: callable like config.env. Missing settings are logged, never fatal.
    """
    sinks = []
    if "tiger" in disabled:
        log.info("telemetry: Tiger Data off (--no-tiger)")
    elif env("TIGER_DATABASE_URL"):
        from sinks.tiger_sink import TigerSink

        sinks.append(TigerSink(env("TIGER_DATABASE_URL")))
        log.info("telemetry: → Tiger Data")
    else:
        log.info("telemetry: TIGER_DATABASE_URL not set, skipping Tiger Data")

    if "snowflake" in disabled:
        log.info("telemetry: Snowflake off (--no-snowflake)")
    else:
        from sinks.snowflake_sink import SnowflakeSink, settings_from_env

        settings, missing = settings_from_env(env)
        if missing:
            log.info("telemetry: skipping Snowflake, missing %s", ", ".join(missing))
        else:
            try:
                sinks.append(SnowflakeSink(settings))
                log.info("telemetry: → Snowflake")
            except ValueError as e:
                log.warning("telemetry: Snowflake misconfigured: %s", e)
    if not sinks:
        log.info("telemetry: no sinks configured, events are only logged")
    return sinks
