"""Run every stage-2 candidate behind each stage-1 variant, replay every tracker variant, and score it.

A pipeline is `<stage2>|s1=<variant>|trk=<variant>`. Frame metrics depend on stage 1 and stage 2,
event metrics on all three. The run writes per-pipeline frames/events CSVs; the analysis step
(bootstrap CIs, paired comparisons, subsets, PR figure, report) only reads those files back.

Usage (from `Fall detection/`):
    .venv/Scripts/python -I benchmark/run_benchmark.py [--models a,b] [--clips c1,c2] [--step 0.3]
        [--device auto] [--stage1-variants prod,lowconf,pose,ft] [--latency-runs 5] [--resume] [--report-only]
        [--split test|train|all]

`--split` restricts the analysis to the clips of that side of benchmark/split.csv and writes it to
results/split_<side>/ and REPORT_FINETUNE.md; scoring still runs on every selected clip, because the
per-pipeline frames/events CSVs are shared. Without `--split` the analysis goes to results/ and REPORT.md as in v3.
"""
import argparse
import csv
import gc
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only
os.environ['YOLO_AUTOINSTALL'] = 'false'   # never pip-install behind our back
os.environ['YOLO_OFFLINE'] = 'true'
os.environ['ULTRALYTICS_SAFE_LOAD'] = '1'   # weights_only torch.load with Ultralytics' class allow-list

from benchmark import frames as fr  # noqa: E402
from benchmark import metrics as mt  # noqa: E402
from benchmark.adapters import load_stage2  # noqa: E402
from benchmark.fetch_models import safe_dest, verify_file  # noqa: E402

BENCH = ROOT / 'benchmark'
RESULTS = BENCH / 'results'
FIGURES = BENCH / 'figures'
PR_FIGURE = FIGURES / 'pr_stage2.png'
MODELS_JSON = BENCH / 'models.json'
REPORT = BENCH / 'REPORT.md'
SPLIT_REPORT = BENCH / 'REPORT_FINETUNE.md'
SPLITS = ('test', 'train', 'all')
# Goal 5 of the fine-tune spec: the fine-tuned pipeline against the v3 recommendation on the same clips.
FT_TARGET = 'jerryg-ft3|s1=ft|trk=gap1'
FT_BASELINE = 'jerryg-v8x-cls|s1=pose|trk=gap1'
THRESHOLD, NEEDED = 0.4, 3
FAILURE_DUMPS = 6
LATENCY_FRAMES = 200
BASELINE = 'leeyunjai-11x'
PROD = 'prod'
# Stage-1 variants: weights id (models.json stage1 or candidates) and confidence. Same imgsz / max_det.
STAGE1_VARIANTS = {'prod': ('yolo11s', 0.3), 'lowconf': ('yolo11s', 0.1), 'pose': ('pose-rule-yolo11s', 0.3),
                   'ft': ('yolo11s-ft', 0.3)}
CI_STATS = ['event_score', 'fall_recall', 'false_alarm_clips', 'frame_f1']
SUMMARY_FIELDS = (['pipeline', 'model', 'kind', 'stage1', 'stage1_variant', 'tracker', 'status', 'error', 'n_frames',
                   'frame_precision', 'frame_recall', 'frame_f1', 'frame_accuracy', 'best_f1', 'best_threshold',
                   'fall_clips', 'nonfall_clips', 'fall_clips_alerted', 'false_alarm_clips', 'mean_latency_s',
                   'fall_clips_alerted_best', 'false_alarm_clips_best', 'mean_latency_s_best',
                   'mean_ms', 'p95_ms', 'stage1_recall', 'event_score', 'fall_recall']
                  + [f'{s}_{b}' for s in CI_STATS for b in ('lo', 'hi')]
                  + ['bootstrap_skipped', 'ap_stage2', 'auc_stage2', 'fa_per_hour', 'fa_basis', 'p95_ms_median'])
RUN_FIELDS = ['model', 'kind', 'stage1', 'stage1_variant', 'status', 'error']
FRAME_FIELDS = ['clip_id', 't', 'label', 'n_persons', 'frame_score', 'stage1_ms', 'stage2_ms']
EVENT_FIELDS = ['clip_id', 'source', 'is_fall', 'counted', 'uncertain', 'threshold', 'alerted', 'false_alarm',
                'latency_s', 'alerts']
LATENCY_FIELDS = ['model', 'stage1', 'run', 'mean_ms', 'p95_ms']
SUBSET_FIELDS = ['pipeline', 'subset', 'clips', 'fall_clips', 'fall_clips_alerted', 'frame_precision',
                 'frame_recall', 'small']
PAIRED_FIELDS = ['scope', 'a', 'b', 'metric', 'diff', 'lo', 'hi', 'verdict']


def load_models():
    return json.loads(MODELS_JSON.read_text(encoding='utf-8'))


def latency_file(split=None):
    """v3 timings stay in latency.csv; runs made for a --split analysis (the fine-tune pairs, and the baseline
    re-timed in the same session) go to latency_split.csv, so they never replace a v3 row."""
    return RESULTS / ('latency.csv' if split is None else 'latency_split.csv')


def local_ids(models):
    """Entries whose files are produced here (`local: true`, the fine-tuned weights)."""
    return {e['id'] for e in models['stage1'] + models['candidates'] if any(f.get('local') for f in e['files'])}


class View:
    """Where one analysis reads its clips from and writes to. split=None is the v3 analysis over every clip.

    `hidden` model ids (and stage-1 variants built on them) are left out; the v3 view hides the fine-tuned
    models, which were trained on 20 of its clips.
    """

    def __init__(self, manifest, split=None, hidden=()):
        self.split, self.hidden = split, set(hidden)
        self.latency = latency_file(split)
        if split is None:
            self.manifest, self.out, self.report, self.suffix, self.figure = manifest, RESULTS, REPORT, '', PR_FIGURE
            return
        if split not in SPLITS:
            raise ValueError(f'unknown split {split!r}')
        from benchmark.finetune.common import read_split   # lazy: the v3 Kaggle bundle ships no finetune/
        sides = read_split()
        missing = [r['clip_id'] for r in manifest if r['clip_id'] not in sides]
        if missing:
            raise ValueError(f'split.csv has no row for {missing}')
        self.manifest = [r for r in manifest if split == 'all' or sides[r['clip_id']] == split]
        self.out = RESULTS / f'split_{split}'
        self.report = SPLIT_REPORT
        self.suffix = '' if split == 'test' else '_all40' if split == 'all' else f'_{split}'
        self.figure = FIGURES / f'pr_stage2_split_{split}.png'

    def keeps(self, model, variant):
        return model not in self.hidden and STAGE1_VARIANTS.get(variant, ('',))[0] not in self.hidden


