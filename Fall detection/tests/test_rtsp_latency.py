import os
import unittest
from unittest import mock
from fallguard.cctv import _configure_rtsp_latency, open_camera


class RtspLatencyTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ('CCTV_LOW_LATENCY', 'OPENCV_FFMPEG_CAPTURE_OPTIONS')}
        for k in self.saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def test_default_rtsp_low_latency(self):
        _configure_rtsp_latency('rtsp://localhost:8554/live/fallguard')
        self.assertIn('fflags;nobuffer', os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'])
        self.assertIn('rtsp_transport;tcp', os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'])

    def test_disable_keeps_default(self):
        os.environ['CCTV_LOW_LATENCY'] = '0'
        _configure_rtsp_latency('rtsp://localhost:8554/live/fallguard')
        self.assertNotIn('OPENCV_FFMPEG_CAPTURE_OPTIONS', os.environ)

    def test_non_rtsp_keeps_default(self):
        _configure_rtsp_latency('https://example.org/mjpeg')
        self.assertNotIn('OPENCV_FFMPEG_CAPTURE_OPTIONS', os.environ)

    def test_explicit_ffmpeg_options_kept(self):
        os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'
        _configure_rtsp_latency('rtsp://localhost:8554/live/fallguard')
        self.assertEqual(os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'], 'rtsp_transport;tcp')

    def test_capture_timeout_properties_unchanged(self):
        fake = mock.Mock()
        fake.CAP_FFMPEG = 200
        fake.CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        fake.CAP_PROP_READ_TIMEOUT_MSEC = 54
        with mock.patch.dict('sys.modules', {'cv2': fake}):
            open_camera('rtsp://localhost:8554/live/fallguard')
        fake.VideoCapture.assert_called_once_with('rtsp://localhost:8554/live/fallguard', 200, [53,5000,54,5000])


if __name__ == '__main__': unittest.main()
