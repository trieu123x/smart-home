"""Run the accuracy part of the benchmark on Kaggle GPUs: one private dataset, one notebook per stage-1 variant.

    bundle  build benchmark/data/kaggle/: a private dataset (code, clips, pinned weights, Ultralytics wheels)
            and one notebook folder per stage-1 variant
    push    upload the dataset (new version if it exists) and push the notebooks (needs the kaggle CLI)
    status  show the notebook run status
    pull    download notebook outputs and merge them into benchmark/results/, then run --report-only locally

Latency is not measured on Kaggle (--latency-runs 0); the 200 ms rule needs the deployment GPU.
Credentials come from the kaggle CLI (KAGGLE_API_TOKEN or ~/.kaggle); nothing secret is bundled:
the benchmark is self-contained (benchmark/legacy.py), so no fallguard/ file and never the project .env.

Usage (from `Fall detection/`): .venv/Scripts/python -I benchmark/kaggle_bundle.py bundle|push|status|pull --user <kaggle user>
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / 'benchmark'
OUT = BENCH / 'data' / 'kaggle'
DATASET_SLUG = 'fallguard-benchmark-v3'
KERNEL_PREFIX = 'fallguard-bench'
VARIANTS = ('prod', 'lowconf', 'pose')
ULTRALYTICS = 'ultralytics==8.4.184'   # same version as the local .venv
BENCH_FILES = ['__init__.py', 'adapters.py', 'fetch_models.py', 'frames.py', 'legacy.py', 'metrics.py',
               'run_benchmark.py', 'models.json', 'manifest.csv']   # self-contained: no fallguard/ module is needed
KAGGLE = Path(sys.executable).with_name('kaggle.exe' if sys.platform == 'win32' else 'kaggle')

NOTEBOOK_CODE = r'''
import csv, io, os, shutil, subprocess, sys, threading, zipfile
from pathlib import Path

VARIANT = {variant!r}
GROUPS = {groups!r}   # one candidate group per GPU, balanced by measured scoring time
INPUT = Path('/kaggle/input')   # the mount path of a dataset changes between Kaggle versions: search it
WORKING = Path('/kaggle/working')

archive = next(INPUT.rglob('fallguard_bench.zip'), None)
if archive:   # not extracted by Kaggle: unpack once and use that as the source tree
    SRC = WORKING / 'src'
    shutil.rmtree(SRC, ignore_errors=True)
    with zipfile.ZipFile(archive) as z:
        z.extractall(SRC)
else:
    SRC = next(INPUT.rglob('run_benchmark.py')).parent.parent
print('project source:', SRC)

def workdir(i):
    """Code copy per process (own results/); clips and weights are symlinked from the read-only input."""
    work = WORKING / f'fd{{i}}'
    shutil.rmtree(work, ignore_errors=True)
    shutil.copytree(SRC / 'benchmark', work / 'benchmark', ignore=shutil.ignore_patterns('data', 'weights'))
    (work / 'benchmark' / 'data').mkdir()
    (work / 'benchmark' / 'data' / 'clips').symlink_to(SRC / 'benchmark' / 'data' / 'clips')
    (work / 'benchmark' / 'weights').symlink_to(SRC / 'benchmark' / 'weights')
    return work

wheels = sorted(str(p) for p in INPUT.rglob('*.whl'))
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '--no-deps', *wheels], check=True)
gpus = subprocess.run(['nvidia-smi', '-L'], capture_output=True, text=True).stdout.strip().splitlines()
print('\n'.join(gpus))
'''

NOTEBOOK_RUN = r'''
def run(i, models, gpu):
    cmd = [sys.executable, '-I', 'benchmark/run_benchmark.py', '--stage1-variants', VARIANT, '--latency-runs', '0',
           '--models', ','.join(models)]
    env = {{**os.environ, 'CUDA_VISIBLE_DEVICES': str(gpu)}}   # select_device only takes cuda:0
    proc = subprocess.Popen(cmd, cwd=workdir(i), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in proc.stdout:
        print(f'[gpu{{gpu}}] {{line}}', end='', flush=True)
    codes[i] = proc.wait()

codes = {{}}
if len(gpus) >= 2:
    threads = [threading.Thread(target=run, args=(i, g, i)) for i, g in enumerate(GROUPS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
else:   # a single GPU: same groups, one after the other
    for i, g in enumerate(GROUPS):
        run(i, g, 0)
assert all(c == 0 for c in codes.values()), f'run_benchmark exit codes: {{codes}}'
'''

NOTEBOOK_SAVE = r'''
out = WORKING / f'results_{{VARIANT}}.zip'
runs, fields = {{}}, None
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for i in range(len(GROUPS)):
        results = WORKING / f'fd{{i}}' / 'benchmark' / 'results'
        for p in results.rglob('*'):
            if p.is_file() and (p.name.startswith(('frames_', 'events_')) or 'failures' in p.parts):
                z.write(p, p.relative_to(results))
        with open(results / 'runs.csv', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            runs.update({{(r['model'], r['stage1_variant']): r for r in reader}})
    buf = io.StringIO()   # error messages may contain commas: let csv quote them
    writer = csv.DictWriter(buf, fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows(runs.values())
    z.writestr('runs.csv', buf.getvalue())
for i in range(len(GROUPS)):
    shutil.rmtree(WORKING / f'fd{{i}}')   # keep only the zip as notebook output
shutil.rmtree(WORKING / 'src', ignore_errors=True)
print(out, out.stat().st_size // 1024, 'KiB;', len(runs), 'runs rows')
'''

# Scoring minutes per candidate measured locally on the 40-clip set (stage 1 prod): YOLO11x on crowded frames
# dominates. Used only to split candidates over the two GPUs of a Kaggle session.
COST = {'leeyunjai-11x': 25, 'khoa05ai-v8m': 8, 'pose-rule-yolo11s': 8, 'jerryg-v8x-cls': 6}


def is_local(entry):
    """Fine-tuned weights produced by finetune/ (`local: true`); the v3 accuracy run leaves them out."""
    return any(f.get('local') for f in entry['files'])


def gpu_groups(candidates, n=2):
    """Greedy split of the runnable candidates into n groups with similar total cost."""
    groups, load = [[] for _ in range(n)], [0] * n
    for c in sorted((c for c in candidates if c.get('status') != 'missing' and not is_local(c)),
                    key=lambda c: -COST.get(c['id'], 5)):
        i = load.index(min(load))
        groups[i].append(c['id'])
        load[i] += COST.get(c['id'], 5)
    return groups


def notebook(variant, groups):
    def cell(i, src):
        return {'cell_type': 'code', 'id': f'c{i}', 'metadata': {}, 'execution_count': None, 'outputs': [],
                'source': src.strip('\n').splitlines(keepends=True)}
    header = {'cell_type': 'markdown', 'id': 'c0', 'metadata': {},
              'source': [f'# FallGuard benchmark: stage 1 `{variant}`\n',
                         'Accuracy only (`--latency-runs 0`), candidates split over the 2 GPUs. Output: '
                         '`results_<variant>.zip`, merged locally by `kaggle_bundle.py pull`.\n']}
    fill = {'variant': variant, 'groups': groups}
    return {'nbformat': 4, 'nbformat_minor': 5,
            'metadata': {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'},
                         'language_info': {'name': 'python'}},
            'cells': [header] + [cell(i, c.format(**fill))
                                 for i, c in enumerate((NOTEBOOK_CODE, NOTEBOOK_RUN, NOTEBOOK_SAVE), 1)]}


def kaggle(*args, check=True, cwd=None):
    if not KAGGLE.is_file():
        sys.exit(f'kaggle CLI not found next to {sys.executable}; pip install kaggle into the .venv first')
    print('$ kaggle ' + ' '.join(args), flush=True)
    return subprocess.run([str(KAGGLE), *args], check=check, text=True, capture_output=not check, cwd=cwd)


def bundle(user):
    clips = sorted((BENCH / 'data' / 'clips').glob('*.mp4'))
    if not clips:
        sys.exit('no clips in benchmark/data/clips (run fetch_clips.py)')
    models = json.loads((BENCH / 'models.json').read_text(encoding='utf-8'))
    weights = []
    for entry in models['stage1'] + models['candidates']:
        for f in entry['files']:
            path = BENCH / 'weights' / entry['id'] / f['path']
            if entry.get('status') != 'missing' and not is_local(entry):   # fine-tuned weights are not v3
                if not path.is_file():
                    sys.exit(f'missing weights {path} (run fetch_models.py)')
                weights.append(path)
    dataset_dir = OUT / 'dataset'
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True)
    with zipfile.ZipFile(dataset_dir / 'fallguard_bench.zip', 'w', zipfile.ZIP_STORED) as z:   # mp4/pt are compressed
        for name in BENCH_FILES:
            z.write(BENCH / name, f'benchmark/{name}')
        for p in clips + weights:
            z.write(p, p.relative_to(ROOT).as_posix())
    subprocess.run([sys.executable, '-m', 'pip', 'download', '-q', '--no-deps', '-d', str(dataset_dir),
                    ULTRALYTICS, 'ultralytics-thop'], check=True)
    (dataset_dir / 'dataset-metadata.json').write_text(json.dumps(
        {'title': DATASET_SLUG, 'id': f'{user}/{DATASET_SLUG}', 'licenses': [{'name': 'other'}]}, indent=2))
    for variant in VARIANTS:
        kdir = OUT / f'kernel_{variant}'
        kdir.mkdir(parents=True, exist_ok=True)
        (kdir / 'fallguard_bench.ipynb').write_text(json.dumps(notebook(variant, gpu_groups(models['candidates'])),
                                                               indent=1),
                                                    encoding='utf-8')
        (kdir / 'kernel-metadata.json').write_text(json.dumps({
            'id': f'{user}/{KERNEL_PREFIX}-{variant}', 'title': f'{KERNEL_PREFIX}-{variant}',
            'code_file': 'fallguard_bench.ipynb', 'language': 'python', 'kernel_type': 'notebook',
            'is_private': True, 'enable_gpu': True, 'enable_internet': False,
            'dataset_sources': [f'{user}/{DATASET_SLUG}'], 'competition_sources': [], 'kernel_sources': []},
            indent=2))
    size = sum(p.stat().st_size for p in dataset_dir.iterdir()) / 2**20
    print(f'Bundled {len(clips)} clips, {len(weights)} weight files: {dataset_dir} ({size:.0f} MiB), '
          f'notebooks for {", ".join(VARIANTS)}')


def upload_dataset(user, slug, dataset_dir, skip=False):
    """Create or version the private dataset `user/slug` from dataset_dir, then wait until it is ready."""
    # The CLI keeps resumable-upload state under %TEMP%/.kaggle/uploads and puts the -p folder into that file
    # name, so it breaks on a nested relative path. Create the folder and upload from inside with -p .
    (Path(tempfile.gettempdir()) / '.kaggle' / 'uploads').mkdir(parents=True, exist_ok=True)
    exists = kaggle('datasets', 'status', f'{user}/{slug}', check=False)
    # check=False on create/version: CLI 1.8 can fail to parse the reply after a successful upload;
    # the status loop below is what decides whether the dataset is usable.
    if skip:
        pass
    elif exists.returncode == 0 and 'ready' in (exists.stdout or '').lower():
        kaggle('datasets', 'version', '-p', '.', '-m', 'update', '-r', 'skip', cwd=dataset_dir, check=False)
    else:
        kaggle('datasets', 'create', '-p', '.', '-r', 'skip', cwd=dataset_dir, check=False)   # private by default
    for _ in range(60):   # notebooks fail to mount a dataset that is still processing
        state = kaggle('datasets', 'status', f'{user}/{slug}', check=False)
        if 'ready' in (state.stdout or '').lower():
            break
        print(f'  dataset status: {(state.stdout or state.stderr or "").strip()}; waiting 30 s', flush=True)
        time.sleep(30)
    else:
        sys.exit('dataset is not ready after 30 min; rerun push later')


def push(user, accelerator, skip_dataset=False):
    upload_dataset(user, DATASET_SLUG, OUT / 'dataset', skip_dataset)
    for variant in VARIANTS:
        kaggle('kernels', 'push', '-p', '.', '--accelerator', accelerator, cwd=OUT / f'kernel_{variant}')


def status(user):
    for variant in VARIANTS:
        done = kaggle('kernels', 'status', f'{user}/{KERNEL_PREFIX}-{variant}', check=False)
        print((done.stdout or done.stderr or '').strip())


def merge_results(zip_path, variant, results):
    """Copy one variant's per-pipeline files into results/ and upsert its runs.csv rows."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        runs = list(csv.DictReader(z.read('runs.csv').decode('utf-8').splitlines())) if 'runs.csv' in names else []
        wanted = [n for n in names if Path(n).match(f'frames_*@{variant}.csv') or Path(n).match(f'events_*@{variant}@*.csv')
                  or (n.startswith('failures/') and f'@{variant}/' in n)]
        for n in wanted:
            dest = (results / n).resolve()
            if not dest.is_relative_to(results.resolve()):   # no zip-slip from a downloaded archive
                raise ValueError(f'unsafe path in {zip_path.name}: {n}')
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(n))
    runs = [r for r in runs if r.get('stage1_variant') == variant]
    path = results / 'runs.csv'
    old = list(csv.DictReader(path.open(encoding='utf-8'))) if path.is_file() else []
    fields = list(old[0]) if old else list(runs[0]) if runs else []
    merged = {(r['model'], r['stage1_variant']): r for r in old}
    merged.update({(r['model'], r['stage1_variant']): r for r in runs})
    if fields:
        with path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fields, extrasaction='ignore')
            w.writeheader()
            w.writerows(merged.values())
    return len(wanted), len(runs)


