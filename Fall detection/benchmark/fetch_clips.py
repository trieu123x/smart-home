"""Download every manifest.csv row and trim it into benchmark/data/clips/<clip_id>.mp4.

Video sites go through yt-dlp with a single-file mp4 format (no ffmpeg needed). Direct
dataset files use HTTPS; `url#member=path/in.zip` extracts one member of a zip archive.
Existing clips are skipped.

Usage (from `Fall detection/`): .venv/Scripts/python -I benchmark/fetch_clips.py [--only c1,c2]
"""
import argparse
import hashlib
import sys
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark.fetch_models import MAX_BYTES, download  # noqa: E402
from benchmark.frames import CLIPS, MAX_SECONDS, is_long, is_short, read_manifest, source_group  # noqa: E402

RAW = CLIPS.parent / 'raw'
DIRECT_EXT = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.mpg', '.zip')
# Single files only (no ffmpeg merge). YouTube often has no muxed mp4 left; video-only H.264 is
# enough (no audio needed) and OpenCV decodes it reliably, unlike AV1.
YTDLP_FORMAT = ('b[ext=mp4][height<=720][protocol^=https]/bv[ext=mp4][vcodec^=avc1][height<=720][protocol^=https]/'
                'bv[ext=mp4][vcodec^=avc1][protocol^=https]/b[ext=mp4][protocol^=https]')
MIN_CLIPS, MIN_FALL, MIN_REAL_FALL, MIN_NONFALL, MIN_LONG_SECONDS = 35, 20, 10, 10, 300


def raw_key(url):
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def finished(key):
    """Complete raw files for a key; yt-dlp leaves .part/.ytdl files when interrupted."""
    return sorted(p for p in RAW.glob(f'{key}.*') if not p.name.endswith(('.part', '.ytdl')))


def fetch_raw(url):
    """Return the local path of the untrimmed source; downloads once per URL."""
    base, _, fragment = url.partition('#')
    member = urllib.parse.parse_qs(fragment).get('member', [None])[0]
    key = raw_key(base)
    RAW.mkdir(parents=True, exist_ok=True)
    if urllib.parse.urlparse(base).path.lower().endswith(DIRECT_EXT):
        src = RAW / f'{key}{Path(urllib.parse.urlparse(base).path).suffix.lower()}'
        if not src.is_file():
            download(base, src, timeout=120)
        if member is None:
            return src
        out = RAW / f'{key}_{raw_key(member)}{Path(member).suffix.lower()}'
        if not out.is_file():
            with zipfile.ZipFile(src) as archive:
                if archive.getinfo(member).file_size > MAX_BYTES:
                    raise ValueError(f'zip member too large: {member}')
            with zipfile.ZipFile(src) as archive, archive.open(member) as f_in, open(out, 'wb') as f_out:
                while chunk := f_in.read(1 << 20):   # written under our own name: no zip-slip
                    f_out.write(chunk)
        return out
    existing = finished(key)
    if existing:
        return existing[0]
    if urllib.parse.urlparse(base).scheme != 'https':
        raise ValueError(f'only https URLs are fetched: {base}')
    from yt_dlp import YoutubeDL
    options = {'format': YTDLP_FORMAT, 'outtmpl': str(RAW / f'{key}.%(ext)s'), 'noplaylist': True,
               'quiet': True, 'no_warnings': True, 'noprogress': True, 'max_filesize': MAX_BYTES}
    with YoutubeDL(options) as ydl:
        ydl.download([base])
    existing = finished(key)
    if not existing:
        raise RuntimeError('yt-dlp produced no file')
    return existing[0]


def crop_side(row):
    """`crop=left|right` in notes keeps one half (URFD files put depth and RGB side by side)."""
    for token in (row.get('notes') or '').replace(';', ' ').split():
        if token.startswith('crop='):
            side = token.split('=', 1)[1]
            if side not in ('left', 'right'):
                raise ValueError(f'unknown crop: {token}')
            return side
    return None


