"""Build the 3-class (`fall` / `sit` / `normal`) stage-2 crop set as an ImageFolder.

Crops are cut with legacy.square_crop (10% margin) around yolo11s-pose boxes at conf 0.3, the benchmark's
`pose` stage 1. Two sources:

- CAUCAFall (CC BY 4.0): fall activities give their frames labelled `fall`, sitting and kneeling the
  second half of the activity (`sit`), walking, hopping and picking up every frame (`normal`). Only frames
  with exactly one person box. Subjects 9-10 form `val`. The 8.3 GB set is read on Kaggle
  (`kaggle_finetune.py --phase prep`), which runs this script with `--source caucafall --partial`.
- The 20 `train` clips of benchmark/split.csv: frames inside [fall_start_s + 0.5, fall_end_s - 0.5] with one
  person box are `fall`; every other frame takes the clip's posture from finetune/clip_postures.csv.
  `fall_crops=skip` there drops a clip's fall crops when the one box stage 1 finds is a helper, not the
  fallen person (found in the crop review).

Frames are >= 0.5 s apart, at most 150 crops per clip or CAUCAFall activity. A test clip in any input
fails the build. stats.json holds the class counts; every train class needs >= 300 crops.

Usage (from `Fall detection/`):
    .venv/Scripts/python -I benchmark/finetune/build_stage2_crops.py --source clips \
        --merge benchmark/data/finetune/stage2_caucafall [--review]
    .venv/Scripts/python -I benchmark/finetune/build_stage2_crops.py --source caucafall --caucafall-root <dir> \
        --out <dir> --partial
"""
import argparse
import csv
import json
import math
import random
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark import frames as fr  # noqa: E402
from benchmark.finetune.common import (DATA, FT, assert_no_test_clips, check_class_floor,  # noqa: E402
                                       read_split)

OUT = DATA / 'stage2'
POSTURES = FT / 'clip_postures.csv'
SHEETS = ROOT / 'benchmark' / 'results' / 'sheets'
CLASSES = ('fall', 'sit', 'normal')
POSTURE_VALUES = ('sit', 'normal', 'skip')
FALL_CROPS_VALUES = ('keep', 'skip')
STEP_S = 0.5
MAX_PER_SOURCE = 150
POSE_CONF = 0.3
VAL_SUBJECTS = {9, 10}
DEFAULT_FPS = 23.0   # only when an activity folder has no video to read the frame rate from
SEED = 0
REVIEW_N, REVIEW_THUMB = 96, 128

# CAUCAFall activity folder (lower case, single spaces) -> rule. Unknown folders fail the build.
CAUCAFALL_ACTIVITIES = {
    'fall backwards': 'fall', 'fall forward': 'fall', 'fall left': 'fall', 'fall right': 'fall',
    'fall sitting': 'fall',
    'sit down': 'sit', 'kneel': 'sit',
    'walk': 'normal', 'hop': 'normal', 'pick up object': 'normal',
}


class FormatError(ValueError):
    pass


# ---------- labels ----------

def activity_rule(folder_name):
    key = ' '.join(folder_name.replace('_', ' ').lower().split())
    if key not in CAUCAFALL_ACTIVITIES:
        raise FormatError(f'unmapped CAUCAFall activity folder {folder_name!r}; add it to CAUCAFALL_ACTIVITIES')
    return CAUCAFALL_ACTIVITIES[key]


def caucafall_labels(rule, frame_is_fall):
    """Class per frame of one activity (None = not used). frame_is_fall: per-frame label in order."""
    n = len(frame_is_fall)
    if rule == 'fall':
        return ['fall' if f else None for f in frame_is_fall]
    if rule == 'sit':
        return ['sit' if i >= n / 2 else None for i in range(n)]
    return ['normal'] * n


def clip_label(t, row, posture, n_boxes, fall_crops='keep'):
    """Class for every crop of a clip frame at time t, or None to skip the frame."""
    if n_boxes == 0:
        return None
    if row.get('is_fall') == '1':
        label = fr.label_at(t, row)   # 'fall' exactly on [start + 0.5, end - 0.5], 'ignore' within 0.5 s of an edge
        if label == 'fall':
            return 'fall' if n_boxes == 1 and fall_crops == 'keep' else None   # helpers next to the person
        if label == 'ignore':
            return None
    return None if posture == 'skip' else posture


