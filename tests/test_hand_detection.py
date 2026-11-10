"""Hand detection tests.

The landmark maths and the model loader are tested directly. The real MediaPipe model is
only exercised when ``mediapipe`` is installed and the model file is available; that test
confirms the detector loads and reports "no hand" on an empty frame. Detecting a real hand
needs a webcam image and has to be checked by running the app.
"""
import pytest

import hand_detection
from hand_detection import HandData, Landmark, ModelDownloadError, ensure_model
from helpers import make_hand


def test_palm_center_is_average_of_palm_points():
    pts = [Landmark(0.0, 0.0) for _ in range(21)]
    for i, (x, y) in zip((0, 5, 9, 13, 17), ((0.2, 0.8), (0.4, 0.6), (0.5, 0.5), (0.6, 0.6), (0.8, 0.8))):
        pts[i] = Landmark(x, y)
    cx, cy = HandData(pts).palm_center
    assert cx == pytest.approx(0.5) and cy == pytest.approx(0.66)


def test_synthetic_hand_is_centred_where_requested():
    assert make_hand(x=0.3).palm_center[0] == pytest.approx(0.3, abs=0.01)


def test_ensure_model_uses_existing_file_without_downloading(tmp_path, monkeypatch):
    model = tmp_path / "m.task"
    model.write_bytes(b"x")
    monkeypatch.setattr(hand_detection.urllib.request, "urlretrieve",
                        lambda *a, **k: pytest.fail("should not download"))
    assert ensure_model(model) == model


def test_ensure_model_downloads_when_missing(tmp_path, monkeypatch):
    model = tmp_path / "sub" / "m.task"

    def fake_retrieve(url, dest):
        open(dest, "wb").write(b"model")

    monkeypatch.setattr(hand_detection.urllib.request, "urlretrieve", fake_retrieve)
    assert ensure_model(model).read_bytes() == b"model"


def test_ensure_model_reports_download_failure(tmp_path, monkeypatch):
    def boom(url, dest):
        raise OSError("offline")

    monkeypatch.setattr(hand_detection.urllib.request, "urlretrieve", boom)
    with pytest.raises(ModelDownloadError):
        ensure_model(tmp_path / "m.task")


def test_real_detector_reports_no_hand_on_blank_frame(tmp_path):
    pytest.importorskip("mediapipe")
    np = pytest.importorskip("numpy")
    try:
        detector = hand_detection.HandDetector(tmp_path / "hand_landmarker.task")
    except ModelDownloadError:
        pytest.skip("model could not be downloaded in this environment")
    try:
        assert detector.detect(np.zeros((240, 320, 3), dtype=np.uint8)) is None
    finally:
        detector.close()
