"""Tracking/API regressions for the 32-pose BiLSTM pipeline."""
import os
import time
import numpy as np
from fastapi.testclient import TestClient
from fallguard.cctv import FallTracker, CameraSettings

os.environ.setdefault('FALLGUARD_PASSWORD', 'Testing-Only-Password-Long-123')
from fallguard.server import create_app

# A legacy frame score alone must never be treated as a BiLSTM prediction.
FALL = {'box': [.1, .1, .8, .9], 'fall_score': .98}


def pose(identity=1, valid=True):
    return {'box': [.1, .1, .8, .9], 'tracking_id': identity,
            'pose_feature': np.ones(55, np.float32), 'pose_valid': valid}


def test_legacy_frame_score_cannot_trigger_lstm_alert():
    tracker = FallTracker()
    for i in range(45):
        track = tracker.update([FALL], .8, 3, i * .15)[0]
        assert not track['danger'] and not track['newAlert']
        assert track['fall_score'] is None


def test_new_explicit_identity_cannot_reuse_pose_history():
    tracker = FallTracker()
    for i in range(31):
        old = tracker.update([pose(1)], .8, 3, i * .15)[0]
    new = tracker.update([pose(2)], .8, 3, 31 * .15)[0]
    assert new['id'] != old['id']
    assert new['window_frames'] == 1
    assert not new['newAlert']


def test_too_few_visible_poses_prevents_scoring():
    tracker = FallTracker()
    def unexpected_score(sequences):
        raise AssertionError('Do not score windows with fewer than 7 valid poses')
    for i in range(32):
        track = tracker.update([pose(valid=i < 6)], .8, 3, i * .15,
                               unexpected_score)[0]
    assert track['window_frames'] == 32
    assert track['fall_score'] is None and not track['danger']


def test_large_inference_gap_restarts_pose_collection():
    tracker = FallTracker()
    tracker.update([pose()], .8, 3, 0)
    tracker.update([pose()], .8, 3, .15)
    track = tracker.update([pose()], .8, 3, 9)[0]
    assert track['window_frames'] == 1
    assert track['streak'] == 0 and not track['newAlert']


class FakeCamera:
    def __init__(self,config):
        self.settings=config; self.enabled=False; self.sequence=0
    def start(self):self.enabled=True
    def stop(self):self.enabled=False
    def close(self):self.enabled=False
    def snapshot(self):
        self.sequence+=1
        return ({'configured':True, 'name':'ADB test', 'enabled':self.enabled,
                 'state':'connected' if self.enabled else 'stopped', 'epoch':0,
                 'sequence':self.sequence, 'frame_age':0.0, 'threshold':.8,'confirmations':3},
                np.full((96,128,3),128,dtype=np.uint8) if self.enabled else None)

class FakeModel:
    calls=0
    device='cpu'
    def predict(self,frame):
        type(self).calls+=1
        return {'detections':[FALL], 'width':frame.shape[1], 'height':frame.shape[0]}


def login(client):
    response=client.post('/api/auth/login',json={'password':os.environ['FALLGUARD_PASSWORD']})
    assert response.status_code==200,response.text


def test_dashboard_cctv_api_and_no_browser_publisher():
    FakeModel.calls=0
    app=create_app(factory=FakeModel,camera_factory=FakeCamera,
        camera_settings=CameraSettings(url='adb:back'))
    with TestClient(app) as client:
        assert client.get('/api/cctv/view').status_code==401
        login(client)
        assert client.get('/camera').status_code==404
        assert client.post('/api/detect',content=b'test').status_code==404
        assert client.get('/').status_code==200
        assert client.post('/api/cctv/start').status_code==200
        assert client.get('/api/cctv/frame').status_code==200
        assert FakeModel.calls==0
        s=client.post('/api/cctv/analysis',json={'enabled':True}).json()
        assert s['analysis_enabled'] is True and s['fall_window_frames']==32
        time.sleep(.5)
        assert FakeModel.calls>0
        view=client.get('/api/cctv/view').json()['view']
        assert view is not None and not any(t['newAlert'] for t in view['tracks'])
        assert client.post('/api/cctv/analysis',json={'enabled':False}).json()['analysis_enabled'] is False
        assert client.get('/api/cctv/frame').status_code==200
        assert client.get('/api/cctv/view').json()['view'] is None

