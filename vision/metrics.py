"""Per-stage latency tracking for GET /metrics. Stores only durations."""

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

WINDOW = 500  # most recent samples kept per stage


class Metrics:
    def __init__(self, window=WINDOW):
        self._samples = defaultdict(lambda: deque(maxlen=window))
        self._counts = defaultdict(int)
        self._lock = threading.Lock()

    def record(self, stage, ms):
        with self._lock:
            self._samples[stage].append(ms)
            self._counts[stage] += 1

    @contextmanager
    def time(self, stage):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, (time.perf_counter() - start) * 1000)

    def summary(self):
        with self._lock:
            stages = {}
            for stage, samples in self._samples.items():
                ordered = sorted(samples)
                stages[stage] = {
                    "avg_ms": round(sum(ordered) / len(ordered), 2),
                    "p50_ms": round(ordered[len(ordered) // 2], 2),
                    "p95_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 2),
                    "last_ms": round(samples[-1], 2),
                    "count": self._counts[stage],
                }
        return {"window": WINDOW, "stages": stages}
