import io

from main import Dispenserve
from memory import MemoryStore
from metrics import Metrics
from serial_link import Dispenser
from state import AppState
from tune import THRESHOLDS, best_threshold, demo_samples, rates, report


def test_rates_count_both_error_types():
    samples = [(0.9, True), (0.35, True), (0.5, False), (0.1, False)]
    false_match, missed = rates(samples, 0.42)
    assert false_match == 0.5  # 0.5 impostor is above 0.42
    assert missed == 0.5  # 0.35 genuine is below 0.42


def test_best_threshold_separates_clean_data():
    samples = [(0.8, True), (0.7, True), (0.2, False), (0.3, False)]
    best = best_threshold(samples)
    assert rates(samples, best) == (0.0, 0.0)
    assert best == max(THRESHOLDS)  # ties go high (fail open)


def test_thresholds_cover_030_to_060():
    assert THRESHOLDS[0] == 0.30 and THRESHOLDS[-1] == 0.60


def test_demo_report_prints_a_best_threshold():
    out = io.StringIO()
    best = report(demo_samples(), out=out)
    assert best in THRESHOLDS
    assert "best threshold" in out.getvalue()


def test_metrics_summary():
    m = Metrics()
    for ms in (10, 20, 30):
        m.record("detect", ms)
    s = m.summary()["stages"]["detect"]
    assert s["avg_ms"] == 20 and s["count"] == 3 and s["last_ms"] == 30


def test_scan_records_stage_timings(person):
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False))
    app.complete_scan([person()])
    stages = app.metrics_json()["stages"]
    assert {"average", "decide", "hold_to_result"} <= stages.keys()
