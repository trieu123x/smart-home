"""Freeze the 20/20 train/test split of the 40 benchmark clips into benchmark/split.csv.

Clips that share a person or a scene form one group and stay on one side. 1000 random group
assignments (seed 0) are drawn; among those with 20 test clips, >= 8 event-eligible fall clips and
the long clip on the test side, the one closest to half of each (fall, non-fall) x (real, lab) cell wins.

Usage (from `Fall detection/`): .venv/Scripts/python -I benchmark/finetune/make_split.py [--seed 0] [--check]
"""
import argparse
import csv
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark import frames as fr  # noqa: E402
from benchmark.finetune.common import SPLIT_CSV  # noqa: E402

TRIES = 1000
TEST_SIZE = 20
MIN_TEST_EVENT_FALLS = 8
SCHOOL = {'yt_neg_kids_floor1', 'yt_neg_kids_floor2', 'yt_neg_kids_floor3', 'yt_long_class1'}   # the same school


def group_of(row):
    clip = row['clip_id']
    if m := re.match(r'gmd_(s\d+)_', clip):
        return f'gmd_{m.group(1)}'
    if clip.startswith('urfd_'):
        return 'urfd'
    if clip in SCHOOL:
        return 'yt_school'
    return clip


def cell(row):
    return ('fall' if row['is_fall'] == '1' else 'nonfall', fr.source_group(row))


def is_event_fall(row):
    return row['is_fall'] == '1' and not fr.is_short(row)


def valid(rows, test):
    return (len(test) == TEST_SIZE and sum(is_event_fall(r) for r in rows if r['clip_id'] in test) >= MIN_TEST_EVENT_FALLS
            and all(r['clip_id'] in test for r in rows if fr.is_long(r)))


def imbalance(rows, test):
    cells = {}
    for r in rows:
        total, in_test = cells.get(cell(r), (0, 0))
        cells[cell(r)] = (total + 1, in_test + (r['clip_id'] in test))
    return sum(abs(in_test - total / 2) for total, in_test in cells.values())


def make_split(rows, seed=0, tries=TRIES):
    """[(clip_id, group, split)] in manifest order. Raises ValueError when no assignment is valid."""
    groups = {}
    for r in rows:
        groups.setdefault(group_of(r), []).append(r['clip_id'])
    names = sorted(groups)
    rng = random.Random(seed)
    best = None
    for _ in range(tries):
        test = {c for g in names if rng.random() < 0.5 for c in groups[g]}
        if valid(rows, test) and (best is None or imbalance(rows, test) < best[0]):
            best = (imbalance(rows, test), test)
    if best is None:
        raise ValueError(f'no group assignment out of {tries} meets the split constraints')
    return [(r['clip_id'], group_of(r), 'test' if r['clip_id'] in best[1] else 'train') for r in rows]


def write_split(split, path=SPLIT_CSV):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(['clip_id', 'group', 'split'])
        writer.writerows(split)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--check', action='store_true', help='only compare with the committed split.csv')
    args = parser.parse_args(argv)
    rows = fr.read_manifest()
    try:
        split = make_split(rows, args.seed)
    except ValueError as e:
        print(f'[ERROR] {e}')
        return 1
    by_clip = {r['clip_id']: r for r in rows}
    for side in ('train', 'test'):
        picked = [by_clip[c] for c, _, s in split if s == side]
        cells = {k: sum(cell(r) == k for r in picked) for k in sorted({cell(r) for r in rows})}
        print(f"{side}: {len(picked)} clips, {sum(is_event_fall(r) for r in picked)} event falls, "
              + ', '.join(f'{f}/{s}={n}' for (f, s), n in cells.items()))
    if args.check:
        with open(SPLIT_CSV, newline='', encoding='utf-8') as f:
            same = [tuple(r) for r in list(csv.reader(f))[1:]] == split
        print('[OK] split.csv matches' if same else '[DIFF] split.csv differs from a fresh split')
        return 0 if same else 1
    write_split(split)
    print(f'Wrote {SPLIT_CSV}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