def trim(src, dst, start, end, crop=None):
    """Copy [start, end] of src to a constant-fps mp4, placing frames by their timestamps (VFR safe)."""
    import cv2
    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise OSError(f'cannot open {src}')
    fps = cap.get(cv2.CAP_PROP_FPS)
    fps = fps if 1 <= fps <= 120 else 30.0
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    part = dst.with_name(dst.stem + '.part.mp4')
    writer, written = None, 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if ts < start - 1e-3:
                continue
            if (end is not None and ts > end) or ts - start > MAX_SECONDS:
                break
            if crop:
                half = frame.shape[1] // 2
                frame = frame[:, half:] if crop == 'right' else frame[:, :half]
            if writer is None:
                h, w = frame.shape[:2]
                writer = cv2.VideoWriter(str(part), cv2.VideoWriter_fourcc(*'mp4v'), fps, (w, h))
            while start + written / fps <= ts + 0.5 / fps and written < MAX_SECONDS * fps:   # fill VFR gaps
                writer.write(frame)
                written += 1
    finally:
        cap.release()
        if writer is not None:
            writer.release()
    if not written:
        part.unlink(missing_ok=True)
        raise RuntimeError(f'no frames between {start}s and {end}s')
    part.replace(dst)
    return written / fps


def clip_seconds(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        return cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps > 0 else 0.0   # our own constant-fps output
    finally:
        cap.release()


def availability(have, seconds):
    """Counts checked against the v2 minimums; returns (lines, ok). A missing long clip only warns:
    the report then computes false alarms per hour over all non-fall footage."""
    falls = [r for r in have if r['is_fall'] == '1' and not is_short(r)]
    real = [r for r in falls if source_group(r) == 'real']
    nonfall = [r for r in have if r['is_fall'] != '1']
    long_s = sum(seconds.get(r['clip_id'], 0.0) for r in nonfall if is_long(r))
    checks = [('clips', len(have), MIN_CLIPS), ('event fall', len(falls), MIN_FALL),
              ('real fall', len(real), MIN_REAL_FALL), ('non-fall', len(nonfall), MIN_NONFALL)]
    lines = ['Available: ' + ', '.join(f'{name}={n} (need >= {need})' for name, n, need in checks)]
    lines.append(f'Long non-fall: {long_s / 60:.1f} min (need >= {MIN_LONG_SECONDS / 60:g})'
                 + ('' if long_s >= MIN_LONG_SECONDS else ' [WARN] FA/h falls back to all non-fall footage'))
    return lines, all(n >= need for _, n, need in checks)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', default='', help='comma-separated clip ids')
    args = parser.parse_args(argv)
    only = {c for c in args.only.split(',') if c}
    rows = [r for r in read_manifest() if not only or r['clip_id'] in only]
    CLIPS.mkdir(parents=True, exist_ok=True)
    ok, failed, skipped, seconds = [], [], [], {}
    for row in rows:
        dst = CLIPS / f"{row['clip_id']}.mp4"
        if dst.is_file():
            skipped.append(row)
            seconds[row['clip_id']] = clip_seconds(dst)
            continue
        try:
            src = fetch_raw(row['url'])
            start = float(row['start_s'] or 0)
            end = float(row['end_s']) if row['end_s'] else None
            seconds[row['clip_id']] = trim(src, dst, start, end, crop_side(row))
            ok.append(row)
            print(f"[OK] {row['clip_id']}: {seconds[row['clip_id']]:.1f}s", flush=True)
        except Exception as e:   # a dead URL must not stop the others
            failed.append(row)
            print(f"[FAIL] {row['clip_id']}: {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f'Summary: OK={len(ok)} failed={len(failed)} skipped(existing)={len(skipped)}')
    lines, enough = availability(ok + skipped, seconds)
    print('\n'.join(lines))
    if failed:
        print('Failed clips: ' + ', '.join(r['clip_id'] for r in failed))
    if only:   # a partial fetch is judged on its own rows, not on the set minimums
        return 1 if failed else 0
    return 0 if enough else 1


if __name__ == '__main__':
    sys.exit(main())
