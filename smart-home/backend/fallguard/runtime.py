"""Camera and inference lifecycle owned by the Smart Home backend."""
import asyncio
import base64
import logging
import time
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class FallRuntime:
    def __init__(self, on_fall, on_camera=None, factory=None, camera_factory=None):
        self.on_fall, self.on_camera = on_fall, on_camera
        self.factory, self.camera_factory = factory, camera_factory
        self.camera = self.model = self.config = None
        self.error = None
        self.enabled = False
        self.generation = 0
        self.view = None
        self.closing = False
        self.tasks = []
        self.jobs = set()
        self.session = uuid.uuid4().hex
        self.telegram = 'not_configured'
        self.telegram_detail = 'Chưa cấu hình Telegram Gateway.'
        self.last_alert = {}
        self.telegram_lock = asyncio.Lock()

    async def start(self):
        try:
            from .cctv import CameraReader, CameraSettings
            from .telegram_client import is_configured
            self.config = CameraSettings.load()
            self.camera = (self.camera_factory or CameraReader)(self.config)
            self.telegram = 'configured' if is_configured() else 'not_configured'
            if is_configured():
                self.telegram_detail = 'Telegram Gateway đã sẵn sàng.'
            if self.config.autostart:
                self.camera.start()
            self.tasks = [asyncio.create_task(self._load()), asyncio.create_task(self._monitor())]
        except Exception:
            log.exception('Cannot initialize Fall Detection')
            self.error = 'Chưa khởi tạo được camera AI. Kiểm tra cấu hình và thư viện trên máy chủ.'

    async def _load(self):
        try:
            from .detector import Detector
            self.model = await asyncio.to_thread(self.factory or Detector)
        except Exception:
            log.exception('Cannot load Fall Detection model')
            self.error = 'Không nạp được model AI. Kiểm tra trọng số và thư viện trên máy chủ.'

    async def close(self):
        self.closing = True
        if self.camera:
            self.camera.stop()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        for job in self.jobs:
            job.cancel()
        if self.jobs:
            await asyncio.gather(*self.jobs, return_exceptions=True)
        if self.camera:
            await asyncio.to_thread(self.camera.close)

    def status(self):
        status = self.camera.snapshot()[0] if self.camera else {
            'configured': False, 'name': 'Camera AI', 'enabled': False,
            'state': 'unavailable', 'sequence': 0, 'epoch': 0,
            'threshold': .8, 'confirmations': 3,
        }
        return {**status, 'ready': self.model is not None, 'error': self.error,
                'analysis_enabled': self.enabled, 'telegram': self.telegram,
                'telegram_detail': self.telegram_detail,
                'ai_device': getattr(self.model, 'device', None),
                'gpu_name': getattr(self.model, 'gpu_name', None)}

    def set_analysis(self, enabled):
        if enabled and self.model is None:
            raise ValueError('Model AI chưa sẵn sàng.')
        if self.enabled != enabled:
            self.enabled = enabled
            self.generation += 1
            self.view = None

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
        self.set_analysis(False)

    def get_view(self):
        camera = self.status()
        view = self.view
        if (not self.enabled or camera['state'] != 'connected' or not view
                or view['epoch'] != camera['epoch'] or time.monotonic() - view['completed_at'] > 3):
            view = None
        return {'camera': camera, 'view': ({**{k: v for k, v in view.items() if k != 'completed_at'},
                                         'age': time.monotonic() - view['completed_at']} if view else None)}

    async def frame(self, sequence):
        if not self.camera:
            return None, 0
        status, frame = self.camera.snapshot()
        if frame is None or sequence == status['sequence']:
            return None, status['sequence']
        def encode():
            import cv2
            height, width = frame.shape[:2]
            ratio = min(1, 960 / max(height, width))
            image = cv2.resize(frame, (round(width * ratio), round(height * ratio))) if ratio < 1 else frame
            ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not ok:
                raise ValueError('Cannot encode camera frame')
            return jpeg.tobytes()
        return await asyncio.to_thread(encode), status['sequence']

    def _job(self, coro):
        job = asyncio.create_task(coro)
        self.jobs.add(job)
        job.add_done_callback(self.jobs.discard)

    async def _deliver(self, incident, image):
        """Persist independently of camera generations and Telegram availability."""
        delay = 1
        while not self.closing:
            try:
                await self.on_fall(incident)
                break
            except Exception:
                log.exception('Cannot persist fall %s; retrying', incident['key'])
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
        if not self.closing:
            await self._notify(incident, image)

    async def _notify(self, incident, image):
        from .telegram_client import is_configured, send_notification, TelegramError
        from .telegram_config import ALERT_COOLDOWN_SECONDS
        if not is_configured():
            return
        async with self.telegram_lock:
            now = time.monotonic()
            self.last_alert = {k: v for k, v in self.last_alert.items() if now - v < ALERT_COOLDOWN_SECONDS}
            person = incident['person_id']
            if person in self.last_alert:
                self.telegram = 'cooldown'
                self.telegram_detail = 'Đã gửi cảnh báo cho người này gần đây.'
                return
            message = (f"Phát hiện dấu hiệu té ngã tại {incident['source']}.\n"
                       f"Người #{person} · Điểm model {incident['score']:.0%}\n"
                       f"Thời gian: {incident['time']}\nHãy kiểm tra trực tiếp.")
            for attempt in range(3):
                try:
                    self.telegram = 'sending'
                    self.telegram_detail = 'Đang gửi cảnh báo ngã kèm ảnh.'
                    result = await asyncio.to_thread(
                        send_notification, title='SMART HOME - CẢNH BÁO TÉ NGÃ',
                        message=message, level='critical', event_id=incident['key'], image_jpeg=image)
                    if not result.get('sent'):
                        raise TelegramError('Gateway chưa xác nhận gửi thành công.')
                    self.last_alert[person] = time.monotonic()
                    self.telegram = 'sent'
                    self.telegram_detail = f"Đã gửi đến {result.get('recipients', 0)} người."
                    return
                except Exception:
                    log.exception('Telegram delivery failed for %s', incident['key'])
                    self.telegram = 'retrying' if attempt < 2 else 'error'
                    self.telegram_detail = 'Gửi Telegram chưa thành công; cảnh báo đã lưu trong nhật ký.'
                    if attempt < 2:
                        await asyncio.sleep(10)

    async def test_telegram(self):
        from .telegram_client import send_notification, is_configured
        if not is_configured():
            raise ValueError('Chưa cấu hình Telegram Gateway.')
        result = await asyncio.to_thread(send_notification, title='SMART HOME - KIỂM TRA',
                                        message='Dashboard chung đã kết nối Telegram Gateway.', level='info')
        self.telegram = 'sent' if result.get('sent') else 'error'
        self.telegram_detail = 'Đã gửi tin kiểm tra.' if result.get('sent') else 'Gateway chưa xác nhận gửi thành công.'
        return result

    async def _monitor(self):
        import cv2
        from .cctv import FallTracker
        tracker = FallTracker()
        previous_epoch = previous_generation = previous_sequence = -1
        last_infer = last_heartbeat = 0
        while not self.closing:
            await asyncio.sleep(.1)
            try:
                status, frame = self.camera.snapshot()
                now = time.monotonic()
                if self.on_camera and now - last_heartbeat >= 5:
                    await self.on_camera(status)
                    last_heartbeat = now
                generation = self.generation
                if status['epoch'] != previous_epoch or generation != previous_generation:
                    tracker.reset()
                    if self.model and hasattr(self.model, 'reset'):
                        await asyncio.to_thread(self.model.reset)
                    previous_epoch, previous_generation = status['epoch'], generation
                    previous_sequence = -1
                    self.view = None
                if (not self.enabled or frame is None or self.model is None
                        or status['sequence'] == previous_sequence or now - last_infer < .15):
                    continue
                previous_sequence, last_infer = status['sequence'], now
                def infer():
                    height, width = frame.shape[:2]
                    ratio = min(1, 960 / max(height, width))
                    resized = cv2.resize(frame, (round(width * ratio), round(height * ratio))) if ratio < 1 else frame.copy()
                    result = self.model.predict(resized)
                    ok, jpeg = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 78])
                    if not ok:
                        raise ValueError('Cannot encode inference frame')
                    tracks = tracker.update(result['detections'], self.config.threshold,
                                            self.config.confirmations, time.monotonic(),
                                            getattr(self.model, 'score_sequences', None))
                    return result, jpeg.tobytes(), tracks
                result, image, tracks = await asyncio.to_thread(infer)
                latest, _ = self.camera.snapshot()
                if (generation != self.generation or not self.enabled or self.closing
                        or latest['epoch'] != status['epoch'] or latest['state'] != 'connected'):
                    continue
                self.error = None
                self.view = {'width': result['width'], 'height': result['height'],
                             'image': base64.b64encode(image).decode('ascii'), 'tracks': tracks,
                             'epoch': status['epoch'], 'sequence': status['sequence'],
                             'completed_at': time.monotonic()}
                for track in tracks:
                    if track['newAlert']:
                        incident = {'key': 'fall-' + uuid.uuid4().hex, 'person_id': track['id'],
                                    'score': track['fall_score'], 'source': self.config.name,
                                    'time': datetime.now(timezone.utc).isoformat()}
                        self._job(self._deliver(incident, image))
            except Exception:
                log.exception('Fall Detection monitor failed')
                self.error = 'Chưa xử lý được hình ảnh. Đang thử lại.'
                self.view = None
                tracker.reset()
                await asyncio.sleep(1)
