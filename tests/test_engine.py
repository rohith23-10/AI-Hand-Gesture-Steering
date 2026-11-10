"""End-to-end tests of the engine with a fake camera, scripted hands and a recording keyboard."""
import pytest

from config import Config
from database import Database
from engine import ControllerEngine, EngineError
from helpers import FIST, OPEN, FakeCamera, ScriptedDetector, make_hand, wait_until
from steering_control import RecordingBackend


@pytest.fixture
def rig(tmp_path):
    cfg = Config(database_path=tmp_path / "t.db", failsafe_enabled=False,
                 no_hand_release_delay=0.05, gesture_frames=2, smoothing=0.8)
    db = Database(cfg.database_path)
    uid = db.get_or_create_default_user()
    backend = RecordingBackend()
    camera = FakeCamera()
    detector = ScriptedDetector(make_hand(OPEN, x=0.5))
    engine = ControllerEngine(cfg, db=db, user_id=uid,
                              camera_factory=lambda c: camera,
                              detector_factory=lambda c: detector,
                              backend_factory=lambda c: backend,
                              failsafe=None)
    yield engine, backend, camera, detector, db, uid
    engine.stop()


def test_open_palm_in_centre_accelerates_without_steering(rig):
    engine, backend, _, _, _, _ = rig
    engine.start("Test Game")
    assert wait_until(lambda: backend.down == {"w"})
    status = engine.get_status()
    assert status["accelerating"] and status["steering"]["direction"] == "center"


def test_hand_right_and_left_steer(rig):
    engine, backend, _, detector, _, _ = rig
    engine.start("Test Game")
    detector.set(make_hand(OPEN, x=0.85))
    assert wait_until(lambda: "d" in backend.down)
    detector.set(make_hand(OPEN, x=0.15))
    assert wait_until(lambda: "a" in backend.down and "d" not in backend.down)


def test_fist_brakes_and_releases_gas(rig):
    engine, backend, _, detector, _, _ = rig
    engine.start("Test Game")
    assert wait_until(lambda: "w" in backend.down)
    detector.set(make_hand(FIST, x=0.5))
    assert wait_until(lambda: backend.down == {"s"})
    assert engine.get_status()["braking"]


def test_no_hand_releases_all_keys(rig):
    engine, backend, _, detector, _, _ = rig
    engine.start("Test Game")
    detector.set(make_hand(OPEN, x=0.85))
    assert wait_until(lambda: {"d", "w"} <= backend.down)
    detector.set(None)
    assert wait_until(lambda: backend.down == set())
    assert engine.get_status()["hand_detected"] is False


def test_stop_releases_keys_closes_camera_and_saves_session(rig):
    engine, backend, camera, detector, db, uid = rig
    engine.start("Traffic Racer")
    detector.set(make_hand(OPEN, x=0.85))
    assert wait_until(lambda: "d" in backend.down)
    engine.stop()
    assert backend.down == set()
    assert camera.released and detector.closed
    assert not engine.running
    sessions = db.list_sessions(uid)
    assert len(sessions) == 1
    assert sessions[0]["game_name"] == "Traffic Racer" and sessions[0]["steering_events"] >= 1


def test_calibration_moves_neutral_to_hand_position(rig):
    engine, backend, _, detector, _, _ = rig
    detector.set(make_hand(OPEN, x=0.3))
    engine.start("Test Game")
    engine.calibrate()
    assert wait_until(lambda: abs(engine.get_status()["neutral_x"] - 0.3) < 0.02)
    assert wait_until(lambda: engine.get_status()["steering"]["direction"] == "center")
    assert "a" not in backend.down and "d" not in backend.down


def test_dry_run_does_not_send_keys(rig):
    engine, backend, _, _, _, _ = rig
    engine.start("Test Game", send_keys=False)
    assert wait_until(lambda: engine.get_status()["accelerating"])
    assert backend.events == []


def test_lost_camera_stops_safely_with_error(tmp_path):
    cfg = Config(database_path=tmp_path / "t.db", failsafe_enabled=False, max_read_failures=3)
    backend = RecordingBackend()
    engine = ControllerEngine(cfg, camera_factory=lambda c: FakeCamera(fail_after=15),
                              detector_factory=lambda c: ScriptedDetector(make_hand(OPEN, x=0.85)),
                              backend_factory=lambda c: backend, failsafe=None)
    engine.start("Test Game")
    assert wait_until(lambda: not engine.running, timeout=5)
    status = engine.get_status()
    assert "Camera connection lost" in status["error"]
    assert backend.down == set()


def test_failsafe_stops_everything(tmp_path):
    cfg = Config(database_path=tmp_path / "t.db")
    backend = RecordingBackend()
    trigger = {"on": False}
    engine = ControllerEngine(cfg, camera_factory=lambda c: FakeCamera(),
                              detector_factory=lambda c: ScriptedDetector(make_hand(OPEN, x=0.85)),
                              backend_factory=lambda c: backend,
                              failsafe=lambda: trigger["on"])
    engine.start("Test Game")
    assert wait_until(lambda: "d" in backend.down)
    trigger["on"] = True
    assert wait_until(lambda: not engine.running)
    assert backend.down == set()
    assert "Failsafe" in engine.get_status()["error"]


def test_camera_open_failure_raises_engine_error(tmp_path):
    def broken(cfg):
        raise EngineError("no camera")

    engine = ControllerEngine(Config(database_path=tmp_path / "t.db", failsafe_enabled=False),
                              camera_factory=broken, detector_factory=lambda c: ScriptedDetector(),
                              backend_factory=lambda c: RecordingBackend(), failsafe=None)
    with pytest.raises(EngineError):
        engine.start("x")
    assert not engine.running
    assert engine.get_status()["camera_status"] == "error"


def test_cannot_start_twice(rig):
    engine, *_ = rig
    engine.start("A")
    with pytest.raises(EngineError):
        engine.start("B")


def test_settings_validation_and_live_update(rig):
    engine, *_ = rig
    applied = engine.apply_settings(steering_sensitivity=2.0, dead_zone=0.1)
    assert applied["steering_sensitivity"] == 2.0 and engine.steering.dead_zone == 0.1
    with pytest.raises(ValueError):
        engine.apply_settings(steering_sensitivity=9)
    with pytest.raises(ValueError):
        engine.apply_settings(acceleration_gesture="fist")  # same as brake gesture
    engine.apply_settings(acceleration_gesture="fist", brake_gesture="open_palm")
    assert engine.settings["acceleration_gesture"] == "fist"


def test_swapped_gestures_swap_gas_and_brake(rig):
    engine, backend, _, _, _, _ = rig
    engine.apply_settings(acceleration_gesture="fist", brake_gesture="open_palm")
    engine.start("Test Game")
    assert wait_until(lambda: backend.down == {"s"})   # open palm now brakes
