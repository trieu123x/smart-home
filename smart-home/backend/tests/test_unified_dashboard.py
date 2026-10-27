"""Integration coverage without a physical camera, GPU, broker or Telegram network."""
import asyncio
import os
from pathlib import Path
import tempfile
import time

os.environ['MQTT_ENABLED'] = 'false'
os.environ['SEED_DEMO'] = 'false'
os.environ['FALL_ENABLED'] = 'true'
os.environ['CCTV_AUTOSTART'] = '1'
os.environ['DASHBOARD_PASSWORD'] = 'Integration-test-password-123'
os.environ['TELEGRAM_GATEWAY_URL'] = ''
os.environ['TELEGRAM_GATEWAY_PATH'] = ''
os.environ['TELEGRAM_GATEWAY_KEY'] = ''
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(tempfile.mkdtemp()) / 'test.db')

import numpy as np
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from sqlalchemy import select, func

from app import main, models, mqtt_bridge
from app.database import Base, engine, SessionLocal
from app.dashboard_auth import auth
from app.fall_events import record_incident
from fallguard.runtime import FallRuntime
from fallguard.cctv import FallTracker


class Camera:
    def __init__(self, config):
        self.enabled = False
        self.epoch = self.sequence = 0
    def start(self):
        self.enabled = True
        self.epoch += 1
    def stop(self):
        self.enabled = False
        self.epoch += 1
    def close(self):
        self.stop()
    def snapshot(self):
        self.sequence += 1
        return ({'configured': True, 'name': 'Test camera', 'enabled': self.enabled,
                 'state': 'connected' if self.enabled else 'stopped', 'epoch': self.epoch,
                 'sequence': self.sequence, 'threshold': .8, 'confirmations': 3},
                np.full((96, 128, 3), 127, np.uint8) if self.enabled else None)


class Model:
    device = 'cpu'
    calls = 0
    def predict(self, frame):
        self.calls += 1
        return {'width': 128, 'height': 96, 'detections': [
            {'box': [.1, .1, .8, .9], 'tracking_id': 1,
             'pose_feature': np.ones(55, np.float32), 'pose_valid': True}]}
    def score_sequences(self, sequences):
        return [.98 for _ in sequences]


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('Condition timed out')


@pytest.fixture
def client(monkeypatch):
    Base.metadata.drop_all(engine)
    auth.sessions.clear()
    auth.failed.clear()
    monkeypatch.setattr(main, 'FallRuntime', lambda callback, heartbeat:
                        FallRuntime(callback, heartbeat, factory=Model, camera_factory=Camera))
    with TestClient(main.app) as value:
        yield value


def login(client):
    response = client.post('/api/auth/login', json={'password': os.environ['DASHBOARD_PASSWORD']})
    assert response.status_code == 200, response.text


def test_shared_session_protects_dashboard_and_camera(client):
    for route in ('/api/fall/view', '/api/fall/frame', '/api/events', '/api/summary', '/api/devices'):
        assert client.get(route).status_code == 401
    assert client.get('/api/health').status_code == 200
    assert client.post('/api/auth/login', json={'password': 'wrong'}).status_code == 401
    login(client)
    for route in ('/api/fall/view', '/api/events', '/api/summary', '/api/devices'):
        assert client.get(route).status_code == 200
    assert client.post('/api/auth/logout').status_code == 200
    assert client.get('/api/fall/view').status_code == 401


