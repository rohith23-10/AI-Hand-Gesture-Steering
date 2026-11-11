import pytest

from app import create_app
from config import Config
from engine import ControllerEngine
from helpers import OPEN, FakeCamera, ScriptedDetector, make_hand, wait_until
from steering_control import RecordingBackend


@pytest.fixture
def client(tmp_path):
    cfg = Config(database_path=tmp_path / "t.db", failsafe_enabled=False)
    backend = RecordingBackend()
    engine = ControllerEngine(cfg, camera_factory=lambda c: FakeCamera(),
                              detector_factory=lambda c: ScriptedDetector(make_hand(OPEN, 0.85)),
                              backend_factory=lambda c: backend, failsafe=None)
    app = create_app(cfg, engine=engine)
    yield app.test_client(), engine, backend
    engine.stop()


def test_dashboard_loads(client):
    c, *_ = client
    res = c.get("/")
    assert res.status_code == 200
    assert b"Virtual wheel" in res.data and b"Calibrate" in res.data


def test_status_when_stopped(client):
    c, *_ = client
    data = c.get("/api/status").get_json()
    assert data["running"] is False and data["camera_status"] == "disconnected"


def test_start_stop_cycle_and_session_history(client):
    c, engine, backend = client
    assert c.post("/api/start", json={"game_name": "Traffic Racer", "key_scheme": "arrows"}).get_json()["ok"]
    assert wait_until(lambda: "right" in backend.down)
    assert c.get("/api/status").get_json()["running"] is True
    assert c.post("/api/stop").get_json()["ok"]
    assert backend.down == set()
    sessions = c.get("/api/sessions").get_json()
    assert sessions and sessions[0]["game_name"] == "Traffic Racer"


def test_calibrate_requires_running(client):
    c, *_ = client
    assert c.post("/api/calibrate").status_code == 400


def test_unknown_key_scheme_is_rejected(client):
    c, *_ = client
    res = c.post("/api/start", json={"key_scheme": "dvorak"})
    assert res.status_code == 400 and "key scheme" in res.get_json()["error"]


def test_settings_are_validated_applied_and_saved(client):
    c, engine, _ = client
    assert c.post("/api/settings", json={"steering_sensitivity": 5}).status_code == 400
    ok = c.post("/api/settings", json={"steering_sensitivity": 1.5, "dead_zone": 0.07})
    assert ok.status_code == 200
    assert c.get("/api/settings").get_json()["steering_sensitivity"] == 1.5
    assert engine.steering.sensitivity == 1.5


def test_settings_persist_across_app_restart(tmp_path):
    cfg = Config(database_path=tmp_path / "t.db", failsafe_enabled=False)
    app1 = create_app(cfg, engine=ControllerEngine(cfg, failsafe=None))
    app1.test_client().post("/api/settings", json={"steering_sensitivity": 2.2})
    app2 = create_app(cfg, engine=ControllerEngine(cfg, failsafe=None))
    assert app2.test_client().get("/api/settings").get_json()["steering_sensitivity"] == 2.2
