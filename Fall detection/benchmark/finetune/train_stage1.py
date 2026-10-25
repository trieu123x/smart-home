"""Stage-1 fine-tune on Kaggle: yolo11s (single class `person`) on the E-FPDS YOLO set.

Run by the `fallguard-ft-stage1` notebook from the unpacked project root; writes <out>/ft_stage1.zip
(best.pt, results.csv, args.yaml).

Usage: python -I benchmark/finetune/train_stage1.py --out /kaggle/working [--epochs 60] [--hours 5.5]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark.finetune.common import DATA, package_run, train_with_fallback  # noqa: E402

WEIGHTS = ROOT / 'benchmark' / 'weights' / 'yolo11s' / 'yolo11s.pt'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--data', type=Path, default=DATA / 'stage1' / 'data.yaml')
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--hours', type=float, default=5.5)
    parser.add_argument('--batch', type=int, default=32)
    args = parser.parse_args(argv)
    import torch
    from ultralytics import YOLO
    project = args.out / 'runs'

    def train(device, hours):
        YOLO(str(WEIGHTS)).train(data=str(args.data), imgsz=704, epochs=args.epochs, batch=args.batch, device=device,
                                 save_period=5, time=hours, patience=15, seed=0, workers=4, plots=False,
                                 project=str(project), name='stage1', exist_ok=True)

    _, device = train_with_fallback(train, torch.cuda.device_count(), args.hours)
    names = YOLO(str(project / 'stage1' / 'weights' / 'best.pt')).names
    if names != {0: 'person'}:
        raise RuntimeError(f'fine-tuned stage 1 has classes {names}, expected {{0: person}}')
    print(f'[OK] trained on device={device}; {package_run(project / "stage1", args.out / "ft_stage1.zip")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
