"""Dashboard's Telegram test endpoint must call the gateway, not Bot API."""
import os

from fastapi.testclient import TestClient

os.environ.setdefault('FALLGUARD_PASSWORD', 'Testing-Only-Password-Long-123')
from fallguard import server
from fallguard.cctv import CameraSettings


class Camera:
    def __init__(self, config):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass

    def snapshot(self):
        return ({'state': 'stopped', 'name': 'test', 'epoch': 0, 'sequence': 0,
                 'configured': False, 'enabled': False}, None)


class Model:
    device = 'cpu'


def test_protected_test_button_sends_gateway_broadcast(monkeypatch):
    calls = []
    monkeypatch.setattr(server, 'telegram_configured', lambda: True)

    def fake_send_notification(**kwargs):
        calls.append(kwargs)
        return {'sent': True, 'recipients': 2}

    monkeypatch.setattr(server, 'send_notification', fake_send_notification)
    app = server.create_app(factory=Model, camera_factory=Camera,
                            camera_settings=CameraSettings())
    with TestClient(app) as client:
        assert client.post('/api/telegram/test').status_code == 401
        assert client.post('/api/auth/login', json={
            'password': os.environ['FALLGUARD_PASSWORD'],
        }).status_code == 200
        response = client.post('/api/telegram/test')
        assert response.status_code == 200
        assert response.json()['sent'] is True
        assert response.json()['recipients'] == 2
        assert len(calls) == 1
        assert calls[0]['level'] == 'info'
        assert 'chat_id' not in calls[0]
