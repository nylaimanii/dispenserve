"""Threshold tuning helper for user testing.

Each time one face is held for 3 seconds, the best similarity against everyone scanned
so far is shown, and you type whether this person really had been scanned before.
Only (score, yes/no) pairs are kept, in memory. On exit it prints false match / missed
match rates for thresholds 0.30 to 0.60 and the best one. Face vectors stay in RAM for
the session and are cleared on exit, same as the real app. Nothing is written to disk.

Run:
    .venv/bin/python vision/tune.py            # live, with the webcam
    .venv/bin/python vision/tune.py --demo     # synthetic scores, to see the output
"""

import argparse
import sys

import numpy as np

from memory import MATCH_THRESHOLD, MemoryStore, average_embeddings

THRESHOLDS = [round(0.30 + 0.02 * i, 2) for i in range(16)]  # 0.30 .. 0.60


def rates(samples, threshold):
    """samples: (score, same_person) pairs. A score above the threshold counts as a match.

    false_match: different people matched → a new person is wrongly told already_served
    missed_match: same person not matched → someone gets a second item
    """
    impostor = [s for s, same in samples if not same]
    genuine = [s for s, same in samples if same]
    false_match = sum(s > threshold for s in impostor) / len(impostor) if impostor else float("nan")
    missed_match = sum(s <= threshold for s in genuine) / len(genuine) if genuine else float("nan")
    return false_match, missed_match


def best_threshold(samples, thresholds=THRESHOLDS):
    """Lowest total error. Ties go to the higher threshold, since failing open (an extra
    item) is better than refusing someone new."""

    def cost(t):
        fm, mm = rates(samples, t)
        return (np.nan_to_num(fm) + np.nan_to_num(mm), -t)

    return min(thresholds, key=cost)


def report(samples, out=sys.stdout):
    genuine = sum(1 for _, same in samples if same)
    impostor = len(samples) - genuine
    print(f"\n{len(samples)} labeled scans: {genuine} same person, {impostor} different people", file=out)
    if genuine == 0 or impostor == 0:
        print("need at least one of each label to compute rates", file=out)
        return None
    best = best_threshold(samples)
    print("\nthreshold  false match  missed match   (false match = new person refused, missed = second item)", file=out)
    for t in THRESHOLDS:
        fm, mm = rates(samples, t)
        marks = ("  <- best" if t == best else "") + ("  (current)" if abs(t - MATCH_THRESHOLD) < 1e-9 else "")
        print(f"  {t:.2f}      {fm:6.1%}       {mm:6.1%}{marks}", file=out)
    print(f"\nbest threshold: {best:.2f}  (current MATCH_THRESHOLD in vision/memory.py: {MATCH_THRESHOLD})", file=out)
    if min(genuine, impostor) < 20:
        print("note: fewer than 20 samples per label, treat these rates as rough", file=out)
    return best


def demo_samples(seed=0):
    rng = np.random.default_rng(seed)
    genuine = np.clip(rng.normal(0.66, 0.11, size=60), -1, 1)
    impostor = np.clip(rng.normal(0.08, 0.10, size=240), -1, 1)
    return [(float(s), True) for s in genuine] + [(float(s), False) for s in impostor]


def ask_label(score):
    while True:
        answer = input(f"best score {score:.3f}. has this person been scanned before? [y/n, s skip, q quit] ").strip().lower()
        if answer in ("y", "n", "s", "q"):
            return answer


def run_live(camera_indexes):
    import time

    import cv2

    from main import CAMERA_INDEXES, FaceEngine, HoldTracker, open_camera

    engine = FaceEngine()
    cap = open_camera(camera_indexes or CAMERA_INDEXES)
    if cap is None:
        sys.exit("no camera found")
    store, tracker, samples = MemoryStore(), HoldTracker(), []
    armed = True
    print("hold one face in frame for 3s. q in the window quits and prints the report.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            faces = engine.detect(frame)
            now = time.monotonic()
            if not armed:
                armed = not faces
            elif len(faces) == 1 and tracker.update(1, now, engine.embed(frame, faces[0])):
                vec = average_embeddings(tracker.embeddings)
                tracker.reset()
                armed = False
                score = store.best_score(vec)
                if score is None:
                    store.add(vec)
                    print("first scan stored in memory, nothing to compare yet")
                    continue
                answer = ask_label(score)
                if answer == "q":
                    break
                if answer in ("y", "n"):
                    samples.append((score, answer == "y"))
                if answer == "n":
                    store.add(vec)
                del vec
            elif len(faces) != 1:
                tracker.update(len(faces), now)
            for face in faces:
                x1, y1, x2, y2 = face.bbox.astype(int)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{len(samples)} labeled  |  q quit", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
            cv2.imshow("dispenserve tune", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    except KeyboardInterrupt:
        pass
    finally:
        tracker.reset()
        store.clear()
        cap.release()
        cv2.destroyAllWindows()
    return samples


def main(argv=None):
    parser = argparse.ArgumentParser(description="match threshold tuning")
    parser.add_argument("--demo", action="store_true", help="run on synthetic scores")
    parser.add_argument("--camera", type=int, help="camera index (default: try 1, then 0)")
    args = parser.parse_args(argv)
    if args.demo:
        print("demo mode: 60 synthetic same-person scores, 240 different-person scores")
        samples = demo_samples()
    else:
        samples = run_live([args.camera] if args.camera is not None else None)
    report(samples)


if __name__ == "__main__":
    main()
