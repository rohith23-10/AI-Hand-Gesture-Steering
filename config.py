"""Central configuration for the Hand Gesture Steering Controller."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)

# Key names are the ones understood by pydirectinput / pyautogui.
KEY_SCHEMES = {
    "wasd": {"left": "a", "right": "d", "gas": "w", "brake": "s"},
    "arrows": {"left": "left", "right": "right", "gas": "up", "brake": "down"},
}

GESTURE_CHOICES = ("open_palm", "fist")


@dataclass
class Config:
    # --- web server ---
    host: str = "127.0.0.1"
    port: int = 5000

    # --- camera ---
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480
    target_fps: int = 30
    jpeg_quality: int = 70
    max_read_failures: int = 30  # consecutive failed reads before the camera counts as lost

    # --- storage ---
    database_path: Path = BASE_DIR / "database" / "steering.db"
    model_path: Path = BASE_DIR / "models" / "hand_landmarker.task"
    model_url: str = MODEL_URL

    # --- steering (defaults; the UI/database can override sensitivity + dead zone) ---
    steering_sensitivity: float = 1.0   # higher = less hand movement needed
    dead_zone: float = 0.05             # fraction of frame width around neutral that means "straight"
    smoothing: float = 0.4              # 0..1, lower = smoother but laggier
    base_range: float = 0.25            # hand travel (frame fraction) for full lock at sensitivity 1.0
    enter_threshold: float = 0.10       # smoothed value needed to start steering (hysteresis)
    exit_threshold: float = 0.05        # smoothed value below which steering stops (hysteresis)

    # --- gestures ---
    gesture_frames: int = 3             # frames a gesture must persist before it is accepted
    acceleration_gesture: str = "open_palm"
    brake_gesture: str = "fist"

    # --- keyboard output ---
    backend: str = "auto"               # auto | pydirectinput | pyautogui
    default_key_scheme: str = "wasd"
    pulse_period: float = 0.10          # seconds per pulse-width cycle for partial steering
    no_hand_release_delay: float = 0.10 # seconds without a hand before all keys are released

    # --- safety ---
    failsafe_enabled: bool = True       # moving the mouse to the top-left screen corner stops everything