def write_csv(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    if not path.is_file():
        return []
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def fmt(value, digits=6):
    """Stored precision; ranking tie-breaks compare these values, so keep more digits than shown."""
    return round(value, digits) if isinstance(value, float) else value


def show(value, digits=3):
    return f'{float(value):.{digits}f}' if value not in ('', None) else ''


def pipeline_id(model, variant, tracker):
    return f'{model}|s1={variant}|trk={tracker}'


def frames_key(model, variant):   # file-name safe ('|' is not allowed on Windows)
    return f'{model}@{variant}'


def events_key(model, variant, tracker):
    return f'{model}@{variant}@{tracker}'


class Timer:
    def __init__(self, device):
        import torch
        self.sync = torch.cuda.synchronize if device.startswith('cuda') else (lambda: None)

    def __call__(self, fn):
        self.sync()
        start = time.perf_counter()
        out = fn()
        self.sync()
        return out, (time.perf_counter() - start) * 1000


def stage1_entry(models, weights_id):
    """Stage-1 weights come from models.json `stage1`, or from `candidates` for the pose variant."""
    return next((e for e in models['stage1'] + models['candidates'] if e['id'] == weights_id), None)


class Stage1:
    """Same call as Detector.predict of the measured FallGuard version (01c3556); conf varies per variant."""

    def __init__(self, entry, device, conf=0.3):
        from ultralytics import YOLO
        path = safe_dest(entry['id'], entry['files'][0]['path'])
        fallback = ROOT / 'models' / 'detection' / Path(entry['files'][0]['path']).name
        if not path.is_file() and fallback.is_file():
            path = fallback
        if not path.is_file():
            raise FileNotFoundError(f'missing stage-1 weights: {path} (run fetch_models.py)')
        verify_file(path, entry['files'][0].get('sha256'))   # the fallback copy must match the pin too
        self.model, self.device, self.conf = YOLO(str(path)), device, conf
        if self.model.names.get(0) != 'person':
            raise ValueError(f"stage-1 class 0 is {self.model.names.get(0)!r}, expected 'person'")

    def __call__(self, frame):
        result = self.model.predict(frame, classes=[0], conf=self.conf, imgsz=640+64, max_det=12,
                                    device=self.device, verbose=False)[0]
        return result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist()


def run_stage1(clips, stage1, timer, step):
    """Cache stage-1 boxes per frame so every candidate sees the same crops."""
    cache = {}
    for row, path in clips:
        items = []
        for t, frame in fr.iter_frames(path, step):
            (boxes, confs), ms = timer(lambda: stage1(frame))
            h, w = frame.shape[:2]
            items.append({'t': t, 'label': fr.label_at(t, row), 'boxes': boxes, 'confs': confs,
                          'norm': [[b[0]/w, b[1]/h, b[2]/w, b[3]/h] for b in boxes], 'stage1_ms': ms})
        cache[row['clip_id']] = items
        print(f"  stage1 {row['clip_id']}: {len(items)} frames", flush=True)
    return cache


def draw_failure(frame, item, scores, title, path):
    import cv2
    out = frame.copy()
    for box, score in zip(item['boxes'], scores):
        x1, y1, x2, y2 = map(int, box)
        color = (0, 0, 255) if score is not None and score >= THRESHOLD else (0, 200, 0)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        cv2.putText(out, 'n/a' if score is None else f'{score:.2f}', (x1, max(15, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, .6, color, 2)
    cv2.putText(out, title, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 255, 255), 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), out)


def score_candidate(adapter, clips, cache, timer, step):
    """Return frame rows and replay input per clip. Re-decodes each clip; the crops match stage 1."""
    from benchmark.legacy import square_crop
    import numpy as np
    adapter.scores([np.zeros((320, 320, 3), np.uint8)] * 2)   # warm-up outside the timed frames
    rows, replay = [], {}
    for row, path in clips:
        items, dets_per_frame = cache[row['clip_id']], []
        for item, (t, frame) in zip(items, fr.iter_frames(path, step), strict=True):
            if abs(item['t'] - t) > 1e-6:
                raise RuntimeError(f"frame times diverged in {row['clip_id']}: {item['t']} vs {t}")
            crops = [square_crop(frame, box) for box in item['boxes']]
            valid = [c for c in crops if c is not None]
            scores, ms = timer(lambda: adapter.scores(valid)) if valid else ([], 0.0)
            it = iter(scores)
            person_scores = [None if c is None else round(float(next(it)), 4) for c in crops]
            frame_score = max((s for s in person_scores if s is not None), default=0.0)
            dets_per_frame.append((t, [{'box': b, 'fall_score': s} for b, s in zip(item['norm'], person_scores)]))
            rows.append({'clip_id': row['clip_id'], 't': t, 'label': item['label'], 'n_persons': len(crops),
                         'frame_score': frame_score, 'stage1_ms': round(item['stage1_ms'], 2),
                         'stage2_ms': round(ms, 2), '_scores': person_scores})
        replay[row['clip_id']] = dets_per_frame
    return rows, replay


def dump_failures(name, rows, clips, cache, step):
    """Save the worst false positive and false negative of each clip (top clips only), boxes and scores drawn."""
    by_clip = {row['clip_id']: (row, path) for row, path in clips}

    def worst_per_clip(label, key):
        worst = {}
        for r in rows:
            if r['label'] == label and (r['clip_id'] not in worst or key(r) < key(worst[r['clip_id']])):
                worst[r['clip_id']] = r
        return sorted(worst.values(), key=key)[:FAILURE_DUMPS]

    fps = worst_per_clip('normal', lambda r: -r['frame_score'])
    fns = worst_per_clip('fall', lambda r: r['frame_score'])
    out_dir = RESULTS / 'failures' / name
    for old in out_dir.glob('*.jpg'):   # images from an earlier run would look like current failures
        old.unlink()
    for kind, picks in (('FP', [r for r in fps if r['frame_score'] >= THRESHOLD]),
                        ('FN', [r for r in fns if r['frame_score'] < THRESHOLD])):
        for r in picks:
            _, path = by_clip[r['clip_id']]
            item = next(i for i in cache[r['clip_id']] if abs(i['t'] - r['t']) < 1e-6)
            frame = fr.frames_at(path, [r['t']]).get(r['t'])
            if frame is not None:
                title = f"{kind} {r['clip_id']} t={r['t']:.1f}s score={r['frame_score']:.2f}"
                draw_failure(frame, item, r['_scores'], title,
                             out_dir / f"{kind}_{r['clip_id']}_{r['t']:.1f}.jpg")


def events_for(replay, clips, threshold, tag, tracker):
    out = []
    for row, _ in clips:
        alerts = mt.replay_alerts(replay[row['clip_id']], threshold, NEEDED, mt.TRACKERS[tracker]())
        result = mt.evaluate_clip(alerts, row, short=fr.is_short(row), uncertain=fr.is_uncertain(row))
        out.append({**result, 'clip_id': row['clip_id'], 'source': row['source'], 'threshold': tag,
                    'alerts': ';'.join(f'{t:.1f}' for t in alerts)})
    return out


def write_events(model, variant, replay, clips, best_th):
    for tracker in mt.TRACKERS:
        rows = (events_for(replay, clips, THRESHOLD, f'{THRESHOLD:g}', tracker)
                + events_for(replay, clips, best_th, f'best={best_th:g}', tracker))
        write_csv(RESULTS / f'events_{events_key(model, variant, tracker)}.csv', EVENT_FIELDS,
                  [{**e, **{k: int(e[k]) for k in ('is_fall', 'counted', 'uncertain', 'alerted', 'false_alarm')}}
                   for e in rows])


# ---------- latency pass ----------

def latency_sample(clips, cache, n=LATENCY_FRAMES, seed=0):
    """(clip_id, t) of n frames with at least one person, spread over all clips (round-robin)."""
    rng = random.Random(seed)
    pools = []
    for row, _ in clips:
        times = [i['t'] for i in cache[row['clip_id']] if i['boxes']]
        rng.shuffle(times)
        if times:
            pools.append((row['clip_id'], times))
    picks = []
    while len(picks) < n and any(times for _, times in pools):
        for clip, times in pools:
            if times and len(picks) < n:
                picks.append((clip, times.pop()))
    return picks


def load_latency_frames(clips, picks):
    paths = {row['clip_id']: path for row, path in clips}
    wanted = {}
    for clip, t in picks:
        wanted.setdefault(clip, []).append(t)
    decoded = {clip: fr.frames_at(paths[clip], times) for clip, times in wanted.items()}
    return [decoded[clip][t] for clip, t in picks if t in decoded[clip]]


def latency_pass(stage1, adapter, frames, timer):
    """Time stage 1 + crops + stage 2 per frame over the fixed sample, after a warm-up."""
    from benchmark.legacy import square_crop

    def pipeline(frame):
        boxes, _ = stage1(frame)
        crops = [c for c in (square_crop(frame, b) for b in boxes) if c is not None]
        return adapter.scores(crops) if crops else []

    for frame in frames[:mt.WARMUP_FRAMES]:
        pipeline(frame)
    return mt.latency_stats([timer(lambda: pipeline(f))[1] for f in frames], warmup=0)


def latency_rounds(stage1, variant, cands, device, frames, timer, runs):
    """`runs` rounds; each round times every candidate once, so GPU heat and clock throttling
    during a long run spread over all candidates instead of penalising the ones measured last."""
    rows = []
    for run in range(1, runs + 1):
        for cand in cands:
            adapter = None
            try:
                adapter = load_stage2(cand, device)
                rows.append({'model': cand['id'], 'stage1': variant, 'run': run,
                             **latency_pass(stage1, adapter, frames, timer)})
            except Exception as e:   # scoring already succeeded; a timing failure only loses this run
                print(f"  latency {cand['id']} run {run} FAILED {type(e).__name__}: {e}", flush=True)
            finally:
                del adapter
                free_gpu()
        print(f"  latency round {run}: " + ', '.join(f"{r['model']}={r['p95_ms']}" for r in rows if r['run'] == run),
              flush=True)
    return rows


def free_gpu():
    import torch
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def already_scored(runs, model, variant, results=RESULTS):
    """--resume: (model, variant) has an ok runs.csv row and its frames CSV exists."""
    ok = any(r['model'] == model and r['stage1_variant'] == variant and r['status'] == 'ok' for r in runs)
    return ok and (results / f'frames_{frames_key(model, variant)}.csv').is_file()


def stage1_failure_rows(candidates, ids, weights_id, variant, reason, keep_runs=()):
    """runs.csv rows when a whole stage-1 variant fails. Missing candidates keep status missing, and
    pairs already ok in keep_runs (--resume) are left out so their earlier rows and files stay valid."""
    rows = []
    for c in candidates:
        if ids and c['id'] not in ids:
            continue
        if any(r['model'] == c['id'] and r['stage1_variant'] == variant and r['status'] == 'ok' for r in keep_runs):
            continue
        missing = c.get('status') == 'missing'
        rows.append({'model': c['id'], 'kind': c['kind'], 'stage1': weights_id, 'stage1_variant': variant,
                     'status': 'missing' if missing else 'failed',
                     'error': c.get('notes', 'weights not found') if missing else reason})
    return rows


def upsert(path, fields, new_rows, key):
    rows = {key(r): r for r in read_csv(path)}
    for r in new_rows:
        rows[key(r)] = {k: r.get(k, '') for k in fields}
    write_csv(path, fields, list(rows.values()))


# ---------- analysis (reads results/ only) ----------

def _bools(e):
    return {**e, **{k: bool(int(e[k] or 0)) for k in ('is_fall', 'counted', 'uncertain', 'alerted', 'false_alarm')},
            'latency_s': float(e['latency_s']) if e['latency_s'] else None}


def clip_durations(frame_rows):
    """Seconds per clip from the sampled times (last t plus one step)."""
    times = {}
    for r in frame_rows:
        times.setdefault(r['clip_id'], []).append(float(r['t']))
    out = {}
    for clip, ts in times.items():
        step = ts[1] - ts[0] if len(ts) > 1 else 0.0
        out[clip] = max(ts) + step
    return out


def n_alerts(event):
    return len(event['alerts'].split(';')) if event['alerts'] else 0


def analyze(models, view):
    """Build summary, subsets, paired and the PR figure from the per-pipeline CSVs, on the view's clips only.
    Returns (summary rows, events at 0.4 per pipeline)."""
    rows_by_clip = {r['clip_id']: r for r in view.manifest}
    entries = {e['id']: e for e in models['candidates']}
    latency = read_csv(view.latency)
    p95_median = {}
    for r in latency:
        p95_median.setdefault((r['model'], r['stage1']), []).append(float(r['p95_ms']))
    summary, subsets, events04, stats, pr_curves = [], [], {}, {}, {}
    for run in read_csv(RESULTS / 'runs.csv'):
        if not view.keeps(run['model'], run['stage1_variant']):
            continue
        model, variant = run['model'], run['stage1_variant']
        frames = read_csv(RESULTS / f'frames_{frames_key(model, variant)}.csv') if run['status'] == 'ok' else []
        frames = [r for r in frames if r['clip_id'] in rows_by_clip]
        if run['status'] == 'ok' and not frames:
            run = {**run, 'status': 'failed', 'error': 'frames CSV missing'}
        labels = [r['label'] for r in frames]
        scores = [float(r['frame_score']) for r in frames]
        frame_clips = [r['clip_id'] for r in frames]
        if frames:
            at = mt.frame_metrics(labels, scores, THRESHOLD)
            best_f1, best_th, _ = mt.threshold_sweep(labels, scores)
            counts = mt.clip_counts(frame_clips, labels, scores, THRESHOLD)
            speed = mt.latency_stats([float(r['stage1_ms']) + float(r['stage2_ms']) for r in frames])
            seen = [(r['label'] == 'fall', float(r['frame_score'])) for r in frames
                    if int(r['n_persons']) > 0 and r['label'] != 'ignore']
            ap = mt.average_precision([y for y, _ in seen], [s for _, s in seen])
            auc = mt.roc_auc([y for y, _ in seen], [s for _, s in seen])
            if variant == PROD:
                pr_curves[model] = (mt.pr_points([y for y, _ in seen], [s for _, s in seen]), ap)
            durations = clip_durations(frames)
            clip_ids = sorted(durations)
            # Short falls get their own stratum so every resample keeps the same number of counted fall clips.
            strata = {c: ('normal' if rows_by_clip[c]['is_fall'] != '1' else
                          'short' if fr.is_short(rows_by_clip[c]) else 'fall') for c in clip_ids if c in rows_by_clip}
            clip_ids = [c for c in clip_ids if c in strata]
            long_ids = [c for c in clip_ids if fr.is_long(rows_by_clip[c])]
            fa_ids = long_ids or [c for c in clip_ids if strata[c] == 'normal']
        runs_p95 = p95_median.get((model, variant))
        for tracker in mt.TRACKERS:
            pid = pipeline_id(model, variant, tracker)
            base = {'pipeline': pid, 'model': model, 'kind': run['kind'], 'stage1': run['stage1'],
                    'stage1_variant': variant, 'tracker': tracker, 'status': run['status'], 'error': run['error'],
                    'p95_ms_median': fmt(statistics.median(runs_p95)) if runs_p95 else ''}
            events = [_bools(e) for e in read_csv(RESULTS / f'events_{events_key(model, variant, tracker)}.csv')
                      if e['clip_id'] in rows_by_clip]
            if base['status'] != 'ok' or not events:
                summary.append({**base, 'status': 'failed' if base['status'] == 'ok' else base['status'],
                                'error': base['error'] or 'events CSV missing'})
                continue
            ev = [e for e in events if e['threshold'] == f'{THRESHOLD:g}']
            ev_best = [e for e in events if e['threshold'] != f'{THRESHOLD:g}']
            s, s_best = mt.summarize_events(ev), mt.summarize_events(ev_best)
            by_clip = {e['clip_id']: e for e in ev}
            events04[pid] = ev
            fns = mt.stat_fns(by_clip, counts)
            stats[pid] = (clip_ids, fns, strata)
            cis = {name: mt.bootstrap(clip_ids, fns[name], strata=strata) for name in CI_STATS}
            fa = mt.fa_per_hour([(n_alerts(by_clip[c]), durations[c]) for c in fa_ids if c in by_clip])
            summary.append({**base, 'n_frames': len(frames),
                            'frame_precision': fmt(at['precision']), 'frame_recall': fmt(at['recall']),
                            'frame_f1': fmt(at['f1']), 'frame_accuracy': fmt(at['accuracy']), 'best_f1': fmt(best_f1),
                            'best_threshold': best_th, 'fall_clips': s['fall_clips'],
                            'nonfall_clips': s['nonfall_clips'], 'fall_clips_alerted': s['fall_clips_alerted'],
                            'false_alarm_clips': s['false_alarm_clips'], 'mean_latency_s': s['mean_latency_s'],
                            'fall_clips_alerted_best': s_best['fall_clips_alerted'],
                            'false_alarm_clips_best': s_best['false_alarm_clips'],
                            'mean_latency_s_best': s_best['mean_latency_s'], **speed,
                            'stage1_recall': fmt(mt.stage1_recall(labels, [int(r['n_persons']) for r in frames])),
                            'event_score': cis['event_score']['point'], 'fall_recall': fmt(cis['fall_recall']['point']),
                            **{f'{n}_{b}': fmt(cis[n][b]) for n in CI_STATS for b in ('lo', 'hi')},
                            'bootstrap_skipped': max(c['skipped'] for c in cis.values()),
                            'ap_stage2': fmt(ap), 'auc_stage2': fmt(auc), 'fa_per_hour': fmt(fa),
                            'fa_basis': 'long' if long_ids else 'all non-fall'})
            manifest_rows = [rows_by_clip[c] for c in clip_ids]
            subsets += [{'pipeline': pid, **r, 'frame_precision': fmt(r['frame_precision']),
                         'frame_recall': fmt(r['frame_recall']), 'small': int(r['small'])}
                        for r in mt.subset_breakdown(manifest_rows, frames, by_clip, THRESHOLD)]
    summary.sort(key=lambda r: (r['model'], list(STAGE1_VARIANTS).index(r['stage1_variant'])
                                if r['stage1_variant'] in STAGE1_VARIANTS else 99, r['tracker']))
    write_csv(view.out / 'summary.csv', SUMMARY_FIELDS, summary)
    write_csv(view.out / 'subsets.csv', SUBSET_FIELDS, subsets)
    extra = [(FT_TARGET, FT_BASELINE)] if view.split else []
    write_csv(view.out / 'paired.csv', PAIRED_FIELDS, paired_rows(summary, entries, stats, extra))
    if pr_curves:
        plot_pr(pr_curves, view.figure)
    return summary, events04


def with_license(rows, entries):
    return [{**r, 'license': entries.get(r['model'], {}).get('license', '')} for r in rows]


def prod_rows(summary):
    return [r for r in summary if r['stage1_variant'] == PROD and r['tracker'] == PROD]


def paired_rows(summary, entries, stats, extra=()):
    """Event-score (and F1) differences on shared resamples.

    Both scopes first compare the top two by rule v2 order (the tie check), then compare the rule-v2
    winner (after any tie-break) with the other side of that pair and with every production pipeline.
    stage2 scope ranks the production pipelines only; pipeline scope ranks every combination.
    `extra` pairs (a, b) of pipeline ids are compared in scope `goal` when both are ok.
    """
    out, done = [], set()

    def add(scope, a, b):
        key = (scope, frozenset((a['pipeline'], b['pipeline'])))   # one row per pair, whatever the order
        if a['pipeline'] == b['pipeline'] or key in done:
            return
        done.add(key)
        ids_a, fns_a, strata = stats[a['pipeline']]
        ids_b, fns_b, _ = stats[b['pipeline']]
        shared = [c for c in ids_a if c in set(ids_b)]
        for metric in ('event_score', 'frame_f1'):
            ci = mt.paired_bootstrap(fns_a[metric], fns_b[metric], shared, strata=strata)
            out.append({'scope': scope, 'a': a['pipeline'], 'b': b['pipeline'], 'metric': metric,
                        'diff': fmt(ci['point']), 'lo': fmt(ci['lo']), 'hi': fmt(ci['hi']),
                        'verdict': 'tie' if mt.is_tie(ci) else 'different'})

    ok = [r for r in with_license(summary, entries) if r['status'] == 'ok' and r['pipeline'] in stats]
    for scope, rows in (('stage2', prod_rows(ok)), ('pipeline', ok)):
        ranked = mt.rank_v2(rows)
        if len(ranked) > 1:
            add(scope, ranked[0], ranked[1])
        winner, _, _ = mt.recommend_v2(rows, lambda a, b: pair_is_tie(out, scope, a, b))
        if winner:
            for other in ranked[:2] + prod_rows(ok):
                add(scope, winner, other)
    by_id = {r['pipeline']: r for r in ok}
    for a, b in extra:
        if a in by_id and b in by_id:
            add('goal', by_id[a], by_id[b])
    return out


def pair_is_tie(paired, scope, a, b):
    """Event-score verdict for a pair in either order; a missing pair is not a tie."""
    for r in paired:
        if r['scope'] == scope and r['metric'] == 'event_score' and {r['a'], r['b']} == {a['pipeline'], b['pipeline']}:
            return r['verdict'] == 'tie'
    return False


def plot_pr(curves, path=PR_FIGURE):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(6.4, 4.8), dpi=100)
    for model in sorted(curves):
        points, ap = curves[model]
        if points:
            ax.plot([0.0] + [r for r, _ in points], [1.0] + [p for _, p in points],
                    label=f"{model} (AP {ap:.3f})" if ap is not None else model, linewidth=1.5)
    ax.set_xlabel('Recall (stage 2, frames with a person)')
    ax.set_ylabel('Precision')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=.3)
    ax.legend(fontsize=8, loc='lower left')
    ax.set_title('Stage-2 PR curves, stage 1 = prod (yolo11s, conf 0.3)')
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, metadata={'Software': None})   # no version string: reruns give the same bytes
    plt.close(fig)


