"""dispenserve: one item per person per day.

Camera loop: when exactly one face stays in frame for 3 seconds, its embeddings are
averaged into one vector and checked against memory (vision/memory.py). New face →
dispense. Seen in the last 24h → already_served. Face vectors never leave RAM.

Run:
    .venv/bin/python vision/main.py                 # webcam + arduino
    .venv/bin/python vision/main.py --no-camera     # fake scans every 10s, for demoing the kiosk
    .venv/bin/python vision/main.py --no-serial     # don't look for the arduino
    .venv/bin/python vision/main.py --liveness      # reject photo spoofs (default: only log the score)
    .venv/bin/python vision/main.py --no-sensor     # ignore the ultrasonic sensor, never sleep
    .venv/bin/python vision/main.py --flush-solana  # write today's total to the donor ledger now
                                                    # (asks the running app; it also writes at midnight)

Sleep / wake: with the Arduino's ultrasonic sensor, the machine sleeps until someone is
standing within 80cm ("near"), and goes back to sleep when they leave ("away"). While
asleep, frames are not run through face detection at all.

Keys (camera window, or type + Enter in the terminal with --no-camera):
    f  force dispense    c  clear memory    r  restock bay    q  quit
"""

import argparse
import datetime
import json
import logging
import queue
import signal
import sys
import threading
import time
import urllib.request

import numpy as np

import config
import liveness
from memory import DISPENSE, Decision, MemoryStore, average_embeddings, decide
from insights import DEFAULT_MODEL, Insights
from ledger import SolanaLedger
from metrics import Metrics
from serial_link import Dispenser
from server import PORT, start_server
from state import ALREADY_SERVED, DISPENSED, IDLE, SCANNING, SLEEP, AppState
from telemetry import Telemetry, build_sinks
from voice import DEFAULT_MODEL as VOICE_MODEL
from voice import DEFAULT_VOICE_ID, Voice

log = logging.getLogger("dispenserve")

