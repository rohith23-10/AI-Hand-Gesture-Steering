"""Gesture classification (open palm / fist) and debouncing."""
from __future__ import annotations

import math
from typing import Sequence

GESTURE_OPEN_PALM = "open_palm"
GESTURE_FIST = "fist"
GESTURE_UNKNOWN = "unknown"   # a hand is visible but the pose is ambiguous
GESTURE_NONE = "none"         # no hand

# (pip joint, fingertip) for index, middle, ring and pinky fingers.
FINGER_JOINTS = ((6, 8), (10, 12), (14, 16), (18, 20))

EXTENDED_RATIO = 1.10  # fingertip must be this much farther from the wrist than its pip joint


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def count_extended_fingers(landmarks: Sequence) -> int:
    """Number of extended fingers (index..pinky). The thumb is ignored on purpose."""
    wrist = landmarks[0]
    count = 0
    for pip, tip in FINGER_JOINTS:
        if _dist(landmarks[tip], wrist) > _dist(landmarks[pip], wrist) * EXTENDED_RATIO:
            count += 1
    return count


def classify_gesture(landmarks: Sequence) -> str:
    """Return open_palm, fist or unknown for a single frame."""
    extended = count_extended_fingers(landmarks)
    if extended >= 3:
        return GESTURE_OPEN_PALM
    if extended <= 1:
        return GESTURE_FIST
    return GESTURE_UNKNOWN


class GestureStabilizer:
    """Accepts a new gesture only after it has been seen for several frames in a row.

    This prevents one noisy frame from toggling gas/brake.
    """

    def __init__(self, frames_required: int = 3):
        self.frames_required = max(1, int(frames_required))
        self.reset()

    def reset(self) -> None:
        self._stable = GESTURE_NONE
        self._candidate = GESTURE_NONE
        self._count = 0

    @property
    def stable(self) -> str:
        return self._stable

    def update(self, raw: str) -> str:
        if raw == self._stable:
            self._candidate, self._count = raw, 0
            return self._stable
        if raw == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = raw, 1
        if self._count >= self.frames_required:
            self._stable = raw
            self._count = 0
        return self._stable
