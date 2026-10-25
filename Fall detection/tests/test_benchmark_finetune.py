"""Offline checks for the fine-tune data builders, the split and the benchmark's --split analysis."""
import csv
import json

import numpy as np
import pytest

from benchmark.finetune.build_stage2_crops import (FormatError, activity_rule, caucafall_labels, clip_label,
                                                   fall_class_id, scan_caucafall, train_clip_rows)
from benchmark.finetune.common import (assert_no_test_clips, check_class_floor, dhash, near_duplicates,
                                       teacher_merge, train_with_fallback)
from benchmark.frames import is_long, is_short, read_manifest

FALL_ROW = {'clip_id': 'f1', 'is_fall': '1', 'fall_start_s': '2.0', 'fall_end_s': '8.0'}
NONFALL_ROW = {'clip_id': 'n1', 'is_fall': '0', 'fall_start_s': '', 'fall_end_s': ''}


def test_split_is_grouped_stratified_and_deterministic():
    from benchmark.finetune.common import read_split
    from benchmark.finetune.make_split import group_of, make_split
    rows = read_manifest()
    split = make_split(rows, seed=0)
    assert split == make_split(rows, seed=0)
    assert [tuple(r) for r in csv.reader(open('benchmark/split.csv', encoding='utf-8'))][1:] == split   # committed
    assert len(split) == 40 and sum(s == 'test' for _, _, s in split) == 20
    sides = {}
    for _, group, side in split:
        sides.setdefault(group, set()).add(side)
    assert all(len(s) == 1 for s in sides.values())
    assert group_of({'clip_id': 'yt_long_class1'}) == group_of({'clip_id': 'yt_neg_kids_floor2'})
    test = {c for c, s in read_split().items() if s == 'test'}
    by_clip = {r['clip_id']: r for r in rows}
    assert sum(by_clip[c]['is_fall'] == '1' and not is_short(by_clip[c]) for c in test) >= 8
    assert any(is_long(by_clip[c]) for c in test)


def test_split_test_clips_never_in_training_manifests(tmp_path):
    split = {'a': 'train', 'b': 'test'}
    rows = [{'clip_id': 'a'}, {'clip_id': 'b'}]
    assert [r['clip_id'] for r in train_clip_rows(rows, split, {'a': 'normal'})] == ['a']
    with pytest.raises(ValueError, match='never feed training'):
        train_clip_rows(rows, split, {'a': 'normal', 'b': 'sit'}, wanted={'a', 'b'})
    with pytest.raises(ValueError, match='never feed training'):
        assert_no_test_clips(['cauca_s1_walk', 'b'], split)   # e.g. origins of merged crops
    with pytest.raises(FormatError, match='no row'):
        train_clip_rows(rows, split, {})


def test_clip_crop_labels_from_interval_and_postures():
    assert clip_label(4.0, FALL_ROW, 'normal', 1) == 'fall'
    assert clip_label(4.0, FALL_ROW, 'normal', 2) is None       # helpers next to the fallen person
    assert clip_label(2.5, FALL_ROW, 'sit', 1) == 'fall'        # start + 0.5 is inside
    assert clip_label(2.2, FALL_ROW, 'sit', 1) is None          # edge window
    assert clip_label(1.0, FALL_ROW, 'sit', 3) == 'sit'         # outside the interval: the clip posture
    assert clip_label(9.0, FALL_ROW, 'normal', 1) == 'normal'
    assert clip_label(1.0, FALL_ROW, 'skip', 1) is None
    assert clip_label(4.0, FALL_ROW, 'skip', 1) == 'fall'       # skip only covers frames outside the interval
    assert clip_label(4.0, FALL_ROW, 'normal', 1, fall_crops='skip') is None   # the one box is a helper
    assert clip_label(9.0, FALL_ROW, 'normal', 1, fall_crops='skip') == 'normal'
    assert clip_label(3.0, NONFALL_ROW, 'sit', 2) == 'sit'
    assert clip_label(3.0, NONFALL_ROW, 'skip', 1) is None
    assert clip_label(3.0, NONFALL_ROW, 'normal', 0) is None
    assert caucafall_labels('sit', [False] * 4) == [None, None, 'sit', 'sit']
    assert caucafall_labels('fall', [False, True, True]) == [None, 'fall', 'fall']
    assert caucafall_labels('normal', [False, False]) == ['normal', 'normal']


