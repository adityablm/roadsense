"""Tests for the pure logic (no database or model needed).   Run:  python -m pytest"""
import numpy as np
from PIL import Image

from app.detector import decode_output, letterbox, to_detections
from app.severity import hotspot_severity, report_severity, severity_level


def det(label, conf, box):
    return {"label": label, "confidence": conf, "box": box}


# ---------------- severity
def test_bigger_and_more_dangerous_damage_scores_higher():
    small_crack = report_severity([det("longitudinal_crack", 0.6, [0.1, 0.1, 0.12, 0.3])])
    big_pothole = report_severity([det("pothole", 0.6, [0.3, 0.5, 0.6, 0.8])])
    assert 0 < small_crack < big_pothole <= 10


def test_more_detections_raise_score_but_never_pass_10():
    one = report_severity([det("pothole", 0.9, [0, 0, 0.5, 0.5])])
    many = report_severity([det("pothole", 0.9, [0, 0, 0.5, 0.5])] * 10)
    assert one < many <= 10


def test_no_detections_is_zero():
    assert report_severity([]) == 0


def test_single_reporter_can_never_be_severe():
    assert hotspot_severity(9.5, 1) < 7
    assert severity_level(hotspot_severity(9.5, 1)) == "moderate"


def test_more_people_raise_the_hotspot_score():
    assert hotspot_severity(6.0, 1) < hotspot_severity(6.0, 2) < hotspot_severity(6.0, 4)
    assert hotspot_severity(9.0, 50) == 10


# ---------------- reading the model output
def test_letterbox_keeps_shape_and_pads_evenly():
    img = Image.new("RGB", (1280, 720))
    square, scale, pad_x, pad_y = letterbox(img, 640)
    assert square.size == (640, 640)
    assert scale == 0.5 and pad_x == 0 and pad_y == 140   # 720 * 0.5 = 360 tall, (640 - 360) / 2 = 140


def test_end_to_end_output_is_decoded_and_mapped_back():
    # a 1280x720 photo becomes 640x360 inside the square, starting 140 px from the top
    raw = np.zeros((1, 300, 6), dtype=np.float32)
    raw[0, 0] = [100, 240, 300, 340, 0.9, 3]     # confident pothole
    raw[0, 1] = [10, 150, 50, 200, 0.1, 0]       # too weak, must be dropped
    boxes, scores, classes = decode_output(raw, conf_threshold=0.3)
    dets = to_detections(boxes, scores, classes, 0.5, 0, 140, 1280, 720)
    assert len(dets) == 1
    d = dets[0]
    assert d["label"] == "pothole" and d["confidence"] == 0.9
    # x: 100/0.5 = 200 px -> 200/1280 ; y: (240-140)/0.5 = 200 px -> 200/720
    assert d["box"] == [round(200 / 1280, 4), round(200 / 720, 4), round(600 / 1280, 4), round(400 / 720, 4)]


def test_classic_output_with_duplicates_is_deduplicated():
    n = 8400
    raw = np.zeros((1, 8, n), dtype=np.float32)        # 4 box numbers + 4 class scores, per candidate
    raw[0, :, 0] = [320, 320, 100, 100, 0, 0, 0, 0.8]   # pothole
    raw[0, :, 1] = [322, 321, 100, 100, 0, 0, 0, 0.7]   # same pothole again, slightly shifted
    raw[0, :, 2] = [100, 100, 40, 40, 0.6, 0, 0, 0]     # a separate crack
    boxes, scores, classes = decode_output(raw, conf_threshold=0.3)
    assert sorted(classes.tolist()) == [0, 3]
    assert np.isclose(scores.max(), 0.8)
