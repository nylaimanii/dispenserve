import datetime
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud" / "api"))

from fleet import BayStats, MachineStats, build_fleet, build_forecast, forecast_bay  # noqa: E402

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 9, 19, 17, 30, tzinfo=UTC)


def bay(since_restock=0, window=0, today=0, name="Kit Kat"):
    return BayStats("m1", name, NOW - datetime.timedelta(hours=5), since_restock, today, window)


def test_forecast_is_remaining_over_rate():
    row = forecast_bay(bay(since_restock=12, window=6), capacity=24, now=NOW, window_hours=3)
    assert row["remaining"] == 12
    assert row["rate_per_hour"] == 2.0
    assert row["hours_left"] == 6.0
    assert row["runs_out_at"] == "2026-09-19T23:30:00+00:00"
    assert row["status"] == "ok"


def test_forecast_low_empty_and_idle():
    assert forecast_bay(bay(since_restock=20, window=6), 24, NOW, 3)["status"] == "low"  # 4 left
    empty = forecast_bay(bay(since_restock=24, window=6), 24, NOW, 3)
    assert empty["status"] == "empty" and empty["hours_left"] == 0
    idle = forecast_bay(bay(since_restock=3, window=0), 24, NOW, 3)
    assert idle["status"] == "idle" and idle["runs_out_at"] is None


def test_forecast_sorts_soonest_first():
    machines = [MachineStats("m1", NOW, [bay(2, 3, name="a"), bay(20, 6, name="b"), bay(0, 0, name="c")])]
    assert [r["bay"] for r in build_forecast(machines, 24, NOW, 3)] == ["b", "a", "c"]


def test_fleet_counts_and_last_seen():
    machines = [MachineStats("m1", NOW - datetime.timedelta(minutes=90), [bay(10, 0, today=4, name="x"), bay(1, 0, today=2, name="y")])]
    [m] = build_fleet(machines, 24, NOW)
    assert m["dispensed_today"] == 6
    assert m["online"] is False and m["minutes_since_seen"] == 90
    assert [(b["name"], b["remaining"]) for b in m["bays"]] == [("x", 14), ("y", 23)]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    from app import create_app

    return TestClient(create_app(fake=True))


def test_fake_fleet_has_three_machines(client):
    body = client.get("/fleet").json()
    assert body["source"] == "fake"
    assert len(body["machines"]) == 3
    for m in body["machines"]:
        assert {"machine_id", "last_seen", "dispensed_today", "bays"} <= m.keys()
        for b in m["bays"]:
            assert 0 <= b["remaining"] <= b["capacity"]


def test_fake_forecast_and_cors(client):
    res = client.get("/forecast", headers={"Origin": "http://localhost:8000"})
    assert res.headers["access-control-allow-origin"] == "*"
    rows = res.json()["bays"]
    assert len(rows) == 6
    assert all(r["status"] in ("ok", "low", "empty", "idle") for r in rows)


def test_fake_data_is_stable_between_requests(client):
    assert client.get("/fleet").json()["machines"] == client.get("/fleet").json()["machines"]


def test_missing_database_url_falls_back_to_fake(monkeypatch):
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
    monkeypatch.delenv("FLEET_FAKE", raising=False)
    monkeypatch.setattr("app.load_dotenv", lambda: None)
    from app import create_app

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    assert TestClient(create_app()).get("/health").json()["source"] == "fake"


def test_unreachable_database_returns_503(monkeypatch):
    monkeypatch.setenv("TIGER_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")
    monkeypatch.setattr("app.load_dotenv", lambda: None)
    from app import create_app

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from fastapi.testclient import TestClient
    res = TestClient(create_app()).get("/fleet")
    assert res.status_code == 503
