"""Configurable gateway routes, tested offline with the standard library."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from fallguard import telegram_client as client
from fallguard.telegram_config import _read_env


class GatewayPathTests(unittest.TestCase):
    def setUp(self):
        settings = patch.multiple(client,
                                  GATEWAY_URL='https://example.invalid/',
                                  GATEWAY_PATH='/gateway/v1/notify',
                                  GATEWAY_API_KEY='test-key-' + 'x' * 32)
        settings.start()
        self.addCleanup(settings.stop)

    def test_existing_bot_route_remains_unchanged(self):
        self.assertEqual(client._gateway_endpoint(),
                         'https://example.invalid/gateway/v1/notify')
        self.assertTrue(client.is_configured())

    def test_custom_path_controls_post_destination_and_preserves_contract(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {'ok': True, 'sent': 1, 'photo': True}).encode()
        with patch.object(client, 'GATEWAY_PATH', '/api/custom-alerts'), \
                patch.object(client.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = response
            photo = b'\xff\xd8\xfftest\xff\xd9'
            result = client.send_notification(title='Test', message='Test alert',
                                              level='critical', event_id='test-1',
                                              image_jpeg=photo)
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://example.invalid/api/custom-alerts')
            self.assertEqual(request.get_method(), 'POST')
            self.assertEqual(request.get_header('X-gateway-key'), client.GATEWAY_API_KEY)
            payload = json.loads(request.data)
            self.assertEqual(set(payload), {'title', 'message', 'level', 'event_id', 'image_base64'})
            self.assertTrue(result['sent'])
            self.assertTrue(result['photo'])

    def test_missing_path_has_no_hardcoded_fallback(self):
        with patch.object(client, 'GATEWAY_PATH', ''):
            self.assertFalse(client.is_configured())
            with self.assertRaisesRegex(client.TelegramError, 'TELEGRAM_GATEWAY_PATH'):
                client._gateway_endpoint()

    def test_invalid_paths_fail_before_network_request(self):
        for value in ['notify', '//other.invalid/api', 'https://other.invalid/api',
                      '/api?key=test', '/api#fragment', '/api\\route', '/api route',
                      '/api\nroute', '/api\x00route']:
            with self.subTest(value=value), patch.object(client, 'GATEWAY_PATH', value), \
                    patch.object(client.urllib.request, 'build_opener') as build:
                self.assertFalse(client.is_configured())
                with self.assertRaises(client.TelegramError):
                    client.send_notification(title='Test', message='Test')
                build.assert_not_called()

    def test_url_must_still_be_https_origin(self):
        for value in ['http://example.invalid', 'https://example.invalid/api',
                      'https://user:pass@example.invalid', 'https://example.invalid?q=1']:
            with self.subTest(value=value), patch.object(client, 'GATEWAY_URL', value):
                self.assertFalse(client.is_configured())

    def test_404_points_to_environment_settings_without_exposing_key(self):
        error = urllib.error.HTTPError('https://example.invalid/api/test', 404,
                                       'Not found', {}, io.BytesIO(b''))
        with patch.object(client.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = error
            with self.assertRaisesRegex(client.TelegramError, 'TELEGRAM_GATEWAY_PATH') as ctx:
                client.send_notification(title='Test', message='Test')
            self.assertNotIn(client.GATEWAY_API_KEY, str(ctx.exception))

    def test_env_file_parses_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text('TELEGRAM_GATEWAY_PATH="/api/from-file"\n', encoding='utf-8')
            self.assertEqual(_read_env(path)['TELEGRAM_GATEWAY_PATH'], '/api/from-file')

    def test_process_environment_controls_config_on_startup(self):
        environment = dict(os.environ, TELEGRAM_GATEWAY_PATH='/api/from-process')
        result = subprocess.run(
            [sys.executable, '-c',
             'from fallguard.telegram_config import GATEWAY_PATH; print(GATEWAY_PATH)'],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.strip(), '/api/from-process')


if __name__ == '__main__':
    unittest.main()
