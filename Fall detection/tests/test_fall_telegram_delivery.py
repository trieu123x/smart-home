"""Regression tests for confirmed fall -> broadcast, even if camera tracking drops."""
import os
import time

import numpy as np
from fastapi.testclient import TestClient

os.environ.setdefault('FALLGUARD_PASSWORD', 'Testing-Only-Password-Long-123')
from fallguard import server
from fallguard.cctv import CameraSettings
from fallguard.telegram_client import TelegramError


class Camera:
    def __init__(self, settings):
        self.enabled = False
        self.seq = 0

    def start(self):
        self.enabled = True

    def stop(self):
        self.enabled = False

    def close(self):
        self.enabled = False

    def snapshot(self):
        self.seq += 1
        return ({'configured': True, 'name': 'Camera test',
                 'state': 'connected' if self.enabled else 'stopped',
                 'enabled': self.enabled, 'epoch': 0, 'sequence': self.seq,
                 'frame_age': 0.0, 'threshold': 0.4, 'confirmations': 3},
                np.zeros((60, 90, 3), dtype=np.uint8) if self.enabled else None)


class Model:
    device = 'cpu'

    def predict(self, frame):
        return {'detections': [{'box': [.1, .1, .8, .9], 'fall_score': .98}],
                'width': frame.shape[1], 'height': frame.shape[0]}


class OneFrameFallTracker:
    """Emits one confirmed alert, then all subsequent frames lose the person."""
    def __init__(self):
        self.count = 0

    def reset(self):
        pass

    def update(self, *args):
        self.count += 1
        if self.count != 1:
            return []
        return [{'id': 1, 'fall_score': .98, 'newAlert': True, 'danger': True,
                 'box': [.1, .1, .8, .9]}]


def login(client):
    assert client.post('/api/auth/login', json={'password': os.environ['FALLGUARD_PASSWORD']}).status_code == 200


def test_automatic_delivery_retries_after_person_disappears(monkeypatch):
    monkeypatch.setattr(server, 'FallTracker', OneFrameFallTracker)
    monkeypatch.setattr(server, 'telegram_configured', lambda: True)
    monkeypatch.setattr(server, 'TELEGRAM_RETRY_SECONDS', 0.05)
    sent = []

    def fake_send_notification(**kwargs):
        sent.append(kwargs)
        if len(sent) == 1:
            raise TelegramError('Gateway dang ban')
        return {'sent': True, 'recipients': 2}

    monkeypatch.setattr(server, 'send_notification', fake_send_notification)
    app = server.create_app(factory=Model, camera_factory=Camera,
                            camera_settings=CameraSettings(url='rtsp://example.org/live/fallguard'))
    with TestClient(app) as client:
        login(client)
        assert client.post('/api/cctv/start').status_code == 200
        assert client.post('/api/cctv/analysis', json={'enabled': True}).status_code == 200
        end = time.monotonic() + 2.0
        result = None
        while time.monotonic() < end:
            result = client.get('/api/cctv/view').json()
            if result['events'] and result['events'][0]['telegram'] == 'sent':
                break
            time.sleep(0.03)
        assert result['events'], 'no confirmed fall event'
        assert result['events'][0]['telegram'] == 'sent', result
        assert result['camera']['telegram'] == 'sent'
        assert result['camera']['telegram_detail'].endswith('2 người.')
        assert len(sent) == 2
        assert sent[0]['event_id'] == sent[1]['event_id'], 'retry must reuse same idempotency key'


def test_gateway_error_visible_to_authenticated_dashboard(monkeypatch):
    monkeypatch.setattr(server, 'telegram_configured', lambda: True)

    def fail(**kwargs):
        raise TelegramError('Gateway từ chối API key. Kiểm tra trên Vercel.')

    monkeypatch.setattr(server, 'send_notification', fail)
    app = server.create_app(factory=Model, camera_factory=Camera,
                            camera_settings=CameraSettings())
    with TestClient(app) as client:
        login(client)
        response = client.post('/api/telegram/test')
        assert response.status_code == 502
        assert 'API key' in response.json()['detail']
        state = client.get('/api/cctv/status').json()
        assert state['telegram'] == 'error'
        assert 'API key' in state['telegram_detail']
