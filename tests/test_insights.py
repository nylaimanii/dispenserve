import json
import re
import time

import insights as I
from main import Dispenserve, FakeCrowd
from memory import MemoryStore
from serial_link import Dispenser
from state import AppState


class FakeGemini:
    def __init__(self, text="Kit Kat will run out around 3pm. Restock it after lunch."):
        self.requests = []
        self.text = text

    def __call__(self, url, headers, body):
        self.requests.append((url, headers, body))
        return {"candidates": [{"content": {"parts": [{"text": self.text}]}}]}


def busy_app(scans=6):
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), result_seconds=0)
    crowd = FakeCrowd(people=4, seed=3)
    vectors = crowd.people
    for _ in range(scans):
        app.complete_scan(crowd.hold())
    return app, vectors


def test_gemini_receives_only_aggregate_counts():
    app, vectors = busy_app()
    gemini = FakeGemini()
    ins = I.Insights(app.app_state, api_key="k", transport=gemini)
    ins.get()
    time.sleep(0.2)
    [(url, headers, body)] = gemini.requests
    prompt = body["contents"][0]["parts"][0]["text"]
    snapshot = json.loads(prompt[prompt.index("{"): prompt.rindex("}") + 1])
    assert set(snapshot) == {"local_time", "bays", "dispensed_per_hour_today", "unique_people_today"}
    assert all(set(b) == {"name", "items_left", "capacity"} for b in snapshot["bays"])
    # every number sent is a whole count; no floats, so no vector or score can be in there
    numbers = re.findall(r"-?\d+\.\d+", json.dumps(body))
    assert numbers == [str(body["generationConfig"]["temperature"])]
    for vec in vectors:
        assert f"{vec[0]:.4f}" not in json.dumps(body)


def test_insight_is_cached_for_ten_minutes():
    app, _ = busy_app()
    gemini = FakeGemini()
    ins = I.Insights(app.app_state, api_key="k", transport=gemini)
    first = ins.get()  # rule-based right away, Gemini fetch starts in the background
    assert first["source"] == "rules"
    time.sleep(0.2)
    assert ins.get()["source"] == "gemini"
    for _ in range(5):
        ins.get()
    assert len(gemini.requests) == 1


def test_no_key_uses_the_rule_based_estimate():
    app, _ = busy_app()
    result = I.Insights(app.app_state).get()
    assert result["source"] == "rules" and "Kit Kat" in result["text"]


def test_gemini_error_falls_back_to_rules():
    app, _ = busy_app()

    def broken(*_):
        raise OSError("network down")

    ins = I.Insights(app.app_state, api_key="k", transport=broken)
    ins.get()
    time.sleep(0.2)
    assert ins.get()["source"] == "rules"


def test_rule_based_numbers():
    snapshot = {"local_time": "14:30", "bays": [{"name": "Kit Kat", "items_left": 6, "capacity": 24}],
                "dispensed_per_hour_today": {"11:00": 3, "12:00": 4, "13:00": 2, "14:00": 1}, "unique_people_today": 10}
    # 10 items over the last 3.5 hours = ~2.9/hr, 6 left = ~2 hours
    assert "about 2 hours" in I.rule_based(snapshot)
    empty = {**snapshot, "bays": [{"name": "Kit Kat", "items_left": 0, "capacity": 24}]}
    assert "empty" in I.rule_based(empty)


def test_slow_bay_does_not_quote_huge_hour_counts():
    snapshot = {"local_time": "11:58", "bays": [{"name": "Kit Kat", "items_left": 22, "capacity": 24}],
                "dispensed_per_hour_today": {"08:00": 0, "09:00": 1, "10:00": 0, "11:00": 1}, "unique_people_today": 2}
    assert "No restock needed today" in I.rule_based(snapshot)


def test_failed_gemini_is_retried_within_a_minute(monkeypatch):
    app, _ = busy_app()
    monkeypatch.setattr(I, "FAILED_CACHE_SECONDS", 60)
    calls = []

    def flaky(url, headers, body):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("503")
        return {"candidates": [{"content": {"parts": [{"text": "Restock Kit Kat after lunch. It is going fast."}]}}]}

    ins = I.Insights(app.app_state, api_key="k", transport=flaky, cache_seconds=600)
    ins.get(); time.sleep(0.3)               # first refresh fails (it retries twice inside)
    assert ins.get()["source"] == "rules"
    # the failed answer is only held for FAILED_CACHE_SECONDS, not the full 10 minutes
    assert ins._fetched_at <= time.monotonic() - (600 - 60) + 1
