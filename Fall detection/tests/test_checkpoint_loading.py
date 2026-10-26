"""Exercise real uploaded weights, both scaler encodings and invalid checkpoints."""
from copy import deepcopy
from pathlib import Path
import pickle

import numpy as np
import pytest
import torch

from fallguard.checkpoint import load_fall_checkpoint
from fallguard.detector import FallLSTM, LSTM_WEIGHTS


def test_uploaded_numpy_checkpoint_loads_strictly_and_forwards():
    previous = list(torch.serialization.get_safe_globals())
    ckpt = load_fall_checkpoint(LSTM_WEIGHTS)
    assert torch.serialization.get_safe_globals() == previous
    assert ckpt['scaler_mean'].shape == (55,)
    assert ckpt['scaler_scale'].shape == (55,)
    model = FallLSTM.build(torch).eval()
    model.load_state_dict(ckpt['model_state_dict'], strict=True)
    with torch.inference_mode():
        x = (torch.zeros(2, 32, 55) - ckpt['scaler_mean']) / ckpt['scaler_scale']
        probabilities = model(x).softmax(dim=1)
    assert probabilities.shape == (2, 2)
    assert torch.isfinite(probabilities).all()
    assert torch.allclose(probabilities.sum(dim=1), torch.ones(2))


@pytest.mark.parametrize('numpy_scalers', [False, True])
def test_tensor_and_numpy_exports_preserve_values(tmp_path, numpy_scalers):
    original = load_fall_checkpoint(LSTM_WEIGHTS)
    exported = deepcopy(original)
    if numpy_scalers:
        for key in ('scaler_mean', 'scaler_scale'):
            exported[key] = exported[key].numpy()
    path = tmp_path / 'export.pth'
    torch.save(exported, path)
    reloaded = load_fall_checkpoint(path)
    for key in ('scaler_mean', 'scaler_scale'):
        assert torch.equal(reloaded[key], original[key])
    for key, weight in original['model_state_dict'].items():
        assert torch.equal(reloaded['model_state_dict'][key], weight)


@pytest.mark.parametrize('key,value,match', [
    ('frames', 16, 'Expected BiLSTM'),
    ('class_names', ['FALL', 'NORMAL'], 'Expected BiLSTM'),
    ('scaler_mean', np.zeros(54, np.float32), '55 finite'),
    ('scaler_mean', np.full(55, np.nan, np.float32), '55 finite'),
    ('scaler_scale', np.zeros(55, np.float32), 'positive'),
    ('pose_weights', 'yolo11s-pose.pt', 'different pose model'),
])
def test_incompatible_checkpoint_fails_clearly(tmp_path, key, value, match):
    ckpt = load_fall_checkpoint(LSTM_WEIGHTS)
    ckpt[key] = value
    path = tmp_path / 'invalid.pth'
    torch.save(ckpt, path)
    with pytest.raises(ValueError, match=match):
        load_fall_checkpoint(path)


def test_missing_checkpoint_explains_destination(tmp_path):
    with pytest.raises(FileNotFoundError, match='models/fall'):
        load_fall_checkpoint(tmp_path / 'missing.pth')


def test_does_not_allow_arbitrary_pickled_classes(tmp_path):
    ckpt = load_fall_checkpoint(LSTM_WEIGHTS)
    ckpt['unsupported'] = Path('unsupported-object')
    path = tmp_path / 'unsupported.pth'
    torch.save(ckpt, path)
    previous = list(torch.serialization.get_safe_globals())
    with pytest.raises(pickle.UnpicklingError):
        load_fall_checkpoint(path)
    assert torch.serialization.get_safe_globals() == previous
