"""Camera or screen capture over USB using scrcpy 4.1 server and ADB.

Protocol: scrcpy standalone server raw H.264 stream -> ADB TCP forward ->
OpenCV (FFmpeg). No Windows scrcpy GUI, DroidCam, RTSP or cloud service.

The internal scrcpy server protocol is version-sensitive. The bundled
scrcpy-server is 4.1; keep the matching ADB tools and server file together.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from .telegram_config import _settings
import subprocess
import tempfile
import time

from .paths import ASSETS as ROOT
ADB_DIR = ROOT / "tools" / "adb"
ADB_EXE = ADB_DIR / "adb.exe"
SCRCPY_SERVER = ADB_DIR / "scrcpy-server"
SCRCPY_VERSION = "4.1"  # Verified against bundled scrcpy-server AndroidManifest.xml
DEVICE_SERVER = "/data/local/tmp/fallguard-scrcpy-server.jar"


class AdbCameraError(RuntimeError):
    pass


def _run_adb(args, serial=None, timeout=12, check=True):
    if not ADB_EXE.is_file():
        raise AdbCameraError("Thieu tools/adb/adb.exe.")
    cmd = [str(ADB_EXE)]
    if serial:
        cmd += ["-s", serial]
    try:
        result = subprocess.run(cmd + list(args), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace", timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdbCameraError("ADB khong the hoan tat lenh; kiem tra cap USB va dien thoai.") from exc
    if check and result.returncode:
        raise AdbCameraError("ADB that bai: " + result.stdout.strip()[-300:])
    return result.stdout.strip()


def _select_device():
    wanted = os.environ.get("ADB_DEVICE_SERIAL", _settings.get("ADB_DEVICE_SERIAL", "")).strip()
    lines = _run_adb(["devices", "-l"]).splitlines()[1:]
    online, unauthorized = [], []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[1] == "device":
            online.append(parts[0])
        elif parts[1] == "unauthorized":
            unauthorized.append(parts[0])
    if wanted:
        if wanted not in online:
            raise AdbCameraError("ADB_DEVICE_SERIAL khong ket noi hoac chua cho phep USB debugging.")
        return wanted
    if not online:
        if unauthorized:
            raise AdbCameraError("Dien thoai chua chap nhan thong bao 'Allow USB debugging'.")
        raise AdbCameraError("Khong tim thay dien thoai ADB. Thu doi cap va bat USB debugging.")
    if len(online) > 1:
        raise AdbCameraError("Co nhieu thiet bi ADB. Dat ADB_DEVICE_SERIAL trong .env.")
    return online[0]


def _env_int(key, default, low, high):
    try:
        value = int(os.environ.get(key, _settings.get(key, str(default))).strip())
    except ValueError as exc:
        raise AdbCameraError(f"{key} phai la so nguyen.") from exc
    if not low <= value <= high:
        raise AdbCameraError(f"{key} phai trong khoang {low}-{high}.")
    return value


class AdbH264Capture:
    """cv2.VideoCapture-compatible adapter with deterministic ADB cleanup."""

    def __init__(self, source):
        import cv2
        if source not in ("adb:back", "adb:front", "adb:display"):
            raise ValueError("CCTV_URL phai la adb:back, adb:front hoac adb:display.")
        self.capture = None
        self.server_process = None
        self.server_log = None
        self.serial = None
        self.forward_active = False
        self.port = _env_int("ADB_STREAM_PORT", 27183, 1024, 65535)
        self.source = source
        self._closed = False
        try:
            self.serial = _select_device()
            api_output = _run_adb(["shell", "getprop", "ro.build.version.sdk"], serial=self.serial)
            try:
                api = int(api_output.strip())
            except ValueError as exc:
                raise AdbCameraError("Khong doc duoc phien ban Android.") from exc
            if source != "adb:display" and api < 31:
                raise AdbCameraError("Camera scrcpy can Android 12 tro len. Dung adb:display de chieu man hinh.")
            if not SCRCPY_SERVER.is_file():
                raise AdbCameraError("Thieu tools/adb/scrcpy-server.")
            _run_adb(["push", str(SCRCPY_SERVER), DEVICE_SERVER], serial=self.serial, timeout=30)
            _run_adb(["forward", f"tcp:{self.port}", "localabstract:scrcpy"], serial=self.serial)
            self.forward_active = True
            args = [str(ADB_EXE), "-s", self.serial, "shell",
                    f"CLASSPATH={DEVICE_SERVER}", "app_process", "/",
                    "com.genymobile.scrcpy.Server", SCRCPY_VERSION,
                    "tunnel_forward=true", "audio=false", "control=false",
                    "cleanup=false", "raw_stream=true", "video_codec=h264",
                    "video_bit_rate=" + str(_env_int("ADB_VIDEO_BIT_RATE", 3000000, 200000, 15000000)),
                    "max_size=" + str(_env_int("ADB_MAX_SIZE", 1280, 320, 3840)),
                    "log_level=info"]
            if source in ("adb:back", "adb:front"):
                args += ["video_source=camera", "camera_facing=" + source.split(":", 1)[1],
                         "camera_fps=" + str(_env_int("ADB_CAMERA_FPS", 20, 1, 60))]
            self.server_log = tempfile.TemporaryFile(mode="w+b")
            self.server_process = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=self.server_log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # ADB forwarding starts before the device-side local socket exists.
            # Give the Android server time to start, then let FFmpeg probe raw H.264.
            time.sleep(0.5)
            for i in range(8):
                if self.server_process.poll() is not None:
                    raise AdbCameraError("scrcpy-server da thoat: " + self._server_error())
                url = f"tcp://127.0.0.1:{self.port}?timeout=5000000"
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    self.capture = cap
                    self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    logging.warning("FallGuard ADB: connected %s / %s", self.serial, source)
                    return
                cap.release()
                time.sleep(0.3)
            raise AdbCameraError("Khong lay duoc H264 qua ADB. Kiem tra camera quyen, cap USB va log scrcpy.")
        except Exception:
            self.release()
            raise

    def _server_error(self):
        if self.server_log is None:
            return "khong co log"
        try:
            self.server_log.flush()
            self.server_log.seek(0)
            return self.server_log.read()[-600:].decode("utf-8", "replace").replace("\r", " ").replace("\n", " ")
        except Exception:
            return "khong doc duoc log"

    def isOpened(self):
        return self.capture is not None and self.capture.isOpened()

    def read(self):
        if self.capture is None:
            return False, None
        return self.capture.read()

    def release(self):
        if self._closed:
            return
        self._closed = True
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        if self.server_process is not None:
            if self.server_process.poll() is None:
                self.server_process.terminate()
                try:
                    self.server_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.server_process.kill()
                    self.server_process.wait(timeout=2)
            self.server_process = None
        if self.forward_active and self.serial:
            try:
                _run_adb(["forward", "--remove", f"tcp:{self.port}"], serial=self.serial, timeout=5, check=False)
            except AdbCameraError:
                pass
            self.forward_active = False
        if self.server_log is not None:
            self.server_log.close()
            self.server_log = None