def test_websocket_requires_same_session(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws'):
            pass
    login(client)
    with client.websocket_connect('/ws') as ws:
        ws.send_text('ping')
        response = client.get('/api/summary')
        assert response.status_code == 200


def test_cross_site_camera_control_is_rejected(client):
    login(client)
    assert client.post('/api/fall/start', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/api/fall/start', headers={'Origin': 'http://localhost:3000'}).status_code == 200


def test_logout_blocks_further_websocket_events(client):
    login(client)
    with client.websocket_connect('/ws') as ws:
        # Clear any queued initial heartbeat before testing an explicit broadcast.
        client.post('/api/auth/logout')
        client.portal.call(main.manager.broadcast, 'private-test', {'secret': True})
        with pytest.raises(WebSocketDisconnect):
            while True:
                message = ws.receive_json()
                assert message['type'] != 'private-test'


def test_invalid_origin_and_preflight(client):
    login(client)
    assert client.post('/api/fall/start', headers={'Origin': 'http://[invalid'}).status_code == 403
    response = client.options('/api/fall/start', headers={'Origin': 'http://localhost:3000',
                                                       'Access-Control-Request-Method': 'POST'})
    assert response.status_code == 200


def test_missing_dashboard_password_fails_closed(client, monkeypatch):
    monkeypatch.setattr(auth, 'password', '')
    assert client.post('/api/auth/login', json={'password': 'anything'}).status_code == 503
    assert client.get('/api/fall/view').status_code == 401


def test_device_ingest_keeps_key_auth_without_browser_session(client):
    payload = {'device_code': 'test-esp', 'type': 'fall_detected', 'severity': 'critical', 'message': 'Test fall'}
    assert client.post('/api/ingest/event', json=payload).status_code == 401
    assert client.post('/api/ingest/event', json=payload,
                       headers={'X-Device-Key': main.settings.device_api_key}).status_code == 202


def test_camera_preview_analysis_and_stop(client):
    login(client)
    wait_until(lambda: client.get('/api/fall/view').json()['camera']['ready'])
    frame = client.get('/api/fall/frame')
    assert frame.status_code == 200 and frame.content.startswith(b'\xff\xd8')
    assert client.get('/api/fall/view').json()['view'] is None
    assert client.post('/api/fall/analysis', json={'enabled': True}).status_code == 200
    wait_until(lambda: client.get('/api/fall/view').json()['view'] is not None)
    data = client.get('/api/fall/view').json()['view']
    assert data['tracks'][0]['window_frames'] > 0
    assert data['tracks'][0]['danger'] is False
    assert client.post('/api/fall/stop').status_code == 200
    data = client.get('/api/fall/view').json()
    assert data['view'] is None and data['camera']['analysis_enabled'] is False
    assert client.get('/api/fall/frame').status_code == 204


def test_confirmed_fall_reaches_history_banner_and_summary(client):
    login(client)
    wait_until(lambda: client.get('/api/fall/view').json()['camera']['ready'])
    client.post('/api/fall/analysis', json={'enabled': True})
    wait_until(lambda: any(event['type'] == 'fall_detected' for event in client.get('/api/events').json()))
    events = [event for event in client.get('/api/events').json() if event['type'] == 'fall_detected']
    assert len(events) == 1
    assert events[0]['severity'] == 'critical' and not events[0]['acknowledged']
    assert client.get('/api/summary').json()['falls_last_24h'] == 1
    assert client.post(f"/api/events/{events[0]['id']}/ack").json()['acknowledged'] is True
    assert client.get('/api/summary').json()['unacknowledged_alerts'] == 0


def test_incident_persistence_is_idempotent_and_survives_runtime_replacement(client):
    incident = {'key': 'test-stable-id', 'source': 'Living room', 'person_id': 3,
                'score': .98, 'time': '2026-10-27T10:00:00+00:00'}
    asyncio.run(record_incident(incident))
    asyncio.run(record_incident(incident))
    with SessionLocal() as db:
        assert db.scalar(select(func.count(models.Event.id)).where(models.Event.type == 'fall_detected')) == 1
        assert db.get(models.FallIncident, incident['key']).score == .98
    login(client)
    assert len(client.get('/api/events?type=fall_detected').json()) == 1


def test_tracker_requires_32_poses_and_three_confirmations():
    tracker = FallTracker()
    pose = {'box': [.1, .1, .8, .9], 'tracking_id': 1,
            'pose_feature': np.ones(55, np.float32), 'pose_valid': True}
    for i in range(33):
        track = tracker.update([pose], .8, 3, i * .15, lambda _: [.98])[0]
        assert not track['newAlert']
    assert tracker.update([pose], .8, 3, 33 * .15, lambda _: [.98])[0]['newAlert']
    assert not tracker.update([pose], .8, 3, 34 * .15, lambda _: [.98])[0]['newAlert']


def test_model_failure_leaves_dashboard_available(client):
    login(client)
    runtime = main.app.state.fall
    runtime.model = None
    runtime.error = 'Test model failure'
    assert client.get('/api/summary').status_code == 200
    assert client.get('/api/fall/view').json()['camera']['error'] == 'Test model failure'
    assert client.post('/api/fall/analysis', json={'enabled': True}).status_code == 503


def test_mqtt_alarm_does_not_change_system_mode(monkeypatch):
    class Broker:
        def __init__(self): self.commands = []
        def publish(self, *args, **kwargs): self.commands.append((args, kwargs))
    broker = Broker()
    monkeypatch.setattr(mqtt_bridge, '_client', broker)
    monkeypatch.setattr(mqtt_bridge, 'get_state', lambda: {'broker_ok': True, 'esp_online': True, 'mode': 'auto'})
    asyncio.run(mqtt_bridge.fall_alarm())
    assert broker.commands == [((mqtt_bridge.T_CMD + 'fall_alarm', 'ON'), {'qos': 1, 'retain': False})]
