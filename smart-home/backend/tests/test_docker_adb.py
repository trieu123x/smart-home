"""Remote ADB routing must be shared by commands and the H264 stream."""
from unittest.mock import Mock

import pytest
from fallguard import adb_camera


@pytest.fixture(autouse=True)
def adb_config(monkeypatch, tmp_path):
    executable = tmp_path / 'adb'
    executable.touch()
    server = tmp_path / 'scrcpy-server'
    server.touch()
    monkeypatch.setattr(adb_camera, 'ADB_EXE', executable)
    monkeypatch.setattr(adb_camera, 'SCRCPY_SERVER', server)
    monkeypatch.setattr(adb_camera, '_settings', {})
    for key in ('ADB_SERVER_HOST', 'ADB_SERVER_PORT', 'ADB_STREAM_HOST', 'ADB_STREAM_PORT'):
        monkeypatch.delenv(key, raising=False)


def test_native_adb_and_stream_remain_local():
    assert adb_camera._adb_command('PHONE') == [str(adb_camera.ADB_EXE), '-s', 'PHONE']
    assert adb_camera._stream_url(27183) == 'tcp://127.0.0.1:27183?timeout=5000000'


def test_remote_adb_routes_control_and_video_to_host(monkeypatch):
    monkeypatch.setenv('ADB_SERVER_HOST', 'host.docker.internal')
    monkeypatch.setenv('ADB_SERVER_PORT', '5038')
    assert adb_camera._adb_command('PHONE')[1:] == ['-H', 'host.docker.internal', '-P', '5038', '-s', 'PHONE']
    assert adb_camera._stream_url(27183) == 'tcp://host.docker.internal:27183?timeout=5000000'


def test_explicit_video_host_and_ipv6(monkeypatch):
    monkeypatch.setenv('ADB_SERVER_HOST', 'control.example')
    monkeypatch.setenv('ADB_STREAM_HOST', '::1')
    assert adb_camera._stream_url(27183) == 'tcp://[::1]:27183?timeout=5000000'


def test_invalid_remote_port_fails_before_spawning(monkeypatch):
    monkeypatch.setenv('ADB_SERVER_HOST', 'host.docker.internal')
    monkeypatch.setenv('ADB_SERVER_PORT', '70000')
    run = Mock()
    monkeypatch.setattr(adb_camera.subprocess, 'run', run)
    with pytest.raises(adb_camera.AdbCameraError):
        adb_camera._run_adb(['devices'])
    run.assert_not_called()


def test_camera_shell_forward_and_cleanup_use_remote_server(monkeypatch):
    import cv2
    monkeypatch.setenv('ADB_SERVER_HOST', 'host.docker.internal')
    monkeypatch.setattr(adb_camera, '_select_device', lambda: 'PHONE')
    monkeypatch.setattr(adb_camera.time, 'sleep', lambda _: None)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return Mock(returncode=0, stdout='34' if 'getprop' in command else 'ok')
    monkeypatch.setattr(adb_camera.subprocess, 'run', run)
    process = Mock()
    process.poll.return_value = None
    popen = Mock(return_value=process)
    monkeypatch.setattr(adb_camera.subprocess, 'Popen', popen)
    capture = Mock()
    capture.isOpened.return_value = True
    open_video = Mock(return_value=capture)
    monkeypatch.setattr(cv2, 'VideoCapture', open_video)
    camera = adb_camera.AdbH264Capture('adb:back')
    camera.release()
    expected = [str(adb_camera.ADB_EXE), '-H', 'host.docker.internal', '-P', '5038', '-s', 'PHONE']
    assert all(command[:7] == expected for command in calls)
    assert popen.call_args.args[0][:7] == expected
    assert open_video.call_args.args[0] == 'tcp://host.docker.internal:27183?timeout=5000000'
    assert any(command[7:9] == ['forward', '--remove'] for command in calls)
    capture.release.assert_called_once()
