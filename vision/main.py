"""dispenserve: one item per person per day.

Camera loop: when exactly one face stays in frame for 3 seconds, its embeddings are
averaged into one vector and checked against memory (vision/memory.py). New face →
dispense. Seen in the last 24h → already_served. Face vectors never leave RAM.

Run:
    .venv/bin/python vision/main.py                 # webcam + arduino
    .venv/bin/python vision/main.py --no-camera     # fake scans every 10s, for demoing the kiosk
    .venv/bin/python vision/main.py --no-serial     # don't look for the arduino

Keys (camera window, or type + Enter in the terminal with --no-camera):
    f  force dispense    c  clear memory    r  restock bay    q  quit
"""

import argparse
import logging
import queue
import signal
import sys
import threading
import time

import numpy as np

import config
from memory import DISPENSE, Decision, MemoryStore, average_embeddings, decide
from serial_link import Dispenser
from server import PORT, start_server
from state import ALREADY_SERVED, DISPENSED, IDLE, SCANNING, AppState

log = logging.getLogger("dispenserve")

HOLD_SECONDS = 3.0
RESULT_SECONDS = 4.0  # how long the kiosk shows dispensed / already_served
DROPOUT_GRACE_S = 0.5  # a face missing for less than this doesn't reset the hold
SAME_FACE_MIN_SIM = 0.3  # a face swap mid-hold restarts the hold
FAKE_SCAN_INTERVAL_S = 10.0
CAMERA_INDEXES = [1, 0]  # external usb webcam first, then the built-in camera


class HoldTracker:
    """Collects embeddings while exactly one face stays in frame for HOLD_SECONDS."""

    def __init__(self, hold_seconds=HOLD_SECONDS):
        self.hold_seconds = hold_seconds
        self.reset()

    def reset(self):
        self.embeddings = []
        self.landmarks = []
        self.started = None
        self.last_seen = None

    @property
    def active(self):
        return self.started is not None

    def progress(self, now):
        if not self.active:
            return 0.0
        return min(1.0, (now - self.started) / self.hold_seconds)

    def update(self, face_count, now, embedding=None, landmarks=None):
        """Feed one frame. Returns True when the hold is complete."""
        if face_count > 1:
            self.reset()
            return False
        if face_count == 0:
            if self.active and now - self.last_seen > DROPOUT_GRACE_S:
                self.reset()
            return False

        if self.active and self.embeddings:
            running = average_embeddings(self.embeddings)
            if float(np.dot(running, embedding / np.linalg.norm(embedding))) < SAME_FACE_MIN_SIM:
                self.reset()
        if not self.active:
            self.started = now
        self.last_seen = now
        self.embeddings.append(embedding)
        if landmarks is not None:
            self.landmarks.append(landmarks)
        return now - self.started >= self.hold_seconds


