"""Real-time controller engine: camera -> hand -> gesture -> steering -> keys."""
from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, Optional

import cv2

from config import GESTURE_CHOICES, KEY_SCHEMES, Config
from gesture_recognition import GESTURE_NONE, GestureStabilizer, classify_gesture
from hand_detection import HandDetector, draw_landmarks
from steering_control import (DIR_CENTER, KeyOutput, SteeringController, SteeringState,
                              create_backend, mouse_failsafe_triggered)


class EngineError(RuntimeError):
    """Raised when the engine cannot start (camera, model or keyboard backend problems)."""


def open_camera(cfg: Config):
    """Open the webcam; raises EngineError when it is missing or busy."""
    if os.name == "nt":
        cap = cv2.VideoCapture(cfg.camera_index, cv2.CAP_DSHOW)  # faster start-up on Windows
    else:
        cap = cv2.VideoCapture(cfg.camera_index)
    if not cap.isOpened():
        cap.release()
        raise EngineError(
            f"Could not open camera {cfg.camera_index}. Close other apps that use the "
            "webcam, check Windows camera privacy settings, or change camera_index in config.py."
        )
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.frame_height)
    cap.set(cv2.CAP_PROP_FPS, cfg.target_fps)
    return cap


class ControllerEngine:
    """Runs the capture/processing loop in a background thread."""

    def __init__(self, config: Optional[Config] = None, db=None, user_id: Optional[int] = None,
                 camera_factory: Optional[Callable] = None,
                 detector_factory: Optional[Callable] = None,
                 backend_factory: Optional[Callable] = None,
                 failsafe: Optional[Callable[[], bool]] = None):
        self.config = config or Config()
        self.db = db
        self.user_id = user_id
        self._camera_factory = camera_factory or open_camera
        self._detector_factory = detector_factory or (
            lambda cfg: HandDetector(cfg.model_path, cfg.model_url))
        self._backend_factory = backend_factory or (lambda cfg: create_backend(cfg.backend))
        if failsafe is not None:
            self._failsafe = failsafe
        else:
            self._failsafe = mouse_failsafe_triggered if self.config.failsafe_enabled else None

        cfg = self.config
        self.settings: Dict = {
            "steering_sensitivity": cfg.steering_sensitivity,
            "dead_zone": cfg.dead_zone,
            "acceleration_gesture": cfg.acceleration_gesture,
            "brake_gesture": cfg.brake_gesture,
        }
        self.steering = SteeringController(
            sensitivity=cfg.steering_sensitivity, dead_zone=cfg.dead_zone,
            smoothing=cfg.smoothing, base_range=cfg.base_range,
            enter_threshold=cfg.enter_threshold, exit_threshold=cfg.exit_threshold)
        self._stabilizer = GestureStabilizer(cfg.gesture_frames)

        self._lock = threading.RLock()
        self._frame_cond = threading.Condition()
        self._stop_event = threading.Event()
        self._calibrate_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._camera = None
        self._detector = None
        self.key_output: Optional[KeyOutput] = None
        self._jpeg: Optional[bytes] = None
        self._frame_id = 0
        self._running = False
        self._started_at = 0.0
        self._steering_events = 0
        self._game_name = ""
        self._send_keys = True
        self._key_scheme = cfg.default_key_scheme
        self._status = self._blank_status()

    # ------------------------------------------------------------- settings
    def apply_settings(self, steering_sensitivity=None, dead_zone=None,
                       acceleration_gesture=None, brake_gesture=None, **_ignored) -> Dict:
        """Validate and apply settings immediately (works while running)."""
        with self._lock:
            new = dict(self.settings)
            if steering_sensitivity is not None:
                v = float(steering_sensitivity)
                if not SteeringController.MIN_SENSITIVITY <= v <= SteeringController.MAX_SENSITIVITY:
                    raise ValueError("steering_sensitivity must be between 0.3 and 3.0")
                new["steering_sensitivity"] = v
            if dead_zone is not None:
                v = float(dead_zone)
                if not 0.0 <= v <= 0.2:
                    raise ValueError("dead_zone must be between 0 and 0.2")
                new["dead_zone"] = v
            if acceleration_gesture is not None:
                if acceleration_gesture not in GESTURE_CHOICES:
                    raise ValueError(f"acceleration_gesture must be one of {GESTURE_CHOICES}")
                new["acceleration_gesture"] = acceleration_gesture
            if brake_gesture is not None:
                if brake_gesture not in GESTURE_CHOICES:
                    raise ValueError(f"brake_gesture must be one of {GESTURE_CHOICES}")
                new["brake_gesture"] = brake_gesture
            if new["acceleration_gesture"] == new["brake_gesture"]:
                raise ValueError("acceleration and brake gestures must be different")
            self.settings = new
            self.steering.sensitivity = new["steering_sensitivity"]
            self.steering.dead_zone = new["dead_zone"]
            return dict(self.settings)

    # ------------------------------------------------------------- lifecycle
    @property
    def running(self) -> bool:
        return self._running

    def start(self, game_name: str = "", send_keys: bool = True, key_scheme: Optional[str] = None) -> None:
        with self._lock:
            if self._running:
                raise EngineError("Already running")
            scheme = key_scheme or self.config.default_key_scheme
            if scheme not in KEY_SCHEMES:
                raise EngineError(f"Unknown key scheme '{scheme}'")

            self._set_status(camera_status="connecting", error=None, message="Starting camera...")
            camera = detector = None
            try:
                camera = self._camera_factory(self.config)
                detector = self._detector_factory(self.config)
                key_output = None
                if send_keys:
                    key_output = KeyOutput(self._backend_factory(self.config),
                                           KEY_SCHEMES[scheme], self.config.pulse_period)
            except Exception as exc:
                if camera is not None:
                    try:
                        camera.release()
                    except Exception:
                        pass
                self._set_status(camera_status="error", error=str(exc), message="")
                if isinstance(exc, EngineError):
                    raise
                raise EngineError(str(exc)) from exc

            self._camera, self._detector, self.key_output = camera, detector, key_output
            self._game_name = game_name or "Unknown game"
            self._send_keys = send_keys
            self._key_scheme = scheme
            self._steering_events = 0
            self._started_at = time.monotonic()
            self._stabilizer.reset()
            self.steering.reset()
            self._stop_event.clear()
            self._calibrate_flag.clear()
            self._running = True
            self._set_status(camera_status="connected", error=None, message="Running")
            self._thread = threading.Thread(target=self._run, name="gesture-engine", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop_event.set()
        if thread is not threading.current_thread():
            thread.join(timeout=5)
        if self.key_output is not None:  # belt and braces: never leave keys held
            self.key_output.release_all()

    def calibrate(self) -> None:
        """Use the hand position in the next frame as the neutral (straight) position."""
        self._calibrate_flag.set()
        self._set_status(message="Calibrating: hold both hands like a straight steering wheel")

    # ------------------------------------------------------------- status / frames
    def _blank_status(self) -> Dict:
        return {
            "running": False, "camera_status": "disconnected", "error": None, "message": "Stopped",
            "fps": 0.0, "hand_detected": False, "gesture": GESTURE_NONE,
            "steering": {"direction": DIR_CENTER, "amount": 0.0, "value": 0.0},
            "accelerating": False, "braking": False, "calibrated": False,
            "neutral_x": 0.5, "steering_events": 0, "sending_keys": False,
            "keys_down": [], "game_name": "", "key_scheme": self.config.default_key_scheme,
        }

    def _set_status(self, **fields) -> None:
        with self._lock:
            self._status.update(fields)

    def get_status(self) -> Dict:
        with self._lock:
            status = dict(self._status)
            status["steering"] = dict(status["steering"])
            status["settings"] = dict(self.settings)
            status["running"] = self._running
            status["session_seconds"] = (
                round(time.monotonic() - self._started_at, 1) if self._running else 0.0)
            return status

    def wait_for_frame(self, last_id: int, timeout: float = 1.0):
        """Block until a newer JPEG frame exists; returns (frame_id, bytes) or None."""
        with self._frame_cond:
            if self._frame_id <= last_id:
                self._frame_cond.wait(timeout)
            if self._frame_id > last_id and self._jpeg is not None:
                return self._frame_id, self._jpeg
        return None

    # ------------------------------------------------------------- main loop
    def _apply_keys(self, state: SteeringState, gas: bool, brake: bool, now: float) -> None:
        if self.key_output is not None:
            self.key_output.apply(state.direction, state.amount, gas, brake, now)

    def _release_keys(self) -> None:
        if self.key_output is not None:
            self.key_output.release_all()

    def _run(self) -> None:
        cfg = self.config
        state = SteeringState()
        gesture = GESTURE_NONE
        hand_detected = False
        gas = brake = False
        no_hand_since: Optional[float] = None
        read_failures = 0
        last_direction = DIR_CENTER
        fps = 0.0
        prev = time.perf_counter()
        error: Optional[str] = None
        try:
            while not self._stop_event.is_set():
                ok, frame = self._camera.read()
                if not ok or frame is None:
                    read_failures += 1
                    if read_failures >= cfg.max_read_failures:
                        error = "Camera connection lost"
                        break
                    time.sleep(0.02)
                    continue
                read_failures = 0

                if self._failsafe is not None and self._failsafe():
                    error = "Failsafe triggered (mouse in top-left corner)"
                    break

                frame = cv2.flip(frame, 1)  # mirror: moving your hand right moves it right on screen
                now = time.monotonic()
                # The production detector supports two-hand wheel control. Older
                # injected detectors retain their one-hand path for compatibility.
                two_hand_mode = hasattr(self._detector, "detect_all")
                if two_hand_mode:
                    hands = self._detector.detect_all(frame)
                else:
                    single = self._detector.detect(frame)
                    hands = [single] if single is not None else []
                hand = hands[0] if hands else None

                if two_hand_mode and len(hands) >= 2:
                    hand_detected = True
                    no_hand_since = None
                    left_hand, right_hand = sorted(hands[:2], key=lambda item: item.palm_center[0])
                    lx, ly = left_hand.palm_center
                    rx, ry = right_hand.palm_center
                    import math
                    wheel_angle = math.degrees(math.atan2(ry - ly, rx - lx))
                    gesture = self._stabilizer.update(classify_gesture(hand.landmarks))
                    if self._calibrate_flag.is_set():
                        self.steering.calibrate_angle(wheel_angle)
                        self._calibrate_flag.clear()
                        self._set_status(message="Wheel calibrated: hold both hands at the centre")
                    state = self.steering.update_angle(wheel_angle)
                    gas = gesture == self.settings["acceleration_gesture"]
                    brake = gesture == self.settings["brake_gesture"]
                    if brake:
                        gas = False
                    self._apply_keys(state, gas, brake, now)
                elif not two_hand_mode and hand is not None:
                    # Compatibility path for older one-hand detector integrations.
                    hand_detected = True
                    no_hand_since = None
                    gesture = self._stabilizer.update(classify_gesture(hand.landmarks))
                    cx, _ = hand.palm_center
                    if self._calibrate_flag.is_set():
                        self.steering.calibrate(cx)
                        self._calibrate_flag.clear()
                        self._set_status(message="Calibrated")
                    state = self.steering.update(cx)
                    gas = gesture == self.settings["acceleration_gesture"]
                    brake = gesture == self.settings["brake_gesture"]
                    if brake:
                        gas = False
                    self._apply_keys(state, gas, brake, now)
                else:
                    # The production two-hand wheel requires both hands. Missing either
                    # hand releases controls after the configured dropout delay.
                    hand_detected = False
                    if no_hand_since is None:
                        no_hand_since = now
                    if now - no_hand_since >= cfg.no_hand_release_delay:
                        self._stabilizer.reset()
                        self.steering.reset()
                        state, gesture, gas, brake = SteeringState(), GESTURE_NONE, False, False
                        self._release_keys()
                    else:
                        self._apply_keys(state, gas, brake, now)

                if state.direction != DIR_CENTER and state.direction != last_direction:
                    self._steering_events += 1
                last_direction = state.direction

                t = time.perf_counter()
                dt = t - prev
                prev = t
                if dt > 0:
                    fps = (1.0 / dt) if fps == 0 else 0.9 * fps + 0.1 * (1.0 / dt)

                self._draw_overlay(frame, hands, state, gesture, fps)
                self._publish(frame)
                self._set_status(
                    fps=round(fps, 1), hand_detected=hand_detected, gesture=gesture,
                    steering={"direction": state.direction, "amount": round(state.amount, 3),
                              "value": round(state.value, 3)},
                    accelerating=gas, braking=brake, calibrated=self.steering.calibrated,
                    neutral_x=round(self.steering.neutral_x, 3),
                    steering_events=self._steering_events,
                    sending_keys=self._send_keys,
                    keys_down=sorted(self.key_output.pressed) if self.key_output else [],
                    game_name=self._game_name, key_scheme=self._key_scheme)
        except Exception as exc:  # never let the thread die with keys held
            error = f"Processing error: {exc}"
        finally:
            self._cleanup(error)

    def _cleanup(self, error: Optional[str]) -> None:
        self._release_keys()
        for resource, closer in ((self._detector, "close"), (self._camera, "release")):
            if resource is not None:
                try:
                    getattr(resource, closer)()
                except Exception:
                    pass
        duration = time.monotonic() - self._started_at
        if self.db is not None and self.user_id is not None:
            try:
                self.db.record_session(self.user_id, self._game_name, duration, self._steering_events)
            except Exception:
                pass
        with self._lock:
            self._running = False
            self._thread = None
            self._status.update(
                running=False, camera_status="error" if error else "disconnected",
                error=error, message=error or "Stopped", hand_detected=False,
                gesture=GESTURE_NONE, accelerating=False, braking=False, keys_down=[],
                steering={"direction": DIR_CENTER, "amount": 0.0, "value": 0.0}, fps=0.0)
        with self._frame_cond:
            self._frame_cond.notify_all()

    # ------------------------------------------------------------- drawing
    def _draw_overlay(self, frame, hands, state: SteeringState, gesture: str, fps: float) -> None:
        h, w = frame.shape[:2]
        centre = int(self.steering.neutral_x * w)
        dz = int(self.steering.dead_zone * w)
        cv2.line(frame, (centre, 0), (centre, h), (255, 170, 40), 1)
        cv2.rectangle(frame, (centre - dz, 0), (centre + dz, h), (255, 170, 40), 1)
        for detected_hand in hands:
            draw_landmarks(frame, detected_hand)
        label = f"{fps:4.1f} FPS | 2-hand wheel | {gesture} | {state.direction} {state.amount:.2f}"
        cv2.putText(frame, label, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    def _publish(self, frame) -> None:
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.config.jpeg_quality])
        if ok:
            with self._frame_cond:
                self._jpeg = buf.tobytes()
                self._frame_id += 1
                self._frame_cond.notify_all()
