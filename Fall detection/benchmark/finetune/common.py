"""Shared helpers for the fine-tune data builders: the frozen split, leakage guards and box merging."""
import csv
from pathlib import Path

import numpy as np

from benchmark.legacy import iou

FT = Path(__file__).resolve().parent
BENCH = FT.parent
SPLIT_CSV = BENCH / 'split.csv'
DATA = BENCH / 'data' / 'finetune'
CLASS_FLOOR = 300
# CAUCAFall has only Sit down and Kneel (second half each) and the train clips add few seated crops:
# 182 sit crops on 2026-10-25. The user chose a lower floor over near-duplicate frames.
CLASS_FLOOR_OVERRIDES = {'sit': 150}
DHASH_MAX_DIST = 6


def read_split(path=SPLIT_CSV):
    """{clip_id: 'train' | 'test'} from the committed split.csv."""
    if not path.is_file():
        raise FileNotFoundError(f'{path} is missing (run finetune/make_split.py)')
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    bad = [r['clip_id'] for r in rows if r.get('split') not in ('train', 'test')]
    if bad:
        raise ValueError(f'{path.name}: split must be train or test, not for {bad}')
    return {r['clip_id']: r['split'] for r in rows}


def assert_no_test_clips(clip_ids, split):
    """A test clip in any training manifest fails the build."""
    leaked = sorted({c for c in clip_ids if split.get(c) == 'test'})
    if leaked:
        raise ValueError(f'test clips must never feed training: {", ".join(leaked)}')


def dhash(image, size=8):
    """64-bit difference hash of a BGR or grey image."""
    import cv2
    grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    small = cv2.resize(grey, (size + 1, size), interpolation=cv2.INTER_AREA)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int(sum(1 << i for i, b in enumerate(bits) if b))


def near_duplicates(hashes, reference, max_dist=DHASH_MAX_DIST, chunk=2048):
    """Boolean mask over `hashes`: True where any `reference` hash is within `max_dist` bits."""
    hashes = np.asarray(hashes, dtype=np.uint64)
    reference = np.asarray(reference, dtype=np.uint64)
    out = np.zeros(len(hashes), dtype=bool)
    if not len(hashes) or not len(reference):
        return out
    for start in range(0, len(hashes), chunk):
        xor = hashes[start:start + chunk, None] ^ reference[None, :]
        bits = np.unpackbits(xor[..., None].view(np.uint8), axis=-1).sum(axis=-1)   # numpy 1.x has no bitwise_count
        out[start:start + chunk] = (bits <= max_dist).any(axis=1)
    return out


def inside_share(box, other):
    """Share of box's area that lies inside other."""
    inter = max(0, min(box[2], other[2]) - max(box[0], other[0])) * max(0, min(box[3], other[3]) - max(box[1], other[1]))
    return inter / max((box[2] - box[0]) * (box[3] - box[1]), 1e-9)


def teacher_merge(gt_boxes, teacher_boxes, teacher_confs, min_conf=0.5, max_iou=0.5, max_inside=0.5):
    """Teacher boxes (conf >= min_conf) that overlap no ground-truth box (IoU < max_iou), and not each other.

    A teacher box with >= max_inside of its area inside a ground-truth box is a fragment of that labelled
    person (YOLO often splits someone lying down into legs and torso) and is dropped too.
    """
    added = []
    for box, conf in sorted(zip(teacher_boxes, teacher_confs), key=lambda bc: -bc[1]):
        if conf < min_conf:
            continue
        if (all(iou(box, other) < max_iou for other in list(gt_boxes) + added)
                and all(inside_share(box, g) < max_inside for g in gt_boxes)):
            added.append(list(box))
    return added


def check_class_floor(counts, floor=CLASS_FLOOR, overrides=None):
    """counts: {class: n} for the train side. Every class needs at least `floor` crops (or its override)."""
    overrides = CLASS_FLOOR_OVERRIDES if overrides is None else overrides
    short = {c: n for c, n in counts.items() if n < overrides.get(c, floor)}
    if short:
        raise ValueError(f'train classes below their floor ({floor}, overrides {overrides}): {short}')


# ---------- Kaggle training (train_stage1.py / train_stage2.py) ----------

def train_with_fallback(train, n_gpus, hours, clock=None):
    """Run train(device, hours) on both GPUs (DDP); on failure retry on GPU 0 with the time that is left.

    Returns (result, device used). Ultralytics' `time` stops training cleanly at the limit.
    """
    import time
    clock = clock or time.monotonic
    start = clock()
    if n_gpus >= 2:
        try:
            return train([0, 1], hours), [0, 1]
        except Exception as e:   # DDP runs in a subprocess; any failure there surfaces here
            print(f'[FALLBACK] DDP on 2 GPUs failed ({type(e).__name__}: {e}); retrying with device=0', flush=True)
    else:
        print(f'[FALLBACK] {n_gpus} GPU(s) visible; training with device=0', flush=True)
    left = round(hours - (clock() - start) / 3600, 3)
    if left <= 0.05:
        raise RuntimeError('no time left for the single-GPU retry')
    return train(0, left), 0


def package_run(run_dir, zip_path, names=('weights/best.pt', 'results.csv', 'args.yaml')):
    """Zip the files the local pull needs from an Ultralytics run folder."""
    import zipfile
    missing = [n for n in names if not (run_dir / n).is_file()]
    if missing:
        raise FileNotFoundError(f'{run_dir} lacks {missing}')
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for n in names:
            z.write(run_dir / n, Path(n).name)
    return zip_path
