"""Two-stage inference using the two supplied YOLO weights; no downloads."""
import os
import logging
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def select_device(torch, requested='auto'):
    requested = (requested or 'auto').strip().lower()
    if requested in ('', 'auto'):
        return 'cuda:0' if torch.cuda.is_available() else 'cpu'
    if requested == 'cpu':
        return 'cpu'
    if requested in ('cuda', 'cuda:0'):
        if not torch.cuda.is_available():
            raise RuntimeError('FALL_DEVICE yeu cau CUDA nhung PyTorch khong nhan GPU. Chay CHECK_GPU.bat.')
        return 'cuda:0'
    raise ValueError('FALL_DEVICE phai la auto, cpu, cuda hoac cuda:0.')


def square_crop(frame, box, margin=0.10):
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    x1, y1 = max(0, int(x1 - bw * margin)), max(0, int(y1 - bh * margin))
    x2, y2 = min(w, int(x2 + bw * margin)), min(h, int(y2 + bh * margin))
    if x2 - x1 < 16 or y2 - y1 < 16:
        return None
    crop = frame[y1:y2, x1:x2]
    ch, cw = crop.shape[:2]
    side = max(ch, cw)
    out = np.zeros((side, side, 3), dtype=frame.dtype)
    out[(side-ch)//2:(side-ch)//2+ch, (side-cw)//2:(side-cw)//2+cw] = crop
    return out


class Detector:
    def __init__(self):
        import torch
        from ultralytics import YOLO
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        from .telegram_config import _settings
        requested = os.environ.get('FALL_DEVICE', _settings.get('FALL_DEVICE', 'auto'))
        self.device = select_device(torch, requested)
        self.gpu_name = torch.cuda.get_device_name(0) if self.device.startswith('cuda') else None
        logging.warning('FallGuard AI: Torch %s | device=%s | GPU=%s',
                        torch.__version__, self.device, self.gpu_name or 'None')
        paths = [ROOT / 'models/detection/yolo11s.pt',
                 ROOT / 'models/pose_classification/leeyunjai-falldetect-11x.pt']
        for p in paths:
            if not p.is_file():
                raise FileNotFoundError(f'Thieu model: {p}')
        self.person, self.fall = (YOLO(str(p)) for p in paths)
        names = self.fall.names
        self.fall_ids = [int(i) for i, n in names.items()
                         if 'fall' in n.lower() and not any(x in n.lower() for x in ('non', 'not', 'no-'))]
        if not self.fall_ids:
            raise ValueError(f'Model khong co nhan fall: {names}')

    def predict(self, frame):
        start = time.perf_counter()
        h, w = frame.shape[:2]
        result = self.person.predict(frame, classes=[0], conf=0.3, imgsz=640+64,
                                     max_det=12, device=self.device, verbose=False)[0]
        detections, crops, indices = [], [], []
        for box, conf in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist()):
            crop = square_crop(frame, box)
            detections.append({'box': [box[0]/w, box[1]/h, box[2]/w, box[3]/h],
                               'person_confidence': round(conf, 4), 'fall_score': None})
            if crop is not None:
                indices.append(len(detections)-1)
                crops.append(crop)
        # Small batches bound memory even when several people appear.
        for offset in range(0, len(crops), 2):
            results = self.fall.predict(crops[offset:offset+2], conf=0.05,
                                       classes=self.fall_ids, imgsz=640,
                                       device=self.device, verbose=False)
            for index, result in zip(indices[offset:offset+2], results):
                score = float(result.boxes.conf.max()) if len(result.boxes) else 0.0
                detections[index]['fall_score'] = round(score, 4)
        return {'detections': detections, 'inference_ms': round((time.perf_counter()-start)*1000),
                'width': w, 'height': h, 'device': self.device}
