"""Convert E-FPDS into a one-class (`person`) YOLO dataset for the stage-1 fine-tune.

E-FPDS (Maldonado-Bascon et al., Electronics 2019, https://gram.web.uah.es/data/datasets/fpds/) states no
license; it is used for research only in this course project and never committed.

Steps: extract train/valid archives, check the annotation format (`<1|-1> left right top bottom` in pixels
per line, one .txt per .png), add yolo11s boxes (conf >= 0.5) that overlap no E-FPDS box (teacher merge),
drop images that are near-duplicates (dHash) of any benchmark clip frame, and write
benchmark/data/finetune/stage1/{images,labels}/{train,val} plus data.yaml and stats.json.
E-FPDS's own split is kept: train -> train, valid -> val; its test set is not used.

Usage (from `Fall detection/`):
    .venv/Scripts/python -I benchmark/finetune/prepare_stage1.py [--src benchmark/data/efpds] [--device auto]
"""
import argparse
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark import frames as fr  # noqa: E402
from benchmark.finetune.common import DATA, dhash, near_duplicates, teacher_merge  # noqa: E402

EFPDS = ROOT / 'benchmark' / 'data' / 'efpds'
OUT = DATA / 'stage1'
SPLITS = {'train': 'train', 'valid': 'val'}   # E-FPDS folder -> YOLO split
EFPDS_CLASSES = {1, -1}   # 1 fallen, -1 non-fallen; both become `person`
TEACHER_CONF = 0.5
CLIP_STEP = 0.5
MIN_BOX = 2   # px; thinner boxes after clipping to the image are dropped


class FormatError(ValueError):
    pass


def extract(src, dest=EFPDS):
    """Return {efpds split: folder}. Uses extracted folders in src or dest, else extracts <split>.tar.gz."""
    out = {}
    for name in SPLITS:
        for base in (src, dest):
            if (base / name).is_dir() and any((base / name).rglob('*.png')):
                out[name] = base / name
                break
        else:
            archive = src / f'{name}.tar.gz'
            if not archive.is_file():
                raise FileNotFoundError(f'neither {src / name}/ nor {archive} exists')
            print(f'Extracting {archive} ...', flush=True)
            dest.mkdir(parents=True, exist_ok=True)
            try:
                with tarfile.open(archive) as tar:
                    tar.extractall(dest, filter='data')   # refuses absolute paths, '..' and links outside dest
            except (tarfile.TarError, EOFError) as e:
                shutil.rmtree(dest / name, ignore_errors=True)
                raise FormatError(f'{archive} is damaged or truncated ({type(e).__name__}: {e}); download it again')
            out[name] = dest / name
    return out


def parse_label(path):
    """[(cls, x1, y1, x2, y2)] from one E-FPDS .txt. Raises FormatError on anything unexpected."""
    boxes = []
    for n, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        try:
            cls, left, right, top, bottom = (int(p) for p in parts)
        except ValueError:
            raise FormatError(f'{path}:{n}: expected 5 integers "<class> left right top bottom", got {line!r}')
        if cls not in EFPDS_CLASSES or right <= left or bottom <= top:
            raise FormatError(f'{path}:{n}: unexpected values {line!r} (class 1/-1, left < right, top < bottom)')
        boxes.append((cls, left, top, right, bottom))
    return boxes


def scan(folders):
    """[(split, png, boxes)] for every image; checks every label before anything is written."""
    items = []
    for name, folder in folders.items():
        pngs = sorted(folder.rglob('*.png'))
        if not pngs:
            raise FormatError(f'no .png images under {folder}')
        for png in pngs:
            txt = png.with_suffix('.txt')
            if not txt.is_file():
                raise FormatError(f'{png} has no {txt.name} next to it')
            items.append((SPLITS[name], png, parse_label(txt)))
    return items


