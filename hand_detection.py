"""MediaPipe hand landmark detection (Tasks API) and landmark drawing."""
from __future__ import annotations

import time
import urllib.request
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from config import MODEL_URL

Landmark = namedtuple("Landmark", "x y z", defaults=(0.0,))

# Wrist + the base knuckle of every finger: a stable estimate of the palm centre.
PALM_INDICES = (0, 5, 9, 13, 17)

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
)


class ModelDownloadError(RuntimeError):
    """Raised when the hand landmark model cannot be downloaded."""


@dataclass
class HandData:
    """Normalised (0..1) landmarks of one detected hand."""

    landmarks: Sequence[Landmark]

    @property
    def wrist(self) -> Tuple[float, float]:
        lm = self.landmarks[0]
        return (lm.x, lm.y)

    @property
    def palm_center(self) -> Tuple[float, float]:
        xs = [self.landmarks[i].x for i in PALM_INDICES]
        ys = [self.landmarks[i].y for i in PALM_INDICES]
        return (sum(xs) / len(xs), sum(ys) / len(ys))


def ensure_model(path, url: str = MODEL_URL) -> Path:
    """Return the model path, downloading the file once if it is missing."""
    path = Path(path)
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
    except Exception as exc:  # network errors, permission errors, ...
        if tmp.exists():
            tmp.unlink()
        raise ModelDownloadError(
            f"Could not download the hand model. Download it manually from\n{url}\n"
            f"and save it as {path}\n({exc})"
        ) from exc
    return path


class HandDetector:
    """Wraps the MediaPipe HandLandmarker (single hand, video mode)."""

    def __init__(self, model_path, model_url: str = MODEL_URL,
                 min_detection_confidence: float = 0.6,
                 min_presence_confidence: float = 0.6,
                 min_tracking_confidence: float = 0.6):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        path = ensure_model(model_path, model_url)
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=min_detection_confidence,
            min_hand_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._t0 = time.monotonic()
        self._last_ts = -1

    def detect(self, frame_bgr) -> Optional[HandData]:
        import cv2

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        ts = int((time.monotonic() - self._t0) * 1000)
        if ts <= self._last_ts:  # MediaPipe needs strictly increasing timestamps
            ts = self._last_ts + 1
        self._last_ts = ts
        result = self._landmarker.detect_for_video(image, ts)
        if not result.hand_landmarks:
            return None
        return HandData([Landmark(p.x, p.y, p.z) for p in result.hand_landmarks[0]])

    def close(self) -> None:
        try:
            self._landmarker.close()
        except Exception:
            pass


def draw_landmarks(frame, hand: HandData) -> None:
    """Draw the hand skeleton and palm centre onto a BGR frame (in place)."""
    import cv2

    h, w = frame.shape[:2]
    pts = [(int(p.x * w), int(p.y * h)) for p in hand.landmarks]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], (255, 170, 40), 2)
    for p in pts:
        cv2.circle(frame, p, 4, (255, 120, 0), -1)
    cx, cy = hand.palm_center
    cv2.circle(frame, (int(cx * w), int(cy * h)), 9, (0, 255, 255), 2)
