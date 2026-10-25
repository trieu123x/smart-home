"""Run the fine-tune data prep and training on Kaggle: one private dataset, one notebook per step.

    --phase prep   notebook `fallguard-ft-prep`: cuts the CAUCAFall crops on Kaggle, where the public
                   8.3 GB dataset tuyenldvn/caucafall is attached directly (no local download)
    --phase train  notebooks `fallguard-ft-stage1` and `fallguard-ft-stage2`: fine-tune on both T4 GPUs (DDP)

    bundle  build benchmark/data/kaggle_ft/: the dataset `fallguard-finetune-v1` (code, pinned base weights,
            Ultralytics wheels and, for train, the stage1/ and stage2/ data) and the notebook folders
    push    upload the dataset (new version if it exists) and push the phase's notebooks (needs the kaggle CLI)
    status  show the run status of the phase's notebooks
    pull    prep: unpack the CAUCAFall crops into benchmark/data/finetune/stage2_caucafall/
            train: unpack best.pt into benchmark/weights/{yolo11s-ft,jerryg-ft3}/ and pin their sha256 in models.json

Credentials come from the kaggle CLI (KAGGLE_API_TOKEN or ~/.kaggle); nothing secret is bundled.

Usage (from `Fall detection/`):
    .venv/Scripts/python -I benchmark/finetune/kaggle_finetune.py bundle|push|status|pull --phase prep|train --user <u>
        [--steps stage1|stage2]   # train phase: one stage only, e.g. stage 1 while the stage-2 crops are not ready
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark.fetch_models import sha256_of, verify_file  # noqa: E402
from benchmark.finetune.common import DATA, assert_no_test_clips, check_class_floor, read_split  # noqa: E402
from benchmark.kaggle_bundle import BENCH_FILES, ULTRALYTICS, kaggle, upload_dataset  # noqa: E402

BENCH = ROOT / 'benchmark'
MODELS_JSON = BENCH / 'models.json'
OUT = BENCH / 'data' / 'kaggle_ft'
DATASET_SLUG = 'fallguard-finetune-v1'
CAUCAFALL = 'tuyenldvn/caucafall'
ARCHIVE = 'fallguard_ft.zip'
THOP = 'ultralytics-thop==2.2.3'   # pinned: these wheels run inside the sessions that produce the pinned weights
CODE_FILES = BENCH_FILES + ['contact_sheet.py', 'split.csv']
BASE_WEIGHTS = ['yolo11s', 'jerryg-v8x-cls', 'pose-rule-yolo11s']   # stage-1 base, stage-2 base, crop boxes
# kernel step -> (data prefix unpacked on Kaggle, output zip, weights id the pull writes)
STEPS = {
    'prep': (None, 'stage2_caucafall.zip', None),
    'stage1': ('benchmark/data/finetune/stage1/', 'ft_stage1.zip', 'yolo11s-ft'),
    'stage2': ('benchmark/data/finetune/stage2/', 'ft_stage2.zip', 'jerryg-ft3'),
}
PHASES = {'prep': ['prep'], 'train': ['stage1', 'stage2']}
PULLED_RUN_FILES = ('best.pt', 'results.csv', 'args.yaml')
CROP_NAME = re.compile(r'(train|val)/(fall|sit|normal)/[A-Za-z0-9_.-]+\.jpg|stats\.json')

NOTEBOOK_SETUP = r'''
import hashlib, os, shutil, subprocess, sys, zipfile
from pathlib import Path

STEP = {step!r}
DATA_PREFIX = {prefix!r}   # only this part of benchmark/data/ is unpacked
STAMP, WHEELS = {stamp!r}, {wheels!r}   # recorded by kaggle_finetune.py bundle; WHEELS: name -> sha256
INPUT, WORKING = Path('/kaggle/input'), Path('/kaggle/working')
ARCHIVE, MARKER = {archive!r}, f'00_bundle_{{STAMP}}.txt'

def wanted(name):
    return not name.startswith('benchmark/data/') or bool(DATA_PREFIX and name.startswith(DATA_PREFIX))

def own_root():
    # our dataset's mount, never a search over all of /kaggle/input: other attached datasets are third-party
    for d in (INPUT / {slug!r}, INPUT / 'datasets' / {user!r} / {slug!r}):   # mount path differs between Kaggle versions
        if (d / ARCHIVE).is_file() and MARKER in zipfile.ZipFile(d / ARCHIVE).namelist():
            return d
        if (d / Path(ARCHIVE).stem / MARKER).is_file():   # Kaggle unpacked the archive itself
            return d
    raise SystemExit(f'bundle {{STAMP}} not found under {{INPUT}}')

ROOT = own_root()
if (ROOT / ARCHIVE).is_file():
    SRC = WORKING / 'src'
    shutil.rmtree(SRC, ignore_errors=True)
    with zipfile.ZipFile(ROOT / ARCHIVE) as z:
        z.extractall(SRC, members=[n for n in z.namelist() if wanted(n)])
else:
    SRC = ROOT / Path(ARCHIVE).stem
print('project source:', SRC)
wheels = []
for name, digest in WHEELS.items():
    if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
        raise SystemExit(f'{{name}}: sha256 does not match the bundle')
    wheels.append(str(ROOT / name))
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', *wheels], check=True)
print(subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True).stdout)
ENV = {{**os.environ, 'YOLO_OFFLINE': 'true', 'YOLO_AUTOINSTALL': 'false'}}

def run(cmd):   # cwd must be writable: Ultralytics creates ./weights, and SRC may be the read-only input
    proc = subprocess.Popen(cmd, cwd=WORKING, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        print(line, end='', flush=True)
    if proc.wait():
        raise SystemExit(f'{{cmd[2]}} exited with {{proc.returncode}}')
'''

NOTEBOOK_PREP = r'''
root = next(p for p in INPUT.rglob('Subject.1') if p.is_dir()).parent
out = WORKING / 'stage2_caucafall'
run([sys.executable, '-I', str(SRC / 'benchmark/finetune/build_stage2_crops.py'), '--source', 'caucafall',
     '--caucafall-root', str(root), '--out', str(out), '--partial'])
shutil.make_archive(str(out), 'zip', out)
shutil.rmtree(out)
'''

NOTEBOOK_TRAIN = r'''
run([sys.executable, '-I', str(SRC / f'benchmark/finetune/train_{{STEP}}.py'), '--out', str(WORKING)])
for name in ('runs', 'weights'):   # keep only the zip as notebook output
    shutil.rmtree(WORKING / name, ignore_errors=True)
'''

NOTEBOOK_CLEANUP = r'''
shutil.rmtree(WORKING / 'src', ignore_errors=True)
for p in WORKING.glob('*.zip'):
    print(p, p.stat().st_size // 1024, 'KiB')
'''


def kernel_slug(step):
    return f'fallguard-ft-{step}'


def notebook(step, user, stamp, wheels):
    prefix, output, _ = STEPS[step]

    def cell(i, src):
        return {'cell_type': 'code', 'id': f'c{i}', 'metadata': {}, 'execution_count': None, 'outputs': [],
                'source': src.strip('\n').splitlines(keepends=True)}
    header = {'cell_type': 'markdown', 'id': 'c0', 'metadata': {},
              'source': [f'# FallGuard fine-tune: {step}\n',
                         f'Built by `benchmark/finetune/kaggle_finetune.py`. Output: `{output}`, unpacked locally by '
                         '`kaggle_finetune.py pull`.\n']}
    body = NOTEBOOK_PREP if step == 'prep' else NOTEBOOK_TRAIN
    fill = {'step': step, 'prefix': prefix, 'archive': ARCHIVE, 'stamp': stamp, 'wheels': wheels, 'user': user,
            'slug': DATASET_SLUG}
    return {'nbformat': 4, 'nbformat_minor': 5,
            'metadata': {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'},
                         'language_info': {'name': 'python'}},
            'cells': [header] + [cell(i, c.format(**fill))
                                 for i, c in enumerate((NOTEBOOK_SETUP, body, NOTEBOOK_CLEANUP), 1)]}


def base_weights(models):
    """Paths of the pinned base weights, each checked against models.json before upload."""
    entries = {e['id']: e for e in models['stage1'] + models['candidates']}
    paths = []
    for wid in BASE_WEIGHTS:
        f = entries[wid]['files'][0]
        path = BENCH / 'weights' / wid / f['path']
        if not path.is_file():
            sys.exit(f'missing weights {path} (run fetch_models.py)')
        verify_file(path, f.get('sha256'))
        paths.append(path)
    return paths


def training_data(steps):
    """Files of stage1/ and/or stage2/ for the given steps, after the leakage and class-floor guards."""
    stage1, stage2 = DATA / 'stage1', DATA / 'stage2'
    files = []
    if 'stage1' in steps:
        if not (stage1 / 'data.yaml').is_file():
            sys.exit(f'{stage1} is not built (run prepare_stage1.py)')
        files += [p for p in sorted(stage1.rglob('*')) if p.is_file() and p.suffix != '.cache']
    if 'stage2' not in steps:
        return files
    stats_path = stage2 / 'stats.json'
    if not stats_path.is_file():
        sys.exit(f'{stage2} is not built (run build_stage2_crops.py)')
    stats = json.loads(stats_path.read_text(encoding='utf-8'))
    assert_no_test_clips(stats['origins'], read_split())
    assert_no_test_clips({p.stem.split('__', 1)[0] for p in stage2.rglob('*.jpg')}, read_split())
    check_class_floor(stats['train'])
    return files + [p for p in sorted(stage2.rglob('*')) if p.is_file()]


def bundle(user, phase, steps):
    models = json.loads(MODELS_JSON.read_text(encoding='utf-8'))
    files = [BENCH / name for name in CODE_FILES] + sorted((BENCH / 'finetune').glob('*.py'))
    files += base_weights(models)
    if phase == 'train':
        files += training_data(steps)
    dataset_dir = OUT / 'dataset'
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True)
    stamp = time.strftime('%Y%m%dT%H%M%S')
    with zipfile.ZipFile(dataset_dir / ARCHIVE, 'w', zipfile.ZIP_STORED) as z:   # png/jpg/pt are compressed
        z.writestr(f'00_bundle_{stamp}.txt', f'{phase} {",".join(steps)}\n')   # sorts first in the file listing
        for p in files:
            z.write(p, p.relative_to(ROOT).as_posix())
    (OUT / 'bundle_stamp.txt').write_text(stamp, encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'pip', 'download', '-q', '--no-deps', '-d', str(dataset_dir),
                    ULTRALYTICS, THOP], check=True)
    wheels = {p.name: sha256_of(p) for p in sorted(dataset_dir.glob('*.whl'))}
    (dataset_dir / 'dataset-metadata.json').write_text(json.dumps(
        {'title': DATASET_SLUG, 'id': f'{user}/{DATASET_SLUG}', 'licenses': [{'name': 'other'}]}, indent=2))
    for step in steps:
        kdir = OUT / f'kernel_{step}'
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / 'fallguard_ft.ipynb').write_text(json.dumps(notebook(step, user, stamp, wheels), indent=1),
                                                 encoding='utf-8')
        sources = [f'{user}/{DATASET_SLUG}'] + ([CAUCAFALL] if step == 'prep' else [])
        (kdir / 'kernel-metadata.json').write_text(json.dumps({
            'id': f'{user}/{kernel_slug(step)}', 'title': kernel_slug(step),
            'code_file': 'fallguard_ft.ipynb', 'language': 'python', 'kernel_type': 'notebook',
            'is_private': True, 'enable_gpu': True, 'enable_internet': False,
            'dataset_sources': sources, 'competition_sources': [], 'kernel_sources': []}, indent=2))
    size = sum(p.stat().st_size for p in dataset_dir.iterdir()) / 2**20
    print(f'Bundled {len(files)} files: {dataset_dir} ({size:.0f} MiB), notebooks for {", ".join(steps)}')


def wait_for_version(user, stamp, tries=60):
    """`datasets status` already says ready for the previous version right after an upload, and a notebook
    pushed then mounts that old version. Wait until the new bundle's stamp file is listed."""
    for _ in range(tries):
        listing = kaggle('datasets', 'files', f'{user}/{DATASET_SLUG}', '--page-size', '5', check=False)
        if f'00_bundle_{stamp}' in (listing.stdout or ''):
            return
        print(f'  waiting for bundle {stamp} to be live; 30 s', flush=True)
        time.sleep(30)
    sys.exit(f'bundle {stamp} is not live after {tries // 2} min; rerun push --skip-dataset later')


