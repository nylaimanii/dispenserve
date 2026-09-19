import time

from telemetry import FIELDS, Telemetry


def test_invalid_events_are_dropped():
    sent = []
    t = Telemetry("m1", sink=sent.extend, flush_interval=0.05)
    assert t.emit("Kit Kat", "face_seen") is None
    assert t.emit("", "dispensed") is None
    assert t.emit(["not", "a", "bay"], "dispensed") is None
    t.close()
    assert sent == []


def test_emit_has_no_way_to_attach_extra_data():
    sent = []
    t = Telemetry("m1", sink=sent.extend, flush_interval=0.05)
    record = t.emit("Kit Kat", "dispensed")
    t.close()
    assert tuple(record) == FIELDS
    assert sent == [record]


def test_batches_flush_on_size_and_close():
    batches = []
    t = Telemetry("m1", sink=batches.append, batch_size=3, flush_interval=60)
    for _ in range(7):
        t.emit("Kit Kat", "dispensed")
    time.sleep(0.2)
    assert [len(b) for b in batches] == [3, 3]  # full batches go out without waiting
    t.close()
    assert sum(len(b) for b in batches) == 7  # close flushes the rest


def test_unreachable_database_never_blocks_emit():
    # port 1 on loopback refuses connections immediately
    t = Telemetry("m1", database_url="postgresql://u:p@127.0.0.1:1/db", batch_size=1, flush_interval=0.05)
    start = time.perf_counter()
    for _ in range(200):
        t.emit("Kit Kat", "dispensed")
    assert time.perf_counter() - start < 0.1
    time.sleep(0.3)
    assert t.pending() == 200  # kept for retry, in order, not lost
    t.close(timeout=1)


def test_no_database_url_just_logs(caplog):
    t = Telemetry("m1", flush_interval=0.05)
    with caplog.at_level("INFO", logger="dispenserve.telemetry"):
        t.emit("Kit Kat", "restocked")
        t.close()
    assert "not sent" in caplog.text
