"""Offline checks for the fall-model benchmark: sampling, labels, metrics and event replay."""
import pytest

from benchmark.frames import is_short, label_at, sample_times, source_group
from benchmark.adapters import pose_rule_score
from benchmark.metrics import (GapTolerantTracker, FallTracker, average_precision, bootstrap, clip_counts,
                               evaluate_clip, fa_per_hour, frame_metrics, paired_bootstrap, rank, recommend,
                               recommend_v2, replay_alerts, roc_auc, stat_fns, subset_breakdown, summarize_events,
                               threshold_sweep)

FALL_ROW = {'clip_id': 'f1', 'is_fall': '1', 'fall_start_s': '2.0', 'fall_end_s': '8.0'}
BOX = [.2, .2, .7, .9]


def person(score):
    return [{'box': BOX, 'fall_score': score}]


def test_sample_times_step():
    assert sample_times(1.0, 0.3) == [0, 0.3, 0.6, 0.9]


def test_label_at_ignore_window():
    assert label_at(1.4, FALL_ROW) == 'normal'
    assert label_at(1.6, FALL_ROW) == 'ignore'
    assert label_at(2.6, FALL_ROW) == 'fall'
    assert label_at(8.6, FALL_ROW) == 'normal'


def test_label_non_fall_clip():
    row = {'clip_id': 'n1', 'is_fall': '0', 'fall_start_s': '', 'fall_end_s': ''}
    assert {label_at(t, row) for t in sample_times(10.0)} == {'normal'}


def test_frame_metrics_known_counts():
    labels = ['fall'] * 4 + ['normal'] * 6 + ['ignore'] * 3
    scores = [.9, .8, .7, .1] + [.9, .5, .1, .1, .1, .1] + [.99, .99, .0]
    m = frame_metrics(labels, scores, .4)
    assert (m['tp'], m['fp'], m['fn'], m['tn']) == (3, 2, 1, 4)
    assert m['precision'] == pytest.approx(3 / 5)
    assert m['recall'] == pytest.approx(3 / 4)
    assert m['f1'] == pytest.approx(2 * .6 * .75 / (.6 + .75))
    assert m['accuracy'] == pytest.approx(7 / 10)


def test_threshold_sweep_picks_best():
    labels = ['fall', 'fall', 'fall', 'normal', 'normal', 'normal']
    scores = [.72, .66, .61, .58, .30, .20]
    best_f1, best_th, rows = threshold_sweep(labels, scores)
    assert best_f1 == pytest.approx(1.0)
    assert best_th == 0.6      # lowest threshold that separates .61 from .58
    assert len(rows) == 17 and rows[0]['threshold'] == 0.1 and rows[-1]['threshold'] == 0.9


def test_event_replay_alert_after_5s():
    times = [round(2.0 + 0.3 * i, 6) for i in range(30)]
    alerts = replay_alerts([(t, person(.9)) for t in times], .4, 3)
    # Streak >= 3 is reached at 2.6, but elapsed >= 5 s first holds at 2.0 + 17 * 0.3.
    assert alerts == [pytest.approx(7.1)]
    result = evaluate_clip(alerts, FALL_ROW)
    assert result['alerted'] and not result['false_alarm']
    assert result['latency_s'] == pytest.approx(5.1)


def test_event_replay_early_alert_is_false_alarm():
    row = {**FALL_ROW, 'fall_start_s': '9.0', 'fall_end_s': '14.0'}
    times = [round(0.3 * i, 6) for i in range(60)]
    alerts = replay_alerts([(t, person(.9 if t < 7.0 else .0)) for t in times], .4, 3)
    assert alerts and alerts[0] < 9.0 - 0.5
    result = evaluate_clip(alerts, row)
    assert result['false_alarm'] and not result['alerted']