class Dispenserve:
    """Decision + side effects: kiosk state, counters, and the servo."""

    def __init__(self, store, app_state, dispenser, result_seconds=RESULT_SECONDS):
        self.store = store
        self.app_state = app_state
        self.dispenser = dispenser
        self.result_seconds = result_seconds
        self._result_until = 0.0
        self._serial_queue = queue.Queue()
        threading.Thread(target=self._serial_worker, name="serial", daemon=True).start()

    def metrics_json(self):
        return {"stages": {}}

    # --- scan outcome ---------------------------------------------------------

    def complete_scan(self, embeddings):
        """Average the hold's embeddings and decide. Any error here fails open (dispense)."""
        try:
            vec = average_embeddings(embeddings)
            decision = decide(self.store, vec)
        except Exception:
            log.exception("matching failed, failing open and dispensing")
            decision = Decision(DISPENSE, None, "error")
        score = "none" if decision.score is None else f"{decision.score:.3f}"
        log.info("scan complete: %s (%s, best score %s, %d in memory)", decision.outcome, decision.reason, score, len(self.store))

        if decision.outcome == DISPENSE:
            self._dispense(new_person=decision.reason == "new")
        else:
            self._show_result(ALREADY_SERVED)
        return decision

    def force_dispense(self):
        log.info("forced dispense")
        self._dispense(new_person=False)

    def clear_memory(self):
        self.store.clear()
        log.info("memory cleared")

    def restock(self):
        self.app_state.restock()
        log.info("restocked %s", self.app_state.bay_name)

    def _dispense(self, new_person):
        remaining = self.app_state.record_dispense(new_person)
        self.app_state.set_item(self.app_state.bay_name)
        self._show_result(DISPENSED)
        if remaining == 0:
            log.warning("%s is empty, press r after restocking", self.app_state.bay_name)
        self._serial_queue.put(True)

    def _serial_worker(self):
        while True:
            self._serial_queue.get()
            if self.dispenser.dispense():
                log.info("arduino: ok")

    # --- kiosk state ----------------------------------------------------------

    def _show_result(self, state):
        self.app_state.set_state(state, progress=1.0 if state == DISPENSED else 0.0)
        self._result_until = time.monotonic() + self.result_seconds

    def showing_result(self):
        return time.monotonic() < self._result_until

    def tick(self, scanning_progress=None):
        """Called every loop iteration to keep /state in sync with the hold."""
        if self.showing_result():
            return
        if scanning_progress is None:
            if self.app_state.state != IDLE:
                self.app_state.set_state(IDLE, progress=0.0)
        else:
            self.app_state.set_state(SCANNING, progress=scanning_progress)


def handle_key(key, disp):
    """Returns False when the app should quit."""
    if key == "q":
        return False
    if key == "f":
        disp.force_dispense()
    elif key == "c":
        disp.clear_memory()
    elif key == "r":
        disp.restock()
    return True


# --- camera mode ----------------------------------------------------------------


class FaceEngine:
    """insightface, split into detect / landmarks / embed so each stage can be timed."""

    def __init__(self, det_size=640):
        from insightface.app import FaceAnalysis

        self.app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection", "recognition", "landmark_2d_106"],
            providers=["CPUExecutionProvider"],
        )
        self.app.prepare(ctx_id=-1, det_size=(det_size, det_size))
        self.det = self.app.models["detection"]
        self.rec = self.app.models["recognition"]
        self.lmk = self.app.models.get("landmark_2d_106")

    def detect(self, frame):
        from insightface.app.common import Face

        bboxes, kpss = self.det.detect(frame, max_num=0, metric="default")
        return [
            Face(bbox=bboxes[i, 0:4], kps=None if kpss is None else kpss[i], det_score=bboxes[i, 4])
            for i in range(bboxes.shape[0])
        ]

    def landmarks(self, frame, face):
        if self.lmk is None:
            return None
        self.lmk.get(frame, face)
        return face.landmark_2d_106

    def embed(self, frame, face):
        self.rec.get(frame, face)
        return face.normed_embedding


def open_camera(indexes):
    import cv2

    for index in indexes:
        cap = cv2.VideoCapture(index)
        if cap.isOpened() and cap.read()[0]:
            log.info("using camera index %d", index)
            return cap
        cap.release()
    return None


def run_camera(disp, camera_indexes, det_size):
    import cv2

    log.info("loading face models")
    engine = FaceEngine(det_size)
    cap = open_camera(camera_indexes)
    if cap is None:
        log.error("no camera found at indexes %s", camera_indexes)
        return

    tracker = HoldTracker()
    armed = True  # after a result, wait until the frame is empty before scanning again
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                log.warning("lost camera feed, reopening")
                cap.release()
                time.sleep(1.0)
                cap = open_camera(camera_indexes)
                if cap is None:
                    log.error("camera did not come back")
                    return
                continue

            now = time.monotonic()
            try:
                faces = engine.detect(frame)
            except Exception:
                log.exception("detection failed on a frame")
                faces = []

            if disp.showing_result() or not armed:
                tracker.reset()
                if not faces and not disp.showing_result():
                    armed = True
            elif len(faces) == 1:
                face = faces[0]
                try:
                    lmk = engine.landmarks(frame, face)
                    emb = engine.embed(frame, face)
                    if tracker.update(1, now, emb, lmk):
                        embeddings = tracker.embeddings
                        tracker.reset()
                        disp.complete_scan(embeddings)
                        del embeddings
                        armed = False
                except Exception:
                    log.exception("embedding failed on a frame")
            else:
                tracker.update(len(faces), now)

            disp.tick(tracker.progress(now) if tracker.active else None)
            draw_overlay(frame, faces, disp.app_state.state_json())
            cv2.imshow("dispenserve", frame)
            key = cv2.waitKey(1) & 0xFF
            if key != 0xFF and not handle_key(chr(key), disp):
                return
    finally:
        tracker.reset()
        cap.release()
        cv2.destroyAllWindows()


