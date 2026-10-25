"""Frame sampling and ground-truth labels for benchmark clips."""
import csv
import math
import re
from pathlib import Path

BENCH = Path(__file__).resolve().parent
MANIFEST = BENCH / 'manifest.csv'
CLIPS = BENCH / 'data' / 'clips'
MAX_SIDE = 960   # same cap as fallguard/server.py
MAX_SECONDS = 600


def sample_times(duration, step=0.3):
    """t = 0, step, 2*step ... up to and including duration."""
    count = int(math.floor(duration / step + 1e-9)) + 1
    return [round(i * step, 6) for i in range(count)]


def _num(value):
    return float(value) if value not in (None, '') else None


def label_at(t, row, ignore=0.5):
    """'fall' inside [fall_start_s, fall_end_s], 'ignore' within `ignore` s of either edge."""
    if not int(row.get('is_fall') or 0):
        return 'normal'
    start, end = _num(row.get('fall_start_s')), _num(row.get('fall_end_s'))
    if start is None or end is None:
        raise ValueError(f"clip {row.get('clip_id')}: is_fall=1 needs fall_start_s and fall_end_s")
    if abs(t - start) < ignore or abs(t - end) < ignore:
        return 'ignore'
    return 'fall' if start <= t <= end else 'normal'


def note_tokens(row):
    return (row.get('notes') or '').lower().replace(',', ' ').replace(';', ' ').split()


def is_short(row):
    return 'short' in note_tokens(row)


def is_long(row):
    """Long daily-life negative used for false alarms per hour."""
    return 'long' in note_tokens(row)


def is_uncertain(row):
    """By-eye fall time ambiguous by more than 1 s; excluded from alert-latency statistics."""
    return 'uncertain' in note_tokens(row)


def source_group(row):
    """'real' for footage from video sites, 'lab' for recorded datasets."""
    return 'real' if (row.get('source') or '').lower() == 'youtube' else 'lab'


def read_manifest(path=MANIFEST):
    """Rows with stripped values. clip_id becomes a file name everywhere, so it must be a plain name."""
    with open(path, newline='', encoding='utf-8') as f:
        rows = [{k: (v or '').strip() for k, v in row.items()} for row in csv.DictReader(f)]
    bad = [r.get('clip_id') for r in rows if not re.fullmatch(r'[A-Za-z0-9_.-]+', r.get('clip_id') or '')
           or set(r['clip_id']) == {'.'}]
    if bad:
        raise ValueError(f'invalid clip_id in {path.name}: {bad}')
    return rows


def resize_max(frame, max_side=MAX_SIDE):
    import cv2
    h, w = frame.shape[:2]
    ratio = min(1, max_side / max(h, w))
    if ratio < 1:
        frame = cv2.resize(frame, (round(w * ratio), round(h * ratio)))   # same call as fallguard/server.py
    return frame


def iter_frames(path, step=0.3, max_side=MAX_SIDE):
    """Yield (t, frame) every `step` s by seeking in milliseconds.

    CAP_PROP_FRAME_COUNT is not trusted (VFR or broken headers): stop at the first failed read.
    """
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise OSError(f'cannot open video: {path}')
    try:
        for i in range(int(MAX_SECONDS / step) + 1):
            t = round(i * step, 6)
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            yield t, resize_max(frame, max_side)
    finally:
        cap.release()


def frames_at(path, times, max_side=MAX_SIDE):
    """{t: frame} for the given sample times, seeking the same way as iter_frames."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise OSError(f'cannot open video: {path}')
    out = {}
    try:
        for t in sorted(times):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if ok and frame is not None:
                out[t] = resize_max(frame, max_side)
    finally:
        cap.release()
    return out