def read_postures(path=POSTURES):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    bad = [r['clip_id'] for r in rows if r.get('posture') not in POSTURE_VALUES
           or r.get('fall_crops') not in FALL_CROPS_VALUES or not (r.get('note') or '').strip()]
    if bad:
        raise FormatError(f'{path.name}: posture must be one of {POSTURE_VALUES}, fall_crops one of '
                          f'{FALL_CROPS_VALUES}, with a note; not so for {bad}')
    return {r['clip_id']: (r['posture'], r['fall_crops']) for r in rows}


def spaced(indices, min_gap):
    """Keep indices (ascending) at least min_gap apart."""
    out = []
    for i in indices:
        if not out or i - out[-1] >= min_gap:
            out.append(i)
    return out


def cap(items, limit=MAX_PER_SOURCE, seed=SEED):
    return items if len(items) <= limit else random.Random(seed).sample(items, limit)


# ---------- CAUCAFall ----------

def find_subjects(root):
    """{subject number: folder} for `Subject.<n>` folders anywhere under root."""
    subjects = {}
    for d in root.rglob('Subject*'):
        m = re.fullmatch(r'Subject[ ._-]?(\d+)', d.name, re.IGNORECASE)
        if d.is_dir() and m:
            subjects[int(m.group(1))] = d
    if not subjects:
        raise FormatError(f'no Subject.<n> folders under {root}')
    return dict(sorted(subjects.items()))


def read_yolo_class(txt):
    """Class id of the first box in a YOLO label file, None when empty."""
    for line in txt.read_text(encoding='utf-8', errors='replace').splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            cls, coords = int(parts[0]), [float(p) for p in parts[1:]]
        except ValueError:
            raise FormatError(f'{txt}: expected "<class> cx cy w h", got {line!r}')
        if len(coords) != 4 or not all(0 <= c <= 1.0001 for c in coords):
            raise FormatError(f'{txt}: expected 4 normalised coordinates, got {line!r}')
        return cls
    return None


def fall_class_id(activities):
    """The class id that means `fall`: from classes.txt when present, else the one id that appears
    only in fall activities. activities: [(rule, [class id per frame])]."""
    still = {c for rule, ids in activities if rule != 'fall' for c in ids if c is not None}
    falling = {c for rule, ids in activities if rule == 'fall' for c in ids if c is not None}
    extra = falling - still
    if len(still) != 1 or len(extra) != 1:
        raise FormatError(f'cannot tell the fall class id: non-fall activities use {sorted(still)}, '
                          f'fall activities {sorted(falling)}')
    return extra.pop()


def classes_txt_fall_id(root):
    for path in sorted(root.rglob('classes.txt')):
        names = [n.strip().lower() for n in path.read_text(encoding='utf-8', errors='replace').splitlines()]
        if 'fall' in names:
            return names.index('fall'), path
    return None, None


def activity_fps(folder):
    import cv2
    for video in sorted(folder.glob('*.avi')) + sorted(folder.glob('*.mp4')):
        cap_ = cv2.VideoCapture(str(video))
        fps = cap_.get(cv2.CAP_PROP_FPS)
        cap_.release()
        if fps and 1 <= fps <= 120:
            return fps
    return None


def scan_caucafall(root, max_unlabelled=0.01):
    """[(subject, folder, rule, [(png, class id)])], every label checked before any crop is written.

    A few stray frames without a label file (e.g. `cas200091 - copia.png`) are skipped and reported;
    more than `max_unlabelled` of all frames means the layout is not what this script expects.
    """
    out, unlabelled, total = [], [], 0
    for subject, sdir in find_subjects(root).items():
        for adir in sorted(d for d in sdir.iterdir() if d.is_dir()):
            rule = activity_rule(adir.name)
            pngs = sorted(adir.glob('*.png'), key=lambda p: (len(p.stem), p.stem))
            if not pngs:
                raise FormatError(f'no .png frames in {adir}')
            frames = []
            for png in pngs:
                txt = png.with_suffix('.txt')
                if txt.is_file():
                    frames.append((png, read_yolo_class(txt)))
                else:
                    unlabelled.append(png)
            total += len(pngs)
            out.append((subject, adir, rule, frames))
    if len(unlabelled) > max_unlabelled * total:
        raise FormatError(f'{len(unlabelled)} of {total} frames have no label file, e.g. {unlabelled[0]}')
    for png in unlabelled:
        print(f'  [SKIP] no label file for {png}', flush=True)
    return out


