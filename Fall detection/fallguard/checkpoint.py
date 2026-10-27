"""Read tensor-only and original Kaggle NumPy checkpoints with restricted loading."""
import importlib
import pickle
from pathlib import Path

import numpy as np


def load_fall_checkpoint(path):
    import torch

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f'Missing BiLSTM checkpoint: {path}. '
            'Copy best_fall_lstm.pth into models/fall/.')
    try:
        checkpoint = torch.load(path, map_location='cpu', weights_only=True)
    except pickle.UnpicklingError:
        # The original Kaggle export stores its two float32 scalers as NumPy
        # arrays. Permit only those NumPy constructors, scoped to this load.
        # Accept exports from both NumPy 1.x and 2.x without unrestricted pickle.
        try:
            multiarray = importlib.import_module('numpy._core.multiarray')
        except ImportError:
            multiarray = importlib.import_module('numpy.core.multiarray')
        allowed = [
            np.ndarray, np.dtype, type(np.dtype('float32')),
            (multiarray._reconstruct, 'numpy.core.multiarray._reconstruct'),
            (multiarray._reconstruct, 'numpy._core.multiarray._reconstruct'),
        ]
        with torch.serialization.safe_globals(allowed):
            checkpoint = torch.load(path, map_location='cpu', weights_only=True)

    if not isinstance(checkpoint, dict):
        raise ValueError('BiLSTM checkpoint must be a dictionary.')
    required = {'model_config', 'model_state_dict', 'frames', 'img_size',
                'class_names', 'scaler_mean', 'scaler_scale'}
    missing = required - checkpoint.keys()
    if missing:
        raise ValueError('BiLSTM checkpoint is missing: ' + ', '.join(sorted(missing)))
    config = checkpoint['model_config']
    if (not isinstance(config, dict) or config.get('dim') != 55
            or config.get('hidden') != 128 or checkpoint['frames'] != 32
            or checkpoint['img_size'] != 384
            or list(checkpoint['class_names']) != ['NORMAL', 'FALL']):
        raise ValueError('Expected BiLSTM dim=55, hidden=128, frames=32, '
                         'img_size=384 and classes NORMAL/FALL.')
    if checkpoint.get('pose_weights', 'yolo11n-pose.pt') != 'yolo11n-pose.pt':
        raise ValueError('This checkpoint requires a different pose model.')
    for key in ('scaler_mean', 'scaler_scale'):
        values = torch.as_tensor(checkpoint[key], dtype=torch.float32)
        if values.shape != (55,) or not torch.isfinite(values).all():
            raise ValueError(f'{key} must contain exactly 55 finite values.')
        if key == 'scaler_scale' and (values <= 0).any():
            raise ValueError('scaler_scale values must be positive.')
        checkpoint[key] = values
    return checkpoint
