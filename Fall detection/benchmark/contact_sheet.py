"""Timestamped frame grids for checking by-eye labels.

Writes results/sheets/<clip_id>.jpg (and <clip_id>_p2.jpg ... for long clips). Frames inside the
labelled fall interval are tinted red, frames in the +-0.5 s ignore window yellow.

Usage (from `Fall detection/`):
    .venv/Scripts/python -I benchmark/contact_sheet.py [--clips id1,id2] [--source youtube] [--step 0.5]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark import frames as fr  # noqa: E402

SHEETS = ROOT / 'benchmark' / 'results' / 'sheets'
THUMB_W, COLS, PER_PAGE = 240, 8, 96
TINT = {'fall': (0, 0, 255), 'ignore': (0, 220, 255)}   # BGR


def thumbnail(frame, t, label):
    import cv2
    h, w = frame.shape[:2]
    thumb = cv2.resize(frame, (THUMB_W, max(1, round(h * THUMB_W / w))))
    if label in TINT:
        overlay = thumb.copy()
        overlay[:] = TINT[label]
        thumb = cv2.addWeighted(thumb, 0.7, overlay, 0.3, 0)
        cv2.rectangle(thumb, (0, 0), (thumb.shape[1] - 1, thumb.shape[0] - 1), TINT[label], 3)
    cv2.rectangle(thumb, (0, 0), (92, 22), (0, 0, 0), -1)
    cv2.putText(thumb, f't={t:.1f}s', (4, 16), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 255, 255), 1)
    return thumb


def grid(thumbs):
    import numpy as np
    h = max(t.shape[0] for t in thumbs)
    rows = []
    for i in range(0, len(thumbs), COLS):
        row = [np.pad(t, ((0, h - t.shape[0]), (0, 0), (0, 0))) for t in thumbs[i:i + COLS]]
        row += [np.zeros_like(row[0])] * (COLS - len(row))
        rows.append(np.hstack(row))
    return np.vstack(rows)


def sheet(row, path, step):
    """Write the pages for one clip; return their paths."""
    import cv2
    thumbs = [thumbnail(frame, t, fr.label_at(t, row)) for t, frame in fr.iter_frames(path, step)]
    if not thumbs:
        raise RuntimeError(f'no frames decoded from {path}')
    SHEETS.mkdir(parents=True, exist_ok=True)
    out = []
    for page, start in enumerate(range(0, len(thumbs), PER_PAGE), 1):
        dst = SHEETS / (f"{row['clip_id']}.jpg" if page == 1 else f"{row['clip_id']}_p{page}.jpg")
        cv2.imwrite(str(dst), grid(thumbs[start:start + PER_PAGE]), [cv2.IMWRITE_JPEG_QUALITY, 85])
        out.append(dst)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--clips', default='', help='comma-separated clip ids (default: all fetched)')
    parser.add_argument('--source', default='', help='only rows with this source, e.g. youtube')
    parser.add_argument('--step', type=float, default=0.5)
    args = parser.parse_args(argv)
    wanted = {c for c in args.clips.split(',') if c}
    rows = [r for r in fr.read_manifest() if (not wanted or r['clip_id'] in wanted)
            and (not args.source or r['source'].lower() == args.source.lower())]
    failed = 0
    for row in rows:
        path = fr.CLIPS / f"{row['clip_id']}.mp4"
        if not path.is_file():
            print(f"[SKIP] {row['clip_id']}: not fetched")
            failed += bool(wanted)
            continue
        try:
            pages = sheet(row, path, args.step)
            print(f"[OK] {row['clip_id']}: {', '.join(p.name for p in pages)}", flush=True)
        except Exception as e:   # one bad file must not stop the others
            failed += 1
            print(f"[FAIL] {row['clip_id']}: {type(e).__name__}: {str(e)[:200]}", flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