def test_short_clip_not_counted_and_rank_rule():
    short = evaluate_clip([], FALL_ROW, short=True)
    normal = evaluate_clip([3.0], {'is_fall': '0'})
    totals = summarize_events([short, normal])
    assert totals['fall_clips'] == 0 and totals['false_alarm_clips'] == 1
    rows = [{'model': 'slow', 'status': 'ok', 'fall_clips_alerted': 9, 'false_alarm_clips': 0, 'frame_f1': .9, 'p95_ms': 250},
            {'model': 'a', 'status': 'ok', 'fall_clips_alerted': 6, 'false_alarm_clips': 1, 'frame_f1': .7, 'p95_ms': 90},
            {'model': 'b', 'status': 'ok', 'fall_clips_alerted': 5, 'false_alarm_clips': 0, 'frame_f1': .8, 'p95_ms': 80},
            {'model': 'broken', 'status': 'failed', 'fall_clips_alerted': '', 'false_alarm_clips': '', 'frame_f1': '', 'p95_ms': ''}]
    assert [r['model'] for r in rank(rows)] == ['b', 'a']


def _events(*outcomes):
    return [{'source': s, 'counted': 1, 'alerted': a, 'false_alarm': f} for s, a, f in outcomes]


def test_recommend_drops_leaky_winner_only_when_ranking_changes():
    rows = [{'model': 'leaky', 'status': 'ok', 'fall_clips_alerted': 3, 'false_alarm_clips': 0, 'frame_f1': .9, 'p95_ms': 50},
            {'model': 'clean', 'status': 'ok', 'fall_clips_alerted': 2, 'false_alarm_clips': 0, 'frame_f1': .8, 'p95_ms': 50}]
    events = {'leaky': _events(('URFD', 1, 0), ('URFD', 1, 0), ('cctv', 1, 0), ('cctv', 0, 0)),
              'clean': _events(('URFD', 0, 0), ('URFD', 0, 0), ('cctv', 1, 0), ('cctv', 1, 0))}
    winner, _, note = recommend(rows, events, {'leaky': {'URFD'}})
    assert winner['model'] == 'clean' and 'excluded' in note
    events['leaky'][3]['alerted'] = 1          # still first on the cctv clips alone
    winner, _, note = recommend(rows, events, {'leaky': {'URFD'}})
    assert winner['model'] == 'leaky' and 'stays first' in note


def _skeleton(horizontal):
    """17 COCO keypoints of a 100 px tall upright person, or the same body rotated 90 degrees."""
    pts = [(50, 5)] * 5 + [(35, 25), (65, 25)] + [(30, 45), (70, 45)] * 3 + [(40, 60), (60, 60)] \
        + [(40, 80), (60, 80), (40, 100), (60, 100)]
    pts = pts[:17]
    return [(y, x) for x, y in pts] if horizontal else pts


def test_pose_rule_upright_low_lying_high():
    conf = [.9] * 17
    assert pose_rule_score(_skeleton(False), conf) < .1
    assert pose_rule_score(_skeleton(True), conf) > .9
    assert pose_rule_score(_skeleton(True), [.1] * 17) == 0.0


def test_short_note_token():
    assert is_short({'notes': 'short; overhead camera; crop=right'})
    assert not is_short({'notes': 'shortly after; wall'})


def test_leak_map_feeds_recommend_with_manifest_spelling():
    from benchmark.run_benchmark import leak_map
    models = {'candidates': [{'id': 'leaky', 'trained_on': ['urfd', 'COCO']}, {'id': 'clean', 'trained_on': []}]}
    leaks = leak_map(models, [{'source': 'URFD'}, {'source': 'youtube'}])
    assert leaks == {'leaky': {'URFD'}, 'clean': set()}
    rows = [{'model': 'leaky', 'status': 'ok', 'fall_clips_alerted': 3, 'false_alarm_clips': 0, 'frame_f1': .9, 'p95_ms': 50},
            {'model': 'clean', 'status': 'ok', 'fall_clips_alerted': 2, 'false_alarm_clips': 0, 'frame_f1': .8, 'p95_ms': 50}]
    events = {'leaky': _events(('URFD', 1, 0), ('URFD', 1, 0), ('youtube', 1, 0), ('youtube', 0, 0)),
              'clean': _events(('URFD', 0, 0), ('URFD', 0, 0), ('youtube', 1, 0), ('youtube', 1, 0))}
    winner, _, _ = recommend(rows, events, leaks)
    assert winner['model'] == 'clean'


