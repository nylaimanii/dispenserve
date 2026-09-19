from main import HOLD_SECONDS, HoldTracker


def run(tracker, frames):
    """frames: list of (time, face_count, embedding). Returns the time the hold completed, or None."""
    for now, count, emb in frames:
        if tracker.update(count, now, emb):
            return now
    return None


def test_one_face_for_three_seconds_completes(person):
    alice = person()
    tracker = HoldTracker()
    done = run(tracker, [(t / 10, 1, alice) for t in range(0, 40)])
    assert done == HOLD_SECONDS
    assert tracker.progress(1.5) == 0.5


def test_second_face_resets_the_hold(person):
    alice = person()
    tracker = HoldTracker()
    frames = [(t / 10, 1, alice) for t in range(0, 20)] + [(2.0, 2, None)]
    frames += [(2.1 + t / 10, 1, alice) for t in range(0, 20)]
    assert run(tracker, frames) is None  # restarted at 2.1, needs until 5.1


def test_brief_dropout_is_forgiven(person):
    alice = person()
    tracker = HoldTracker()
    frames = [(t / 10, 1, alice) for t in range(0, 15)] + [(1.6, 0, None)]
    frames += [(1.7 + t / 10, 1, alice) for t in range(0, 20)]
    assert run(tracker, frames) is not None


def test_face_swap_mid_hold_restarts(person):
    alice, bob = person(), person()
    tracker = HoldTracker()
    run(tracker, [(t / 10, 1, alice) for t in range(0, 20)])
    tracker.update(1, 2.0, bob)
    assert tracker.started == 2.0
