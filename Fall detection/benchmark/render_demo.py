"""Render annotated demo videos of one benchmark pipeline: person boxes, fall score, tracker state, alerts.

Inference runs every --step seconds of video time (0.3 s, as in the benchmark); frames in between show the
last result, so the rendered alerts are the ones the benchmark scored. Output: results/demo/<clip>__<pipeline>.mp4
(gitignored). Box colours: green = normal, orange = fall score >= threshold but not yet confirmed (5 s rule),
red = alert. The banner shows the manifest ground truth for comparison.

Usage (from `Fall detection/`):
    .venv/Scripts/python -I benchmark/render_demo.py --clips c1,c2 [--stage1 pose] [--stage2 jerryg-v8x-cls]
        [--tracker gap1] [--step 0.3]
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only
os.environ['YOLO_AUTOINSTALL'] = 'false'
os.environ['YOLO_OFFLINE'] = 'true'
os.environ['ULTRALYTICS_SAFE_LOAD'] = '1'

from benchmark import frames as fr  # noqa: E402
from benchmark import metrics as mt  # noqa: E402
from benchmark.adapters import load_stage2  # noqa: E402
from benchmark.run_benchmark import NEEDED, RESULTS, STAGE1_VARIANTS, THRESHOLD, Stage1, load_models, stage1_entry  # noqa: E402

DEMO = RESULTS / 'demo'
GREEN, ORANGE, RED, WHITE, BLACK = (0, 200, 0), (0, 165, 255), (0, 0, 255), (255, 255, 255), (0, 0, 0)


def track_style(track):
    """(colour, label) for one tracker output."""
    score = track.get('fall_score')
    text = f"#{track['id']} " + ('n/a' if score is None else f'fall {score:.2f}')
    if track['danger']:
        return RED, text + ' ALERT'
    if track['pending']:
        return ORANGE, text + f" {track['fall_elapsed']:.1f}s"
    return GREEN, text


def draw(frame, boxes, tracks, t, truth, alerts, title):
    import cv2
    out = frame.copy()
    for box, track in zip(boxes, tracks):
        colour, text = track_style(track)
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(out, (x1, y1), (x2, y2), colour, 3 if track['danger'] else 2)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, .55, 2)
        cv2.rectangle(out, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), colour, -1)
        cv2.putText(out, text, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, .55, WHITE, 2)
    h, w = out.shape[:2]
    cv2.rectangle(out, (0, 0), (w, 30), BLACK, -1)
    cv2.putText(out, f'{title}   t={t:5.1f}s   ground truth: {truth}', (8, 21), cv2.FONT_HERSHEY_SIMPLEX, .55, WHITE, 1)
    if any(tr['danger'] for tr in tracks):
        cv2.rectangle(out, (0, h - 44), (w, h), RED, -1)
        cv2.putText(out, 'FALL ALERT', (12, h - 13), cv2.FONT_HERSHEY_SIMPLEX, 1.0, WHITE, 3)
    if alerts:
        cv2.putText(out, f"alerts at {', '.join(f'{a:.1f}s' for a in alerts[-3:])}", (w - 330, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, .5, (80, 80, 255), 1)
    return out


def open_writer(path, fps, size):
    import cv2
    for codec in ('avc1', 'mp4v'):   # H.264 plays everywhere; OpenCV builds without it fall back to mp4v
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*codec), fps, size)
        if writer.isOpened():
            return writer, codec
        writer.release()
    raise RuntimeError(f'cannot open a video writer for {path}')


def render(row, stage1, adapter, tracker_name, step, title):
    import cv2
    from benchmark.legacy import square_crop
    src = fr.CLIPS / f"{row['clip_id']}.mp4"
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise OSError(f'cannot open {src}')
    fps = cap.get(cv2.CAP_PROP_FPS)
    fps = fps if 1 <= fps <= 120 else 30.0
    tracker, alerts = mt.TRACKERS[tracker_name](), []
    boxes, tracks, next_t, writer = [], [], 0.0, None
    dst = DEMO / f"{row['clip_id']}__{title.replace('|', '_').replace('=', '-')}.mp4"
    DEMO.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            frame = fr.resize_max(frame)
            if t + 1e-6 >= next_t:   # inference tick: same cadence as the benchmark replay
                next_t += step
                boxes, _ = stage1(frame)
                h, w = frame.shape[:2]
                crops = [square_crop(frame, b) for b in boxes]
                valid = [c for c in crops if c is not None]
                it = iter(adapter.scores(valid) if valid else [])
                scores = [None if c is None else float(next(it)) for c in crops]
                dets = [{'box': [b[0] / w, b[1] / h, b[2] / w, b[3] / h], 'fall_score': s} for b, s in zip(boxes, scores)]
                tracks = tracker.update(dets, THRESHOLD, NEEDED, t)
                alerts += [t for tr in tracks if tr['newAlert']][:1]
            truth = fr.label_at(t, row)
            if writer is None:
                writer, codec = open_writer(dst, fps, (frame.shape[1], frame.shape[0]))
            writer.write(draw(frame, boxes, tracks, t, truth, alerts, title))
    finally:
        cap.release()
        if writer is not None:
            writer.release()
    return dst, alerts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--clips', required=True, help='comma-separated clip ids from manifest.csv')
    parser.add_argument('--stage1', default='pose', choices=list(STAGE1_VARIANTS))
    parser.add_argument('--stage2', default='jerryg-v8x-cls', help='candidate id from models.json')
    parser.add_argument('--tracker', default='gap1', choices=list(mt.TRACKERS))
    parser.add_argument('--step', type=float, default=0.3)
    parser.add_argument('--device', default='auto')
    args = parser.parse_args(argv)

    import torch
    from benchmark.legacy import select_device
    device = select_device(torch, args.device)
    models = load_models()
    rows = {r['clip_id']: r for r in fr.read_manifest()}
    wanted = [c for c in args.clips.split(',') if c]
    unknown = [c for c in wanted if c not in rows]
    if unknown:
        print(f"[ERROR] unknown clip ids: {', '.join(unknown)}")
        return 1
    cand = next((c for c in models['candidates'] if c['id'] == args.stage2), None)
    if cand is None:
        print(f'[ERROR] unknown stage-2 id {args.stage2}')
        return 1
    weights_id, conf = STAGE1_VARIANTS[args.stage1]
    stage1 = Stage1(stage1_entry(models, weights_id), device, conf)
    adapter = load_stage2(cand, device)
    title = f'{args.stage2}|s1={args.stage1}|trk={args.tracker}'
    for clip in wanted:
        dst, alerts = render(rows[clip], stage1, adapter, args.tracker, args.step, title)
        print(f"[OK] {dst.name}: alerts at {[round(a, 1) for a in alerts]} "
              f"(fall {rows[clip]['fall_start_s'] or '-'}-{rows[clip]['fall_end_s'] or '-'} s)", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
