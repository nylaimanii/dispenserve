import numpy as np
import pytest

from memory import ALREADY_SERVED, DISPENSE, MATCH_THRESHOLD, TTL_SECONDS, MemoryStore, average_embeddings, decide

NOW = 1_800_000_000.0


def test_same_person_twice_is_already_served(person):
    store = MemoryStore()
    alice = person()
    assert decide(store, alice, now=NOW).outcome == DISPENSE
    second = decide(store, alice, now=NOW + 60)
    assert second.outcome == ALREADY_SERVED
    assert second.reason == "match"
    assert len(store) == 1


def test_different_people_both_dispense(person):
    store = MemoryStore()
    assert decide(store, person(), now=NOW).outcome == DISPENSE
    second = decide(store, person(), now=NOW + 60)
    assert second.outcome == DISPENSE
    assert second.score < MATCH_THRESHOLD
    assert len(store) == 2


def test_entry_older_than_24h_dispenses_again(person):
    store = MemoryStore()
    alice = person()
    decide(store, alice, now=NOW)
    assert decide(store, alice, now=NOW + TTL_SECONDS - 60).outcome == ALREADY_SERVED
    again = decide(store, alice, now=NOW + TTL_SECONDS + 1)
    assert again.outcome == DISPENSE
    assert again.reason == "new"
    assert len(store) == 1  # the old entry was purged, the new one stored


def test_purge_zeroes_dropped_vectors(person):
    store = MemoryStore()
    decide(store, person(), now=NOW)
    held = store._vectors[0]
    store.purge(now=NOW + TTL_SECONDS + 1)
    assert len(store) == 0
    assert not held.any()


@pytest.mark.parametrize("similarity", [0.9, 0.7, 0.5])
def test_noisy_version_of_same_person_still_matches(person, noisy, similarity):
    store = MemoryStore()
    alice = person()
    decide(store, alice, now=NOW)
    result = decide(store, noisy(alice, similarity), now=NOW + 60)
    assert result.outcome == ALREADY_SERVED
    assert result.score == pytest.approx(similarity, abs=0.01)


def test_noisy_frames_average_back_toward_the_person(person, noisy):
    alice = person()
    frames = [noisy(alice, 0.6) for _ in range(15)]
    assert float(np.dot(average_embeddings(frames), alice)) > 0.9


def test_threshold_is_strictly_greater(person, noisy):
    store = MemoryStore()
    alice = person()
    decide(store, alice, now=NOW)
    below = noisy(alice, MATCH_THRESHOLD - 0.01)
    assert decide(store, below, now=NOW + 60).outcome == DISPENSE


def test_clear_empties_memory(person):
    store = MemoryStore()
    alice = person()
    decide(store, alice, now=NOW)
    store.clear()
    assert len(store) == 0
    assert decide(store, alice, now=NOW + 60).outcome == DISPENSE