def test_md_cell_escapes_table_breakers():
    from benchmark.run_benchmark import md_cell
    assert md_cell('depth|RGB\nside') == r'depth\|RGB side'
    assert '<!--' not in md_cell('x <!-- END GENERATED: results -->')


def _steps(start, count, step=0.3):
    return [round(start + step * i, 6) for i in range(count)]


def test_gap_tracker_keeps_fall_since_over_one_miss():
    times = _steps(2.0, 30)
    full = [(t, person(.9)) for t in times]
    holed = [(t, [] if i == 8 else person(.9)) for i, t in enumerate(times)]
    uninterrupted = replay_alerts(full, .4, 3, FallTracker())
    assert replay_alerts(holed, .4, 3, GapTolerantTracker(1)) == uninterrupted == [pytest.approx(7.1)]
    prod = replay_alerts(holed, .4, 3, FallTracker())
    assert not prod or prod[0] > uninterrupted[0]


def test_gap_tracker_does_not_alert_on_missing_frames():
    # 4.8 s of positives (one short of the 5 s rule), then the person is never detected again.
    frames = [(t, person(.9)) for t in _steps(0.0, 17)] + [(t, []) for t in _steps(5.1, 10)]
    assert replay_alerts(frames, .4, 3, GapTolerantTracker(2)) == []


def test_gap_tracker_respects_inference_gap_reset():
    frames = [(t, person(.9)) for t in _steps(0.0, 11)] + [(t, person(.9)) for t in _steps(5.5, 20)]
    # 3.0 -> 5.5 is a 2.5 s inference gap: fall_since restarts at 5.5, so no alert before 10.5.
    assert replay_alerts(frames, .4, 3, GapTolerantTracker(2)) == [pytest.approx(10.6)]


def test_gap_tracker_does_not_carry_a_track_across_a_camera_cut():
    other = [{'box': [.75, .1, .95, .4], 'fall_score': .9}]   # no overlap with BOX
    frames = [(t, person(.9)) for t in _steps(0.0, 11)] + [(t, other) for t in _steps(3.3, 20)]
    assert replay_alerts(frames, .4, 3, GapTolerantTracker(2)) == [pytest.approx(8.4)]


def _bootstrap_fixture():
    events = {'f1': {'is_fall': True, 'counted': True, 'alerted': True, 'false_alarm': False},
              'f2': {'is_fall': True, 'counted': True, 'alerted': False, 'false_alarm': False},
              'f3': {'is_fall': True, 'counted': True, 'alerted': True, 'false_alarm': False},
              'n1': {'is_fall': False, 'counted': True, 'alerted': False, 'false_alarm': True},
              'n2': {'is_fall': False, 'counted': True, 'alerted': False, 'false_alarm': False}}
    counts = clip_counts(['f1', 'f1', 'f2', 'f3', 'n1', 'n2'], ['fall', 'fall', 'fall', 'fall', 'normal', 'normal'],
                         [.9, .2, .1, .8, .7, .1], .4)
    strata = {c: e['is_fall'] for c, e in events.items()}
    return events, counts, strata


def test_bootstrap_ci_contains_point_and_is_deterministic():
    events, counts, strata = _bootstrap_fixture()
    fns = stat_fns(events, counts)
    for name, fn in fns.items():
        first = bootstrap(list(events), fn, n=500, seed=0, strata=strata)
        assert first == bootstrap(list(events), fn, n=500, seed=0, strata=strata)
        assert first['lo'] <= first['point'] <= first['hi'], name
    assert fns['event_score'](list(events)) == 1
    assert fns['fall_recall'](list(events)) == pytest.approx(2 / 3)
    assert fns['frame_f1'](list(events)) == pytest.approx(2 * (2 / 3) * .5 / (2 / 3 + .5))
    # Stratified: every resample keeps 3 fall clips, so recall is never undefined.
    assert bootstrap(list(events), fns['fall_recall'], n=500, strata=strata)['skipped'] == 0
    assert bootstrap(['n1', 'n2'], fns['fall_recall'], n=10)['skipped'] == 10


