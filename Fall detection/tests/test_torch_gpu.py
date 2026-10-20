"""CUDA setup and inference selection are tested without downloading CUDA wheels."""
from types import SimpleNamespace

import pytest

from fallguard import detector, torch_setup


class FakeCUDA:
    def __init__(self, available):
        self.available = available

    def is_available(self):
        return self.available


def test_gpu_device_selected_when_cuda_works():
    assert detector.select_device(SimpleNamespace(cuda=FakeCUDA(True)), 'auto') == 'cuda:0'
    assert detector.select_device(SimpleNamespace(cuda=FakeCUDA(False)), 'auto') == 'cpu'
    assert detector.select_device(SimpleNamespace(cuda=FakeCUDA(True)), 'cpu') == 'cpu'
    assert detector.select_device(SimpleNamespace(cuda=FakeCUDA(True)), 'cuda:0') == 'cuda:0'


def test_gpu_required_without_cuda_raises():
    with pytest.raises(RuntimeError, match='CHECK_GPU'):
        detector.select_device(SimpleNamespace(cuda=FakeCUDA(False)), 'cuda:0')
    with pytest.raises(ValueError):
        detector.select_device(SimpleNamespace(cuda=FakeCUDA(True)), 'unknown')


def fake_status(ready=False, build=None, installed=True):
    return dict(installed=installed, cuda_ready=ready, cuda_build=build,
                torch_version='2.10.0', torchvision='0.25',
                gpu_name='Test NVIDIA GPU' if ready else None, error=None)


def test_gpu_installer_converts_cpu_venv_even_if_already_installed(monkeypatch):
    monkeypatch.setattr(torch_setup, 'setting', lambda key, default='': {'FALL_DEVICE': 'auto', 'FALL_TORCH_CUDA_INDEX': 'cu126'}.get(key, default))
    monkeypatch.setattr(torch_setup, 'nvidia_gpu', lambda: 'Test NVIDIA GPU')
    statuses = iter([fake_status(), fake_status(ready=True, build='12.6')])
    monkeypatch.setattr(torch_setup, 'probe', lambda: next(statuses))
    installed = []
    monkeypatch.setattr(torch_setup, 'install', lambda index: installed.append(index) or True)
    assert torch_setup.main() == 0
    assert installed == ['cu126']


def test_no_nvidia_stays_cpu_without_reinstall(monkeypatch):
    monkeypatch.setattr(torch_setup, 'setting', lambda key, default='': default)
    monkeypatch.setattr(torch_setup, 'nvidia_gpu', lambda: None)
    monkeypatch.setattr(torch_setup, 'probe', lambda: fake_status())
    monkeypatch.setattr(torch_setup, 'install', lambda index: pytest.fail('unexpected install'))
    assert torch_setup.main() == 0


def test_cuda_already_available_is_not_reinstalled(monkeypatch):
    monkeypatch.setattr(torch_setup, 'setting', lambda key, default='': default)
    monkeypatch.setattr(torch_setup, 'nvidia_gpu', lambda: 'Test NVIDIA GPU')
    monkeypatch.setattr(torch_setup, 'probe', lambda: fake_status(ready=True, build='12.6'))
    monkeypatch.setattr(torch_setup, 'install', lambda index: pytest.fail('unexpected install'))
    assert torch_setup.main() == 0


def test_cuda_requested_without_gpu_aborts(monkeypatch):
    monkeypatch.setattr(torch_setup, 'setting', lambda key, default='': 'cuda:0' if key == 'FALL_DEVICE' else default)
    monkeypatch.setattr(torch_setup, 'nvidia_gpu', lambda: None)
    monkeypatch.setattr(torch_setup, 'probe', lambda: fake_status())
    assert torch_setup.main() == 1
