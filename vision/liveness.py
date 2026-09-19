"""Simple anti-spoof check over the 3 second hold, from landmarks insightface already returns.

Two signals, either one counts as live:

- blink: eye openness (height / width of the eye contour in the 106-point landmarks)
  dips well below its typical value for the hold.
- depth: a flat photo, however it's waved around, moves its 5 keypoints (eyes, nose,
  mouth corners) by close to a 2D affine transform. A real head is 3D, so small natural
  turns shift the nose relative to the eyes and mouth in a way an affine fit can't
  explain. The leftover (residual), relative to eye distance, is the depth score.

Thresholds are starting guesses. Run with the flag off, read the logged scores for
real faces and for a phone photo, then adjust MOTION_MIN / BLINK_DROP.
Landmarks are only used in memory for the current hold, never stored or logged.
"""

from dataclasses import dataclass

import numpy as np

MOTION_MIN = 0.02  # mean affine residual / eye distance (synthetic: photo ~0.01, 8° head sway ~0.027)
BLINK_DROP = 0.35  # openness must fall this fraction below the hold's median
MIN_FRAMES = 5
SMOOTH_FRAMES = 3

# eye contours in insightface's 106-point landmark layout
LEFT_EYE = list(range(33, 43))
RIGHT_EYE = list(range(87, 97))


@dataclass
class LivenessResult:
    live: bool
    score: float  # >= 1.0 means live; max of the two signals relative to their thresholds
    motion: float  # affine residual / eye distance
    blink: float  # largest fractional drop in eye openness
    frames: int


def eye_openness(lmk106):
    values = []
    for idx in (LEFT_EYE, RIGHT_EYE):
        pts = np.asarray(lmk106)[idx]
        width = np.ptp(pts[:, 0])
        if width > 0:
            values.append(np.ptp(pts[:, 1]) / width)
    return float(np.mean(values)) if values else float("nan")


def blink_score(lmk_seq):
    openness = np.array([eye_openness(l) for l in lmk_seq])
    openness = openness[np.isfinite(openness)]
    if len(openness) < MIN_FRAMES:
        return 0.0
    typical = np.median(openness)
    if typical <= 0:
        return 0.0
    return float(max(0.0, 1.0 - openness.min() / typical))


def motion_score(kps_seq):
    """Mean non-affine residual of the 5 keypoints across the hold, over eye distance."""
    kps_seq = [np.asarray(k, dtype=np.float64) for k in kps_seq]
    if len(kps_seq) < MIN_FRAMES:
        return 0.0
    # detector jitter is independent per frame, real head motion is smooth: a 3-frame
    # moving average cuts the jitter floor without hiding the motion
    kps_seq = [np.mean(kps_seq[i : i + SMOOTH_FRAMES], axis=0) for i in range(len(kps_seq) - SMOOTH_FRAMES + 1)]
    ref = kps_seq[0]
    eye_dist = np.linalg.norm(ref[0] - ref[1])
    if eye_dist <= 0:
        return 0.0
    residuals = []
    for kps in kps_seq[1:]:
        src = np.hstack([kps, np.ones((len(kps), 1))])
        affine, *_ = np.linalg.lstsq(src, ref, rcond=None)
        residuals.append(np.sqrt(np.mean(np.sum((src @ affine - ref) ** 2, axis=1))))
    return float(np.mean(residuals) / eye_dist)


def check(kps_seq, lmk_seq=None):
    motion = motion_score(kps_seq)
    blink = blink_score(lmk_seq) if lmk_seq else 0.0
    score = max(motion / MOTION_MIN, blink / BLINK_DROP)
    return LivenessResult(live=score >= 1.0, score=round(score, 3), motion=round(motion, 4), blink=round(blink, 3), frames=len(kps_seq))
