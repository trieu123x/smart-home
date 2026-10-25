"""Stage-2 adapters: every candidate turns person crops into a fall probability in [0, 1]."""
import math
from pathlib import Path

import numpy as np

from benchmark.fetch_models import safe_dest, verify_file

BENCH = Path(__file__).resolve().parent
WEIGHTS = BENCH / 'weights'
BATCH = 2   # same small batches as fallguard.detector.Detector.predict

# COCO-17 keypoint indices
NOSE, L_SH, R_SH, L_HIP, R_HIP = 0, 5, 6, 11, 12
KP_CONF = 0.3


def weight_path(entry, index=0):
    return safe_dest(entry['id'], entry['files'][index]['path'])


def label_ids(names, fall_labels):
    """Map explicit fall_labels (case-insensitive exact match) to class ids. No substring rule."""
    wanted = {label.lower() for label in fall_labels}
    ids = [int(i) for i, n in names.items() if str(n).lower() in wanted]
    if not ids:
        raise ValueError(f'none of fall_labels {fall_labels} in model classes {dict(names)}')
    return ids


class Stage2:
    name = ''
    kind = ''

    def scores(self, crops: list[np.ndarray]) -> list[float]:
        raise NotImplementedError


class YoloDetect(Stage2):
    """YOLO detector with a fall class run on the crop; score = best fall box confidence."""
    kind = 'yolo-detect'

    def __init__(self, entry, device):
        from ultralytics import YOLO
        self.name, self.device = entry['id'], device
        self.model = YOLO(str(weight_path(entry)))
        self.fall_ids = label_ids(self.model.names, entry['fall_labels'])
        self.imgsz, self.conf = int(entry.get('imgsz', 640)), float(entry.get('conf', 0.05))

    def scores(self, crops):
        out = []
        for offset in range(0, len(crops), BATCH):
            results = self.model.predict(crops[offset:offset+BATCH], conf=self.conf, classes=self.fall_ids,
                                         imgsz=self.imgsz, device=self.device, verbose=False)
            out += [float(r.boxes.conf.max()) if len(r.boxes) else 0.0 for r in results]
        return out


class YoloClassify(Stage2):
    """Ultralytics classification model; score = summed probability of the fall classes."""
    kind = 'classify'

    def __init__(self, entry, device):
        from ultralytics import YOLO
        self.name, self.device = entry['id'], device
        self.model = YOLO(str(weight_path(entry)))
        if self.model.task != 'classify':
            raise ValueError(f'expected a classify model, got task={self.model.task}')
        self.fall_ids = label_ids(self.model.names, entry['fall_labels'])
        self.imgsz = int(entry.get('imgsz', 224))

    def scores(self, crops):
        out = []
        for offset in range(0, len(crops), BATCH):
            results = self.model.predict(crops[offset:offset+BATCH], imgsz=self.imgsz,
                                         device=self.device, verbose=False)
            out += [float(r.probs.data[self.fall_ids].sum()) for r in results]
        return out


def _mid(xy, conf, a, b):
    if conf[a] < KP_CONF or conf[b] < KP_CONF:
        return None
    return (xy[a] + xy[b]) / 2


def pose_rule_score(xy, conf):
    """Rule on one person's COCO keypoints: torso tilt from vertical plus body aspect ratio.

    Upright torso (< 30 deg) scores 0, horizontal (>= 70 deg) scores 1. A wide keypoint
    spread (w/h >= 1.5) also pushes the score up. Returns 0 when too few keypoints are visible.
    """
    xy, conf = np.asarray(xy, dtype=float), np.asarray(conf, dtype=float)
    visible = xy[conf >= KP_CONF]
    if len(visible) < 5:
        return 0.0
    w, h = np.ptp(visible[:, 0]), np.ptp(visible[:, 1])
    aspect = min(1.0, max(0.0, (w / max(h, 1.0) - 0.8) / 0.7))
    shoulders, hips = _mid(xy, conf, L_SH, R_SH), _mid(xy, conf, L_HIP, R_HIP)
    if shoulders is None or hips is None:
        return round(aspect, 4)
    dx, dy = shoulders - hips
    tilt = math.degrees(math.atan2(abs(dx), -dy)) if (dx or dy) else 0.0   # 0 = upright, 180 = upside down
    angle = min(1.0, max(0.0, (tilt - 30) / 40))
    return round(0.7 * angle + 0.3 * aspect, 4)


class PoseRule(Stage2):
    """YOLO pose on the crop, then pose_rule_score on the most confident person."""
    kind = 'pose'

    def __init__(self, entry, device):
        from ultralytics import YOLO
        self.name, self.device = entry['id'], device
        self.model = YOLO(str(weight_path(entry)))
        if self.model.task != 'pose':
            raise ValueError(f'expected a pose model, got task={self.model.task}')
        self.imgsz = int(entry.get('imgsz', 640))

    def scores(self, crops):
        out = []
        for offset in range(0, len(crops), BATCH):
            results = self.model.predict(crops[offset:offset+BATCH], conf=0.25, imgsz=self.imgsz,
                                         device=self.device, verbose=False)
            for r in results:
                if r.keypoints is None or not len(r.boxes):
                    out.append(0.0)
                    continue
                best = int(r.boxes.conf.argmax())
                out.append(pose_rule_score(r.keypoints.xy[best].cpu().numpy(),
                                           r.keypoints.conf[best].cpu().numpy()))
        return out


ADAPTERS = {('yolo-detect', 'ultralytics'): YoloDetect,
            ('classify', 'ultralytics'): YoloClassify,
            ('pose', 'ultralytics-rule'): PoseRule}


def load_stage2(entry, device):
    key = (entry['kind'], entry.get('backend', 'ultralytics'))
    if key not in ADAPTERS:
        raise ValueError(f'no adapter for kind={key[0]} backend={key[1]}')
    for i, file in enumerate(entry['files']):
        path = weight_path(entry, i)
        if not path.is_file():
            raise FileNotFoundError(f'missing weights: {path} (run fetch_models.py)')
        verify_file(path, file.get('sha256'))   # .pt files are pickles: check the pin right before loading
    return ADAPTERS[key](entry, device)
