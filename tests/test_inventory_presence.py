import sys
import warnings
from pathlib import Path

from main import Dispenserve
from memory import MemoryStore
from serial_link import Dispenser
from state import LOW_STOCK, AppState

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud" / "api"))


def app(capacity=20):
    return Dispenserve(MemoryStore(), AppState("Kit Kat", capacity), Dispenser(enabled=False), result_seconds=0)


def test_stats_expose_remaining_dispensed_and_low_flag(person):
    a = app()
    [bay] = a.stats_json()["bays"]
    assert (bay["remaining"], bay["capacity"], bay["low"]) == (20, 20, False)
    for _ in range(17):
        a.complete_scan([person()])
    stats = a.stats_json()
    assert stats["dispensed_today"] == 17
    assert stats["bays"][0]["remaining"] == 3 == LOW_STOCK
    assert stats["bays"][0]["low"] and stats["low_stock"]  # warning at 3


def test_restock_refills_to_capacity_and_reports_how_many(person):
    a = app()
    for _ in range(6):
        a.complete_scan([person()])
    assert a.app_state.stats_json()["bays"][0]["remaining"] == 14
    a.restock()
    assert a.app_state.stats_json()["bays"][0]["remaining"] == 20


def test_restock_emits_one_restocked_event_to_every_sink(person):
    from sinks.base import CallbackSink
    from telemetry import Telemetry

    sent = []
    t = Telemetry("m1", sinks=[CallbackSink(sent.extend)], flush_interval=0.05)
    a = Dispenserve(MemoryStore(), AppState("Kit Kat", 20), Dispenser(enabled=False), telemetry=t, result_seconds=0)
    a.complete_scan([person()])
    a.restock()
    t.close()
    assert [e["event"] for e in sent] == ["dispensed", "restocked"]


def test_dispensed_per_hour_is_in_stats(person):
    a = app()
    a.complete_scan([person()])
    hours = a.stats_json()["dispensed_per_hour"]
    assert sum(hours.values()) == 1 and all(":" in h for h in hours)


def test_presence_drives_state_payload():
    a = app()
    assert a.app_state.state_json()["present"] is False
    a.app_state.set_presence(True)
    s = a.app_state.state_json()
    assert s["present"] is True and s["present_for"] >= 0
    a.app_state.set_presence(False)
    assert a.app_state.state_json()["present_for"] == 0


def test_sensor_near_marks_presence():
    a = Dispenserve(MemoryStore(), AppState("Kit Kat", 20), Dispenser(enabled=False), use_sensor=True, result_seconds=0)
    a.on_sensor("near")
    assert a.app_state.state_json()["present"] is True
    a.on_sensor("away")
    assert a.app_state.state_json()["present"] is False


def test_fleet_hourly_endpoint():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    from app import create_app

    body = TestClient(create_app(fake=True)).get("/hourly?hours=6").json()
    assert body["hours"] == 6 and body["buckets"]
    for b in body["buckets"]:
        assert set(b) == {"hour", "machine_id", "bay", "dispensed"}
        assert isinstance(b["dispensed"], int)
