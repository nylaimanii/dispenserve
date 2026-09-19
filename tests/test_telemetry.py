import datetime
import json
import time

import pytest

from sinks.base import CallbackSink, FIELDS
from sinks.snowflake_sink import SnowflakeSink, settings_from_env
from sinks.tiger_sink import TigerSink
from telemetry import EVENTS, Telemetry, build_sinks


def capture(**kw):
    sent = []
    return sent, Telemetry("m1", sinks=[CallbackSink(sent.extend)], flush_interval=0.05, **kw)


def test_invalid_events_are_dropped():
    sent, t = capture()
    assert t.emit("Kit Kat", "face_seen") is None
    assert t.emit("", "dispensed") is None
    assert t.emit(["not", "a", "bay"], "dispensed") is None
    t.close()
    assert sent == []


def test_emit_has_no_way_to_attach_extra_data():
    sent, t = capture()
    record = t.emit("Kit Kat", "dispensed")
    t.close()
    assert tuple(record) == FIELDS
    assert sent == [record]


def test_batches_flush_on_size_and_close():
    batches = []
    t = Telemetry("m1", sinks=[CallbackSink(batches.append)], batch_size=3, flush_interval=60)
    for _ in range(7):
        t.emit("Kit Kat", "dispensed")
    time.sleep(0.2)
    assert [len(b) for b in batches] == [3, 3]  # full batches go out without waiting
    t.close()
    assert sum(len(b) for b in batches) == 7  # close flushes the rest


def test_every_sink_gets_the_same_events():
    a, b = [], []
    t = Telemetry("m1", sinks=[CallbackSink(a.extend), CallbackSink(b.extend)], flush_interval=0.05)
    for e in EVENTS:
        t.emit("Kit Kat", e)
    t.close()
    assert a == b and len(a) == 3


def test_one_failing_sink_does_not_hold_up_another():
    good = []

    class Down(CallbackSink):
        name = "down"

        def send(self, batch):
            raise ConnectionError("unreachable")

    t = Telemetry("m1", sinks=[Down(None), CallbackSink(good.extend)], batch_size=1, flush_interval=0.05)
    t.emit("Kit Kat", "dispensed")
    time.sleep(0.3)
    assert len(good) == 1
    assert t.workers[0].pending() == 1  # kept for retry, not lost
    t.close(timeout=1)


def test_unreachable_database_never_blocks_emit():
    # port 1 on loopback refuses connections immediately
    t = Telemetry("m1", sinks=[TigerSink("postgresql://u:p@127.0.0.1:1/db")], batch_size=1, flush_interval=0.05)
    start = time.perf_counter()
    for _ in range(200):
        t.emit("Kit Kat", "dispensed")
    assert time.perf_counter() - start < 0.1
    time.sleep(0.3)
    assert t.pending() == 200  # kept for retry, in order
    t.close(timeout=1)


def test_no_sinks_just_logs(caplog):
    t = Telemetry("m1", flush_interval=0.05)
    with caplog.at_level("INFO", logger="dispenserve.telemetry"):
        t.emit("Kit Kat", "restocked")
        t.close()
    assert "not sent" in caplog.text


# --- Snowflake ---------------------------------------------------------------------


class FakeSnowflake:
    def __init__(self):
        self.statements = []

    def cursor(self):
        return self

    def executemany(self, sql, rows):
        self.statements.append((sql, rows))

    def close(self):
        pass


SETTINGS = {"account": "a", "user": "u", "password": "p", "warehouse": "w", "database": "d", "schema": "s", "table": "EVENTS"}


def test_snowflake_receives_only_the_four_anonymous_fields():
    conn = FakeSnowflake()
    t = Telemetry("m1", sinks=[SnowflakeSink(SETTINGS, connect=lambda: conn)], flush_interval=0.05)
    for e in EVENTS:
        t.emit("Kit Kat", e)
    t.close()
    [(sql, rows)] = conn.statements
    assert sql == "INSERT INTO EVENTS (MACHINE_ID, BAY, EVENT, TS) VALUES (%s, %s, %s, %s)"
    assert len(rows) == 3
    for machine_id, bay, event, ts in rows:
        assert (machine_id, bay) == ("m1", "Kit Kat") and event in EVENTS
        datetime.datetime.fromisoformat(ts)
    # nothing but short strings: no vectors, scores, images or ids
    assert all(isinstance(v, str) and len(v) <= 64 for row in rows for v in row)
    assert "score" not in json.dumps(rows) and "embedding" not in sql.lower()


def test_snowflake_settings_and_missing_keys():
    env = {"SNOWFLAKE_ACCOUNT": "acct", "SNOWFLAKE_USER": "me"}.get
    settings, missing = settings_from_env(lambda k, d=None: env(k) or d)
    assert missing == ["SNOWFLAKE_PASSWORD", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"]
    assert settings["table"] == "EVENTS"
    with pytest.raises(ValueError):
        SnowflakeSink({**SETTINGS, "table": "EVENTS; DROP TABLE X"})


def test_build_sinks_respects_keys_and_flags():
    full = {"TIGER_DATABASE_URL": "postgresql://x", **{f"SNOWFLAKE_{k.upper()}": v for k, v in SETTINGS.items()}}
    env = lambda k, d=None: full.get(k, d)  # noqa: E731
    assert [s.name for s in build_sinks(env)] == ["tiger", "snowflake"]
    assert [s.name for s in build_sinks(env, disabled={"tiger"})] == ["snowflake"]
    assert [s.name for s in build_sinks(env, disabled={"tiger", "snowflake"})] == []
    assert build_sinks(lambda k, d=None: d) == []