def pull(user):
    results = BENCH / 'results'
    for variant in VARIANTS:
        dest = OUT / f'output_{variant}'
        kaggle('kernels', 'output', f'{user}/{KERNEL_PREFIX}-{variant}', '-p', str(dest), check=False)
        zips = list(dest.glob(f'results_{variant}.zip'))
        if not zips:
            print(f'[WARN] no results_{variant}.zip yet for {variant}')
            continue
        files, runs = merge_results(zips[0], variant, results)
        print(f'[OK] {variant}: {files} files, {runs} runs rows merged')
    subprocess.run([sys.executable, '-I', str(BENCH / 'run_benchmark.py'), '--report-only'], check=True, cwd=ROOT)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=['bundle', 'push', 'status', 'pull'])
    parser.add_argument('--user', required=True, help='Kaggle username that owns the dataset and notebooks')
    parser.add_argument('--accelerator', default='NvidiaTeslaT4')
    parser.add_argument('--skip-dataset', action='store_true', help='push: only push the notebooks')
    args = parser.parse_args(argv)
    {'bundle': lambda: bundle(args.user), 'push': lambda: push(args.user, args.accelerator, args.skip_dataset),
     'status': lambda: status(args.user), 'pull': lambda: pull(args.user)}[args.command]()
    return 0


if __name__ == '__main__':
    sys.exit(main())