HOLD_SECONDS = 3.0
RESULT_SECONDS = 4.0  # how long the kiosk shows dispensed / already_served
DROPOUT_GRACE_S = 0.5  # a face missing for less than this doesn't reset the hold
SAME_FACE_MIN_SIM = 0.3  # a face swap mid-hold restarts the hold
FAKE_SCAN_INTERVAL_S = 10.0
GOODBYE_WITHIN_S = 90.0  # say goodbye if they leave within this long of getting an item
NOT_LIVE = "not_live"
CAMERA_INDEXES = [1, 0]  # fallback order when CAMERA_INDEX isn't set: external usb webcam, then built-in


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

    def __init__(self, store, app_state, dispenser, metrics=None, telemetry=None, ledger=None, voice=None,
                 require_liveness=False, use_sensor=False, result_seconds=RESULT_SECONDS):
        self.store = store
        self.app_state = app_state
        self.dispenser = dispenser
        self.metrics = metrics or Metrics()
        self.telemetry = telemetry  # anonymous {machine_id, bay, event, ts} only
        self.ledger = ledger  # Solana donor ledger: restocks and daily totals only
        self.insights = None  # GET /insights (Gemini or rule-based), set in main()
        self.voice = voice  # fixed spoken lines only
        self.require_liveness = require_liveness
        self.result_seconds = result_seconds
        self.use_sensor = use_sensor
        self.awake = True  # without a working sensor the machine is always awake
        self._result_until = 0.0
        self._last_dispense_at = 0.0
        self._serial_queue = queue.Queue()
        threading.Thread(target=self._serial_worker, name="serial", daemon=True).start()

    def metrics_json(self):
        return self.metrics.summary()

    def stats_json(self):
        """GET /stats: the dashboard's counts, plus a jam flag (last dispense got no "ok")."""
        return {**self.app_state.stats_json(), "jam": bool(getattr(self.dispenser, "jammed", False))}

    def insights_json(self):
        if self.insights is None:
            self.insights = Insights(self.app_state)  # rule-based only
        return self.insights.get()

    # --- scan outcome ---------------------------------------------------------

    def complete_scan(self, embeddings, landmarks=None):
        """Average the hold's embeddings and decide. Any error here fails open (dispense).

        landmarks: optional per-frame (kps, landmark_2d_106) pairs for the liveness check.
        """
        start = time.perf_counter()
        if landmarks and not self._liveness_ok(landmarks):
            self.app_state.set_state(IDLE, progress=0.0)
            return Decision(NOT_LIVE, None, "liveness")
        try:
            with self.metrics.time("average"):
                vec = average_embeddings(embeddings)
            with self.metrics.time("decide"):
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
            self._emit("already_served")
            self._serial_queue.put("x")  # red LED
        self.metrics.record("hold_to_result", (time.perf_counter() - start) * 1000)
        return decision

    def _liveness_ok(self, landmarks):
        """Always scores and logs. Only rejects with --liveness, and fails open on errors."""
        try:
            with self.metrics.time("liveness"):
                result = liveness.check([k for k, _ in landmarks], [l for _, l in landmarks if l is not None])
        except Exception:
            log.exception("liveness check failed, treating as live")
            return True
        log.info(
            "liveness %s: score %.2f (depth %.4f, blink %.2f, %d frames)%s",
            "pass" if result.live else "FAIL", result.score, result.motion, result.blink, result.frames,
            "" if self.require_liveness else " [log only]",
        )
        return result.live or not self.require_liveness

    def force_dispense(self):
        log.info("forced dispense")
        self._dispense(new_person=False)

    def clear_memory(self):
        self.store.clear()
        log.info("memory cleared")

    def restock(self):
        added = self.app_state.restock()
        self._emit("restocked")
        log.info("restocked %s (+%d)", self.app_state.bay_name, added)
        if self.ledger is not None:
            self.ledger.record_restock(datetime.date.today(), self.app_state.bay_name, added)

    def flush_solana(self):
        """Write today's running total to the donor ledger now."""
        if self.ledger is None:
            return {"ok": False, "error": "solana ledger is off (no SOLANA_KEYPAIR_PATH, or --no-solana)"}
        day, total = self.app_state.today()
        return {"ok": True, "queued": self.ledger.record_daily_total(day, total)}

    def close_finished_days(self):
        """Called about once a minute: writes the total for any day that just ended."""
        for day, total in self.app_state.pop_closed_days():
            log.info("day %s ended with %d dispensed", day, total)
            if self.ledger is not None:
                self.ledger.record_daily_total(day, total)

    def _dispense(self, new_person):
        remaining = self.app_state.record_dispense(new_person)
        self.app_state.set_item(self.app_state.bay_name)
        self._show_result(DISPENSED)
        self._last_dispense_at = time.monotonic()
        self._emit("dispensed")
        if remaining == 0:
            log.warning("%s is empty, press r after restocking", self.app_state.bay_name)
        self._serial_queue.put("d")

    # --- sleep / wake -----------------------------------------------------------

    def on_sensor(self, line):
        """From the serial thread: "near" wakes the scanner, "away" puts it to sleep."""
        if not self.use_sensor:
            return
        if line in ("near", "away"):
            self.app_state.set_presence(line == "near")
        if line == "nosensor":
            log.warning("arduino reports no ultrasonic sensor, staying awake")
            self.use_sensor = False
            self.awake = True
        elif line == "near" and not self.awake:
            log.info("someone is here, waking up")
            self.awake = True
        elif line == "away" and self.awake:
            log.info("nobody here, going to sleep")
            self.awake = False
            self.person_left()

    def on_connection(self, connected):
        """The board resets on connect and starts with nobody near, so sleep until "near".
        If it goes away, stay awake: a missing sensor must never stop the machine."""
        if not self.use_sensor:
            return
        self.awake = not connected
        log.info("sensor %s: %s", "connected" if connected else "lost", "asleep until someone walks up" if connected else "staying awake")

    def person_left(self):
        """Someone walked away (sensor "away", or the frame emptied without a sensor)."""
        if self._last_dispense_at and time.monotonic() - self._last_dispense_at < GOODBYE_WITHIN_S:
            self._say("goodbye")
        self._last_dispense_at = 0.0

    def _say(self, kind):
        if self.voice is not None:
            try:
                self.voice.say(kind)
            except Exception:
                log.exception("voice failed")

    def _emit(self, event):
        if self.telemetry is not None:
            self.telemetry.emit(self.app_state.bay_name, event)

    def _serial_worker(self):
        while True:
            command = self._serial_queue.get()
            if command == "x":
                self.dispenser.show_refused()
                continue
            start = time.perf_counter()
            ok = self.dispenser.dispense()
            if ok:
                self.metrics.record("serial", (time.perf_counter() - start) * 1000)
                log.info("arduino: ok")

    # --- kiosk state ----------------------------------------------------------

    def _show_result(self, state):
        self.app_state.set_state(state, progress=1.0 if state == DISPENSED else 0.0)
        self._result_until = time.monotonic() + self.result_seconds
        self._say("dispensed" if state == DISPENSED else "already_served")

    def showing_result(self):
        return time.monotonic() < self._result_until

    def tick(self, scanning_progress=None):
        """Called every loop iteration to keep /state in sync with the hold."""
        if self.showing_result():
            return
        if not self.awake:
            if self.app_state.state != SLEEP:
                self.app_state.set_state(SLEEP, progress=0.0)
            return
        if scanning_progress is None:
            if self.app_state.state != IDLE:
                self.app_state.set_state(IDLE, progress=0.0)
        else:
            if self.app_state.state != SCANNING:
                self._say("scanning")
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
        ok, frame = (False, None)
        if cap.isOpened():
            ok, frame = cap.read()
        if ok:
            log.info("using camera index %d (%dx%d)", index, frame.shape[1], frame.shape[0])
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
            if not disp.awake and not disp.showing_result():
                disp.app_state.set_presence(False)
                # asleep: the frame is not looked at, not even for face detection
                tracker.reset()
                armed = True
                disp.tick(None)
                frame[:] = 0
                draw_overlay(frame, [], disp.app_state.state_json())
                cv2.imshow("dispenserve", frame)
                key = cv2.waitKey(30) & 0xFF
                if key != 0xFF and not handle_key(chr(key), disp):
                    return
                continue
            try:
                with disp.metrics.time("detect"):
                    faces = engine.detect(frame)
            except Exception:
                log.exception("detection failed on a frame")
                faces = []
            disp.app_state.set_presence(bool(faces))

            if disp.showing_result() or not armed:
                tracker.reset()
                if not faces and not disp.showing_result():
                    armed = True
                    if not disp.use_sensor:
                        disp.person_left()
            elif len(faces) == 1:
                face = faces[0]
                try:
                    with disp.metrics.time("landmarks"):
                        lmk = engine.landmarks(frame, face)
                    with disp.metrics.time("embed"):
                        emb = engine.embed(frame, face)
                    if tracker.update(1, now, emb, (face.kps, lmk)):
                        embeddings, landmarks = tracker.embeddings, tracker.landmarks
                        tracker.reset()
                        disp.complete_scan(embeddings, landmarks)
                        del embeddings, landmarks
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
        while time.monotonic() < next_scan:
            disp.tick(None)  # keeps /state in sync with sleep / wake between scans
            if stop.wait(min(0.2, max(0.0, next_scan - time.monotonic()))):
                return
        start = time.monotonic()
        next_scan = start + interval
        if not disp.awake:
            continue  # nobody at the machine, so nobody to scan
        disp.app_state.set_presence(True)
        while (elapsed := time.monotonic() - start) < hold_seconds:
            disp.tick(elapsed / hold_seconds)
            if stop.wait(0.1):
                return
        disp.complete_scan(crowd.hold())
        while disp.showing_result():
            if stop.wait(0.1):
                return
        disp.app_state.set_presence(False)
        disp.tick(None)


