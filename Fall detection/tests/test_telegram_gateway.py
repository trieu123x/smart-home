"""Regression tests: FallGuard only calls the EXISTING /gateway/v1/notify API."""
import base64
import io
import json
import os
import urllib.error

import pytest

from fallguard import telegram_client as client

URL = 'https://telegram-owner.vercel.app'
KEY = 'A' * 43


class Response:
    def __init__(self, content=None):
        self.content = content or {'ok': True, 'sent': 3, 'failed': 0, 'duplicate': False}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return json.dumps(self.content).encode()


class Opener:
    def __init__(self, output, response=None):
        self.output = output
        self.response = response or Response()

    def open(self, request, timeout):
        assert request.full_url == URL + '/gateway/v1/notify'
        assert request.headers['X-gateway-key'] == KEY
        assert request.get_method() == 'POST'
        assert request.headers['Content-type'] == 'application/json'
        assert timeout >= 30
        self.output.append(json.loads(request.data))
        return self.response


@pytest.fixture(autouse=True)
def gateway_settings(monkeypatch):
    monkeypatch.setattr(client, 'GATEWAY_URL', URL)
    monkeypatch.setattr(client, 'GATEWAY_API_KEY', KEY)


def test_notification_matches_deployed_gateway_contract(monkeypatch):
    output = []
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: Opener(output))
    assert client.is_configured()
    result = client.send_notification(title='FallGuard', message='Camera 01: ngã',
                                      level='critical', event_id='fallguard-001')
    assert result['sent'] is True and result['recipients'] == 3
    assert output == [{
        'title': 'FallGuard', 'message': 'Camera 01: ngã',
        'level': 'critical', 'event_id': 'fallguard-001',
    }]
    assert 'chat_id' not in json.dumps(output)
    assert 'bot_token' not in json.dumps(output).lower()
    assert 'image_base64' not in json.dumps(output)


def test_invalid_config_and_http_only_refused(monkeypatch):
    monkeypatch.setattr(client, 'GATEWAY_URL', 'http://telegram-owner.vercel.app')
    assert not client.is_configured()
    with pytest.raises(client.TelegramError, match='TELEGRAM_GATEWAY_URL'):
        client.send_notification(title='Test', message='Test')
    monkeypatch.setattr(client, 'GATEWAY_URL', URL)
    monkeypatch.setattr(client, 'GATEWAY_API_KEY', 'tiny')
    assert not client.is_configured()
    with pytest.raises(client.TelegramError, match='TELEGRAM_GATEWAY_KEY'):
        client.send_notification(title='Test', message='Test')


def test_http_errors_do_not_leak_secrets(monkeypatch):
    class Failure:
        def open(self, request, timeout):
            raise urllib.error.HTTPError(request.full_url, 401, 'Unauthorized', {}, io.BytesIO(b'secret'))
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: Failure())
    with pytest.raises(client.TelegramError, match='API key') as error:
        client.send_notification(title='Test', message='Test')
    assert KEY not in str(error.value)
    assert 'secret' not in str(error.value)


def test_duplicate_is_not_counted_as_fresh_delivery(monkeypatch):
    response = Response({'ok': True, 'duplicate': True, 'source': 'fall_detection', 'event_id': 'fallguard-1'})
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: Opener([], response))
    result = client.send_notification(title='Test', message='Test', event_id='fallguard-1')
    assert result['sent'] is False and result['reason'] == 'duplicate'


def test_no_subscribers_and_partial_delivery_fail(monkeypatch):
    for value in [
        {'ok': True, 'sent': 0, 'subscribers': 0},
        {'ok': False, 'sent': 2, 'failed': 1, 'subscribers': 3},
    ]:
        monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: Opener([], Response(value)))
        with pytest.raises(client.TelegramError):
            client.send_notification(title='Test', message='Test')


def test_rejects_embedded_credentials_in_gateway_url(monkeypatch):
    monkeypatch.setattr(client, 'GATEWAY_URL', 'https://user:password@telegram-owner.vercel.app')
    assert not client.is_configured()
    with pytest.raises(client.TelegramError, match='TELEGRAM_GATEWAY_URL'):
        client.send_notification(title='Test', message='Test')


def test_jpeg_photo_sent_as_base64_with_alert(monkeypatch):
    output = []
    class PhotoOpener(Opener):
        def __init__(self, output):
            super().__init__(output, Response({'ok': True, 'sent': 3, 'failed': 0, 'duplicate': False, 'photo': True}))
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: PhotoOpener(output))
    photo = b'\xff\xd8\xff' + b'jpeg-bits' + b'\xff\xd9'
    result = client.send_notification(title='FallGuard', message='Ngã', level='critical',
                                      event_id='fallguard-123', image_jpeg=photo)
    assert result['photo'] is True
    assert result['sent'] is True
    assert base64.b64decode(output[0]['image_base64']) == photo
    assert output[0]['event_id'] == 'fallguard-123'


def test_gw_old_version_must_not_silently_downgrade_to_text(monkeypatch):
    output = []
    monkeypatch.setattr(client.urllib.request, 'build_opener', lambda *_: Opener(output))
    photo = b'\xff\xd8\xff' + b'jpeg-bits' + b'\xff\xd9'
    with pytest.raises(client.TelegramError, match='chưa xác nhận gửi ảnh'):
        client.send_notification(title='FallGuard', message='Ngã', image_jpeg=photo)
