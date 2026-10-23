"""The fall timer is server-side and MUST never alert on a brief fall."""
import os
import time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from fallguard.cctv import FallTracker, CameraSettings

os.environ.setdefault('FALLGUARD_PASSWORD', 'Testing-Only-Password-Long-123')
from fallguard.server import create_app

FALL = {'box':[.1,.1,.8,.9], 'fall_score':.98}
UP = {'box':[.1,.1,.8,.9], 'fall_score':.01}


def tracked(t, detection=FALL, tracker=None):
    return tracker.update([detection], .4, 3, t)[0]


def test_alert_only_after_five_seconds_and_confirmation_frames():
    tr=FallTracker()
    times=(100,101,102,103,104.99)
    for t in times:
        track=tracked(t,tracker=tr)
        assert not track['danger']
        assert not track['newAlert']
    track=tracked(105.0,tracker=tr)
    assert track['danger'] and track['newAlert']
    assert track['fall_elapsed']==5.0
    track=tracked(105.3,tracker=tr)
    assert track['danger'] and not track['newAlert']


def test_person_stands_up_before_five_seconds():
    tr=FallTracker()
    for t in (0,1,2,3,4):
        assert not tracked(t,tracker=tr)['danger']
    track=tracked(4.9,UP,tr)
    assert not track['danger'] and not track['pending']
    for t in (5,6,7,8,9,9.9):
        assert not tracked(t,tracker=tr)['danger']
    assert tracked(10,tracker=tr)['newAlert']


def test_large_frame_gap_does_not_count_as_five_seconds():
    tr=FallTracker()
    tracked(0,tracker=tr)
    tracked(1,tracker=tr)
    after_gap=tracked(9,tracker=tr)
    assert after_gap['streak']==1
    assert after_gap['fall_elapsed']==0
    assert not after_gap['newAlert']


def test_identity_change_cannot_reuse_timer():
    tr=FallTracker()
    tracked(0,tracker=tr)
    tracked(1,tracker=tr)
    new_person={'box':[.0,.0,.05,.05], 'fall_score':.95}
    person=tracked(2,new_person,tr)
    assert person['streak']==1
    assert person['fall_elapsed']==0


def test_missing_detection_and_manual_reset_restart_counter():
    tr=FallTracker()
    tracked(0,tracker=tr)
    tracked(1,tracker=tr)
    assert tr.update([], .4, 3, 2)==[]
    assert not tracked(5,tracker=tr)['newAlert']
    tr.reset()
    assert tracked(9,tracker=tr)['fall_elapsed']==0


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
                 'sequence':self.sequence, 'frame_age':0.0, 'threshold':.4,'confirmations':3},
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
        assert s['analysis_enabled'] is True and s['fall_confirm_seconds']==5.0
        time.sleep(.5)
        assert FakeModel.calls>0
        view=client.get('/api/cctv/view').json()['view']
        assert view is not None and not any(t['newAlert'] for t in view['tracks'])
        assert client.post('/api/cctv/analysis',json={'enabled':False}).json()['analysis_enabled'] is False
        assert client.get('/api/cctv/frame').status_code==200
        assert client.get('/api/cctv/view').json()['view'] is None

