"""Shared fakes for the tests (no webcam, no model, no real keyboard needed)."""
import threading
import time

import numpy as np

from hand_detection import HandData, Landmark


def make_hand(extended=(True, True, True, True), x=0.5) -> HandData:
    """Build a synthetic hand whose palm centre is near ``x``.

    ``extended`` says which of index/middle/ring/pinky are stretched out.
    """
    pts = [Landmark(x, 0.8, 0.0) for _ in range(21)]
    for i, (mcp, pip, tip) in enumerate(zip((5, 9, 13, 17), (6, 10, 14, 18), (8, 12, 16, 20))):
        fx = x + (i - 1.5) * 0.04
        pts[mcp] = Landmark(fx, 0.65, 0.0)
        pts[pip] = Landmark(fx, 0.55, 0.0)
        pts[tip] = Landmark(fx, 0.35, 0.0) if extended[i] else Landmark(fx, 0.70, 0.0)
    return HandData(pts)


OPEN = (True, True, True, True)
FIST = (False, False, False, False)


class FakeCamera:
    def __init__(self, fail_after=None):
        self.released = False
        self.reads = 0
        self.fail_after = fail_after

    def read(self):
        time.sleep(0.003)
        self.reads += 1
        if self.fail_after is not None and self.reads > self.fail_after:
            return False, None
        return True, np.zeros((120, 160, 3), dtype=np.uint8)

    def release(self):
        self.released = True


class ScriptedDetector:
    """Returns hands from a mutable ``current`` attribute (None = no hand)."""

    def __init__(self, current=None):
        self.current = current
        self.closed = False
        self._lock = threading.Lock()

    def set(self, hand):
        with self._lock:
            self.current = hand

    def detect(self, frame):
        with self._lock:
            return self.current

    def close(self):
        self.closed = True


def wait_until(predicate, timeout=3.0, interval=0.01):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()