def caucafall_crops(root, stage1, out_dir):
    """Write CAUCAFall crops into out_dir/{train,val}/<class>/; return per-origin counts."""
    import cv2
    from benchmark.legacy import square_crop
    activities = scan_caucafall(root)
    fall_id, source = classes_txt_fall_id(root)
    if fall_id is None:
        fall_id, source = fall_class_id([(rule, [c for _, c in frames]) for _, _, rule, frames in activities]), 'inferred'
    print(f'CAUCAFall: {len(activities)} activities, fall class id {fall_id} ({source})', flush=True)
    counts = {}
    for subject, adir, rule, frames in activities:
        fps = activity_fps(adir)
        if fps is None:
            print(f'  [WARN] {adir}: no video to read fps from, assuming {DEFAULT_FPS}', flush=True)
        gap = math.ceil((fps or DEFAULT_FPS) * STEP_S - 1e-9)
        labels = caucafall_labels(rule, [c == fall_id for _, c in frames])
        picks = spaced([i for i, lab in enumerate(labels) if lab], gap)
        split = 'val' if subject in VAL_SUBJECTS else 'train'
        origin = f"cauca_s{subject}_{re.sub(r'[^a-z0-9]+', '', adir.name.lower())}"
        crops = []
        for i in picks:
            image = cv2.imread(str(frames[i][0]))
            if image is None:
                raise FormatError(f'cannot read {frames[i][0]}')
            image = fr.resize_max(image)
            boxes, _ = stage1(image)
            if len(boxes) != 1:
                continue
            crop = square_crop(image, boxes[0])
            if crop is not None:
                crops.append((labels[i], f'{origin}__f{i:05d}', crop))
        for label, name, crop in cap(crops):
            save(out_dir / split / label / f'{name}.jpg', crop)
            counts.setdefault(origin, {}).setdefault(f'{split}/{label}', 0)
            counts[origin][f'{split}/{label}'] += 1
        print(f'  {origin}: {len(picks)} frames -> {min(len(crops), MAX_PER_SOURCE)} crops', flush=True)
    return counts


# ---------- benchmark train clips ----------

def train_clip_rows(manifest, split, postures, wanted=None):
    """Manifest rows of the train clips. Raises if a test clip is requested or a posture is missing."""
    rows = [r for r in manifest if (wanted is None and split.get(r['clip_id']) == 'train')
            or (wanted is not None and r['clip_id'] in wanted)]
    assert_no_test_clips([r['clip_id'] for r in rows], split)
    unknown = [r['clip_id'] for r in rows if split.get(r['clip_id']) != 'train']
    if unknown:
        raise ValueError(f'clips not in split.csv: {unknown}')
    missing = [r['clip_id'] for r in rows if r['clip_id'] not in postures]
    if missing:
        raise FormatError(f'clip_postures.csv has no row for {missing}')
    return rows


def clip_crops(rows, postures, stage1, out_dir):
    from benchmark.legacy import square_crop
    counts = {}
    for row in rows:
        path = fr.CLIPS / f"{row['clip_id']}.mp4"
        if not path.is_file():
            raise FileNotFoundError(f'{path} is missing (run fetch_clips.py)')
        crops = []
        for t, frame in fr.iter_frames(path, STEP_S):
            boxes, _ = stage1(frame)
            posture, fall_crops = postures[row['clip_id']]
            label = clip_label(t, row, posture, len(boxes), fall_crops)
            if label is None:
                continue
            for p, box in enumerate(boxes):
                crop = square_crop(frame, box)
                if crop is not None:
                    crops.append((label, f"{row['clip_id']}__t{t:06.1f}_p{p}", crop))
        for label, name, crop in cap(crops):
            save(out_dir / 'train' / label / f'{name}.jpg', crop)
            counts.setdefault(row['clip_id'], {}).setdefault(f'train/{label}', 0)
            counts[row['clip_id']][f'train/{label}'] += 1
        print(f"  {row['clip_id']}: {min(len(crops), MAX_PER_SOURCE)} crops", flush=True)
    return counts


# ---------- output ----------

def save(path, crop):
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(path), crop, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise OSError(f'cannot write {path}')


def origin_of(path):
    return path.stem.split('__', 1)[0]


def merge(src, out_dir):
    """Copy a pre-built crop folder (e.g. the CAUCAFall crops pulled from Kaggle) into out_dir."""
    files = [p for p in src.rglob('*.jpg')]
    for p in files:
        rel = p.relative_to(src)
        if len(rel.parts) != 3 or rel.parts[0] not in ('train', 'val') or rel.parts[1] not in CLASSES:
            raise FormatError(f'unexpected file in {src}: {rel.as_posix()} (want <train|val>/<class>/<name>.jpg)')
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
    return len(files)


