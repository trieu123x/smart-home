"""ADB selection and settings tests, no physical phone required."""
from unittest.mock import Mock
import pytest
from fallguard import cctv
from fallguard import adb_camera


def test_source_load(monkeypatch):
    monkeypatch.setattr(cctv, 'setting', lambda k, d='': {'CCTV_URL': 'adb:front', 'CCTV_NAME': 'Android Camera'}.get(k,d))
    c = cctv.CameraSettings.load()
    assert c.url == 'adb:front' and c.name == 'Android Camera'


@pytest.mark.parametrize('src', ['usb:0','rtsp://example.com','adb:test','adb:', '', 'rtmp://example.com'])
def test_reject_old_camera_sources(monkeypatch, src):
    monkeypatch.setattr(cctv, 'setting', lambda k, d='': src if k == 'CCTV_URL' else d)
    with pytest.raises(ValueError): cctv.CameraSettings.load()


@pytest.mark.parametrize('src', ['adb:back', 'adb:front', 'adb:display'])
def test_supported_modes(src,monkeypatch):
    monkeypatch.setattr(cctv, 'setting', lambda k, d='': src if k=='CCTV_URL' else d)
    assert cctv.CameraSettings.load().url == src


def test_one_device(monkeypatch):
    monkeypatch.delenv('ADB_DEVICE_SERIAL', raising=False)
    monkeypatch.setattr(adb_camera,'_run_adb', lambda *a, **kw:'List of devices attached\nABC123 device product:xx model:yy\n')
    assert adb_camera._select_device() == 'ABC123'


def test_not_authorized(monkeypatch):
    monkeypatch.delenv('ADB_DEVICE_SERIAL', raising=False)
    monkeypatch.setattr(adb_camera,'_run_adb', lambda *a, **kw:'List of devices attached\nABC123 unauthorized\n')
    with pytest.raises(adb_camera.AdbCameraError,match='Allow USB debugging'):
        adb_camera._select_device()


def test_two_devices(monkeypatch):
    monkeypatch.delenv('ADB_DEVICE_SERIAL', raising=False)
    monkeypatch.setattr(adb_camera,'_run_adb', lambda *a, **kw:'List of devices attached\nA device\nB device\n')
    with pytest.raises(adb_camera.AdbCameraError,match='nhieu'):
        adb_camera._select_device()


def test_invalid_source_rejected_without_spawning_adb():
    with pytest.raises(ValueError): adb_camera.AdbH264Capture('usb:0')


def test_capture_launches_camera_and_cleans_forward(monkeypatch):
    import cv2
    monkeypatch.setattr(adb_camera, '_select_device', lambda: 'SERIAL123')
    calls = []
    def fake_adb(args, serial=None, timeout=12, check=True):
        calls.append((args, serial))
        return '34' if args[:3] == ['shell','getprop','ro.build.version.sdk'] else 'ok'
    monkeypatch.setattr(adb_camera,'_run_adb',fake_adb)
    monkeypatch.setattr(adb_camera.time, 'sleep', lambda _: None)
    fake_capture = Mock()
    fake_capture.isOpened.return_value = True
    fake_capture.read.return_value = True, 'frame'
    monkeypatch.setattr(cv2,'VideoCapture',lambda *a:fake_capture)
    fake_process = Mock()
    fake_process.poll.return_value = None
    fake_process.wait.return_value = 0
    params = {}
    def fake_popen(args, **kw):
        params['cmd'] = args
        return fake_process
    monkeypatch.setattr(adb_camera.subprocess,'Popen',fake_popen)
    c = adb_camera.AdbH264Capture('adb:back')
    assert c.isOpened()
    assert c.read() == (True, 'frame')
    assert 'video_source=camera' in params['cmd']
    assert 'camera_facing=back' in params['cmd']
    assert 'raw_stream=true' in params['cmd']
    c.release()
    fake_capture.release.assert_called_once()
    fake_process.terminate.assert_called_once()
    assert any(args[:2] == ['forward','--remove'] for args,_ in calls)


def test_android_below_12_uses_display_fallback(monkeypatch):
    monkeypatch.setattr(adb_camera, '_select_device',lambda:'SERIAL123')
    monkeypatch.setattr(adb_camera,'_run_adb',lambda *a, **k:'30')
    with pytest.raises(adb_camera.AdbCameraError, match='Android 12'):
        adb_camera.AdbH264Capture('adb:front')