def read_stdin_keys(disp, stop):
    if not sys.stdin or not sys.stdin.isatty():
        return
    for line in sys.stdin:
        key = line.strip().lower()[:1]
        if key and not handle_key(key, disp):
            stop.set()
            return


def watch_days(disp, stop):
    while not stop.wait(60):
        disp.close_finished_days()


def flush_running_app(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/flush-solana", timeout=5) as res:
            reply = json.loads(res.read())
    except OSError as e:
        log.error("couldn't reach the running app on port %d (%s). Is vision/main.py running?", port, e)
        return 1
    if reply.get("ok"):
        log.info("queued for Solana: %s", reply["queued"])
        return 0
    log.error("%s", reply.get("error"))
    return 1


def raise_interrupt(*_):
    raise KeyboardInterrupt  # so SIGTERM runs the same cleanup as Ctrl+C


def main(argv=None):
    parser = argparse.ArgumentParser(description="dispenserve vision app")
    parser.add_argument("--no-camera", action="store_true", help="fake scans every 10s instead of the webcam")
    parser.add_argument("--no-serial", action="store_true", help="don't look for the arduino")
    parser.add_argument("--no-sensor", action="store_true", help="ignore the ultrasonic sensor and stay awake")
    parser.add_argument("--no-tiger", action="store_true", help="don't send telemetry to Tiger Data")
    parser.add_argument("--no-snowflake", action="store_true", help="don't send telemetry to Snowflake")
    parser.add_argument("--no-solana", action="store_true", help="don't write the donor ledger to Solana devnet")
    parser.add_argument("--no-gemini", action="store_true", help="rule-based restock insight only, don't call Gemini")
    parser.add_argument("--no-elevenlabs", action="store_true", help="speak with macOS say instead of ElevenLabs clips")
    parser.add_argument("--mute", action="store_true", help="no spoken lines at all")
    parser.add_argument("--flush-solana", action="store_true", help="ask the running app to write today's total to Solana, then exit")
    parser.add_argument("--liveness", action="store_true", help="reject scans that fail the anti-spoof check (default: log only)")
    parser.add_argument("--camera", type=int, help="camera index (default: CAMERA_INDEX from .env, else try 1 then 0)")
    parser.add_argument("--det-size", type=int, default=640, help="face detector input size")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)

    config.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if args.flush_solana:
        return flush_running_app(args.port)
    machine_id = config.env("MACHINE_ID", "dispenserve-1")

    app_state = AppState(config.env("BAY_NAME", "Kit Kat"), config.env_int("BAY_CAPACITY", 20))
    dispenser = Dispenser(enabled=not args.no_serial)
    disabled = {name for name in ("tiger", "snowflake") if getattr(args, f"no_{name}")}
    telemetry = Telemetry(machine_id, build_sinks(config.env, disabled))
    ledger = None if args.no_solana else SolanaLedger.from_env(machine_id, config.env)
    voice = Voice(
        api_key=None if args.no_elevenlabs else config.env("ELEVENLABS_API_KEY"),
        voice_id=config.env("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID),
        model=config.env("ELEVENLABS_MODEL", VOICE_MODEL),
        mute=args.mute,
    )
    voice.prepare()
    disp = Dispenserve(
        MemoryStore(), app_state, dispenser, telemetry=telemetry, ledger=ledger, voice=voice,
        require_liveness=args.liveness, use_sensor=not args.no_sensor and not args.no_serial,
    )
    disp.insights = Insights(
        app_state,
        api_key=None if args.no_gemini else config.env("GEMINI_API_KEY"),
        model=config.env("GEMINI_MODEL", DEFAULT_MODEL),
    )
    dispenser.on_sensor = disp.on_sensor
    dispenser.on_connection = disp.on_connection
    dispenser.start()
    server = start_server(disp, port=args.port)

    stop = threading.Event()
    signal.signal(signal.SIGTERM, raise_interrupt)
    threading.Thread(target=watch_days, args=(disp, stop), name="days", daemon=True).start()
    try:
        if args.no_camera:
            threading.Thread(target=read_stdin_keys, args=(disp, stop), daemon=True).start()
            run_fake(disp, stop)
        else:
            configured = args.camera if args.camera is not None else config.env_int("CAMERA_INDEX", None)
            indexes = [configured] if configured is not None else CAMERA_INDEXES
            run_camera(disp, indexes, args.det_size)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        disp.clear_memory()
        server.shutdown()
        dispenser.close()
        telemetry.close()
        if ledger is not None:
            ledger.close()
        log.info("bye")


if __name__ == "__main__":
    sys.exit(main())