def draw_overlay(frame, faces, state):
    import cv2

    for face in faces:
        x1, y1, x2, y2 = face.bbox.astype(int)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
    text = state["state"]
    if state["state"] == SCANNING:
        text += f" {state['progress'] * 100:.0f}%"
    cv2.putText(frame, text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
    cv2.putText(frame, "f dispense  c clear  r restock  q quit", (20, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)


# --- no-camera mode -------------------------------------------------------------


class FakeCrowd:
    """Random in-memory 'people' so the kiosk can be demoed without a camera."""

    def __init__(self, people=6, dim=512, seed=None):
        self.rng = np.random.default_rng(seed)
        self.people = [self._unit(self.rng.normal(size=dim)) for _ in range(people)]

    @staticmethod
    def _unit(v):
        return (v / np.linalg.norm(v)).astype(np.float32)

    def hold(self, frames=15, noise=0.02):
        """One person's embeddings over a hold, each with a little per-frame noise."""
        person = self.people[self.rng.integers(len(self.people))]
        return [self._unit(person + self.rng.normal(scale=noise, size=person.shape)) for _ in range(frames)]


def run_fake(disp, stop, interval=FAKE_SCAN_INTERVAL_S, hold_seconds=HOLD_SECONDS):
    crowd = FakeCrowd()
    log.info("no-camera mode: fake scan every %.0fs", interval)
    next_scan = time.monotonic() + interval - hold_seconds
    while not stop.is_set():
        if stop.wait(max(0.0, next_scan - time.monotonic())):
            return
        start = time.monotonic()
        next_scan = start + interval
        while (elapsed := time.monotonic() - start) < hold_seconds:
            disp.tick(elapsed / hold_seconds)
            if stop.wait(0.1):
                return
        disp.complete_scan(crowd.hold())
        while disp.showing_result():
            if stop.wait(0.1):
                return
        disp.tick(None)


def read_stdin_keys(disp, stop):
    if not sys.stdin or not sys.stdin.isatty():
        return
    for line in sys.stdin:
        key = line.strip().lower()[:1]
        if key and not handle_key(key, disp):
            stop.set()
            return


def raise_interrupt(*_):
    raise KeyboardInterrupt  # so SIGTERM runs the same cleanup as Ctrl+C


def main(argv=None):
    parser = argparse.ArgumentParser(description="dispenserve vision app")
    parser.add_argument("--no-camera", action="store_true", help="fake scans every 10s instead of the webcam")
    parser.add_argument("--no-serial", action="store_true", help="don't look for the arduino")
    parser.add_argument("--camera", type=int, help="camera index (default: try 1, then 0)")
    parser.add_argument("--det-size", type=int, default=640, help="face detector input size")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)

    config.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    app_state = AppState(config.env("BAY_NAME", "Kit Kat"), config.env_int("BAY_CAPACITY", 24))
    dispenser = Dispenser(enabled=not args.no_serial)
    dispenser.connect()
    disp = Dispenserve(MemoryStore(), app_state, dispenser)
    server = start_server(disp, port=args.port)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, raise_interrupt)
    try:
        if args.no_camera:
            threading.Thread(target=read_stdin_keys, args=(disp, stop), daemon=True).start()
            run_fake(disp, stop)
        else:
            indexes = [args.camera] if args.camera is not None else CAMERA_INDEXES
            run_camera(disp, indexes, args.det_size)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        disp.clear_memory()
        server.shutdown()
        dispenser.close()
        log.info("bye")


if __name__ == "__main__":
    main()