# ---------- report tables ----------

def md_cell(value):
    text = '' if value is None else str(value)
    return ' '.join(text.split()).replace('|', '\\|').replace('<!--', '&lt;!--')


def md_table(headers, rows):
    lines = ['| ' + ' | '.join(headers) + ' |', '|' + '--|' * len(headers)]
    lines += ['| ' + ' | '.join(md_cell(v) for v in row) + ' |' for row in rows]
    return '\n'.join(lines)


def leak_map(models, manifest):
    """Candidate id -> manifest source names (original spelling) that appear in its trained_on."""
    sources = {r['source'].lower(): r['source'] for r in manifest}
    return {e['id']: {sources[t.lower()] for t in e.get('trained_on', []) if t.lower() in sources}
            for e in models['candidates']}


def ci(row, name, digits=3):
    if row.get(f'{name}_lo') in ('', None):
        return show(row.get(name), digits)
    return f"{show(row[name], digits)} [{show(row[f'{name}_lo'], digits)}, {show(row[f'{name}_hi'], digits)}]"


def ratio(a, b):
    return f'{a}/{b}' if a not in ('', None) else ''


def pair_row(paired, scope, a, b, metric='event_score'):
    """The paired row for a − b, flipping a stored b − a row; None when the pair was not computed."""
    for r in paired:
        if r['scope'] != scope or r['metric'] != metric:
            continue
        if (r['a'], r['b']) == (a, b):
            return r
        if (r['a'], r['b']) == (b, a):
            def neg(v):
                return '' if v in ('', None) else -float(v)
            return {**r, 'a': a, 'b': b, 'diff': neg(r['diff']), 'lo': neg(r['hi']), 'hi': neg(r['lo'])}
    return None