def tally(out_dir):
    """Class counts per side and per origin, read back from the written files."""
    stats = {side: {c: 0 for c in CLASSES} for side in ('train', 'val')}
    origins = {}
    for p in out_dir.rglob('*.jpg'):
        side, label = p.parent.parent.name, p.parent.name
        stats[side][label] += 1
        key = f'{side}/{label}'
        origins.setdefault(origin_of(p), {}).setdefault(key, 0)
        origins[origin_of(p)][key] += 1
    return {**stats, 'origins': dict(sorted(origins.items()))}


def review_sheets(out_dir, sheets=SHEETS, n=REVIEW_N, seed=SEED):
    """results/sheets/crops_<class>.jpg: n random crops per class (both sides), origin printed on each."""
    import cv2
    from benchmark.contact_sheet import grid
    sheets.mkdir(parents=True, exist_ok=True)
    written = []
    for label in CLASSES:
        files = sorted(out_dir.glob(f'*/{label}/*.jpg'))
        if not files:
            continue
        thumbs = []
        for p in sorted(random.Random(seed).sample(files, min(n, len(files)))):
            thumb = cv2.resize(cv2.imread(str(p)), (REVIEW_THUMB, REVIEW_THUMB))
            cv2.rectangle(thumb, (0, 0), (REVIEW_THUMB - 1, 13), (0, 0, 0), -1)
            cv2.putText(thumb, p.stem[:22], (2, 10), cv2.FONT_HERSHEY_SIMPLEX, .3, (255, 255, 255), 1)
            thumbs.append(thumb)
        dest = sheets / f'crops_{label}.jpg'
        cv2.imwrite(str(dest), grid(thumbs), [cv2.IMWRITE_JPEG_QUALITY, 85])
        written.append(dest)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', choices=['clips', 'caucafall', 'all'], default='clips')
    parser.add_argument('--caucafall-root', type=Path, help='folder that contains the Subject.<n> folders')
    parser.add_argument('--merge', type=Path, help='pre-built crop folder to add (CAUCAFall crops from Kaggle)')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--partial', action='store_true', help='skip the class floor (one source of several)')
    parser.add_argument('--review', action='store_true', help='write results/sheets/crops_<class>.jpg')
    parser.add_argument('--device', default='auto')
    args = parser.parse_args(argv)
    if args.source in ('caucafall', 'all') and not args.caucafall_root:
        parser.error('--caucafall-root is required for --source caucafall|all')

    try:
        split = read_split()
        rows = []
        if args.source in ('clips', 'all'):
            rows = train_clip_rows(fr.read_manifest(), split, read_postures())
        if args.merge and not args.merge.is_dir():
            raise FileNotFoundError(f'--merge folder {args.merge} does not exist')
        if args.merge:
            assert_no_test_clips({origin_of(p) for p in args.merge.rglob('*.jpg')}, split)
        if args.source in ('caucafall', 'all'):
            scan_caucafall(args.caucafall_root)   # format check before the output folder is touched
    except (FormatError, FileNotFoundError, ValueError) as e:
        print(f'[ERROR] {e}')
        return 1

    import torch
    from benchmark.legacy import select_device
    from benchmark.run_benchmark import Stage1, load_models, stage1_entry
    stage1 = Stage1(stage1_entry(load_models(), 'pose-rule-yolo11s'), select_device(torch, args.device), POSE_CONF)
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)
    if args.source in ('caucafall', 'all'):
        caucafall_crops(args.caucafall_root, stage1, args.out)
    if rows:
        clip_crops(rows, read_postures(), stage1, args.out)
    if args.merge:
        print(f'Merged {merge(args.merge, args.out)} crops from {args.merge}')

    stats = tally(args.out)
    assert_no_test_clips(stats['origins'], split)
    (args.out / 'stats.json').write_text(json.dumps(stats, indent=2) + '\n', encoding='utf-8')
    print('train ' + json.dumps(stats['train']) + ' | val ' + json.dumps(stats['val']))
    if args.review:
        for p in review_sheets(args.out):
            print(f'[SHEET] {p}')
    if not args.partial:
        try:
            check_class_floor(stats['train'])
        except ValueError as e:
            print(f'[ERROR] {e}')
            return 1
    print(f'Wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