def clip_hashes(step=CLIP_STEP):
    hashes = []
    for row in fr.read_manifest():
        path = fr.CLIPS / f"{row['clip_id']}.mp4"
        if not path.is_file():
            raise FileNotFoundError(f'{path} is missing (run fetch_clips.py); the leakage filter needs all 40 clips')
        hashes += [dhash(frame) for _, frame in fr.iter_frames(path, step)]
    return hashes


def yolo_line(box, w, h):
    x1, y1, x2, y2 = max(0, box[0]), max(0, box[1]), min(w, box[2]), min(h, box[3])
    if x2 - x1 < MIN_BOX or y2 - y1 < MIN_BOX:
        return None
    return f'0 {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}'


def place(src, dst):
    try:
        os.link(src, dst)   # same volume: no copy of ~2 GB of png
    except OSError:
        shutil.copy2(src, dst)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--src', type=Path, default=EFPDS, help='folder with train/ valid/ or their .tar.gz')
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--device', default='auto')
    args = parser.parse_args(argv)
    try:
        items = scan(extract(args.src))
    except (FormatError, FileNotFoundError) as e:
        print(f'[ERROR] {e}')
        return 1
    print(f'E-FPDS: {len(items)} images, {sum(len(b) for _, _, b in items)} boxes, format ok', flush=True)

    import cv2
    import torch
    from benchmark.legacy import select_device
    from benchmark.run_benchmark import Stage1, load_models, stage1_entry
    print('Hashing benchmark clip frames for the leakage filter...', flush=True)
    reference = clip_hashes()
    device = select_device(torch, args.device)
    teacher = Stage1(stage1_entry(load_models(), 'yolo11s'), device, TEACHER_CONF)

    if args.out.exists():
        shutil.rmtree(args.out)
    for split in SPLITS.values():
        (args.out / 'images' / split).mkdir(parents=True)
        (args.out / 'labels' / split).mkdir(parents=True)
    stats = {'images': {s: 0 for s in SPLITS.values()}, 'efpds_boxes': 0, 'teacher_boxes': 0,
             'dropped_small_boxes': 0, 'dropped_leakage': 0, 'leakage_examples': [], 'unreadable': 0}
    for i, (split, png, boxes) in enumerate(items, 1):
        image = cv2.imread(str(png))
        if image is None:
            stats['unreadable'] += 1
            continue
        if near_duplicates([dhash(image)], reference)[0]:
            stats['dropped_leakage'] += 1
            if len(stats['leakage_examples']) < 20:
                stats['leakage_examples'].append(png.relative_to(png.parents[2]).as_posix())
            continue
        h, w = image.shape[:2]
        gt = [list(b[1:]) for b in boxes]
        t_boxes, t_confs = teacher(image)
        extra = teacher_merge(gt, t_boxes, t_confs, TEACHER_CONF)
        lines = []
        for box in gt + extra:
            line = yolo_line(box, w, h)
            if line is None:
                stats['dropped_small_boxes'] += 1
            else:
                lines.append(line)
        stats['efpds_boxes'] += len(gt)
        stats['teacher_boxes'] += len(extra)
        name = f'{png.parent.name}_{png.stem}' if not png.stem.startswith(png.parent.name) else png.stem
        if (args.out / 'images' / split / f'{name}.png').exists():
            raise FormatError(f'two E-FPDS images map to {split}/{name}.png, e.g. {png}')
        place(png, args.out / 'images' / split / f'{name}.png')
        (args.out / 'labels' / split / f'{name}.txt').write_text('\n'.join(lines) + ('\n' if lines else ''),
                                                                 encoding='utf-8')
        stats['images'][split] += 1
        if i % 500 == 0:
            print(f'  {i}/{len(items)} images', flush=True)
    # No `path:` key: Ultralytics then resolves train/val against the folder of data.yaml, wherever it is unpacked.
    (args.out / 'data.yaml').write_text('train: images/train\nval: images/val\nnames:\n  0: person\n', encoding='utf-8')
    (args.out / 'stats.json').write_text(json.dumps(stats, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in stats.items() if k != 'leakage_examples'}))
    print(f'Wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