def recommendation_block(title, scope, rows, events, leaks, paired):
    """Rule v2 applied to `rows`; returns (markdown lines, winner)."""
    def tie(a, b):
        return pair_is_tie(paired, scope, a, b)

    winner, ranked, tied = mt.recommend_v2(rows, tie)
    lines = [f'**{title}**', '']
    if not ranked:
        return lines + [f'_Không có pipeline nào có trạng thái ok và p95 trung vị ≤ {mt.MAX_P95_MS:g} ms._', ''], None
    table = [(i + 1, r['pipeline'], ci(r, 'event_score', 0), ratio(r['fall_clips_alerted'], r['fall_clips']),
              r['false_alarm_clips'], show(r['fa_per_hour'], 2), show(r['frame_f1'], 4), show(r['p95_ms_median'], 1),
              r['license']) for i, r in enumerate(ranked[:10])]
    lines += [md_table(['Hạng', 'Pipeline', 'Điểm sự kiện [CI 95%]', 'Clip ngã cảnh báo', 'Clip cảnh báo sai',
                        'Cảnh báo sai/giờ', 'F1 frame', 'p95 trung vị (ms)', 'License'], table), '']
    if len(ranked) > 1:
        a, b = mt.rank_v2(rows)[:2]   # order before the tie-break
        hit = pair_row(paired, scope, a['pipeline'], b['pipeline'])
        if hit:
            verdict = '**hoà (tie)**' if hit['verdict'] == 'tie' else '**khác biệt (different)**'
            lines.append(f"Hai pipeline đầu: `{a['pipeline']}` − `{b['pipeline']}` = {show(hit['diff'], 0)} điểm sự kiện, "
                         f"CI 95% [{show(hit['lo'], 0)}, {show(hit['hi'], 0)}] → {verdict}."
                         + (f" Áp dụng tie-break (cảnh báo sai/giờ thấp hơn, rồi có license, rồi p95 trung vị thấp hơn) "
                            f"→ `{winner['pipeline']}`." if tied else ''))
        else:
            lines.append('_Không có CI cặp cho hai pipeline đầu._')
        lines.append('')
    overlap_of = (lambda r: leaks.get(r['model'], set()))
    winner, note = mt.leak_check(winner, ranked, events, overlap_of, tie)
    if winner:
        lines.append(f"**Đề xuất: `{winner['pipeline']}`**: cảnh báo đúng {winner['fall_clips_alerted']}/"
                     f"{winner['fall_clips']} clip ngã (recall {ci(winner, 'fall_recall', 2)}), cảnh báo sai "
                     f"{winner['false_alarm_clips']} clip ({show(winner['fa_per_hour'], 2)}/giờ, cơ sở: "
                     f"{winner['fa_basis']}), F1 frame {ci(winner, 'frame_f1')}, p95 trung vị "
                     f"{show(winner['p95_ms_median'], 1)} ms.")
    if note:
        lines.append(f'\nGhi chú leakage: {note}.')
    real, _ = mt.winner_on(ranked, events, lambda e: fr.source_group(e) == 'real', tie)
    if real and winner:
        same = real['pipeline'] == winner['pipeline']
        lines.append(f"\nChỉ xét nhóm `real` (youtube), cùng luật v2: đứng đầu là `{real['pipeline']}` "
                     f"({real['fall_clips_alerted']} clip ngã cảnh báo, {real['false_alarm_clips']} clip cảnh báo sai)"
                     f" → {'không đổi người thắng' if same else '**người thắng thay đổi**'}.")
    lines.append('')
    return lines, winner


