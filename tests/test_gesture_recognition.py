from gesture_recognition import (GESTURE_FIST, GESTURE_NONE, GESTURE_OPEN_PALM,
                                 GESTURE_UNKNOWN, GestureStabilizer, classify_gesture,
                                 count_extended_fingers)
from helpers import FIST, OPEN, make_hand


def test_open_palm_is_classified():
    hand = make_hand(OPEN)
    assert count_extended_fingers(hand.landmarks) == 4
    assert classify_gesture(hand.landmarks) == GESTURE_OPEN_PALM


def test_fist_is_classified():
    hand = make_hand(FIST)
    assert count_extended_fingers(hand.landmarks) == 0
    assert classify_gesture(hand.landmarks) == GESTURE_FIST


def test_three_fingers_still_counts_as_open_palm():
    assert classify_gesture(make_hand((True, True, True, False)).landmarks) == GESTURE_OPEN_PALM


def test_ambiguous_pose_is_unknown():
    assert classify_gesture(make_hand((True, True, False, False)).landmarks) == GESTURE_UNKNOWN


def test_stabilizer_ignores_single_noisy_frame():
    s = GestureStabilizer(frames_required=3)
    for _ in range(3):
        s.update(GESTURE_OPEN_PALM)
    assert s.stable == GESTURE_OPEN_PALM
    assert s.update(GESTURE_FIST) == GESTURE_OPEN_PALM   # one glitch frame
    assert s.update(GESTURE_OPEN_PALM) == GESTURE_OPEN_PALM


def test_stabilizer_switches_after_enough_frames():
    s = GestureStabilizer(frames_required=3)
    for _ in range(3):
        s.update(GESTURE_OPEN_PALM)
    results = [s.update(GESTURE_FIST) for _ in range(3)]
    assert results[:2] == [GESTURE_OPEN_PALM, GESTURE_OPEN_PALM]
    assert results[2] == GESTURE_FIST


def test_stabilizer_reset_returns_to_none():
    s = GestureStabilizer(frames_required=1)
    s.update(GESTURE_FIST)
    assert s.stable == GESTURE_FIST
    s.reset()
    assert s.stable == GESTURE_NONE
