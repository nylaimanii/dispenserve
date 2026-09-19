import numpy as np

import liveness
from main import NOT_LIVE, Dispenserve
from memory import DISPENSE, MemoryStore
from serial_link import Dispenser
from state import AppState

# 3D keypoints: left eye, right eye, nose tip (sticks out toward the camera), mouth corners
FACE_3D = np.array([[-30, -20, 0], [30, -20, 0], [0, 10, 25], [-22, 35, 0], [22, 35, 0]], float)
FRAMES = 15


def rotation(yaw, pitch):
    y, p = np.radians(yaw), np.radians(pitch)
    ry = np.array([[np.cos(y), 0, np.sin(y)], [0, 1, 0], [-np.sin(y), 0, np.cos(y)]])
    rx = np.array([[1, 0, 0], [0, np.cos(p), -np.sin(p)], [0, np.sin(p), np.cos(p)]])
    return ry @ rx


def real_head(rng, degrees=12, jitter=0.5):
    """A head swaying ~12°, projected to 2D, with detector jitter. Around 8° sits right at the
    threshold, so small movements alone are borderline; blinks carry those cases."""
    t = np.linspace(0, 1, FRAMES)
    return [
        (FACE_3D @ rotation(degrees * np.sin(4.4 * ti), 0.6 * degrees * np.sin(3.1 * ti + 1)).T)[:, :2]
        + [320, 240]
        + rng.normal(0, jitter, (5, 2))
        for ti in t
    ]


def phone_photo(rng, jitter=0.5):
    """A flat photo waved around: scaled, sheared, rotated and shifted in 2D."""
    flat = (FACE_3D @ rotation(3, 2).T)[:, :2]
    frames = []
    for i in range(FRAMES):
        affine = np.eye(2) * (1 + 0.05 * np.sin(i / 3)) + np.array([[0, 0.05], [-0.05, 0]]) * np.sin(i / 4)
        frames.append(flat @ affine.T + [320 + 10 * np.sin(i / 2), 240] + rng.normal(0, jitter, (5, 2)))
    return frames


def eye_landmarks(openness):
    """106-point landmarks where only the eye contours matter: width 30, height 30 * openness."""
    lmk = np.zeros((106, 2))
    for idx, cx in ((liveness.LEFT_EYE, 290), (liveness.RIGHT_EYE, 350)):
        angles = np.linspace(0, 2 * np.pi, len(idx), endpoint=False)
        lmk[idx] = np.c_[cx + 15 * np.cos(angles), 220 + 15 * openness * np.sin(angles)]
    return lmk


def test_flat_photo_is_not_live(rng):
    result = liveness.check(phone_photo(rng), [eye_landmarks(0.4)] * FRAMES)
    assert not result.live
    assert result.motion < liveness.MOTION_MIN


def test_swaying_head_is_live(rng):
    result = liveness.check(real_head(rng), [eye_landmarks(0.4)] * FRAMES)
    assert result.live
    assert result.motion > liveness.MOTION_MIN


def test_blink_is_live_even_when_still(rng):
    openness = [0.4] * FRAMES
    openness[7] = 0.1
    result = liveness.check(phone_photo(rng), [eye_landmarks(o) for o in openness])
    assert result.live
    assert result.blink > liveness.BLINK_DROP


def test_too_few_frames_is_not_live(rng):
    assert not liveness.check(real_head(rng)[:3]).live


def test_liveness_flag_off_only_logs(rng, person):
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), require_liveness=False)
    landmarks = list(zip(phone_photo(rng), [eye_landmarks(0.4)] * FRAMES))
    assert app.complete_scan([person()], landmarks).outcome == DISPENSE


def test_liveness_flag_on_rejects_photo(rng, person):
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), require_liveness=True)
    landmarks = list(zip(phone_photo(rng), [eye_landmarks(0.4)] * FRAMES))
    assert app.complete_scan([person()], landmarks).outcome == NOT_LIVE
    assert len(app.store) == 0  # a rejected spoof is never remembered
    assert app.app_state.stats_json()["dispensed_today"] == 0


def test_liveness_error_fails_open(person):
    app = Dispenserve(MemoryStore(), AppState("Kit Kat", 24), Dispenser(enabled=False), require_liveness=True)
    garbage = [("not", "landmarks")] * FRAMES
    assert app.complete_scan([person()], garbage).outcome == DISPENSE
