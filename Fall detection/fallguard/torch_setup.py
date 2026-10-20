"""Install/check PyTorch for FallGuard on Windows (CUDA when available).

Runs in the project's virtual environment; does not need Administrator rights.
Never touches the project's YOLO weight files.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROBE_PREFIX = 'FALLGUARD_TORCH=' 
PROBE_CODE = r'''
import json
result = {'installed': False, 'cuda_ready': False, 'cuda_build': None,
          'torch_version': None, 'torchvision': None, 'gpu_name': None, 'error': None}
try:
    import torch
    result['torch_version'] = torch.__version__
    result['cuda_build'] = torch.version.cuda
    import torchvision
    result['torchvision'] = torchvision.__version__
    result['installed'] = True
    if torch.cuda.is_available():
        try:
            torch.zeros((2, 2), device='cuda:0').add_(1)
            torch.cuda.synchronize()
            result['cuda_ready'] = True
            result['gpu_name'] = torch.cuda.get_device_name(0)
        except Exception as e:
            result['error'] = str(e)
except Exception as e:
    result['error'] = str(e)
print('FALLGUARD_TORCH=' + json.dumps(result, ensure_ascii=False))
'''


def setting(key, default=''):
    # Parser already used by the main application. Never echo .env secrets.
    from .telegram_config import _settings
    import os
    return os.environ.get(key, _settings.get(key, default)).strip()


def nvidia_gpu():
    try:
        proc = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'],
                              capture_output=True, text=True, timeout=10, check=False)
        return proc.stdout.strip().splitlines()[0].strip() if proc.returncode == 0 and proc.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def probe():
    proc = subprocess.run([sys.executable, '-c', PROBE_CODE], capture_output=True,
                          text=True, timeout=60, check=False)
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith(PROBE_PREFIX):
            return json.loads(line[len(PROBE_PREFIX):])
    return {'installed': False, 'cuda_ready': False, 'cuda_build': None,
            'torch_version': None, 'torchvision': None, 'gpu_name': None,
            'error': (proc.stderr or proc.stdout or 'Khong the tai torch')[-500:]}


def install(index):
    url = 'https://download.pytorch.org/whl/' + index
    print(f'[PyTorch] Dang cai torch + torchvision tu {url}', flush=True)
    proc = subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade',
                           '--force-reinstall', 'torch', 'torchvision', '--index-url', url],
                          check=False)
    return proc.returncode == 0


def main(check=False):
    preference = setting('FALL_DEVICE', 'auto').lower() or 'auto'
    if preference not in ('auto', 'cpu', 'cuda', 'cuda:0'):
        print('[ERROR] FALL_DEVICE chi chap nhan auto, cpu, cuda hoac cuda:0.')
        return 1
    index = setting('FALL_TORCH_CUDA_INDEX', 'cu126').lower() or 'cu126'
    if index not in ('cu126', 'cu128'):
        print('[ERROR] FALL_TORCH_CUDA_INDEX chi chap nhan cu126 hoac cu128.')
        return 1

    hardware = nvidia_gpu()
    current = probe()
    print('[GPU] NVIDIA:', hardware or 'Khong phat hien qua nvidia-smi')
    print('[Torch] Phien ban:', current['torch_version'] or 'Chua cai',
          '| CUDA build:', current['cuda_build'] or 'CPU-only')
    print('[Torch] CUDA san sang:', 'YES' if current['cuda_ready'] else 'NO')
    if current.get('error'):
        print('[Torch] Chi tiet:', str(current['error'])[:240])
    if check:
        print('[Ket qua] GPU dang duoc PyTorch su dung.' if current['cuda_ready'] else
              '[Ket qua] PyTorch hien chua su dung GPU CUDA.')
        return 0 if current['cuda_ready'] else 1

    if preference == 'cpu':
        if not current['installed'] and not install('cpu'):
            return 1
        print('[Torch] FALL_DEVICE=cpu: se chay tren CPU theo cau hinh.')
        return 0
    if current['installed'] and current['cuda_ready']:
        print('[Torch] CUDA hoat dong. Khong can tai lai! GPU:', current['gpu_name'])
        return 0

    if hardware:
        if current['cuda_build'] and current['installed']:
            print('[WARN] Da co torch CUDA nhung khong dung duoc GPU. Kiem tra NVIDIA driver.')
            if preference.startswith('cuda'):
                return 1
            print('[Torch] Tu dong chuyen sang CPU cho den khi sua driver.')
            return 0
        # A CPU wheel already in .venv must be actively replaced, not skipped.
        print('[Torch] Phat hien NVIDIA, chuyen torch CPU sang torch CUDA (' + index + ').')
        if install(index):
            updated = probe()
            if updated['installed'] and updated['cuda_ready']:
                print('[Torch] CUDA da kich hoat thanh cong:', updated['gpu_name'])
                return 0
            print('[WARN] Cai xong CUDA nhung chua chay duoc:', (updated.get('error') or 'Kiem tra NVIDIA driver'))
        else:
            print('[WARN] Cai Torch CUDA that bai (kiem tra mang, o dia, driver).')
        if preference.startswith('cuda'):
            return 1
        current = probe()
        if current['installed']:
            print('[Torch] Tu dong dung CPU; khong xoa torch CUDA vua cai.')
            return 0
        print('[Torch] Khoi phuc ban CPU de server tiep tuc chay.')
        return 0 if install('cpu') and probe()['installed'] else 1

    if preference.startswith('cuda'):
        print('[ERROR] Khong co GPU NVIDIA/CUDA duoc nhan dien. Chay nvidia-smi de kiem tra driver.')
        return 1
    if not current['installed']:
        if not install('cpu') or not probe()['installed']:
            return 1
    print('[Torch] Khong co NVIDIA CUDA. Chay CPU; co the nang cap GPU sau.')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Chi kiem tra, khong cai dat')
    args = parser.parse_args()
    sys.exit(main(check=args.check))
