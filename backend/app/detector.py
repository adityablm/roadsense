"""
Runs the trained YOLO model (the roadsense.onnx file) on a photo.

Steps for every photo:
1. "Letterbox" it: shrink it to fit inside a 640x640 square without
   stretching, and fill the empty space with grey. This is exactly how the
   model saw photos during training.
2. Turn the pixels into numbers between 0 and 1 in the layout the model wants.
3. Run the model.
4. Read the model's output, drop weak guesses, and convert the boxes back
   to positions on the ORIGINAL photo, as fractions (0-1) of its width/height.
   Fractions are handy: the website can draw the box at any display size.
"""
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

CLASS_NAMES = ["longitudinal_crack", "transverse_crack", "alligator_crack", "pothole"]
PAD_COLOR = (114, 114, 114)   # the grey YOLO uses for padding


def letterbox(img: Image.Image, size: int):
    """Returns (square image, scale, pad_x, pad_y)."""
    w, h = img.size
    scale = min(size / w, size / h)
    new_w, new_h = max(1, round(w * scale)), max(1, round(h * scale))
    resized = img.resize((new_w, new_h), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), PAD_COLOR)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas.paste(resized, (pad_x, pad_y))
    return canvas, scale, pad_x, pad_y


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    """Non-maximum suppression: when several boxes cover the same thing,
    keep the most confident one and drop the others that overlap it a lot."""
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        area_o = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (boxes[order[1:], 3] - boxes[order[1:], 1])
        iou = inter / np.maximum(area_i + area_o - inter, 1e-9)
        order = order[1:][iou < iou_threshold]
    return keep


def decode_output(raw: np.ndarray, conf_threshold: float, iou_threshold: float = 0.5,
                  num_classes: int = len(CLASS_NAMES)):
    """Reads the model's raw output. Handles both output styles:
    - "end-to-end" models (like YOLO26): rows of [x1, y1, x2, y2, score, class], already de-duplicated.
    - classic models (YOLOv8/YOLO11): (4 + classes) x N grid of [cx, cy, w, h, score per class], needs NMS.
    Returns (boxes as x1,y1,x2,y2 in 640-square pixels, scores, class ids)."""
    a = np.asarray(raw, dtype=np.float32)
    if a.ndim == 3:
        a = a[0]
    if a.ndim == 2 and a.shape[-1] == 6:                     # end-to-end style
        keep = a[:, 4] >= conf_threshold
        return a[keep, :4], a[keep, 4], a[keep, 5].astype(int)

    if a.shape[0] == 4 + num_classes and a.shape[1] != 4 + num_classes:
        a = a.T                                              # -> one row per candidate box
    cls_scores = a[:, 4:4 + num_classes]
    classes = cls_scores.argmax(axis=1)
    scores = cls_scores.max(axis=1)
    keep = scores >= conf_threshold
    cx, cy, w, h = a[keep, 0], a[keep, 1], a[keep, 2], a[keep, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    scores, classes = scores[keep], classes[keep]
    if len(scores) == 0:
        return boxes, scores, classes
    shifted = boxes + classes[:, None] * 10_000.0              # trick: NMS per class in one call
    idx = _nms(shifted, scores, iou_threshold)
    return boxes[idx], scores[idx], classes[idx]


def to_detections(boxes, scores, classes, scale, pad_x, pad_y, orig_w, orig_h) -> list[dict]:
    """Moves boxes from the 640 square back onto the original photo, as 0-1 fractions."""
    out = []
    for (x1, y1, x2, y2), score, cls in zip(boxes, scores, classes):
        x1 = min(max((x1 - pad_x) / scale, 0), orig_w) / orig_w
        x2 = min(max((x2 - pad_x) / scale, 0), orig_w) / orig_w
        y1 = min(max((y1 - pad_y) / scale, 0), orig_h) / orig_h
        y2 = min(max((y2 - pad_y) / scale, 0), orig_h) / orig_h
        if x2 - x1 < 0.002 or y2 - y1 < 0.002:              # skip boxes that collapsed to a line
            continue
        cls = int(cls)
        if not 0 <= cls < len(CLASS_NAMES):
            continue
        out.append({
            "class_id": cls,
            "label": CLASS_NAMES[cls],
            "confidence": round(float(score), 3),
            "box": [round(float(v), 4) for v in (x1, y1, x2, y2)],
        })
    out.sort(key=lambda d: d["confidence"], reverse=True)
    return out


class Detector:
    def __init__(self, model_path: Path, conf_threshold: float = 0.3, threads: int = 1):
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        size = inp.shape[-1]
        self.size = size if isinstance(size, int) else 640    # some exports leave the size open
        self.conf_threshold = conf_threshold

    def detect(self, img: Image.Image) -> list[dict]:
        img = img.convert("RGB")
        square, scale, pad_x, pad_y = letterbox(img, self.size)
        x = np.asarray(square, dtype=np.float32) / 255.0      # pixels 0-255 -> 0-1
        x = x.transpose(2, 0, 1)[None]                         # (H, W, 3) -> (1, 3, H, W)
        raw = self.session.run(None, {self.input_name: x})[0]
        boxes, scores, classes = decode_output(raw, self.conf_threshold)
        return to_detections(boxes, scores, classes, scale, pad_x, pad_y, *img.size)