def test_caucafall_folder_map_rejects_unknown_folder(tmp_path):
    assert activity_rule('Fall backwards') == 'fall'
    assert activity_rule('Sit_down') == 'sit'
    assert activity_rule('pick up  object') == 'normal'
    with pytest.raises(FormatError, match='unmapped'):
        activity_rule('Dance')
    folder = tmp_path / 'CAUCAFall' / 'Subject.1' / 'Dance'
    folder.mkdir(parents=True)
    (folder / 'cas100001.png').write_bytes(b'')
    (folder / 'cas100001.txt').write_text('0 0.5 0.5 0.2 0.4\n', encoding='utf-8')
    with pytest.raises(FormatError, match='unmapped'):
        scan_caucafall(tmp_path)
    folder.rename(folder.parent / 'Walk')
    (folder.parent / 'Walk' / 'cas100001.txt').write_text('0 512 300 80 200\n', encoding='utf-8')
    with pytest.raises(FormatError, match='normalised'):
        scan_caucafall(tmp_path)
    assert fall_class_id([('normal', [0, 0]), ('sit', [0]), ('fall', [0, 1, 1])]) == 1
    with pytest.raises(FormatError, match='fall class id'):
        fall_class_id([('normal', [0, 1]), ('fall', [0, 1])])


def test_teacher_merge_adds_only_non_overlapping_boxes():
    gt = [[0, 0, 10, 10]]
    boxes = [[0, 0, 10, 10], [7, 0, 17, 10], [20, 20, 30, 30], [40, 40, 50, 50], [0, 0, 4, 10]]
    confs = [0.9, 0.8, 0.7, 0.4, 0.95]
    added = teacher_merge(gt, boxes, confs)
    assert [0, 0, 10, 10] not in added                          # IoU 1 with the ground truth
    assert [7, 0, 17, 10] in added                              # IoU 0.18 < 0.5, 30% inside
    assert [20, 20, 30, 30] in added
    assert [40, 40, 50, 50] not in added                        # conf < 0.5
    assert [0, 0, 4, 10] not in added                           # IoU 0.4 but a fragment fully inside the box
    assert teacher_merge([], [[0, 0, 10, 10], [1, 0, 11, 10]], [0.9, 0.8]) == [[0, 0, 10, 10]]   # no duplicate pair


def test_dhash_filter_drops_near_duplicates():
    import cv2
    rng = np.random.default_rng(0)
    image = cv2.GaussianBlur(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8), (31, 31), 0)
    resized = cv2.resize(image, (288, 216))
    other = cv2.flip(image, 1)
    mask = near_duplicates([dhash(resized), dhash(other)], [dhash(image)])
    assert mask.tolist() == [True, False]
    assert near_duplicates([], [dhash(image)]).tolist() == []


def test_class_floor_fails_on_small_class():
    check_class_floor({'fall': 300, 'sit': 412, 'normal': 900})
    check_class_floor({'fall': 300, 'sit': 182, 'normal': 900})          # sit has its own floor of 150
    with pytest.raises(ValueError, match="'normal': 299"):
        check_class_floor({'fall': 300, 'sit': 412, 'normal': 299})
    with pytest.raises(ValueError, match="'sit': 149"):
        check_class_floor({'fall': 300, 'sit': 149, 'normal': 900})
    with pytest.raises(ValueError, match='sit'):
        check_class_floor({'fall': 300, 'sit': 299, 'normal': 900}, overrides={})