def push(user, steps, accelerator, skip_dataset=False):
    upload_dataset(user, DATASET_SLUG, OUT / 'dataset', skip_dataset)
    if not skip_dataset:
        wait_for_version(user, (OUT / 'bundle_stamp.txt').read_text(encoding='utf-8').strip())
    for step in steps:
        kaggle('kernels', 'push', '-p', '.', '--accelerator', accelerator, cwd=OUT / f'kernel_{step}')


def status(user, steps):
    for step in steps:
        done = kaggle('kernels', 'status', f'{user}/{kernel_slug(step)}', check=False)
        print((done.stdout or done.stderr or '').strip())


def safe_extract(zip_path, dest, allowed):
    """Extract members whose name fully matches `allowed` (a regex); anything else fails before writing."""
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if not n.endswith('/')]
        bad = [n for n in names if not allowed.fullmatch(n)]
        if bad:
            raise ValueError(f'unexpected or unsafe path in {zip_path.name}: {bad[:3]}')
        for n in names:
            target = dest / n
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(n))
    return len(names)


def pin_local(models, wid, digest):
    """Pin the pulled file's sha256 and mark the entry available."""
    entry = next(e for e in models['stage1'] + models['candidates'] if e['id'] == wid)
    entry['files'][0]['sha256'] = digest
    entry.pop('status', None)
    return entry


