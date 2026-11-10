import pytest

from config import KEY_SCHEMES
from steering_control import (DIR_CENTER, DIR_LEFT, DIR_RIGHT, KeyOutput, RecordingBackend,
                              create_backend)


@pytest.fixture
def out():
    backend = RecordingBackend()
    return KeyOutput(backend, KEY_SCHEMES["wasd"], pulse_period=0.1), backend


def test_steer_right_holds_right_key(out):
    ko, backend = out
    ko.apply(DIR_RIGHT, 1.0, gas=False, brake=False, now=0.05)
    assert backend.down == {"d"}


def test_steer_left_holds_left_key(out):
    ko, backend = out
    ko.apply(DIR_LEFT, 1.0, gas=False, brake=False, now=0.05)
    assert backend.down == {"a"}


def test_switching_direction_releases_the_other_key(out):
    ko, backend = out
    ko.apply(DIR_RIGHT, 1.0, False, False, now=0.05)
    ko.apply(DIR_LEFT, 1.0, False, False, now=0.06)
    assert backend.down == {"a"}


def test_acceleration_holds_gas(out):
    ko, backend = out
    ko.apply(DIR_CENTER, 0.0, gas=True, brake=False, now=0.0)
    assert backend.down == {"w"}


def test_braking_holds_brake_and_overrides_gas(out):
    ko, backend = out
    ko.apply(DIR_CENTER, 0.0, gas=True, brake=False, now=0.0)
    ko.apply(DIR_CENTER, 0.0, gas=True, brake=True, now=0.01)
    assert backend.down == {"s"}


def test_partial_steering_pulses(out):
    ko, backend = out
    ko.apply(DIR_RIGHT, 0.5, False, False, now=0.02)   # phase 0.2 -> on
    assert "d" in backend.down
    ko.apply(DIR_RIGHT, 0.5, False, False, now=0.08)   # phase 0.8 -> off
    assert "d" not in backend.down


def test_release_all_leaves_no_key_pressed(out):
    ko, backend = out
    ko.apply(DIR_RIGHT, 1.0, gas=True, brake=False, now=0.05)
    assert backend.down
    ko.release_all()
    assert backend.down == set() and ko.pressed == set()


def test_release_all_is_safe_when_nothing_is_pressed(out):
    ko, backend = out
    ko.release_all()
    assert backend.events == []


def test_arrow_key_scheme():
    backend = RecordingBackend()
    ko = KeyOutput(backend, KEY_SCHEMES["arrows"])
    ko.apply(DIR_LEFT, 1.0, gas=True, brake=False, now=0.0)
    assert backend.down == {"left", "up"}


def test_create_backend_unknown_name_raises():
    with pytest.raises(RuntimeError):
        create_backend("does-not-exist")
