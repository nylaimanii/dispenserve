import sys
from pathlib import Path

import numpy as np
import pytest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vision"))

DIM = 512


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def person(rng):
    """Returns a function that makes a new random identity vector."""
    return lambda: unit(rng.normal(size=DIM))


@pytest.fixture
def noisy(rng):
    """Returns a function that perturbs a vector to a target cosine similarity."""

    def make(vec, similarity):
        noise = rng.normal(size=vec.shape)
        noise -= noise.dot(vec) * vec  # orthogonal to vec
        noise = unit(noise)
        return unit(similarity * vec + np.sqrt(1 - similarity**2) * noise)

    return make