def goal_block(summary, paired, decides=True):
    """Goal 5 of the fine-tune spec: FT_TARGET against FT_BASELINE on the view's clips. Only the test split
    decides Goal 5; other views get the same table marked as reference only."""
    rows = {r['pipeline']: r for r in summary if r['status'] == 'ok'}
    target, base = rows.get(FT_TARGET), rows.get(FT_BASELINE)
    if not target or not base:
        return f'_Chưa có kết quả ok cho cả `{FT_TARGET}` và `{FT_BASELINE}`._'
    table = md_table(['Pipeline', 'Điểm sự kiện [CI 95%]', 'Clip ngã cảnh báo', 'Clip cảnh báo sai', 'Cảnh báo sai/giờ',
                      'F1 frame', 'p95 trung vị (ms)'],
                     [(r['pipeline'], ci(r, 'event_score', 0), ratio(r['fall_clips_alerted'], r['fall_clips']),
                       r['false_alarm_clips'], show(r['fa_per_hour'], 2), show(r['frame_f1'], 4),
                       show(r['p95_ms_median'], 1)) for r in (target, base)])
    hit = pair_row(paired, 'goal', FT_TARGET, FT_BASELINE)
    pair = (f"Hiệu cặp `{FT_TARGET}` − `{FT_BASELINE}` = {show(hit['diff'], 0)} điểm sự kiện, CI 95% "
            f"[{show(hit['lo'], 0)}, {show(hit['hi'], 0)}] → "
            f"{'hoà (tie)' if hit['verdict'] == 'tie' else 'khác biệt (different)'}." if hit
            else '_Không có CI cặp._')
    p95 = mt._num(target.get('p95_ms_median'))
    checks = [
        (f"điểm sự kiện {mt.event_score(target)} ≥ {mt.event_score(base)} (baseline)",
         mt.event_score(target) >= mt.event_score(base)),
        (f"clip cảnh báo sai {target['false_alarm_clips']} ≤ {base['false_alarm_clips']} (baseline)",
         int(target['false_alarm_clips']) <= int(base['false_alarm_clips'])),
        (f"p95 trung vị {show(target.get('p95_ms_median'), 1) or 'chưa đo'} ms ≤ {mt.MAX_P95_MS:g} ms",
         p95 <= mt.MAX_P95_MS),
    ]
    met = all(ok for _, ok in checks)
    lines = [table, '', pair, ''] + [f"- {'✅' if ok else '❌'} {text}" for text, ok in checks]
    if decides:
        lines += ['', f"**Goal 5: {'ĐẠT' if met else 'KHÔNG ĐẠT'}** (tính tự động từ ba điều kiện trên)."]
    else:
        lines += ['', '_Chỉ để tham khảo: tập clip này chứa dữ liệu huấn luyện stage 2 (bị nhiễm), nên không quyết định '
                      'Goal 5. Chỉ kết quả trên 20 clip test quyết định._']
    return '\n'.join(lines)


