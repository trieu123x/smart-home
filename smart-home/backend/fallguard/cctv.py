"""Camera capture for FallGuard: ADB USB and local DroidCam MJPEG."""
import os
import re
import threading
import time
import ipaddress
from urllib.parse import urlsplit
from dataclasses import dataclass

from .telegram_config import _settings


def setting(key, default=''):
    return os.environ.get(key, _settings.get(key, default)).strip()

ADB_SOURCES = ('adb:back', 'adb:front', 'adb:display')

# ----- KẾT NỐI VỚI DROIDCAM -------
def normalize_url(raw):
    """adb:* (Android USB) | droidcam:IP[:cong] (iPhone) | http(s)/rtsp URL."""
    value = raw.strip()
    lowered = value.lower()
    if lowered in ADB_SOURCES:
        return lowered
    if lowered.startswith('droidcam:'):
        host = value.split(':', 1)[1].strip().strip('/')
        if not re.fullmatch(r'[A-Za-z0-9.-]+(:\d{1,5})?', host):
            raise ValueError('droidcam phai co dang droidcam:192.168.1.50 hoac droidcam:192.168.1.50:4747.')
        if ':' not in host:
            host += ':4747'
        return f'http://{host}/video'
    if lowered.startswith(('http://', 'https://', 'rtsp://')):
        return value
    raise ValueError('CCTV_URL phai la adb:back, adb:front, adb:display, droidcam:<IP> hoac URL http(s)/rtsp.')


@dataclass(frozen=True)
class CameraSettings:
    url: str = 'adb:back'
    name: str = 'Android USB ADB'
    autostart: bool = True
    threshold: float = .80
    confirmations: int = 3

    @classmethod
    def load(cls):
        url = normalize_url(setting('CCTV_URL', 'adb:back'))
        try:
            threshold = float(setting('CCTV_FALL_THRESHOLD', '0.80'))
            confirmations = int(setting('CCTV_CONFIRMATIONS', '3'))
            if not .05 <= threshold <= .95 or not 1 <= confirmations <= 20:
                raise ValueError()
        except ValueError:
            raise ValueError('Ngưỡng CCTV cần từ 0.05–0.95; số lần xác nhận từ 1–20.') from None
        return cls(url, setting('CCTV_NAME', 'Android USB ADB')[:80],
                   setting('CCTV_AUTOSTART', '1').lower() in ('1', 'true', 'yes'),
                   threshold, confirmations)


def droidcam_url(host: str, port: int = 4747) -> str:
    """Accept only numeric, non-public IPv4 on the LAN (no DNS/redirect URLs)."""
    try:
        ip = ipaddress.IPv4Address(host.strip())
    except (ipaddress.AddressValueError, ValueError):
        raise ValueError('Nhap IPv4 noi bo cua dien thoai, vi du 192.168.1.20.') from None
    networks = (ipaddress.IPv4Network('10.0.0.0/8'),
                ipaddress.IPv4Network('172.16.0.0/12'),
                ipaddress.IPv4Network('192.168.0.0/16'))
    if not any(ip in network for network in networks):
        raise ValueError('Chi cho phep IP LAN RFC1918 (10.x, 172.16-31.x, 192.168.x).')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Port DroidCam phai tu 1024 den 65535.')
    return f'http://{ip}:{port}/video'