def test_run_benchmark_split_filters_manifest_and_output_dir(tmp_path, monkeypatch):
    from benchmark import run_benchmark as rb
    from benchmark.finetune import common
    monkeypatch.setattr(rb, 'RESULTS', tmp_path)
    monkeypatch.setattr(rb, 'BENCH', tmp_path)
    monkeypatch.setattr(rb, 'FIGURES', tmp_path / 'figures')
    monkeypatch.setattr(rb, 'SPLIT_REPORT', tmp_path / 'REPORT_FINETUNE.md')
    monkeypatch.setattr(rb, 'REPORT', tmp_path / 'REPORT.md')            # never the real v3 report
    monkeypatch.setattr(rb, 'PR_FIGURE', tmp_path / 'figures' / 'pr_stage2.png')
    monkeypatch.setattr(common, 'read_split', lambda: {'f1': 'test', 'n1': 'test', 'f2': 'train'})
    extra = {'source': 'youtube', 'view': 'wall', 'notes': ''}
    manifest = [{**FALL_ROW, **extra}, {**NONFALL_ROW, **extra}, {**FALL_ROW, **extra, 'clip_id': 'f2'}]
    assert rb.View(manifest).out == tmp_path and rb.View(manifest).manifest == manifest
    view = rb.View(manifest, 'test')
    assert [r['clip_id'] for r in view.manifest] == ['f1', 'n1']
    assert view.out == tmp_path / 'split_test' and view.suffix == ''
    assert rb.View(manifest, 'all').suffix == '_all40' and len(rb.View(manifest, 'all').manifest) == 3
    assert rb.View(manifest).latency.name == 'latency.csv' and view.latency.name == 'latency_split.csv'   # no v3 overwrite

    rb.write_csv(tmp_path / 'runs.csv', rb.RUN_FIELDS,
                 [{'model': 'm', 'kind': 'classify', 'stage1': 'yolo11s', 'stage1_variant': 'pose', 'status': 'ok'}])
    frames = [{'clip_id': c, 't': t, 'label': lab, 'n_persons': 1, 'frame_score': s, 'stage1_ms': 5, 'stage2_ms': 5}
              for c, lab, s in (('f1', 'fall', .9), ('n1', 'normal', .1), ('f2', 'fall', .9)) for t in (3.0, 4.0)]
    rb.write_csv(tmp_path / 'frames_m@pose.csv', rb.FRAME_FIELDS, frames)
    for tracker in ('prod', 'gap1', 'gap2'):
        rb.write_csv(tmp_path / f'events_m@pose@{tracker}.csv', rb.EVENT_FIELDS,
                     [{'clip_id': c, 'source': 'youtube', 'is_fall': int(c != 'n1'), 'counted': 1, 'uncertain': 0,
                       'threshold': '0.4', 'alerted': int(c != 'n1'), 'false_alarm': 0, 'latency_s': 5.0 if c != 'n1'
                       else '', 'alerts': '7.0' if c != 'n1' else ''} for c in ('f1', 'n1', 'f2')])
    models = {'stage1': [], 'candidates': [{'id': 'm', 'kind': 'classify', 'source_url': '', 'files': [{}]}]}
    summary, _ = rb.report(models, manifest, 'test')
    row = next(r for r in summary if r['tracker'] == 'gap1')
    assert row['n_frames'] == 4 and row['fall_clips'] == 1 and row['nonfall_clips'] == 1   # f2 (train) left out
    assert (tmp_path / 'split_test' / 'summary.csv').is_file() and not (tmp_path / 'summary.csv').exists()
    assert '**Goal 5:' not in rb.goal_block([{**row, 'pipeline': p} for p in (rb.FT_TARGET, rb.FT_BASELINE)], [],
                                            decides=False)          # only the test split decides Goal 5

    # The v3 view (no --split) never sees fine-tuned models: a `local` candidate or the `ft` stage-1 variant.
    models['candidates'].append({'id': 'ft3', 'kind': 'classify', 'source_url': '', 'files': [{'local': True}]})
    models['stage1'].append({'id': 'yolo11s-ft', 'files': [{'local': True}]})
    rb.write_csv(tmp_path / 'runs.csv', rb.RUN_FIELDS,
                 [{'model': m, 'kind': 'classify', 'stage1': 'w', 'stage1_variant': v, 'status': 'ok'}
                  for m, v in (('m', 'pose'), ('m', 'ft'), ('ft3', 'pose'))])
    for m, v in (('m', 'ft'), ('ft3', 'pose')):
        (tmp_path / f'frames_{m}@{v}.csv').write_bytes((tmp_path / 'frames_m@pose.csv').read_bytes())
        for tracker in ('prod', 'gap1', 'gap2'):
            (tmp_path / f'events_{m}@{v}@{tracker}.csv').write_bytes(
                (tmp_path / f'events_m@pose@{tracker}.csv').read_bytes())
    v3, _ = rb.report(models, manifest)
    assert {r['pipeline'].split('|trk=')[0] for r in v3} == {'m|s1=pose'}
    split_all, _ = rb.report(models, manifest, 'all')
    assert {r['pipeline'].split('|trk=')[0] for r in split_all} == {'m|s1=pose', 'm|s1=ft', 'ft3|s1=pose'}


