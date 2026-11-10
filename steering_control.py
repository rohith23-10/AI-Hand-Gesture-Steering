"""Steering logic and safe keyboard output."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

DIR_LEFT = "left"
DIR_RIGHT = "right"
DIR_CENTER = "center"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class SteeringState:
    direction: str = DIR_CENTER
    amount: float = 0.0   # 0..1 magnitude of the turn
    value: float = 0.0    # -1..1 signed (negative = left)


class SteeringController:
    """Turns the horizontal palm position (0..1, mirrored) into a steering state.

    * ``calibrate`` sets the neutral position.
    * A dead zone around neutral means "straight".
    * Exponential smoothing and enter/exit hysteresis stop rapid flicker.
    """

    MIN_SENSITIVITY = 0.3
    MAX_SENSITIVITY = 3.0

    def __init__(self, sensitivity: float = 1.0, dead_zone: float = 0.05,
                 smoothing: float = 0.4, base_range: float = 0.25,
                 enter_threshold: float = 0.10, exit_threshold: float = 0.05,
                 neutral_x: float = 0.5):
        self.sensitivity = sensitivity
        self.dead_zone = dead_zone
        self.smoothing = _clamp(smoothing, 0.05, 1.0)
        self.base_range = base_range
        self.enter_threshold = enter_threshold
        self.exit_threshold = min(exit_threshold, enter_threshold)
        self.neutral_x = neutral_x
        self.neutral_angle = 0.0
        self.wheel_calibrated = False
        self.max_wheel_angle = 45.0
        self.calibrated = False
        self._value = 0.0
        self._direction = DIR_CENTER

    @property
    def sensitivity(self) -> float:
        return self._sensitivity

    @sensitivity.setter
    def sensitivity(self, v: float) -> None:
        self._sensitivity = _clamp(float(v), self.MIN_SENSITIVITY, self.MAX_SENSITIVITY)

    @property
    def dead_zone(self) -> float:
        return self._dead_zone

    @dead_zone.setter
    def dead_zone(self, v: float) -> None:
        self._dead_zone = _clamp(float(v), 0.0, 0.2)

    def calibrate(self, x: float) -> None:
        """Use the current hand position as the neutral (straight) position."""
        self.neutral_x = _clamp(x, 0.1, 0.9)
        self.calibrated = True
        self.reset()

    def calibrate_angle(self, angle_degrees: float) -> None:
        """Set the current line angle between the two hands as straight ahead."""
        self.neutral_angle = float(angle_degrees)
        self.wheel_calibrated = True
        self.calibrated = True
        self.reset()

    def update_angle(self, angle_degrees: float) -> SteeringState:
        """Convert two-hand steering-wheel rotation into the normal steering state.

        The angle is measured from the left palm to the right palm. Positive
        rotation maps to right steering; negative rotation maps to left.
        """
        delta = float(angle_degrees) - self.neutral_angle
        # Hand-line orientation is periodic over 180 degrees. Wrap to [-90, 90].
        delta = (delta + 90.0) % 180.0 - 90.0
        normalised = 0.5 + max(-1.0, min(1.0, delta / self.max_wheel_angle)) * 0.5
        return self.update(normalised)

    def reset(self) -> None:
        self._value = 0.0
        self._direction = DIR_CENTER

    def update(self, x: float) -> SteeringState:
        offset = x - self.neutral_x
        half_range = max(self.base_range / self.sensitivity, self.dead_zone + 0.02)
        magnitude = abs(offset)

        if magnitude <= self.dead_zone:
            target = 0.0
        else:
            target = min(1.0, (magnitude - self.dead_zone) / (half_range - self.dead_zone))
            target = target if offset > 0 else -target

        self._value += self.smoothing * (target - self._value)
        m = abs(self._value)
        want = DIR_RIGHT if self._value > 0 else DIR_LEFT

        if self._direction == DIR_CENTER:
            if m >= self.enter_threshold:
                self._direction = want
        elif self._direction == want:
            if m < self.exit_threshold:
                self._direction = DIR_CENTER
        else:  # hand crossed to the other side
            self._direction = want if m >= self.enter_threshold else DIR_CENTER

        amount = m if self._direction != DIR_CENTER else 0.0
        return SteeringState(self._direction, amount, self._value if amount else 0.0)


# ---------------------------------------------------------------- keyboard backends
class KeyBackend:
    def key_down(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def key_up(self, key: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class RecordingBackend(KeyBackend):
    """Does not touch the keyboard; records events. Used for tests and dry runs."""

    def __init__(self):
        self.events: List[Tuple[str, str]] = []
        self.down: Set[str] = set()

    def key_down(self, key: str) -> None:
        self.events.append(("down", key))
        self.down.add(key)

    def key_up(self, key: str) -> None:
        self.events.append(("up", key))
        self.down.discard(key)


class PyDirectInputBackend(KeyBackend):
    """Sends hardware scan codes. Works in many games that ignore normal key events."""

    def __init__(self):
        import pydirectinput

        pydirectinput.PAUSE = 0
        pydirectinput.FAILSAFE = False
        self._p = pydirectinput

    def key_down(self, key: str) -> None:
        self._p.keyDown(key)

    def key_up(self, key: str) -> None:
        self._p.keyUp(key)


class PyAutoGUIBackend(KeyBackend):
    def __init__(self):
        import pyautogui

        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = False  # we run our own failsafe
        self._p = pyautogui

    def key_down(self, key: str) -> None:
        self._p.keyDown(key)

    def key_up(self, key: str) -> None:
        self._p.keyUp(key)


def create_backend(name: str = "auto") -> KeyBackend:
    """pydirectinput first (best for games), then pyautogui."""
    errors = []
    candidates = {
        "auto": (PyDirectInputBackend, PyAutoGUIBackend),
        "pydirectinput": (PyDirectInputBackend,),
        "pyautogui": (PyAutoGUIBackend,),
    }.get(name, ())
    for cls in candidates:
        try:
            return cls()
        except Exception as exc:  # missing package, no display, ...
            errors.append(f"{cls.__name__}: {exc}")
    raise RuntimeError("No keyboard backend available. " + "; ".join(errors))


# ---------------------------------------------------------------- key output
class KeyOutput:
    """Holds/releases game keys for a steering state. Always releasable with release_all()."""

    def __init__(self, backend: KeyBackend, keys: Dict[str, str], pulse_period: float = 0.10):
        self.backend = backend
        self.keys = dict(keys)
        self.pulse_period = max(0.02, pulse_period)
        self._down: Set[str] = set()

    @property
    def pressed(self) -> Set[str]:
        return set(self._down)

    def _set(self, key: str, want_down: bool) -> None:
        if want_down and key not in self._down:
            self.backend.key_down(key)
            self._down.add(key)
        elif not want_down and key in self._down:
            self.backend.key_up(key)
            self._down.discard(key)

    def apply(self, direction: str, amount: float, gas: bool, brake: bool,
              now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        phase = (now % self.pulse_period) / self.pulse_period
        pulse_on = phase < amount  # pulse-width steering: bigger turn = longer key press

        self._set(self.keys["right"], direction == DIR_RIGHT and pulse_on)
        self._set(self.keys["left"], direction == DIR_LEFT and pulse_on)
        self._set(self.keys["brake"], brake)
        self._set(self.keys["gas"], gas and not brake)

    def release_all(self) -> None:
        for key in list(self._down):
            try:
                self.backend.key_up(key)
            finally:
                self._down.discard(key)


# ---------------------------------------------------------------- failsafe
def mouse_failsafe_triggered(margin: int = 2) -> bool:
    """True when the mouse pointer sits in the top-left corner of the screen."""
    try:
        import pyautogui

        x, y = pyautogui.position()
        return x <= margin and y <= margin
    except Exception:
        return False
