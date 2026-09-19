import time

import numpy as np

from main import Dispenserve
from memory import DISPENSE, MemoryStore, decide
from serial_link import Dispenser
from state import DISPENSED, AppState


def make_app():
    return Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False))


def test_exception_in_matching_dispenses(person, monkeypatch):
    store = MemoryStore()
    alice = person()
    decide(store, alice)

    def boom(vec):
        raise RuntimeError("matcher exploded")

    monkeypatch.setattr(store, "best_score", boom)
    result = decide(store, alice)  # would be already_served if matching worked
    assert result.outcome == DISPENSE
    assert result.reason == "error"


def test_exception_in_purge_dispenses(person, monkeypatch):
    store = MemoryStore()
    monkeypatch.setattr(store, "purge", lambda now=None: 1 / 0)
    assert decide(store, person()).outcome == DISPENSE


def test_bad_embeddings_in_app_still_dispense():
    app = make_app()
    decision = app.complete_scan([np.zeros(512, dtype=np.float32)])  # can't normalize a zero vector
    assert decision.outcome == DISPENSE
    assert app.app_state.state == DISPENSED
    assert app.app_state.stats_json()["dispensed_today"] == 1


def test_missing_arduino_does_not_crash(person):
    app = make_app()
    app.complete_scan([person()])
    time.sleep(0.1)  # let the serial worker run
    assert app.app_state.state == DISPENSED
