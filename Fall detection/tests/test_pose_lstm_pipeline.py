"""New regression tests: 32-frame pose windows + BiLSTM, not old frame timer."""
import os
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

from fallguard.cctv import CameraSettings, FallTracker
from fallguard.detector import feature_from_pose

os.environ.setdefault('FALLGUARD_PASSWORD', 'Testing-Only-Password-Long-123')
from fallguard.server import create_app


def detection(box=None, pose_valid=True, tracking_id=5):
    return {'box': box or [.1,.15,.5,.8], 'tracking_id': tracking_id,
            'pose_feature': np.ones(55, dtype=np.float32),
            'pose_valid': pose_valid, 'person_confidence': .9}


def test_fall_alert_requires_full_pose_history_and_multiple_scores():
    tracker = FallTracker()
    calls = []

    def scorer(sequences):
        calls.append(tuple(x.shape for x in sequences))
        return [.98] * len(sequences)

    for i in range(31):
        t = tracker.update([detection()], .8, 3, i * .15, scorer)[0]
        assert t['fall_score'] is None
        assert not t['newAlert']
        assert t['state'] == 'COLLECTING'
    for i in (31, 32):
        t = tracker.update([detection()], .8, 3, i * .15, scorer)[0]
        assert t['pending'] and not t['newAlert']
    t = tracker.update([detection()], .8, 3, 33*.15, scorer)[0]
    assert t['danger'] and t['newAlert'] and t['fall_score'] == .98
    assert all(shape == (32,55) for batch in calls for shape in batch)
    t = tracker.update([detection()], .8, 3, 34*.15, scorer)[0]
    assert t['danger'] and not t['newAlert']


def test_no_alert_without_model_scores():
    tracker = FallTracker()
    for i in range(50):
        track = tracker.update([detection()], .8, 3, i * .15)[0]
    assert track['fall_score'] is None
    assert not track['danger']


def test_recovery_rearms_after_eight_negative_windows():
    tracker = FallTracker()
    probs = [0.98] * 3 + [0.02] * 8 + [0.97] * 3

    def scorer(batch):
        return [probs.pop(0)] * len(batch)

    events = 0
    for i in range(31 + 3 + 8 + 3):
        t = tracker.update([detection()], .8, 3, i * .15, scorer)[0]
        events += int(t['newAlert'])
    assert events == 2
    assert not probs


def test_camera_restart_and_missing_person_wipe_stale_window():
    tracker = FallTracker()
    calls = []
    def scorer(xs):
        calls.append(xs)
        return [.99 for _ in xs]
    for i in range(31):
        tracker.update([detection()], .8, 3, i*.15, scorer)
    assert not calls
    t = tracker.update([detection()], .8, 3, 8.0, scorer)[0]
    assert t['window_frames'] == 1
    assert not calls
    tracker.reset()
    t = tracker.update([detection()], .8, 3, 9.0, scorer)[0]
    assert t['window_frames'] == 1
    tracker.update([], .8, 3, 9.15, scorer)
    t = tracker.update([detection()], .8, 3, 10.2, scorer)[0]
    assert t['window_frames'] == 1


def test_separate_pose_buffers_for_multiple_people():
    tracker = FallTracker()
    def scorer(xs):
        return [float(x[0,0]) for x in xs]
    for i in range(34):
        a = detection(box=[.1,.1,.35,.9], tracking_id=7)
        b = detection(box=[.55,.1,.8,.9], tracking_id=8)
        a['pose_feature'][:] = .95
        b['pose_feature'][:] = .02
        result = tracker.update([a,b], .8, 3, i*.15, scorer)
    assert result[0]['newAlert'] and result[0]['danger']
    assert not result[1]['danger']
    assert result[0]['id'] != result[1]['id']


def test_feature_extraction_matches_kaggle_formula():
    pts = np.array([[.20 + i*.01, .10 + i*.015] for i in range(17)], dtype=np.float32)
    scores = np.linspace(.1, 1, 17, dtype=np.float32)
    box = np.array([60, 20, 240, 270], dtype=np.float32)
    v, valid = feature_from_pose(box, pts, scores, height=300, width=400)
    cx,cy = (60+240)/(2*400),(20+270)/(2*300)
    bw,bh = (240-60)/400,(270-20)/300
    visible = scores >= .25
    rel=(pts-np.array([cx,cy],np.float32))/max(bw,bh)
    rel[~visible]=0
    expected=np.concatenate((np.column_stack((rel,np.where(visible,scores,0))).reshape(-1),
                             [bw/bh,cy,bh,visible.mean()])).astype('float32')
    assert valid and v.shape == (55,)
    assert np.allclose(v,expected)


class FakeCamera:
    def __init__(self, config):
        self.enabled=False;self.sequence=0
    def start(self):self.enabled=True
    def stop(self):self.enabled=False
    def close(self):self.enabled=False
    def snapshot(self):
        self.sequence+=1
        return ({'configured': True,'name':'ADB test','enabled':self.enabled,
                 'state':'connected' if self.enabled else 'stopped', 'epoch':0,
                 'sequence':self.sequence, 'frame_age':0.0,
                 'threshold':.8, 'confirmations':3},
                np.full((96,128,3),128,dtype=np.uint8) if self.enabled else None)


class FakeModel:
    calls=0
    device='cpu'
    def predict(self, frame):
        type(self).calls+=1
        return {'detections':[detection()], 'width':frame.shape[1], 'height':frame.shape[0]}
    def score_sequences(self, seqs):
        return [.01]*len(seqs)


def login(client):
    response=client.post('/api/auth/login',json={'password':os.environ['FALLGUARD_PASSWORD']})
    assert response.status_code == 200


def test_dashboard_cctv_api_uses_new_window_size():
    FakeModel.calls=0
    app=create_app(factory=FakeModel,camera_factory=FakeCamera,
        camera_settings=CameraSettings(url='adb:back'))
    with TestClient(app) as client:
        assert client.get('/api/cctv/view').status_code == 401
        login(client)
        assert client.get('/camera').status_code == 404
        assert client.get('/').status_code == 200
        assert client.post('/api/cctv/start').status_code == 200
        assert client.get('/api/cctv/frame').status_code == 200
        s=client.post('/api/cctv/analysis',json={'enabled':True}).json()
        assert s['analysis_enabled'] is True and s['fall_window_frames'] == 32
        time.sleep(.55)
        assert FakeModel.calls > 0
        view=client.get('/api/cctv/view').json()['view']
        assert view is not None and not any(t['newAlert'] for t in view['tracks'])
        assert client.post('/api/cctv/analysis',json={'enabled':False}).json()['analysis_enabled'] is False
        assert client.get('/api/cctv/view').json()['view'] is None


def test_real_uploaded_lstm_checkpoint_loads_and_scores(monkeypatch):
    """Load shipped user checkpoint without downloading YOLO; execute actual torch forward."""
    import sys
    import types
    import torch
    from pathlib import Path
    from fallguard import detector

    class FakePose:
        pass

    # YOLO is imported lazily in production; unit test needs only BiLSTM.
    monkeypatch.setitem(sys.modules, 'ultralytics', types.SimpleNamespace(YOLO=object))
    model = detector.Detector(pose=FakePose())
    assert model.frames == 32 and model.img_size == 384
    actual = model.score_sequences([np.zeros((32, 55), dtype=np.float32),
                                    np.ones((32, 55), dtype=np.float32)])
    assert len(actual) == 2
    assert all(np.isfinite(v) and 0 <= v <= 1 for v in actual)
    for weight in model.model.parameters():
        assert torch.isfinite(weight).all()