def pull(user, steps):
    models = json.loads(MODELS_JSON.read_text(encoding='utf-8'))
    pinned = False
    for step in steps:
        _, output, wid = STEPS[step]
        dest = OUT / f'output_{step}'
        shutil.rmtree(dest, ignore_errors=True)   # the CLI skips files it thinks are up to date
        # Only the expected zip: the CLI joins output file names onto -p unchecked.
        kaggle('kernels', 'output', f'{user}/{kernel_slug(step)}', '-p', str(dest), '-o',
               '--file-pattern', f'^{re.escape(output)}$', check=False)
        archive = dest / output
        if not archive.is_file():
            print(f'[WARN] no {output} yet for {step}')
            continue
        if step == 'prep':
            target = DATA / 'stage2_caucafall'
            shutil.rmtree(target, ignore_errors=True)
            n = safe_extract(archive, target, CROP_NAME)
            print(f'[OK] {step}: {n} files -> {target}')
            continue
        target = BENCH / 'weights' / wid
        with zipfile.ZipFile(archive) as z:
            if 'best.pt' not in z.namelist():
                raise ValueError(f'{output} has no best.pt')
        shutil.rmtree(target, ignore_errors=True)   # a stale best.pt must never be the file that gets pinned
        n = safe_extract(archive, target, re.compile('|'.join(re.escape(f) for f in PULLED_RUN_FILES)))
        digest = sha256_of(target / 'best.pt')
        pin_local(models, wid, digest)
        pinned = True
        print(f'[OK] {step}: {n} files -> {target}; best.pt sha256={digest}')
    if pinned:
        MODELS_JSON.write_text(json.dumps(models, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        print('[PIN] models.json updated')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['bundle', 'push', 'status', 'pull'])
    parser.add_argument('--phase', choices=list(PHASES), required=True)
    parser.add_argument('--user', required=True, help='Kaggle username that owns the dataset and notebooks')
    parser.add_argument('--accelerator', default='NvidiaTeslaT4')
    parser.add_argument('--skip-dataset', action='store_true', help='push: only push the notebooks')
    parser.add_argument('--steps', default='', help='train phase: only these steps, e.g. stage1 (default: all)')
    args = parser.parse_args(argv)
    steps = [s for s in args.steps.split(',') if s] or PHASES[args.phase]
    if any(s not in PHASES[args.phase] for s in steps):
        parser.error(f"--steps must be from {', '.join(PHASES[args.phase])}")
    {'bundle': lambda: bundle(args.user, args.phase, steps),
     'push': lambda: push(args.user, steps, args.accelerator, args.skip_dataset),
     'status': lambda: status(args.user, steps), 'pull': lambda: pull(args.user, steps)}[args.command]()
    return 0


if __name__ == '__main__':
    sys.exit(main())
