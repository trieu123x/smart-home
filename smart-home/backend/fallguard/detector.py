"""YOLO11 Pose (17 keypoints) + Kaggle-trained bidirectional LSTM.

Input features deliberately match the Kaggle training cell; no previous
FallDetect image classifier or second YOLO is used.
"""
import logging
import os
import time
from pathlib import Path

import numpy as np

from .checkpoint import load_fall_checkpoint

from .paths import ASSETS as ROOT
POSE_WEIGHTS = ROOT / 'models' / 'pose' / 'yolo11n-pose.pt'
LSTM_WEIGHTS = ROOT / 'models' / 'fall' / 'best_fall_lstm.pth'


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


def feature_from_pose(box, xyn, confidence, height, width):
    """Training parity: 17*(rel_x,rel_y,conf) + aspect,cy,height,visible.

    box: absolute xyxy; xyn: (17,2) normalized to *original frame*;
    confidence: per-joint YOLO confidence. Failed/low-visibility pose is zero.
    """
    vec = np.zeros(55, dtype=np.float32)
    pts = np.asarray(xyn, dtype=np.float32)
    scores = np.asarray(confidence, dtype=np.float32)
    if pts.shape != (17, 2) or scores.shape != (17,):
        return vec, False
    visible = (scores >= .25) & np.isfinite(pts).all(axis=1)
    if visible.sum() < 5:
        return vec, False
    x1, y1, x2, y2 = map(float, box)
    cx = (x1 + x2) / (2 * width)
    cy = (y1 + y2) / (2 * height)
    bw = max((x2 - x1) / width, 1e-5)
    bh = max((y2 - y1) / height, 1e-5)
    scale = max(bw, bh, 1e-5)
    rel = (pts - np.asarray([cx, cy], dtype=np.float32)) / scale
    rel[~visible] = 0
    joint = np.column_stack([rel, np.where(visible, scores, 0)])
    vec[:51] = joint.reshape(-1)
    vec[51:] = [bw / bh, cy, bh, visible.mean()]
    return vec, True


class FallLSTM:
    """Exact trained torch network, defined without requiring torch at import."""
    @staticmethod
    def build(torch, dim=55, hidden=128):
        from torch import nn

        class Net(nn.Module):
            def __init__(self):
                super().__init__()
                self.lstm = nn.LSTM(dim, hidden, num_layers=2, dropout=.25,
                                    bidirectional=True, batch_first=True)
                self.classifier = nn.Sequential(
                    nn.LayerNorm(hidden * 4), nn.Linear(hidden * 4, 128),
                    nn.ReLU(), nn.Dropout(.3), nn.Linear(128, 2))

            def forward(self, x):
                z, _ = self.lstm(x)
                return self.classifier(torch.cat((z.mean(dim=1), z[:, -1]), dim=1))
        return Net()