def render_sections(summary, models, view, events):
    manifest = view.manifest
    available = {p.stem for p in fr.CLIPS.glob('*.mp4')}
    entries = {e['id']: e for e in models['candidates']}
    summary = with_license(summary, entries)
    clip_rows = [(r['clip_id'], r['source'], r['view'], r.get('lighting', ''),
                  'ngã' if r['is_fall'] == '1' else 'không ngã',
                  f"{r['fall_start_s']}–{r['fall_end_s']}" if r['is_fall'] == '1' else '—',
                  r['notes'] or '', 'có' if r['clip_id'] in available else '**thiếu**') for r in manifest]
    leaks = leak_map(models, manifest)
    cand_rows = [(e['id'], e['kind'], e['source_url'], e.get('license', ''), ', '.join(e.get('trained_on', [])),
                  ('**có**: ' + ', '.join(sorted(leaks[e['id']]))) if leaks[e['id']] else 'không',
                  e.get('status', 'ok')) for e in models['candidates']]

    prod = sorted(prod_rows(summary), key=lambda r: (r['status'] != 'ok', r['model']))
    res_rows = [(r['model'], r['kind'], r['status'], show(r.get('frame_precision')), show(r.get('frame_recall')),
                 show(r.get('frame_f1')), show(r.get('frame_accuracy')),
                 ratio(r.get('fall_clips_alerted'), r.get('fall_clips')),
                 ratio(r.get('false_alarm_clips'), int(r.get('fall_clips') or 0) + int(r.get('nonfall_clips') or 0))
                 if r['status'] == 'ok' else '', show(r.get('mean_latency_s'), 2), show(r.get('mean_ms'), 1),
                 show(r.get('p95_ms_median'), 1), show(r.get('stage1_recall')), r['error']) for r in prod]
    best_rows = [(r['model'], r['best_threshold'], show(r['best_f1']),
                  ratio(r['fall_clips_alerted_best'], r['fall_clips']), r['false_alarm_clips_best'],
                  show(r['mean_latency_s_best'], 2)) for r in prod if r['status'] == 'ok']
    ok_prod = [r for r in prod if r['status'] == 'ok']
    skipped = [r for r in summary if r.get('bootstrap_skipped') not in ('', None)
               and int(r['bootstrap_skipped']) > mt.BOOTSTRAP_N // 100]
    ci_rows = [(r['model'], ci(r, 'event_score', 0), ci(r, 'fall_recall', 2), ci(r, 'false_alarm_clips', 0),
                ci(r, 'frame_f1')) for r in ok_prod]
    ci_text = [md_table(['Model', 'Điểm sự kiện', 'Recall clip ngã', 'Clip cảnh báo sai', 'F1 frame'], ci_rows), '',
               f'Bootstrap {mt.BOOTSTRAP_N} lần, lấy mẫu lại theo clip, phân tầng ngã / không ngã, seed 0.']
    if skipped:
        ci_text.append('Resample suy biến bị bỏ > 1%: ' + ', '.join(
            f"`{r['pipeline']}` ({r['bootstrap_skipped']})" for r in skipped) + '.')

    paired = read_csv(view.out / 'paired.csv')
    scope_names = {'stage2': 'stage 2 (s1=prod, trk=prod)', 'pipeline': 'pipeline tốt nhất', 'goal': 'Goal 5'}
    paired_table = [(scope_names.get(r['scope'], r['scope']), r['a'], r['b'],
                     'điểm sự kiện' if r['metric'] == 'event_score' else 'F1 frame',
                     show(r['diff'], 0 if r['metric'] == 'event_score' else 4),
                     f"[{show(r['lo'], 0 if r['metric'] == 'event_score' else 4)}, "
                     f"{show(r['hi'], 0 if r['metric'] == 'event_score' else 4)}]",
                     'hoà (tie)' if r['verdict'] == 'tie' else 'khác biệt (different)') for r in paired]

    subsets = read_csv(view.out / 'subsets.csv')
    by_subset = {}
    for r in subsets:
        by_subset.setdefault(r['subset'], {})[r['pipeline']] = r
    models_ok = [r['model'] for r in ok_prod]
    subset_rows = []
    for key in sorted(by_subset):
        cells = by_subset[key]
        any_row = next(iter(cells.values()))
        label = f"{key} (n < {mt.SMALL_SUBSET})" if any_row['small'] == '1' else key
        subset_rows.append([label, any_row['clips'], any_row['fall_clips']] + [
            (f"R {show(c['frame_recall'], 2)} · P {show(c['frame_precision'], 2)} · "
             f"{c['fall_clips_alerted']}/{c['fall_clips']}") if (c := cells.get(pipeline_id(m, PROD, PROD))) else ''
            for m in models_ok])

    stage2_rows = [(r['model'], show(r['ap_stage2']), show(r['auc_stage2'])) for r in ok_prod]
    figure = view.figure.relative_to(BENCH).as_posix()

    ok_all = [r for r in summary if r['status'] == 'ok']
    top10 = sorted(ok_all, key=lambda r: (-mt.event_score(r), -float(r['frame_f1']),
                                          mt._num(r.get('p95_ms_median'))))[:10]
    pipe_rows = [(i + 1, r['pipeline'], ci(r, 'event_score', 0), ratio(r['fall_clips_alerted'], r['fall_clips']),
                  r['false_alarm_clips'], show(r['fa_per_hour'], 2), show(r['frame_f1'], 4), show(r['stage1_recall']),
                  show(r['p95_ms_median'], 1), 'có' if mt._num(r.get('p95_ms_median')) <= mt.MAX_P95_MS else 'không')
                 for i, r in enumerate(top10)]

    latency = [r for r in read_csv(view.latency) if view.keeps(r['model'], r['stage1'])]
    lat = {}
    for r in latency:
        lat.setdefault((r['stage1'], r['model']), []).append(r)
    lat_rows = [(s1, m, len(rs), ' / '.join(show(r['p95_ms'], 1) for r in sorted(rs, key=lambda r: int(r['run']))),
                 show(statistics.median(float(r['p95_ms']) for r in rs), 1),
                 show(statistics.mean(float(r['mean_ms']) for r in rs), 1))
                for (s1, m), rs in sorted(lat.items(), key=lambda kv: (list(STAGE1_VARIANTS).index(kv[0][0])
                                                                       if kv[0][0] in STAGE1_VARIANTS else 99, kv[0][1]))]

    sample = [int(r['n_persons']) for r in read_csv(RESULTS / 'latency_sample.csv')]
    sample_note = (f' Số người mỗi frame trong mẫu (stage 1 đầu tiên): trung vị {statistics.median(sample):g}, '
                   f'{sum(n >= 6 for n in sample)}/{len(sample)} frame có ≥ 6 người; stage 2 chạy theo batch 2 crop '
                   'nên thời gian tăng gần tuyến tính theo số người.') if sample else ''

    rule = ('Luật v2: chỉ xét pipeline có trạng thái ok và p95 trung vị ≤ 200 ms; xếp theo điểm sự kiện (số clip ngã '
            'được cảnh báo − số clip cảnh báo sai) ở ngưỡng 0.4, rồi F1 frame, rồi p95 trung vị. Nếu CI 95% của hiệu '
            'điểm sự kiện giữa hai pipeline đầu chứa 0 thì coi là hoà và xét lần lượt: cảnh báo sai/giờ thấp hơn, có '
            'license, p95 trung vị thấp hơn.')
    rec_stage2, _ = recommendation_block('Đề xuất stage 2 cho pipeline hiện tại (s1=prod, trk=prod)', 'stage2',
                                         prod_rows(summary), events, leaks, paired)
    rec_pipe, winner_p = recommendation_block('Đề xuất pipeline đầy đủ (mọi tổ hợp)', 'pipeline', summary,
                                              events, leaks, paired)
    gain = []
    if winner_p:
        same = pipeline_id(winner_p['model'], PROD, PROD)
        hit = pair_row(paired, 'pipeline', winner_p['pipeline'], same)
        if winner_p['pipeline'] == same:
            gain.append('Pipeline tốt nhất chính là pipeline production của stage 2 này.')
        elif hit:
            gain.append(f"So với pipeline production của cùng stage 2 (`{same}`): {float(hit['diff']):+.0f} điểm sự kiện, "
                        f"CI 95% [{show(hit['lo'], 0)}, {show(hit['hi'], 0)}] → "
                        f"{'hoà (tie)' if hit['verdict'] == 'tie' else 'khác biệt (different)'}.")
        else:
            gain.append(f'_Không có CI cặp giữa pipeline đề xuất và `{same}`._')

    sections = {
        'clips': md_table(['clip_id', 'Nguồn', 'Góc nhìn', 'Ánh sáng', 'Loại', 'Ngã (s)', 'Ghi chú', 'File'], clip_rows),
        'candidates': md_table(['id', 'Loại', 'Nguồn', 'License', 'trained_on', 'Leakage', 'Trạng thái'], cand_rows),
        'results': md_table(['Model', 'Loại', 'Trạng thái', 'Precision', 'Recall', 'F1', 'Accuracy',
                             'Clip ngã cảnh báo', 'Clip cảnh báo sai', 'Độ trễ TB (s)', 'TB (ms)', 'p95 trung vị (ms)',
                             'Stage-1 recall', 'Lỗi'], res_rows),
        'results_best': md_table(['Model', 'Ngưỡng tốt nhất', 'F1 tốt nhất', 'Clip ngã cảnh báo',
                                  'Clip cảnh báo sai', 'Độ trễ TB (s)'], best_rows),
        'results_ci': '\n'.join(ci_text),
        'paired': md_table(['Phạm vi', 'A', 'B', 'Chỉ số', 'A − B', 'CI 95%', 'Kết luận'], paired_table)
        if paired_table else '_Chưa có so sánh cặp._',
        'subsets': md_table(['Tập con', 'Clip', 'Clip ngã'] + models_ok, subset_rows)
        + '\n\nMỗi ô: recall frame (R) · precision frame (P) · clip ngã được cảnh báo, pipeline s1=prod, trk=prod.',
        'stage2_only': md_table(['Model', 'AP', 'ROC AUC'], stage2_rows)
        + f'\n\nChỉ tính frame stage 1 `prod` tìm thấy người và nhãn khác `ignore`.\n\n![PR stage 2]({figure})',
        'pipelines': md_table(['Hạng', 'Pipeline', 'Điểm sự kiện [CI 95%]', 'Clip ngã cảnh báo', 'Clip cảnh báo sai',
                               'Cảnh báo sai/giờ', 'F1 frame', 'Stage-1 recall', 'p95 trung vị (ms)', '≤ 200 ms'],
                              pipe_rows),
        'latency': md_table(['Stage 1', 'Stage 2', 'Số lần chạy', 'p95 từng lần (ms)', 'p95 trung vị (ms)', 'TB (ms)'],
                            lat_rows) + f'\n\nMẫu cố định {LATENCY_FRAMES} frame có người (seed 0, lần lượt qua từng clip), '
                                        'stage 1 + crop + stage 2, CUDA synchronize trước và sau mỗi frame. Mỗi vòng đo '
                                        'lần lượt mọi model nên nhiệt độ GPU ảnh hưởng đều.' + sample_note,
        'recommendation': '\n'.join([rule, ''] + rec_stage2 + rec_pipe + gain),
    }
    if view.split:
        sections['goal'] = goal_block(summary, paired, decides=view.split == 'test')
    return sections


def write_report(sections, view):
    """Replace <!-- BEGIN GENERATED: x<suffix> --> ... <!-- END GENERATED: x<suffix> --> blocks in the view's report."""
    view.out.mkdir(parents=True, exist_ok=True)
    (view.out / 'report_tables.md').write_text(
        '\n\n'.join(f'## {k}\n\n{v}' for k, v in sections.items()) + '\n', encoding='utf-8')
    if not view.report.is_file():
        return
    text = view.report.read_text(encoding='utf-8')
    for key, body in sections.items():
        key += view.suffix
        begin, end = f'<!-- BEGIN GENERATED: {key} -->', f'<!-- END GENERATED: {key} -->'
        if begin in text and end in text:
            head, rest = text.split(begin, 1)
            text = f'{head}{begin}\n{body}\n{end}{rest.split(end, 1)[1]}'
    view.report.write_text(text, encoding='utf-8')


def report(models, manifest, split=None):
    view = View(manifest, split, local_ids(models) if split is None else ())
    models = {**models, 'candidates': [c for c in models['candidates'] if c['id'] not in view.hidden]}
    summary, events = analyze(models, view)
    write_report(render_sections(summary, models, view, events), view)
    return summary, view


def stored_latency_sample(clips):
    """(clip_id, t) picks from results/latency_sample.csv, kept only for clips in this run."""
    names = {row['clip_id'] for row, _ in clips}
    return [(r['clip_id'], float(r['t'])) for r in read_csv(RESULTS / 'latency_sample.csv') if r['clip_id'] in names]


def latency_only(models, manifest, clips, variants, ids, runs, device, timer, n_runs, split=None):
    """--latency-only: time every (variant, ok model) pair on the stored sample; no scoring.

    Falls back to drawing a new sample from stage 1 prod when none is stored. Each variant's rows in
    latency.csv are replaced as a whole, so one variant never mixes sessions.
    """
    picks = stored_latency_sample(clips)
    if not picks:
        weights_id, conf = STAGE1_VARIANTS[PROD]
        stage1 = Stage1(stage1_entry(models, weights_id), device, conf)
        print(f'No stored latency sample: running stage 1 {PROD} on {len(clips)} clips to draw one...', flush=True)
        cache = run_stage1(clips, stage1, timer, 0.3)
        picks = latency_sample(clips, cache)
        persons = {(c, i['t']): len(i['boxes']) for c, items in cache.items() for i in items}
        write_csv(RESULTS / 'latency_sample.csv', ['clip_id', 't', 'n_persons'],
                  [{'clip_id': c, 't': t, 'n_persons': persons[(c, t)]} for c, t in picks])
        del stage1, cache
        free_gpu()
    frames = load_latency_frames(clips, picks)
    print(f'Latency sample: {len(frames)} frames', flush=True)
    for variant in variants:
        cands = [c for c in models['candidates'] if (not ids or c['id'] in ids)
                 and any(r['model'] == c['id'] and r['stage1_variant'] == variant and r['status'] == 'ok' for r in runs)]
        if not cands:
            print(f'[SKIP] {variant}: no ok pairs in runs.csv')
            continue
        weights_id, conf = STAGE1_VARIANTS[variant]
        stage1 = Stage1(stage1_entry(models, weights_id), device, conf)
        print(f'Stage 1 {variant}: timing {len(cands)} candidates x {n_runs} rounds', flush=True)
        rows = latency_rounds(stage1, variant, cands, device, frames, timer, n_runs)
        done = {(c['id'], variant) for c in cands}
        kept = [r for r in read_csv(latency_file(split)) if (r['model'], r['stage1']) not in done]
        write_csv(latency_file(split), LATENCY_FIELDS, kept + rows)
        del stage1
        free_gpu()
    summary, view = report(models, manifest, split)
    print(f"Wrote {view.out / 'summary.csv'} ({len(summary)} pipelines)")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--models', default='', help='comma-separated candidate ids (default: all)')
    parser.add_argument('--clips', default='', help='comma-separated clip ids (default: all fetched)')
    parser.add_argument('--step', type=float, default=0.3)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--stage1-variants', default='prod,lowconf,pose',
                        help=f"comma-separated, from {', '.join(STAGE1_VARIANTS)} (default: the v3 three)")
    parser.add_argument('--latency-runs', type=int, default=5, help='timed passes over the fixed frame sample')
    parser.add_argument('--report-only', action='store_true', help='only rerun the analysis and report from results/')
    parser.add_argument('--resume', action='store_true',
                        help='skip (model, stage-1 variant) pairs already ok in results/runs.csv (same clip set only); '
                             'they are still timed in the latency rounds')
    parser.add_argument('--latency-only', action='store_true',
                        help='only time the pairs already ok in results/runs.csv (e.g. after scoring on another '
                             'machine), on the frame sample stored in results/latency_sample.csv')
    parser.add_argument('--split', choices=SPLITS,
                        help='analyse only that side of split.csv into results/split_<side>/ and REPORT_FINETUNE.md '
                             '(scoring still covers every selected clip)')
    args = parser.parse_args(argv)
    if args.latency_only and args.latency_runs < 1:
        parser.error('--latency-only needs --latency-runs >= 1')

    models, manifest = load_models(), fr.read_manifest()
    if args.report_only:
        report(models, manifest, args.split)
        return 0

    variants = [v for v in args.stage1_variants.split(',') if v]
    unknown = [v for v in variants if v not in STAGE1_VARIANTS]
    if unknown or not variants:
        print(f"[ERROR] unknown stage-1 variant(s): {', '.join(unknown) or '(none given)'}")
        return 1

    import torch
    from benchmark.legacy import select_device
    device = select_device(torch, args.device)
    print(f'torch {torch.__version__} | device={device}', flush=True)

    wanted = {c for c in args.clips.split(',') if c}
    clips = [(r, fr.CLIPS / f"{r['clip_id']}.mp4") for r in manifest if not wanted or r['clip_id'] in wanted]
    missing = [r['clip_id'] for r, p in clips if not p.is_file()]
    clips = [(r, p) for r, p in clips if p.is_file()]
    if missing:
        print(f'[WARN] missing clips (run fetch_clips.py): {", ".join(missing)}')
    if not clips:
        print('[ERROR] no clips to evaluate')
        return 1

    ids = {m for m in args.models.split(',') if m}
    previous_runs = read_csv(RESULTS / 'runs.csv')
    timer, latency_frames = Timer(device), None
    if args.latency_only:
        return latency_only(models, manifest, clips, variants, ids, previous_runs, device, timer, args.latency_runs,
                            args.split)
    for variant in variants:   # one stage-1 model on the GPU at a time
        weights_id, conf = STAGE1_VARIANTS[variant]
        entry = stage1_entry(models, weights_id)
        runs, lat_rows, scored = [], [], []
        stage1 = None
        try:
            if entry is None:
                raise ValueError(f'unknown stage-1 weights id {weights_id}')
            stage1 = Stage1(entry, device, conf)
            print(f'Stage 1 {variant} ({weights_id}, conf {conf}) on {len(clips)} clips...', flush=True)
            cache = run_stage1(clips, stage1, timer, args.step)
            if latency_frames is None and args.latency_runs > 0:
                picks = latency_sample(clips, cache)
                latency_frames = load_latency_frames(clips, picks)
                persons = {(c, i['t']): len(i['boxes']) for c, items in cache.items() for i in items}
                write_csv(RESULTS / 'latency_sample.csv', ['clip_id', 't', 'n_persons'],
                          [{'clip_id': c, 't': t, 'n_persons': persons[(c, t)]} for c, t in picks])
                print(f'  latency sample: {len(latency_frames)} frames (from stage 1 {variant})', flush=True)
        except Exception as e:   # the whole variant fails; record it for every candidate
            reason = f'stage 1 {variant}: {type(e).__name__}: {e}'.replace('\n', ' ')[:300]
            print(f'[FAIL] {reason}', flush=True)
            runs = stage1_failure_rows(models['candidates'], ids, weights_id, variant, reason,
                                       previous_runs if args.resume else [])
            upsert(RESULTS / 'runs.csv', RUN_FIELDS, runs, lambda r: (r['model'], r['stage1_variant']))
            del stage1
            free_gpu()
            continue

        for cand in models['candidates']:
            if ids and cand['id'] not in ids:
                continue
            name = cand['id']
            base = {'model': name, 'kind': cand['kind'], 'stage1': weights_id, 'stage1_variant': variant}
            if cand.get('status') == 'missing':
                runs.append({**base, 'status': 'missing', 'error': cand.get('notes', 'weights not found')})
                print(f'- {name}: missing')
                continue
            if args.resume and already_scored(previous_runs, name, variant):
                print(f'- {name} | s1={variant}: already scored (--resume), latency only', flush=True)
                scored.append(cand)
                continue
            print(f'- {name} ({cand["kind"]}) | s1={variant}...', flush=True)
            adapter = None
            try:
                adapter = load_stage2(cand, device)
                rows, replay = score_candidate(adapter, clips, cache, timer, args.step)
                write_csv(RESULTS / f'frames_{frames_key(name, variant)}.csv', FRAME_FIELDS, rows)
                _, best_th, _ = mt.threshold_sweep([r['label'] for r in rows], [r['frame_score'] for r in rows])
                write_events(name, variant, replay, clips, best_th)
                dump_failures(frames_key(name, variant), rows, clips, cache, args.step)
                runs.append({**base, 'status': 'ok', 'error': ''})
                scored.append(cand)
            except Exception as e:   # one broken candidate must not stop the run
                reason = f'{type(e).__name__}: {e}'.replace('\n', ' ')[:300]
                runs.append({**base, 'status': 'failed', 'error': reason})
                print(f'  FAILED {reason}', flush=True)
            finally:
                del adapter
                free_gpu()
        upsert(RESULTS / 'runs.csv', RUN_FIELDS, runs, lambda r: (r['model'], r['stage1_variant']))
        if latency_frames and scored:
            lat_rows = latency_rounds(stage1, variant, scored, device, latency_frames, timer, args.latency_runs)
        if lat_rows or (latency_frames and scored):
            # Every timed candidate loses its older rows, even if all its runs failed now, so the latency
            # numbers of one variant never mix sessions.
            done = {(c['id'], variant) for c in scored} | {(r['model'], r['stage1']) for r in lat_rows}
            kept = [r for r in read_csv(latency_file(args.split)) if (r['model'], r['stage1']) not in done]
            write_csv(latency_file(args.split), LATENCY_FIELDS, kept + lat_rows)
        del stage1, cache
        free_gpu()

    summary, view = report(models, manifest, args.split)
    print(f"Wrote {view.out / 'summary.csv'} ({len(summary)} pipelines)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
