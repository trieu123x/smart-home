"""Stage-2 fine-tune on Kaggle: jerryg-v8x-cls to 3 classes (`fall` / `sit` / `normal`) at 128 px.

Ultralytics rebuilds the classifier head for the dataset's class count (ClassificationModel.reshape_outputs).
Run by the `fallguard-ft-stage2` notebook from the unpacked project root; writes <out>/ft_stage2.zip
(best.pt, results.csv, args.yaml).

Usage: python -I benchmark/finetune/train_stage2.py --out /kaggle/working [--epochs 40] [--hours 5.5]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))   # -I drops the script dir from sys.path; add the project root only

from benchmark.finetune.common import DATA, package_run, train_with_fallback  # noqa: E402

WEIGHTS = ROOT / 'benchmark' / 'weights' / 'jerryg-v8x-cls' / 'best.pt'
CLASSES = {'fall', 'sit', 'normal'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--data', type=Path, default=DATA / 'stage2')
    parser.add_argument('--epochs', type=int, default=40)
    parser.add_argument('--hours', type=float, default=5.5)
    parser.add_argument('--batch', type=int, default=256)
    args = parser.parse_args(argv)
    import torch
    from ultralytics import YOLO
    project = args.out / 'runs'

    def train(device, hours):
        YOLO(str(WEIGHTS)).train(data=str(args.data), imgsz=128, epochs=args.epochs, batch=args.batch, device=device,
                                 time=hours, seed=0, workers=4, plots=False,
                                 project=str(project), name='stage2', exist_ok=True)

    _, device = train_with_fallback(train, torch.cuda.device_count(), args.hours)
    names = YOLO(str(project / 'stage2' / 'weights' / 'best.pt')).names
    if set(names.values()) != CLASSES:
        raise RuntimeError(f'fine-tuned stage 2 has classes {names}, expected {sorted(CLASSES)}')
    print(f'[OK] trained on device={device}; {package_run(project / "stage2", args.out / "ft_stage2.zip")}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