def test_fetch_models_local_entry_is_verified_not_downloaded(tmp_path, monkeypatch, capsys):
    from benchmark import fetch_models as fm
    monkeypatch.setattr(fm, 'WEIGHTS', tmp_path / 'weights')
    monkeypatch.setattr(fm, 'MODELS_JSON', tmp_path / 'models.json')
    monkeypatch.setattr(fm, 'download', lambda *a, **k: pytest.fail('a local entry must never be downloaded'))

    def run(sha, argv=()):
        entry = {'id': 'ft', 'files': [{'url': 'https://example.invalid/x.pt', 'path': 'best.pt', 'sha256': sha,
                                        'local': True}]}
        (tmp_path / 'models.json').write_text(json.dumps({'stage1': [entry], 'candidates': []}), encoding='utf-8')
        return fm.main(list(argv))

    assert run('') == 0 and '[SKIP]' in capsys.readouterr().out             # not produced yet: v3 setup still passes
    assert run('', ['--only', 'ft']) == 1 and 'kaggle_finetune.py pull' in capsys.readouterr().out   # asked for
    weights = tmp_path / 'weights' / 'ft' / 'best.pt'
    weights.parent.mkdir(parents=True)
    weights.write_bytes(b'weights')
    assert run('') == 0 and '[PIN]' in capsys.readouterr().out
    assert run(fm.sha256_of(weights)) == 0
    assert run('0' * 64) == 1 and weights.is_file()                 # mismatch is reported, never deleted


def test_train_with_fallback_retries_on_one_gpu_with_time_left():
    calls, now = [], [0.0]

    def train(device, hours):
        calls.append((device, hours))
        if device == [0, 1]:
            now[0] += 1800   # DDP failed after half an hour
            raise RuntimeError('NCCL error')
        return 'ok'

    assert train_with_fallback(train, 2, 5.5, clock=lambda: now[0]) == ('ok', 0)
    assert calls == [([0, 1], 5.5), (0, 5.0)]
    calls.clear()
    assert train_with_fallback(train, 1, 5.5, clock=lambda: now[0]) == ('ok', 0) and calls == [(0, 5.5)]


def test_kaggle_finetune_pull_rejects_unexpected_paths(tmp_path):
    import zipfile
    from benchmark.finetune.kaggle_finetune import CROP_NAME, safe_extract
    good = tmp_path / 'good.zip'
    with zipfile.ZipFile(good, 'w') as z:
        z.writestr('train/fall/cauca_s1_fallleft__f00010.jpg', b'x')
        z.writestr('stats.json', '{}')
    assert safe_extract(good, tmp_path / 'out', CROP_NAME) == 2
    evil = tmp_path / 'evil.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr('train/fall/../../../escape.jpg', b'x')
    with pytest.raises(ValueError, match='unsafe'):
        safe_extract(evil, tmp_path / 'out2', CROP_NAME)
    assert not (tmp_path / 'out2').exists()
