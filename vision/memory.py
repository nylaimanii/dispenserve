"""In-memory face store and the dispense decision.

Privacy rules (see PRIVACY.md):
- vectors live only in this process's memory; nothing here touches disk or the network
- entries are purged after 24h, and purged/cleared vectors are zeroed before being dropped
- decide() fails open: any error while matching results in a dispense
"""

import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

log = logging.getLogger("dispenserve.memory")

MATCH_THRESHOLD = 0.42  # cosine similarity; strictly greater than this is a match
TTL_SECONDS = 24 * 60 * 60

DISPENSE = "dispense"
ALREADY_SERVED = "already_served"


def normalize(vec):
    vec = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(vec)
    if not np.isfinite(norm) or norm == 0:
        raise ValueError("cannot normalize a zero or non-finite vector")
    return vec / norm


def average_embeddings(embeddings):
    """Mean of several embeddings, re-normalized to unit length."""
    if len(embeddings) == 0:
        raise ValueError("no embeddings to average")
    stacked = np.stack([normalize(e) for e in embeddings])
    return normalize(stacked.mean(axis=0))


class MemoryStore:
    """(unit vector, timestamp) pairs held in RAM only."""

    def __init__(self, threshold=MATCH_THRESHOLD, ttl=TTL_SECONDS):
        self.threshold = threshold
        self.ttl = ttl
        self._vectors = []
        self._timestamps = []
        self._lock = threading.Lock()

    def __len__(self):
        with self._lock:
            return len(self._vectors)

    def purge(self, now=None):
        """Drop entries older than the TTL. Returns how many were removed."""
        now = time.time() if now is None else now
        with self._lock:
            keep_vectors, keep_timestamps, removed = [], [], 0
            for vec, ts in zip(self._vectors, self._timestamps):
                if now - ts > self.ttl:
                    vec.fill(0)
                    removed += 1
                else:
                    keep_vectors.append(vec)
                    keep_timestamps.append(ts)
            self._vectors, self._timestamps = keep_vectors, keep_timestamps
            return removed

    def best_score(self, vec):
        """Highest cosine similarity against everything stored, or None if empty."""
        with self._lock:
            if not self._vectors:
                return None
            matrix = np.stack(self._vectors)
        return float(np.max(matrix @ normalize(vec)))

    def add(self, vec, now=None):
        now = time.time() if now is None else now
        with self._lock:
            self._vectors.append(normalize(vec).copy())
            self._timestamps.append(now)

    def clear(self):
        with self._lock:
            for vec in self._vectors:
                vec.fill(0)
            self._vectors, self._timestamps = [], []


@dataclass
class Decision:
    outcome: str  # DISPENSE or ALREADY_SERVED
    score: float | None  # best similarity found; None if memory was empty or matching failed
    reason: str  # "new", "match", or "error"


def decide(store, vec, now=None):
    """Purge stale entries, then match. Match → already_served; no match → remember and dispense.

    Fails open: any exception while matching returns a dispense.
    """
    now = time.time() if now is None else now
    try:
        store.purge(now)
        score = store.best_score(vec)
        if score is not None and score > store.threshold:
            return Decision(ALREADY_SERVED, score, "match")
        store.add(vec, now)
        return Decision(DISPENSE, score, "new")
    except Exception:
        log.exception("matching failed, failing open and dispensing")
        return Decision(DISPENSE, None, "error")