class Detector:
    """Pose extractor and sequence scorer. Person histories live in FallTracker."""
    def __init__(self, pose=None, checkpoint_path=LSTM_WEIGHTS):
        import torch
        from ultralytics import YOLO
        from .telegram_config import _settings

        self.torch = torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        requested = os.environ.get('FALL_DEVICE', _settings.get('FALL_DEVICE', 'auto'))
        self.device = select_device(torch, requested)
        self.gpu_name = torch.cuda.get_device_name(0) if self.device.startswith('cuda') else None
        logging.warning('FallGuard Pose+BiLSTM: device=%s GPU=%s', self.device, self.gpu_name or 'None')

        checkpoint_path = Path(checkpoint_path)
        if not checkpoint_path.is_file():
            raise FileNotFoundError(f'Missing BiLSTM checkpoint: {checkpoint_path}')
        # Accept both the original NumPy-scaler export and tensor-only exports.
        ckpt = load_fall_checkpoint(checkpoint_path)
        dim = int(ckpt['model_config']['dim'])
        hidden = int(ckpt['model_config']['hidden'])
        self.frames = int(ckpt['frames'])
        self.img_size = int(ckpt['img_size'])
        if (dim, self.frames) != (55, 32) or list(ckpt['class_names']) != ['NORMAL', 'FALL']:
            raise ValueError('Checkpoint does not match 32x55 NORMAL/FALL training pipeline.')
        self.model = FallLSTM.build(torch, dim, hidden).to(self.device)
        self.model.load_state_dict(ckpt['model_state_dict'], strict=True)
        self.model.eval()
        self.mean = torch.as_tensor(ckpt['scaler_mean'], dtype=torch.float32, device=self.device).view(1, 1, dim)
        self.scale = torch.as_tensor(ckpt['scaler_scale'], dtype=torch.float32, device=self.device).view(1, 1, dim)
        if not torch.isfinite(self.mean).all() or not torch.isfinite(self.scale).all() or (self.scale <= 0).any():
            raise ValueError('Invalid preprocessing scaler in checkpoint')
        if pose is not None:
            self.pose = pose
        elif POSE_WEIGHTS.is_file():
            self.pose = YOLO(str(POSE_WEIGHTS))
        else:
            # Ultralytics will download the official 6MB model on first use.
            # Models from the old two-YOLO pipeline are NEVER loaded.
            logging.warning('Missing %s: downloading yolo11n-pose.pt on first launch.', POSE_WEIGHTS)
            self.pose = YOLO('yolo11n-pose.pt')
            # Place downloaded weight at the documented model path for offline restarts.
            downloaded = Path('yolo11n-pose.pt')
            if downloaded.is_file():
                try:
                    import shutil
                    POSE_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(downloaded, POSE_WEIGHTS)
                    if downloaded.resolve() != POSE_WEIGHTS.resolve():
                        downloaded.unlink()
                except OSError as exc:
                    logging.warning('Pose model runs, but cannot cache weights under models/pose/: %s', exc)
        if pose is None and (self.pose.task != 'pose'
                             or tuple(self.pose.model.model[-1].kpt_shape) != (17, 3)):
            raise ValueError('Expected YOLO Pose with 17 keypoints and confidence scores.')
        self._track_mode = True
        logging.warning('FallGuard loaded new LSTM checkpoint: %s | window=%d | pose_imgsz=%d',
                        checkpoint_path, self.frames, self.img_size)

    def reset(self):
        """Reset YOLO ByteTrack state on new camera stream/analysis session."""
        if hasattr(self.pose, 'predictor') and self.pose.predictor is not None:
            for tracker in getattr(self.pose.predictor, 'trackers', []):
                try:
                    tracker.reset()
                except Exception:
                    logging.warning('Unable to reset pose tracker; fallback association will be used.')

    def predict(self, frame):
        start = time.perf_counter()
        h, w = frame.shape[:2]
        # Track stable person IDs when available, fall back to spatial matching.
        # Always use pose model and its 17 COCO joint coordinates.
        if self._track_mode:
            try:
                result = self.pose.track(frame, persist=True, conf=.25, imgsz=self.img_size,
                                         max_det=12, device=self.device, tracker='bytetrack.yaml', verbose=False)[0]
            except Exception as exc:
                logging.warning('ByteTrack dependency unavailable (%s); using pose.predict instead.', exc)
                self._track_mode = False
                result = self.pose.predict(frame, conf=.25, imgsz=self.img_size,
                                           max_det=12, device=self.device, verbose=False)[0]
        else:
            result = self.pose.predict(frame, conf=.25, imgsz=self.img_size,
                                       max_det=12, device=self.device, verbose=False)[0]
        detections = []
        if result.boxes is not None and result.keypoints is not None:
            boxes = result.boxes.xyxy.detach().cpu().numpy()
            conf = result.boxes.conf.detach().cpu().numpy()
            pts = result.keypoints.xyn.detach().cpu().numpy()
            joint_scores = (result.keypoints.conf.detach().cpu().numpy()
                            if result.keypoints.conf is not None else np.ones((len(boxes), 17), dtype=np.float32))
            track_ids = result.boxes.id
            ids = track_ids.int().cpu().tolist() if track_ids is not None else [None] * len(boxes)
            for i, (box, person_conf) in enumerate(zip(boxes, conf)):
                if i >= len(pts) or i >= len(joint_scores):
                    continue
                vec, valid = feature_from_pose(box, pts[i], joint_scores[i], h, w)
                normalized_box = [round(float(box[0] / w), 6), round(float(box[1] / h), 6),
                                  round(float(box[2] / w), 6), round(float(box[3] / h), 6)]
                detections.append({'box': normalized_box, 'person_confidence': round(float(person_conf), 4),
                                   'pose_feature': vec, 'pose_valid': valid,
                                   'tracking_id': ids[i], 'fall_score': None})
        return {'detections': detections, 'inference_ms': round((time.perf_counter()-start)*1000),
                'width': w, 'height': h, 'device': self.device}

    def score_sequences(self, sequences):
        """Return P(FALL) for (N,32,55) input; standardized with checkpoint scaler."""
        if not sequences:
            return []
        data = np.stack(sequences).astype(np.float32)
        if data.ndim != 3 or data.shape[1:] != (self.frames, 55):
            raise ValueError(f'Expected sequence shape (N,{self.frames},55), got {data.shape}')
        with self.torch.inference_mode():
            x = self.torch.as_tensor(data, device=self.device)
            logits = self.model((x - self.mean) / self.scale)
            probs = logits.softmax(dim=1)[:, 1].cpu().tolist()
        return [float(x) for x in probs]