def parse_droidcam_url(value: str) -> str:
    """Validate configured URL; runtime uses a fixed /video path."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'http' or parsed.username or parsed.password or parsed.path not in ('', '/', '/video') or parsed.query or parsed.fragment:
            raise ValueError()
        return droidcam_url(parsed.hostname or '', parsed.port or 4747)
    except (ValueError, TypeError):
        raise ValueError('DROIDCAM_URL phai co dang http://192.168.1.20:4747/video') from None


def open_camera(url):
    """Open ADB H264 or local DroidCam MJPEG. FFmpeg read/open timeouts avoid hanging."""
    if url.startswith('adb:'):
        from .adb_camera import AdbH264Capture
        return AdbH264Capture(url)
    safe_url = parse_droidcam_url(url)
    import cv2
    cap = cv2.VideoCapture(safe_url, cv2.CAP_FFMPEG, [
        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 4000,
        cv2.CAP_PROP_READ_TIMEOUT_MSEC, 4000,
    ])
    if not cap.isOpened():
        cap.release()
        raise RuntimeError('DroidCam khong ket noi duoc. Kiem tra IP, port va Wi-Fi.')
    return cap

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

    def configure(self, config, start=True):
        """Change camera safely; old reader exits on epoch change."""
        with self._lock:
            self.config = config
            self._enabled = start
            self._epoch += 1
            self._frame = self._captured_at = None
            self._state = 'connecting' if start else 'stopped'
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
            except Exception as exc:
                # Local ADB errors are useful during USB setup; no credentials in URLs.
                import logging
                logging.warning('FallGuard camera: %s', exc)
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
    """Match YOLO Pose identities and classify 32-frame pose windows per person.

    Unlike the former still-image detector, no score exists until enough
    observations of this *same person* have been collected. The user-facing
    score is P(FALL) from the trained BiLSTM, not a YOLO bounding-box score.
    """
    FRAMES = 32
    MAX_INFERENCE_GAP = 2.0
    TRACK_TTL = 0.9
    RECOVERY_FRAMES = 8
    MIN_VALID_POSES = 7  # training excluded sequences with <20% recognized poses

    def __init__(self):
        self.tracks = []
        self._state = {}
        self.next_id = 1
        self.last_time = None

    def reset(self):
        self.tracks = []
        self._state = {}
        self.last_time = None

    @staticmethod
    def _center(box):
        return ((box[0] + box[2]) * .5, (box[1] + box[3]) * .5)

    def update(self, detections, threshold, needed, now, scorer=None):
        """Update tracks and optionally evaluate new 32-frame windows.

        `scorer` accepts list[np.ndarray(32,55)] and returns FALL probabilities.
        Defaults to None for camera/test doubles; without a scorer, no fake
        fall detection occurs. Do not infer FALL from single pose frame.
        """
        from collections import deque
        import numpy as np

        if self.last_time is not None and (now < self.last_time or now - self.last_time > self.MAX_INFERENCE_GAP):
            self.reset()
        self.last_time = now
        for identity, state in list(self._state.items()):
            if now - state['last_seen'] > self.TRACK_TTL:
                del self._state[identity]

        # First use tracker IDs from YOLO ByteTrack, then fallback to IoU.
        assigned = {}
        used = set()
        for i, d in enumerate(detections):
            external_id = d.get('tracking_id')
            if external_id is None:
                continue
            for identity, state in self._state.items():
                if identity not in used and state.get('external_id') == external_id:
                    assigned[i] = identity
                    used.add(identity)
                    break

        pairs = []
        for di, d in enumerate(detections):
            if di in assigned:
                continue
            for identity, state in self._state.items():
                if identity in used:
                    continue
                # Preserve tracker identity: a different explicit ByteTrack ID
                # must not inherit someone else's 32-frame pose history.
                if (d.get('tracking_id') is not None and state.get('external_id') is not None
                        and d['tracking_id'] != state['external_id']):
                    continue
                score = iou(d['box'], state['box'])
                cx1, cy1 = self._center(d['box'])
                cx2, cy2 = self._center(state['box'])
                distance = ((cx1-cx2)**2 + (cy1-cy2)**2)**0.5
                # Low-IoU fallback for rapid posture changes, but avoid leaps.
                if score >= .15 or distance < .08:
                    pairs.append((score + max(0, .08-distance), di, identity))
        for _, di, identity in sorted(pairs, reverse=True):
            if di not in assigned and identity not in used:
                assigned[di] = identity
                used.add(identity)

        # Stage sequences first and batch classification in one torch call.
        pending_sequences = []
        ready_ids = []
        visible = []
        for di, d in enumerate(detections):
            identity = assigned.get(di)
            if identity is None:
                identity = self.next_id
                self.next_id += 1
                self._state[identity] = dict(
                    box=d['box'], last_seen=now, external_id=d.get('tracking_id'),
                    features=deque(maxlen=self.FRAMES), valid=deque(maxlen=self.FRAMES),
                    positive=0, negative=0, danger=False, alerted=False,
                    score=None, fall_since=None, streak=0, invalid_windows=0)
            state = self._state[identity]
            state['box'] = d['box']
            state['last_seen'] = now
            if d.get('tracking_id') is not None:
                state['external_id'] = d['tracking_id']

            vec = d.get('pose_feature')
            if vec is None:
                # No feature vector = incomplete observation, not a prediction.
                # For tests/mocks or temporary pose loss do not manufacture a score.
                vec = np.zeros(55, np.float32)
                valid = False
            else:
                vec = np.asarray(vec, dtype=np.float32)
                if vec.shape != (55,) or not np.isfinite(vec).all():
                    raise ValueError('Pose features must contain 55 finite values')
                valid = bool(d.get('pose_valid', False))
            state['features'].append(vec)
            state['valid'].append(valid)
            if (scorer is not None and len(state['features']) == self.FRAMES
                    and sum(state['valid']) >= self.MIN_VALID_POSES):
                pending_sequences.append(np.stack(state['features']))
                ready_ids.append(identity)
                state['invalid_windows'] = 0
            elif len(state['features']) == self.FRAMES:
                # With many missing joints there is no trustworthy FALL probability.
                state['score'] = None
                state['invalid_windows'] += 1
                state['positive'] = 0
                state['streak'] = 0
                state['fall_since'] = None
                if state['invalid_windows'] >= self.RECOVERY_FRAMES:
                    state['danger'] = False
                    # Do not rearm another incident until normal pose resumes.
            visible.append((identity, d))

        if ready_ids:
            scores = scorer(pending_sequences)
            if len(scores) != len(ready_ids):
                raise RuntimeError('Sequence classifier returned wrong number of results')
            for identity, score in zip(ready_ids, scores):
                state = self._state[identity]
                score = float(score)
                if not np.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError('Invalid P(FALL) from BiLSTM')
                state['score'] = score
                if score >= threshold:
                    state['positive'] += 1
                    state['negative'] = 0
                    state['streak'] += 1
                    if state['fall_since'] is None:
                        state['fall_since'] = now
                    if state['positive'] >= needed:
                        state['danger'] = True
                else:
                    state['positive'] = 0
                    state['negative'] += 1
                    state['streak'] = 0
                    state['fall_since'] = None
                    if state['negative'] >= self.RECOVERY_FRAMES:
                        state['danger'] = False
                        state['alerted'] = False  # arm next incident after recovery
        output = []
        for identity, d in visible:
            state = self._state[identity]
            danger = state['danger']
            new_alert = danger and not state['alerted']
            if new_alert:
                state['alerted'] = True
            score = state['score']
            count = len(state['features'])
            output.append({
                'id': identity, 'box': d['box'],
                'person_confidence': d.get('person_confidence'),
                'fall_score': round(score, 4) if score is not None else None,
                'window_frames': count, 'window_target': self.FRAMES,
                'fall_elapsed': round(max(0, now-state['fall_since']), 2) if state['fall_since'] is not None else 0.,
                'streak': state['positive'], 'danger': danger,
                'pending': state['positive'] > 0 and not danger,
                'newAlert': new_alert,
                'state': 'FALL' if danger else 'PENDING' if state['positive'] else 'ANALYZING' if score is not None else 'COLLECTING',
            })
        self.tracks = output
        return output