def test_paired_bootstrap_identical_models_is_zero():
    events, counts, strata = _bootstrap_fixture()
    a, b = stat_fns(events, counts), stat_fns(dict(events), dict(counts))
    ci = paired_bootstrap(a['event_score'], b['event_score'], list(events), n=300, strata=strata)
    assert (ci['point'], ci['lo'], ci['hi']) == (0, 0, 0)


def test_average_precision_and_auc_known_values():
    labels = [1, 1, 0, 0]
    assert average_precision(labels, [.9, .8, .2, .1]) == pytest.approx(1.0)
    assert roc_auc(labels, [.9, .8, .2, .1]) == pytest.approx(1.0)
    # Inverted: PR points (0, 0), (0.5, 1/3), (1, 0.5) after the (0, 1) start.
    assert average_precision(labels, [.1, .2, .8, .9]) == pytest.approx(7 / 24)
    assert roc_auc(labels, [.1, .2, .8, .9]) == pytest.approx(0.0)
    assert average_precision([1, 0, 1, 0], [.9, .8, .7, .6]) == pytest.approx(19 / 24)
    assert roc_auc([1, 0, 1, 0], [.9, .8, .7, .6]) == pytest.approx(0.75)
    assert roc_auc([1, 0], [.5, .5]) == pytest.approx(0.5)      # a tie is one step, not two
    assert average_precision([0, 0], [.1, .2]) is None and roc_auc([1, 1], [.1, .2]) is None


def test_fa_per_hour():
    assert fa_per_hour([(2, 600.0), (0, 1200.0)]) == pytest.approx(4.0)
    assert fa_per_hour([]) is None


def test_subset_breakdown_flags_small_groups():
    manifest = [{'clip_id': 'a', 'source': 'youtube', 'view': 'wall', 'lighting': 'day'},
                {'clip_id': 'b', 'source': 'GMDCSA-24', 'view': 'wall', 'lighting': 'night'}]
    frames = [{'clip_id': 'a', 'label': 'fall', 'frame_score': .9}, {'clip_id': 'b', 'label': 'fall', 'frame_score': .1}]
    events = {'a': {'is_fall': True, 'counted': True, 'alerted': True},
              'b': {'is_fall': True, 'counted': True, 'alerted': False}}
    rows = {r['subset']: r for r in subset_breakdown(manifest, frames, events, .4)}
    assert source_group(manifest[0]) == 'real' and source_group(manifest[1]) == 'lab'
    assert rows['group=real']['frame_recall'] == 1.0 and rows['group=lab']['frame_recall'] == 0.0
    assert rows['view=wall']['fall_clips'] == 2 and rows['view=wall']['fall_clips_alerted'] == 1
    assert all(r['small'] for r in rows.values())


def _pipe(name, alerted, fa_clips=0, fa_hour=1.0, license='MIT', p95=50.0, f1=.5):
    return {'pipeline': name, 'status': 'ok', 'fall_clips_alerted': alerted, 'false_alarm_clips': fa_clips,
            'frame_f1': f1, 'fa_per_hour': fa_hour, 'license': license, 'p95_ms_median': p95}


def test_recommend_v2_tie_breaks_on_fa_then_license_then_latency():
    def pick(rows, tied=True):
        winner, _, tie = recommend_v2(rows, lambda a, b: tied)
        return winner['pipeline'], tie

    a = _pipe('a', 6, fa_hour=2.0, license='not stated', p95=40.0)
    assert pick([a, _pipe('b', 5, fa_hour=1.0)]) == ('b', True)                        # lower FA/h
    assert pick([a, _pipe('b', 5, fa_hour=2.0)]) == ('b', True)                        # stated license
    assert pick([a, _pipe('b', 5, fa_hour=2.0, license='no LICENSE file', p95=30.0)]) == ('b', True)   # latency
    assert pick([a, _pipe('b', 5, fa_hour=2.0, license='', p95=60.0)]) == ('a', True)
    assert pick([a, _pipe('b', 5, fa_hour=0.0)], tied=False) == ('a', False)          # no tie: keep the lead
    slow = _pipe('slow', 9, p95=250.0)
    assert pick([slow, a], tied=False) == ('a', False)                                # over 200 ms: not eligible


