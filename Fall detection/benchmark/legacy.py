"""Frozen copy of the FallGuard production pieces the benchmark measured.

Copied verbatim from commit 01c3556 (`fallguard/cctv.py`: iou, FallTracker; `fallguard/detector.py`:
select_device, square_crop). Commit 2638a55 replaced them with a Pose + BiLSTM pipeline. Keeping this copy
means every benchmark result, including the `trk=prod` tracker, stays reproducible whatever fallguard/ becomes.
The new pipeline is not benchmarked here.
"""
import numpy as np


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


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    def area(box):
        return max(0, box[2]-box[0]) * max(0, box[3]-box[1])
    return intersection / (area(a) + area(b) - intersection or 1)


class FallTracker:
    """Require continuous positive tracking AND at least 5 real seconds.

    Missing detections, identity changes, or a gap in processed frames reset the
    pending window. A person is alerted once per continuous fall episode.
    """
    FALL_SECONDS = 5.0
    MAX_INFERENCE_GAP = 2.0

    def __init__(self):
        self.tracks = []
        self.next_id = 1
        self.last_time = None

    def reset(self):
        self.tracks = []
        self.last_time = None

    def update(self, detections, threshold, needed, now):
        if self.last_time is not None and (now < self.last_time or now-self.last_time > self.MAX_INFERENCE_GAP):
            self.reset()
        self.last_time = now
        candidates = sorted(((iou(d['box'], t['box']), di, ti)
                             for di, d in enumerate(detections) for ti, t in enumerate(self.tracks)), reverse=True)
        matched, used = {}, set()
        for score, di, ti in candidates:
            if score >= .25 and di not in matched and ti not in used:
                matched[di] = ti
                used.add(ti)
        tracks = []
        for di, d in enumerate(detections):
            old = self.tracks[matched[di]] if di in matched else None
            identity = old['id'] if old else self.next_id
            if old is None:
                self.next_id += 1
            positive = d.get('fall_score') is not None and d['fall_score'] >= threshold
            streak = (old['streak'] if old else 0) + 1 if positive else 0
            fall_since = (old.get('fall_since') if old and old.get('fall_since') is not None else now) if positive else None
            fall_elapsed = max(0.0, now-fall_since) if positive else 0.0
            danger = positive and streak >= needed and fall_elapsed >= self.FALL_SECONDS
            tracks.append({**d, 'id': identity, 'streak': streak, 'fall_since': fall_since,
                           'fall_elapsed': round(fall_elapsed, 2), 'danger': danger,
                           'pending': positive and not danger, 'newAlert': danger and not (old and old['danger'])})
        self.tracks = tracks
        return tracks
