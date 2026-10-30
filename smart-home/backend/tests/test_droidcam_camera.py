"""DroidCam LAN validation and two independent capture threads; no phone required."""
import time
import unittest

import numpy as np
from fallguard.cctv import CameraReader, CameraSettings, droidcam_url, parse_droidcam_url


class FakeCapture:
    def __init__(self, url):
        self.url = url
        self.closed = False

    def isOpened(self):
        return True

    def read(self):
        time.sleep(.02)
        return True, np.zeros((24, 32, 3), dtype=np.uint8)

    def release(self):
        self.closed = True


class DroidCamTests(unittest.TestCase):
    def test_validate_lan_urls(self):
        self.assertEqual(droidcam_url('192.168.1.20'), 'http://192.168.1.20:4747/video')
        self.assertEqual(parse_droidcam_url('http://10.0.0.15:4848/video'), 'http://10.0.0.15:4848/video')
        for host in ('127.0.0.1', '8.8.8.8', 'example.com', '169.254.10.1', '0.0.0.0'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                droidcam_url(host)
        for url in ('https://192.168.1.2/video', 'http://192.168.1.2:4747/admin',
                    'http://user:pass@192.168.1.2:4747/video', 'http://192.168.1.2:4747/video?x=1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                parse_droidcam_url(url)

    def test_reconfigure_stream(self):
        camera = CameraReader(CameraSettings(url=''), opener=FakeCapture, reconnect_seconds=.05)
        try:
            self.assertFalse(camera.snapshot()[0]['configured'])
            camera.configure(CameraSettings(url=droidcam_url('192.168.1.20')))
            deadline = time.monotonic() + 2
            while camera.snapshot()[0]['state'] != 'connected' and time.monotonic() < deadline:
                time.sleep(.02)
            status, frame = camera.snapshot()
            self.assertEqual(status['state'], 'connected')
            self.assertEqual(frame.shape, (24, 32, 3))
            camera.stop()
            self.assertEqual(camera.snapshot()[0]['state'], 'stopped')
        finally:
            camera.close()

class RuntimeSourceTests(unittest.TestCase):
    def test_dual_source_jpeg_preview(self):
        import asyncio
        from fallguard.runtime import FallRuntime
        runtime = FallRuntime(None)
        class FrameReader:
            def snapshot(self):
                return ({'sequence': 1, 'state': 'connected'}, np.zeros((36, 48, 3), dtype=np.uint8))
        runtime.camera = FrameReader()
        runtime.droidcam_camera = FrameReader()
        for source in ('adb', 'droidcam'):
            data, sequence = asyncio.run(runtime.frame(-1, source))
            self.assertEqual(sequence, 1)
            self.assertTrue(data.startswith(b'\xff\xd8'))

    def test_source_switch_clears_old_analysis(self):
        from fallguard.runtime import FallRuntime
        runtime = FallRuntime(None)
        class FakeReader:
            def __init__(self, name): self.name = name
            def snapshot(self):
                return ({'configured': True, 'name': self.name, 'enabled': True,
                         'state': 'connected', 'epoch': 1, 'sequence': 3,
                         'threshold': .8, 'confirmations': 3}, None)
        runtime.camera = FakeReader('ADB')
        runtime.droidcam_camera = FakeReader('DroidCam')
        runtime.view = {'epoch': 1, 'sequence': 3, 'completed_at': time.monotonic()}
        self.assertEqual(runtime.status()['analysis_source'], 'adb')
        runtime.set_source('droidcam')
        self.assertEqual(runtime.status()['name'], 'DroidCam')
        self.assertEqual(runtime.status()['analysis_source'], 'droidcam')
        self.assertIsNone(runtime.view)
        self.assertEqual(runtime.status()['cameras']['adb']['name'], 'ADB')


if __name__ == '__main__':
    unittest.main()
