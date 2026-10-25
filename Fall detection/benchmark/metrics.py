"""Pure metric functions: frame metrics, threshold sweep, event replay, bootstrap and ranking. No model imports."""
import functools
import math
import random

from benchmark.frames import source_group
from benchmark.legacy import FallTracker

THRESHOLDS = [round(0.10 + 0.05 * i, 2) for i in range(17)]   # 0.10 .. 0.90
EARLY_TOLERANCE = 0.5
WARMUP_FRAMES = 5
MAX_P95_MS = 200.0
BOOTSTRAP_N = 2000
SMALL_SUBSET = 3   # subsets with fewer fall clips are flagged "n < 3"


class GapTolerantTracker(FallTracker):
    """FallTracker that keeps a track unmatched for up to `max_missing` consecutive inferences.

    A kept track holds its streak, fall_since and danger state, so a re-matched track continues
    the same fall episode. While unmatched it is not positive and never raises newAlert.
    IoU matching, confirmations, the 5 s rule and the inference-gap reset are inherited.
    """

    def __init__(self, max_missing=1):
        super().__init__()
        self.max_missing = max_missing

    def update(self, detections, threshold, needed, now):
        gap = self.last_time is not None and (now < self.last_time or now - self.last_time > self.MAX_INFERENCE_GAP)
        previous = [] if gap else self.tracks
        tracks = super().update(detections, threshold, needed, now)
        seen = {t['id'] for t in tracks}
        held = [{**t, 'missing': t.get('missing', 0) + 1, 'pending': False, 'newAlert': False}
                for t in previous if t['id'] not in seen and t.get('missing', 0) < self.max_missing]
        self.tracks = tracks + held
        return tracks


TRACKERS = {'prod': FallTracker, 'gap1': lambda: GapTolerantTracker(1), 'gap2': lambda: GapTolerantTracker(2)}


def _ratio(a, b):
    return a / b if b else 0.0


def frame_metrics(labels, scores, threshold):
    """Counts and P/R/F1/accuracy over 'fall'/'normal' frames; 'ignore' frames are skipped."""
    tp = fp = fn = tn = 0
    for label, score in zip(labels, scores, strict=True):
        if label == 'ignore':
            continue
        positive = score >= threshold
        if label == 'fall':
            tp, fn = tp + positive, fn + (not positive)
        else:
            fp, tn = fp + positive, tn + (not positive)
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': precision, 'recall': recall,
            'f1': _ratio(2 * precision * recall, precision + recall),
            'accuracy': _ratio(tp + tn, tp + fp + fn + tn)}


def threshold_sweep(labels, scores, thresholds=THRESHOLDS):
    """Return (best_f1, best_threshold, per-threshold metrics). Ties keep the lowest threshold."""
    rows = [{'threshold': th, **frame_metrics(labels, scores, th)} for th in thresholds]
    best = max(rows, key=lambda r: (r['f1'], -r['threshold']))
    return best['f1'], best['threshold'], rows


def replay_alerts(frames, threshold, needed=3, tracker=None):
    """Feed [(t, detections)] through FallTracker with now=t; return the times of every newAlert.

    Each detection is {'box': [x1, y1, x2, y2] normalized, 'fall_score': float | None}.
    """
    tracker = tracker or FallTracker()
    alerts = []
    for t, detections in frames:
        tracks = tracker.update(detections, threshold, needed, t)
        if any(track['newAlert'] for track in tracks):
            alerts.append(t)
    return alerts


def evaluate_clip(alerts, row, short=False, uncertain=False):
    """Event outcome for one clip given its alert times.

    alerted: a fall clip has an alert at or after fall_start_s - 0.5.
    false_alarm: any alert on a non-fall clip, or an alert before fall_start_s - 0.5 on a fall clip.
    latency_s: first valid alert minus fall_start_s.
    Short fall clips (too short for the 5 s rule) are excluded from event metrics.
    Uncertain clips (fall moment ambiguous by > 1 s) are excluded from the mean latency only.
    """
    is_fall = bool(int(row.get('is_fall') or 0))
    out = {'is_fall': is_fall, 'counted': not (is_fall and short), 'alerted': False, 'false_alarm': False,
           'latency_s': None, 'first_alert_t': alerts[0] if alerts else None, 'uncertain': uncertain}
    if not is_fall:
        out['false_alarm'] = bool(alerts)
        return out
    start = float(row['fall_start_s'])
    valid = [t for t in alerts if t >= start - EARLY_TOLERANCE]
    out['false_alarm'] = any(t < start - EARLY_TOLERANCE for t in alerts)
    if valid:
        out['alerted'] = True
        out['latency_s'] = round(valid[0] - start, 3)
    return out