def test_rerank_and_leak_check_reuse_the_tie_break():
    from benchmark.metrics import leak_check, winner_on
    a = _pipe('a', 6, license='not stated')
    b = _pipe('b', 5, license='MIT')
    events = {'a': _events(*[('youtube', 1, 0)] * 6), 'b': _events(*[('youtube', 1, 0)] * 5)}
    tie = lambda x, y: True   # noqa: E731
    winner, ranked, _ = recommend_v2([a, b], tie)
    assert winner['pipeline'] == 'b'                                  # license tie-break
    real, _ = winner_on(ranked, events, lambda e: e['source'] == 'youtube', tie)
    assert real['pipeline'] == 'b'                                    # same rule: unchanged
    kept, note = leak_check(winner, ranked, events, lambda r: {'URFD'} if r['pipeline'] == 'b' else set(), tie)
    assert kept['pipeline'] == 'b' and 'stays first' in note           # no URFD clips: nothing to lose


def test_paired_rows_cover_the_tie_broken_winner():
    from benchmark.metrics import stat_fns
    from benchmark.run_benchmark import pair_row, paired_rows
    clips = ['f1', 'f2', 'n1']
    strata = {'f1': 'fall', 'f2': 'fall', 'n1': 'normal'}

    def stats(alerted):
        events = {c: {'is_fall': c != 'n1', 'counted': True, 'alerted': c in alerted, 'false_alarm': False}
                  for c in clips}
        return clips, stat_fns(events, {'f1': (1, 0, 0), 'f2': (1, 0, 0)}), strata

    def row(model, variant, alerted, license):
        return {**_pipe(f'{model}|s1={variant}|trk=prod', alerted, license=license), 'model': model,
                'stage1_variant': variant, 'tracker': 'prod'}

    summary = [row('x', 'lowconf', 2, 'not stated'), row('y', 'lowconf', 1, 'MIT'),
               row('x', 'prod', 1, 'not stated'), row('y', 'prod', 1, 'MIT')]
    st = {r['pipeline']: stats({'f1', 'f2'} if r['fall_clips_alerted'] == 2 else {'f1'}) for r in summary}
    paired = paired_rows(summary, {'x': {'license': 'not stated'}, 'y': {'license': 'MIT'}}, st)
    winner, _, tied = recommend_v2(summary, lambda a, b: any(
        r['verdict'] == 'tie' for r in paired if r['scope'] == 'pipeline' and r['metric'] == 'event_score'
        and {r['a'], r['b']} == {a['pipeline'], b['pipeline']}))
    assert tied and winner['pipeline'] == 'y|s1=lowconf|trk=prod'      # 2 vs 1 alert on 2 clips is a tie
    gain = pair_row(paired, 'pipeline', winner['pipeline'], 'y|s1=prod|trk=prod')
    assert gain is not None and float(gain['diff']) == 0


def test_kaggle_auth_header_is_not_redirected(monkeypatch):
    import email.message
    from benchmark.fetch_models import _HttpsOnlyRedirect, build_request
    monkeypatch.setenv('KAGGLE_API_TOKEN', 'test-token')
    req = build_request('https://www.kaggle.com/api/v1/models/a/b/pyTorch/default/1/download/best.pt', 'kaggle')
    assert req.unredirected_hdrs['Authorization'] == 'Bearer test-token'
    assert 'Authorization' not in req.headers
    moved = _HttpsOnlyRedirect().redirect_request(req, None, 302, 'Found', email.message.Message(),
                                                   'https://storage.googleapis.com/bucket/best.pt')
    assert moved.full_url.startswith('https://storage.googleapis.com/')
    assert not moved.has_header('Authorization')
    assert build_request('https://huggingface.co/x/resolve/main/best.pt').unredirected_hdrs == {}


