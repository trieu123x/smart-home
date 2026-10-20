"""One configured IP camera, read on the server with bounded network timeouts."""
import os
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .telegram_config import _settings


def setting(key, default=''):
    return os.environ.get(key, _settings.get(key, default)).strip()


@dataclass(frozen=True)
class CameraSettings:
    url: str = ''
    name: str = 'Camera CCTV'
    autostart: bool = False
    threshold: float = .4
    confirmations: int = 3

    @classmethod
    def load(cls):
        url = setting('CCTV_URL')
        if url:
            try:
                parts = urlsplit(url)
                if parts.scheme not in ('rtsp', 'http', 'https') or not parts.hostname:
                    raise ValueError()
                _ = parts.port
            except ValueError:
                raise ValueError('CCTV_URL cần là địa chỉ luồng RTSP hoặc HTTP(S) hợp lệ.') from None
        try:
            threshold = float(setting('CCTV_FALL_THRESHOLD', '0.4'))
            confirmations = int(setting('CCTV_CONFIRMATIONS', '3'))
            if not .05 <= threshold <= .95 or not 1 <= confirmations <= 20:
                raise ValueError()
        except ValueError:
            raise ValueError('Ngưỡng CCTV cần từ 0.05–0.95; số lần xác nhận từ 1–20.') from None
        return cls(url, setting('CCTV_NAME', 'Camera CCTV')[:80],
                   setting('CCTV_AUTOSTART', '0').lower() in ('1', 'true', 'yes'),
                   threshold, confirmations)


def _configure_rtsp_latency(url):
    """Reduce RTSP client-side buffering; never override explicit FFmpeg settings.

    OpenCV/FFmpeg reads this process variable at capture creation. This can
    improve input buffering, but cannot remove latency already in the sender,
    internet uplink, or encoder. Disable with CCTV_LOW_LATENCY=0 if needed.
    """
    if urlsplit(url).scheme.lower() != 'rtsp':
        return
    if setting('CCTV_LOW_LATENCY', '1').lower() in ('0', 'false', 'no', 'off'):
        return
    os.environ.setdefault(
        'OPENCV_FFMPEG_CAPTURE_OPTIONS',
        'rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0'
    )


def open_camera(url):
    _configure_rtsp_latency(url)
    import cv2
    # FFmpeg supports these open-only properties. Do not fall back to an unbounded read.
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
    ])


class CameraReader:
    """Only this thread owns VideoCapture; callers never release it during read()."""
    def __init__(self, config, opener=open_camera, reconnect_seconds=3):
        self.config, self.opener = config, opener
        self.reconnect_seconds = reconnect_seconds
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = False
        self._enabled = False
        self._epoch = 0
        self._sequence = 0
        self._state = 'stopped'
        self._frame = None
        self._captured_at = None
        self._thread = threading.Thread(target=self._run, name='cctv-capture', daemon=True)
        self._thread.start()

    def start(self):
        if not self.config.url:
            raise ValueError('Chưa cấu hình CCTV_URL trong .env trên máy chủ.')
        with self._lock:
            if self._enabled:
                return
            self._enabled = True
            self._epoch += 1
            self._state = 'connecting'
        self._wake.set()

    def stop(self):
        with self._lock:
            self._enabled = False
            self._epoch += 1
            self._state = 'stopped'
            self._frame = self._captured_at = None
        self._wake.set()

    def close(self):
        self.stop()
        with self._lock:
            self._closed = True
        self._wake.set()
        self._thread.join(timeout=6)

    def snapshot(self):
        with self._lock:
            age = None if self._captured_at is None else time.monotonic() - self._captured_at
            state = self._state
            if state == 'connected' and age is not None and age > 6:
                state = 'reconnecting'
            fresh = state == 'connected' and age is not None and age <= 6
            return ({'configured': bool(self.config.url), 'name': self.config.name,
                     'enabled': self._enabled, 'state': state, 'epoch': self._epoch,
                     'sequence': self._sequence, 'frame_age': age,
                     'threshold': self.config.threshold, 'confirmations': self.config.confirmations},
                    self._frame if fresh else None)

    def _wanted(self, epoch):
        with self._lock:
            return not self._closed and self._enabled and epoch == self._epoch

    def _run(self):
        while True:
            self._wake.clear()
            with self._lock:
                if self._closed:
                    return
                enabled, epoch = self._enabled, self._epoch
            if not enabled:
                self._wake.wait(1)
                continue
            capture = None
            try:
                capture = self.opener(self.config.url)
                if not capture.isOpened():
                    raise RuntimeError('open failed')
                while self._wanted(epoch):
                    ok, frame = capture.read()
                    if not ok or frame is None:
                        break
                    with self._lock:
                        if epoch != self._epoch or not self._enabled:
                            break
                        self._frame = frame
                        self._captured_at = time.monotonic()
                        self._sequence += 1
                        self._state = 'connected'
            except Exception:
                # Never place the URL or credentials in API errors.
                pass
            finally:
                if capture is not None:
                    capture.release()
            with self._lock:
                if self._epoch == epoch and self._enabled:
                    self._state = 'reconnecting'
                    self._frame = self._captured_at = None
                    self._epoch += 1  # Old inference/track streaks are now invalid.
            self._wake.wait(self.reconnect_seconds)


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    def area(box):
        return max(0, box[2]-box[0]) * max(0, box[3]-box[1])
    return intersection / (area(a) + area(b) - intersection or 1)


class FallTracker:
    """Require continuous positive tracking AND at least 5 real seconds.

    Missing detections, identity changes, or a gap in processed frames reset the
    pending window. A person is alerted once per continuous fall episode.
    """
    FALL_SECONDS = 5.0
    MAX_INFERENCE_GAP = 2.0

    def __init__(self):
        self.tracks = []
        self.next_id = 1
        self.last_time = None

    def reset(self):
        self.tracks = []
        self.last_time = None

    def update(self, detections, threshold, needed, now):
        if self.last_time is not None and (now < self.last_time or now-self.last_time > self.MAX_INFERENCE_GAP):
            self.reset()
        self.last_time = now
        candidates = sorted(((iou(d['box'], t['box']), di, ti)
                             for di, d in enumerate(detections) for ti, t in enumerate(self.tracks)), reverse=True)
        matched, used = {}, set()
        for score, di, ti in candidates:
            if score >= .25 and di not in matched and ti not in used:
                matched[di] = ti
                used.add(ti)
        tracks = []
        for di, d in enumerate(detections):
            old = self.tracks[matched[di]] if di in matched else None
            identity = old['id'] if old else self.next_id
            if old is None:
                self.next_id += 1
            positive = d.get('fall_score') is not None and d['fall_score'] >= threshold
            streak = (old['streak'] if old else 0) + 1 if positive else 0
            fall_since = (old.get('fall_since') if old and old.get('fall_since') is not None else now) if positive else None
            fall_elapsed = max(0.0, now-fall_since) if positive else 0.0
            danger = positive and streak >= needed and fall_elapsed >= self.FALL_SECONDS
            tracks.append({**d, 'id': identity, 'streak': streak, 'fall_since': fall_since,
                           'fall_elapsed': round(fall_elapsed, 2), 'danger': danger,
                           'pending': positive and not danger, 'newAlert': danger and not (old and old['danger'])})
        self.tracks = tracks
        return tracks