def summarize_events(results):
    """Totals over evaluate_clip outputs; uncounted (short) clips are skipped."""
    counted = [r for r in results if r['counted']]
    latencies = [r['latency_s'] for r in counted if r['latency_s'] is not None and not r.get('uncertain')]
    return {'fall_clips': sum(r['is_fall'] for r in counted),
            'nonfall_clips': sum(not r['is_fall'] for r in counted),
            'fall_clips_alerted': sum(r['alerted'] for r in counted),
            'false_alarm_clips': sum(r['false_alarm'] for r in counted),
            'mean_latency_s': round(sum(latencies) / len(latencies), 3) if latencies else None}


def percentile(values, q):
    """Linear-interpolated percentile (same as numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def latency_stats(per_frame_ms, warmup=WARMUP_FRAMES):
    timed = per_frame_ms[warmup:]
    if not timed:
        return {'mean_ms': None, 'p95_ms': None}
    return {'mean_ms': round(sum(timed) / len(timed), 2), 'p95_ms': round(percentile(timed, 95), 2)}


def stage1_recall(labels, person_counts):
    """Share of 'fall' frames where stage 1 found at least one person."""
    falls = [n for label, n in zip(labels, person_counts, strict=True) if label == 'fall']
    return _ratio(sum(n > 0 for n in falls), len(falls))


def event_score(row):
    return int(row['fall_clips_alerted']) - int(row['false_alarm_clips'])


def rank(rows, max_p95_ms=MAX_P95_MS):
    """Recommendation rule: p95 <= limit, then most (alerted - false alarm clips) at 0.4,
    then frame F1, then lowest p95. Rows need fall_clips_alerted, false_alarm_clips, frame_f1, p95_ms."""
    eligible = [r for r in rows if r.get('status') == 'ok' and r.get('p95_ms') not in (None, '')
                and float(r['p95_ms']) <= max_p95_ms]
    return sorted(eligible, key=lambda r: (-event_score(r), -float(r['frame_f1']), float(r['p95_ms'])))


def recommend(rows, events, leaks, max_p95_ms=MAX_P95_MS):
    """Apply rank(); if the winner's training data overlaps test sources, re-score every eligible
    model on the clips outside that overlap. Keep the winner only if the ranking does not change.

    events: {model: [{'source', 'counted', 'alerted', 'false_alarm'} at threshold 0.4]}
    leaks: {model: set of overlapping source names}
    Returns (winner row or None, ranked rows, note).
    """
    ranked = rank(rows, max_p95_ms)
    if not ranked:
        return None, ranked, f'no candidate with status ok and p95 <= {max_p95_ms:g} ms'
    top = ranked[0]
    overlap = leaks.get(top['model']) or set()
    if not overlap:
        return top, ranked, ''

    def rescored(row):
        kept = [e for e in events.get(row['model'], []) if e['source'] not in overlap and int(e['counted'])]
        return {**row, 'fall_clips_alerted': sum(int(e['alerted']) for e in kept),
                'false_alarm_clips': sum(int(e['false_alarm']) for e in kept)}

    reranked = rank([rescored(r) for r in ranked], max_p95_ms)
    if reranked[0]['model'] == top['model']:
        return top, ranked, f"{top['model']} overlaps {sorted(overlap)} but stays first without those clips"
    clean = next((r for r in reranked if not leaks.get(r['model'])), None)
    winner = next((r for r in ranked if clean and r['model'] == clean['model']), None)
    return winner, ranked, (f"{top['model']} overlaps {sorted(overlap)} and loses first place without those "
                            f"clips; excluded from the recommendation")


# ---------- v2: uncertainty, stage-2-only curves, subsets, rule v2 ----------

@functools.lru_cache(maxsize=8)
def _resamples(clip_ids, strata, n, seed):
    """n stratified resamples of clip_ids (tuples, so the result can be cached and shared by paired runs)."""
    rng = random.Random(seed)
    groups = {}
    for clip, stratum in zip(clip_ids, strata, strict=True):
        groups.setdefault(stratum, []).append(clip)
    ordered = [groups[k] for k in sorted(groups, key=str)]
    return tuple(tuple(g[rng.randrange(len(g))] for g in ordered for _ in g) for _ in range(n))


def bootstrap(clip_ids, stat_fn, n=BOOTSTRAP_N, seed=0, strata=None):
    """Percentile bootstrap over clips, resampled with replacement within each stratum.

    stat_fn(list of clip ids) -> float, or None when the statistic is undefined for that resample
    (such resamples are skipped and counted). strata: {clip_id: stratum}, e.g. is_fall.
    Returns {'point', 'lo', 'hi', 'skipped'} with lo / hi the 2.5 / 97.5 percentiles.
    """
    clip_ids = tuple(clip_ids)
    keys = tuple(strata[c] if strata else 0 for c in clip_ids)
    values = [stat_fn(list(ids)) for ids in _resamples(clip_ids, keys, n, seed)]
    kept = [v for v in values if v is not None]
    return {'point': stat_fn(list(clip_ids)), 'lo': percentile(kept, 2.5), 'hi': percentile(kept, 97.5),
            'skipped': n - len(kept)}


def paired_bootstrap(a, b, clip_ids, n=BOOTSTRAP_N, seed=0, strata=None):
    """CI of stat a minus stat b, both computed on the same resamples."""
    def diff(ids):
        x, y = a(ids), b(ids)
        return None if x is None or y is None else x - y
    return bootstrap(clip_ids, diff, n, seed, strata)


def is_tie(ci):
    """A paired difference is a tie when its 95% CI includes 0."""
    return ci['lo'] is not None and ci['lo'] <= 0 <= ci['hi']


def clip_counts(clip_ids, labels, scores, threshold):
    """{clip_id: (tp, fp, fn)} at threshold; 'ignore' frames skipped."""
    out = {}
    for clip, label, score in zip(clip_ids, labels, scores, strict=True):
        tp, fp, fn = out.get(clip, (0, 0, 0))
        if label == 'fall':
            tp, fn = tp + (score >= threshold), fn + (score < threshold)
        elif label == 'normal':
            fp += score >= threshold
        out[clip] = (tp, fp, fn)
    return out


def stat_fns(events, counts):
    """Bootstrap statistics for one pipeline.

    events: {clip_id: {'is_fall', 'counted', 'alerted', 'false_alarm'}}; counts: clip_counts() output.
    Recall and F1 are undefined (None) on a resample without fall clips / fall frames.
    """
    def counted(ids):
        return [events[c] for c in ids if c in events and events[c]['counted']]

    def event_score_fn(ids):
        rows = counted(ids)
        return sum(r['alerted'] for r in rows) - sum(r['false_alarm'] for r in rows)

    def fall_recall(ids):
        falls = [r for r in counted(ids) if r['is_fall']]
        return sum(r['alerted'] for r in falls) / len(falls) if falls else None

    def false_alarms(ids):
        return sum(r['false_alarm'] for r in counted(ids))

    def frame_f1(ids):
        tp, fp, fn = (sum(counts.get(c, (0, 0, 0))[i] for c in ids) for i in range(3))
        if not tp + fn:
            return None
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        return _ratio(2 * precision * recall, precision + recall)

    return {'event_score': event_score_fn, 'fall_recall': fall_recall, 'false_alarm_clips': false_alarms,
            'frame_f1': frame_f1}


def _curve(labels, scores):
    """(tp, fp) after each distinct score, highest score first. labels are truthy for fall."""
    pairs = sorted(zip(scores, labels), key=lambda p: -p[0])
    points, tp, fp = [], 0, 0
    for i, (score, label) in enumerate(pairs):
        tp, fp = tp + bool(label), fp + (not label)
        if i + 1 == len(pairs) or pairs[i + 1][0] != score:
            points.append((tp, fp))
    return points


def average_precision(labels, scores):
    """Area under the precision-recall curve by the trapezoid rule, starting at (recall 0, precision 1).
    Returns None without positives."""
    positives = sum(map(bool, labels))
    if not positives:
        return None
    area, r0, p0 = 0.0, 0.0, 1.0
    for tp, fp in _curve(labels, scores):
        r, p = tp / positives, tp / (tp + fp)
        area += (r - r0) * (p + p0) / 2
        r0, p0 = r, p
    return area


def roc_auc(labels, scores):
    """Area under the ROC curve by the trapezoid rule. Returns None without both classes."""
    positives = sum(map(bool, labels))
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    area, x0, y0 = 0.0, 0.0, 0.0
    for tp, fp in _curve(labels, scores):
        x, y = fp / negatives, tp / positives
        area += (x - x0) * (y + y0) / 2
        x0, y0 = x, y
    return area


def pr_points(labels, scores):
    """[(recall, precision)] for plotting, same points as average_precision."""
    positives = sum(map(bool, labels))
    return [(tp / positives, tp / (tp + fp)) for tp, fp in _curve(labels, scores)] if positives else []


def fa_per_hour(clips):
    """clips: [(alert count, duration in s)]. Alerts per hour of footage, None without footage."""
    seconds = sum(d for _, d in clips)
    return sum(n for n, _ in clips) * 3600 / seconds if seconds else None


def subset_breakdown(manifest, frame_rows, events, threshold):
    """Frame recall / precision and fall clips alerted per source group, view and lighting.

    frame_rows: [{'clip_id', 'label', 'frame_score'}]; events: {clip_id: evaluate_clip-like dict}.
    """
    subsets = {}
    for row in manifest:
        for key in (f'group={source_group(row)}', f"view={row.get('view') or '?'}",
                    f"lighting={row.get('lighting') or '?'}"):
            subsets.setdefault(key, set()).add(row['clip_id'])
    out = []
    for key in sorted(subsets):
        ids = subsets[key]
        rows = [r for r in frame_rows if r['clip_id'] in ids]
        m = frame_metrics([r['label'] for r in rows], [float(r['frame_score']) for r in rows], threshold)
        falls = [e for c, e in events.items() if c in ids and e['counted'] and e['is_fall']]
        out.append({'subset': key, 'clips': len(ids), 'fall_clips': len(falls),
                    'fall_clips_alerted': sum(e['alerted'] for e in falls),
                    'frame_precision': m['precision'], 'frame_recall': m['recall'],
                    'small': len(falls) < SMALL_SUBSET})
    return out


def has_license(text):
    text = (text or '').strip().lower()
    return bool(text) and not text.startswith(('not stated', 'no license', 'unknown'))


def _num(value, default=math.inf):
    return float(value) if value not in (None, '') else default


def rank_v2(rows, max_p95_ms=MAX_P95_MS):
    """Eligible: status ok and median p95 <= limit. Order: event score, then frame F1, then median p95."""
    eligible = [r for r in rows if r.get('status') == 'ok' and _num(r.get('p95_ms_median')) <= max_p95_ms]
    return sorted(eligible, key=lambda r: (-event_score(r), -float(r['frame_f1']), _num(r['p95_ms_median'])))


def recommend_v2(rows, tie, max_p95_ms=MAX_P95_MS):
    """Rule v2. tie(a, b) -> True when the paired CI of a's event-score lead over b includes 0.

    On a tie between the top two, the one with lower fa_per_hour wins, then the one with a stated
    license, then lower median p95. Returns (winner or None, ranked rows, tied).
    """
    ranked = rank_v2(rows, max_p95_ms)
    if len(ranked) < 2:
        return (ranked[0] if ranked else None), ranked, False
    a, b = ranked[:2]
    tied = bool(tie(a, b))
    if tied:
        def key(r):
            return _num(r.get('fa_per_hour')), not has_license(r.get('license')), _num(r.get('p95_ms_median'))
        if key(b) < key(a):
            ranked = [b, a] + ranked[2:]
    return ranked[0], ranked, tied


def rescore(rows, events, keep):
    """Recount fall_clips_alerted / false_alarm_clips per row ('pipeline' key) on the events where keep(e)."""
    out = []
    for row in rows:
        kept = [e for e in events.get(row['pipeline'], []) if int(e['counted']) and keep(e)]
        out.append({**row, 'fall_clips_alerted': sum(int(e['alerted']) for e in kept),
                    'false_alarm_clips': sum(int(e['false_alarm']) for e in kept)})
    return out


def winner_on(rows, events, keep, tie, max_p95_ms=MAX_P95_MS):
    """Rule v2 (tie-break included) on the events where keep(e). Returns (winner or None, ranked)."""
    winner, ranked, _ = recommend_v2(rescore(rows, events, keep), tie, max_p95_ms)
    return winner, ranked


def leak_check(winner, ranked, events, overlap_of, tie, max_p95_ms=MAX_P95_MS):
    """v1 leakage rule on rule-v2 rows: re-apply rule v2 without the clips whose source is in the
    winner's training data; keep the winner only if it stays first, else take the best row without
    overlap from that re-ranking. overlap_of(row) -> set of manifest sources. Returns (winner or None, note)."""
    overlap = overlap_of(winner) if winner else set()
    if not overlap:
        return winner, ''
    top, reranked = winner_on(ranked, events, lambda e: e['source'] not in overlap, tie, max_p95_ms)
    if top and top['pipeline'] == winner['pipeline']:
        return winner, f"{winner['pipeline']} overlaps {sorted(overlap)} but stays first without those clips"
    clean = next((r for r in reranked if not overlap_of(r)), None)
    clean = next((r for r in ranked if clean and r['pipeline'] == clean['pipeline']), None)
    return clean, (f"{winner['pipeline']} overlaps {sorted(overlap)} and loses first place without those clips; "
                   f"excluded from the recommendation")
