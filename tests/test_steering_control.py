from steering_control import (DIR_CENTER, DIR_LEFT, DIR_RIGHT, SteeringController)


def settle(ctrl, x, frames=30):
    state = None
    for _ in range(frames):
        state = ctrl.update(x)
    return state


def test_hand_in_centre_goes_straight():
    state = settle(SteeringController(), 0.5)
    assert state.direction == DIR_CENTER and state.amount == 0.0


def test_hand_right_steers_right():
    state = settle(SteeringController(), 0.8)
    assert state.direction == DIR_RIGHT
    assert state.amount > 0.9 and state.value > 0


def test_hand_left_steers_left():
    state = settle(SteeringController(), 0.2)
    assert state.direction == DIR_LEFT
    assert state.amount > 0.9 and state.value < 0


def test_small_movement_inside_dead_zone_is_ignored():
    state = settle(SteeringController(dead_zone=0.08), 0.56)
    assert state.direction == DIR_CENTER


def test_partial_movement_gives_partial_steering():
    state = settle(SteeringController(), 0.65)
    assert state.direction == DIR_RIGHT
    assert 0.2 < state.amount < 0.9


def test_higher_sensitivity_needs_less_movement():
    low = settle(SteeringController(sensitivity=0.5), 0.62)
    high = settle(SteeringController(sensitivity=2.0), 0.62)
    assert high.amount > low.amount


def test_calibration_sets_new_neutral():
    ctrl = SteeringController()
    ctrl.calibrate(0.3)
    assert ctrl.calibrated and abs(ctrl.neutral_x - 0.3) < 1e-9
    assert settle(ctrl, 0.3).direction == DIR_CENTER
    assert settle(ctrl, 0.6).direction == DIR_RIGHT


def test_smoothing_prevents_instant_full_lock():
    ctrl = SteeringController(smoothing=0.3)
    first = ctrl.update(0.9)
    assert first.amount < 0.5   # moves toward full lock gradually


def test_hysteresis_avoids_flicker_near_threshold():
    ctrl = SteeringController()
    settle(ctrl, 0.65, frames=40)
    changes = 0
    last = ctrl.update(0.65).direction
    for i in range(60):
        x = 0.65 + (0.012 if i % 2 else -0.012)   # jitter around the same position
        d = ctrl.update(x).direction
        changes += d != last
        last = d
    assert changes == 0


def test_crossing_to_the_other_side_switches_direction():
    ctrl = SteeringController()
    assert settle(ctrl, 0.85).direction == DIR_RIGHT
    assert settle(ctrl, 0.15).direction == DIR_LEFT


def test_reset_clears_steering():
    ctrl = SteeringController()
    settle(ctrl, 0.85)
    ctrl.reset()
    assert ctrl.update(0.5).direction == DIR_CENTER


def test_two_hand_wheel_calibration_and_rotation():
    ctrl = SteeringController(smoothing=1.0)
    ctrl.calibrate_angle(0.0)
    assert ctrl.update_angle(0.0).direction == DIR_CENTER
    assert ctrl.update_angle(25.0).direction == DIR_RIGHT
    assert ctrl.update_angle(-25.0).direction == DIR_LEFT


def test_two_hand_wheel_small_angle_is_inside_dead_zone():
    ctrl = SteeringController(smoothing=1.0, dead_zone=0.05)
    ctrl.calibrate_angle(0.0)
    assert ctrl.update_angle(1.0).direction == DIR_CENTER
