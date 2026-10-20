"""Validate RTSP credential synchronization without printing/rotating secrets."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
from io import StringIO

from fallguard import camera_receiver_setup as camera


class RepairTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.env = root / '.env'
        self.config = root / 'mediamtx.yml'
        self.connection = root / 'LARIX_CONNECTION.txt'
        self.secret_read = 'another-reader-secret-456'
        self.secret_pub = 'existing-publisher-secret-123'
        self.config.write_text(camera.make_config(self.secret_pub, self.secret_read), encoding='utf-8')
        self.env.write_text(
            'FALLGUARD_PASSWORD=local-password-abcdef\n'
            'TELEGRAM_GATEWAY_KEY=do-not-touch-key\n'
            'CCTV_URL=rtsp://fallguard_read:old-pass@127.0.0.1:8554/live/fallguard\n'
            'CCTV_NAME=Camera Larix\n', encoding='utf-8')
        for name, value in [('ROOT', root), ('ENV', self.env),
                            ('CONFIG', self.config), ('CONNECTION', self.connection)]:
            patcher = patch.object(camera, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_repairs_only_reader_url_and_creates_one_backup(self):
        before_config = self.config.read_bytes()
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(camera.diagnose(), 0)
            self.assertEqual(camera.repair(), 0)
        result = self.env.read_text()
        self.assertIn('CCTV_URL=rtsp://fallguard_read:another-reader-secret-456@127.0.0.1:8554/live/fallguard', result)
        self.assertIn('TELEGRAM_GATEWAY_KEY=do-not-touch-key', result)
        self.assertIn('FALLGUARD_PASSWORD=local-password-abcdef', result)
        self.assertEqual(self.config.read_bytes(), before_config)
        self.assertIn('old-pass', (self.config.parent/'.env.backup.camera-auth').read_text())
        self.assertNotIn(self.secret_read, stdout.getvalue())
        self.assertNotIn(self.secret_pub, stdout.getvalue())
        self.assertEqual(camera.camera_auth_status()[0], True)

    def test_repair_idempotent_and_backup_not_overwritten(self):
        with redirect_stdout(StringIO()):
            camera.repair()
        backup = self.config.parent / '.env.backup.camera-auth'
        previous = backup.read_bytes()
        with redirect_stdout(StringIO()):
            self.assertEqual(camera.repair(), 0)
        self.assertEqual(previous, backup.read_bytes())

    def test_custom_camera_is_not_overwritten(self):
        self.env.write_text('CCTV_URL=rtsp://example.com:554/another\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            camera.repair()
        self.assertIn('example.com', self.env.read_text())
        self.assertFalse((self.config.parent/'.env.backup.camera-auth').exists())

    def test_missing_reader_fails_closed(self):
        self.config.write_text(camera.make_config(self.secret_pub, self.secret_read).replace('fallguard_read','other_user'), encoding='utf-8')
        with self.assertRaises(ValueError):
            camera.repair()
        self.assertIn('old-pass', self.env.read_text())

    def test_no_credentials_in_startup_warning(self):
        stdout = StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(camera.diagnose(), 0)
        self.assertIn('chua khop', stdout.getvalue())
        self.assertNotIn(self.secret_read, stdout.getvalue())
        self.assertNotIn(self.secret_pub, stdout.getvalue())


if __name__ == '__main__':
    unittest.main()