def test_kaggle_token_missing_raises(monkeypatch):
    from benchmark.fetch_models import kaggle_token
    monkeypatch.delenv('KAGGLE_API_TOKEN', raising=False)
    with pytest.raises(RuntimeError, match='KAGGLE_API_TOKEN'):
        kaggle_token()
    monkeypatch.setenv('KAGGLE_API_TOKEN', '  ')
    with pytest.raises(RuntimeError, match='KAGGLE_API_TOKEN'):
        kaggle_token()
    monkeypatch.setenv('KAGGLE_API_TOKEN', 'KGAT_part1\npart2')
    with pytest.raises(RuntimeError) as err:
        kaggle_token()
    assert 'part1' not in str(err.value)                         # the token is never echoed


def test_stage1_failure_keeps_resumed_and_missing_rows():
    from benchmark.run_benchmark import stage1_failure_rows
    cands = [{'id': 'a', 'kind': 'k'}, {'id': 'b', 'kind': 'k'}, {'id': 'c', 'kind': 'k', 'status': 'missing', 'notes': 'gone'}]
    keep = [{'model': 'a', 'stage1_variant': 'pose', 'status': 'ok'}]
    rows = {r['model']: r for r in stage1_failure_rows(cands, set(), 'w', 'pose', 'OOM', keep)}
    assert 'a' not in rows                                       # --resume keeps its ok row
    assert rows['b']['status'] == 'failed' and rows['b']['error'] == 'OOM'
    assert rows['c']['status'] == 'missing' and rows['c']['error'] == 'gone'
    assert {r['model'] for r in stage1_failure_rows(cands, set(), 'w', 'pose', 'OOM')} == {'a', 'b', 'c'}


def test_paired_rows_compute_each_pair_once():
    from benchmark.run_benchmark import paired_rows
    clips, strata = ['f1', 'n1'], {'f1': 'fall', 'n1': 'normal'}

    def stats(alerted):
        events = {c: {'is_fall': c == 'f1', 'counted': True, 'alerted': c == 'f1' and alerted, 'false_alarm': False}
                  for c in clips}
        return clips, stat_fns(events, {'f1': (1, 0, 0)}), strata

    rows = [{**_pipe(f'{m}|s1=prod|trk=prod', a), 'model': m, 'stage1_variant': 'prod', 'tracker': 'prod'}
            for m, a in (('x', 1), ('y', 1), ('z', 0))]
    # x ranks first, but y wins the tie-break on license, so the winner's pairs include (y, x) after (x, y).
    entries = {'x': {'license': 'not stated'}, 'y': {'license': 'MIT'}, 'z': {'license': 'MIT'}}
    paired = paired_rows(rows, entries, {r['pipeline']: stats(r['fall_clips_alerted']) for r in rows})
    keys = [(r['scope'], frozenset((r['a'], r['b'])), r['metric']) for r in paired]
    assert any(r['a'].startswith('y|') for r in paired)          # the tie-broken winner was compared
    assert keys and len(keys) == len(set(keys))


def test_resume_skips_only_complete_pairs(tmp_path):
    from benchmark.run_benchmark import already_scored
    runs = [{'model': 'm', 'stage1_variant': 'prod', 'status': 'ok'},
            {'model': 'm', 'stage1_variant': 'pose', 'status': 'failed'},
            {'model': 'm', 'stage1_variant': 'lowconf', 'status': 'ok'}]
    for variant in ('prod', 'pose'):
        (tmp_path / f'frames_m@{variant}.csv').write_text('clip_id\n', encoding='utf-8')
    assert already_scored(runs, 'm', 'prod', tmp_path)
    assert not already_scored(runs, 'm', 'pose', tmp_path)       # failed row
    assert not already_scored(runs, 'm', 'lowconf', tmp_path)    # no frames file
    assert not already_scored(runs, 'other', 'prod', tmp_path)


def test_kaggle_merge_results_filters_variant_and_rejects_zip_slip(tmp_path):
    import zipfile
    from benchmark.kaggle_bundle import merge_results
    results = tmp_path / 'results'
    results.mkdir()
    (results / 'runs.csv').write_text('model,stage1_variant,status\nm,prod,ok\nm,pose,failed\n', encoding='utf-8')
    archive = tmp_path / 'results_pose.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('runs.csv', 'model,stage1_variant,status\nm,pose,ok\nm,prod,failed\n')
        z.writestr('frames_m@pose.csv', 'x\n')
        z.writestr('frames_m@prod.csv', 'stale\n')            # another variant: not copied
        z.writestr('events_m@pose@gap1.csv', 'x\n')
        z.writestr('failures/m@pose/FP_a_1.0.jpg', b'jpg')
    assert merge_results(archive, 'pose', results) == (3, 1)
    rows = {(r.split(',')[0], r.split(',')[1]): r.split(',')[2] for r in
            (results / 'runs.csv').read_text(encoding='utf-8').split()[1:]}
    assert rows == {('m', 'prod'): 'ok', ('m', 'pose'): 'ok'}
    assert not (results / 'frames_m@prod.csv').exists()
    evil = tmp_path / 'results_x.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr('failures/../../escape@x/a.jpg', b'x')
    with pytest.raises(ValueError, match='unsafe path'):
        merge_results(evil, 'x', results)


def test_stored_latency_sample_keeps_only_current_clips(tmp_path, monkeypatch):
    from benchmark import run_benchmark as rb
    monkeypatch.setattr(rb, 'RESULTS', tmp_path)
    (tmp_path / 'latency_sample.csv').write_text('clip_id,t,n_persons\na,0.3,1\nb,1.2,4\ngone,0.0,1\n', encoding='utf-8')
    clips = [({'clip_id': 'a'}, None), ({'clip_id': 'b'}, None)]
    assert rb.stored_latency_sample(clips) == [('a', 0.3), ('b', 1.2)]
    (tmp_path / 'latency_sample.csv').unlink()
    assert rb.stored_latency_sample(clips) == []


def test_render_demo_track_style():
    from benchmark.render_demo import GREEN, ORANGE, RED, track_style
    base = {'id': 3, 'fall_score': .91, 'fall_elapsed': 2.4, 'danger': False, 'pending': False}
    assert track_style({**base, 'danger': True}) == (RED, '#3 fall 0.91 ALERT')
    assert track_style({**base, 'pending': True}) == (ORANGE, '#3 fall 0.91 2.4s')
    assert track_style({**base, 'fall_score': None}) == (GREEN, '#3 n/a')


def test_benchmark_does_not_import_fallguard():
    """Results are tied to the frozen copy in benchmark/legacy.py, not to whatever fallguard/ becomes."""
    import ast
    from pathlib import Path
    bench = Path(__file__).resolve().parent.parent / 'benchmark'
    for path in bench.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n.split('.')[0] == 'fallguard' for n in names), f'{path.name} imports {names}'


def test_read_manifest_rejects_path_like_clip_ids(tmp_path):
    from benchmark.frames import read_manifest
    good = tmp_path / 'ok.csv'
    good.write_text('clip_id,source\nyt_a.1,youtube\n', encoding='utf-8')
    assert read_manifest(good)[0]['clip_id'] == 'yt_a.1'
    for bad in ('..', r'..\..\x', 'a/b', ''):
        path = tmp_path / 'bad.csv'
        path.write_text(f'clip_id,source\n"{bad}",youtube\n', encoding='utf-8')
        with pytest.raises(ValueError, match='invalid clip_id'):
            read_manifest(path)


def test_verify_file_rejects_unpinned_and_mismatch(tmp_path):
    from benchmark.fetch_models import sha256_of, verify_file
    f = tmp_path / 'w.pt'
    f.write_bytes(b'weights')
    verify_file(f, sha256_of(f).upper())
    with pytest.raises(ValueError, match='not pinned'):
        verify_file(f, '')
    with pytest.raises(ValueError, match='does not match'):
        verify_file(f, '0' * 64)
