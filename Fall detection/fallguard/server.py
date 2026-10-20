import asyncio
import base64
import uuid
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .telegram_client import TelegramError, is_configured, send_notification

from .detector import Detector
from .cctv import CameraReader, CameraSettings, FallTracker
from .auth import Auth, COOKIE_NAME, SESSION_AGE, same_origin

from .telegram_config import ALERT_COOLDOWN_SECONDS

ROOT = Path(__file__).resolve().parent.parent
TELEGRAM_RETRY_SECONDS = 10


def telegram_configured():
    """Gateway URL + project-specific API key; no Telegram credentials on this host."""
    return is_configured()


class LoginPayload(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class AnalysisPayload(BaseModel):
    enabled: bool


class AlertPayload(BaseModel):
    person_id: int = Field(ge=1)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    confirmations: int = Field(ge=1, le=20)
    session_id: str = Field(default='legacy', min_length=1, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    event_id: str | None = Field(default=None, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]*$')


def make_fall_snapshot(image_base64: str, track: dict) -> bytes:
    """Freeze the actual confirmed-fall frame; highlight the detected person."""
    import numpy as np

    original = base64.b64decode(image_base64, validate=True)
    image = cv2.imdecode(np.frombuffer(original, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Fall snapshot cannot be decoded')
    height, width = image.shape[:2]
    box = track.get('box')
    if box and len(box) == 4:
        # Detector returns normalized xyxy boxes; clamp to visible pixels.
        x1, y1, x2, y2 = [float(v) for v in box]
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        a = (max(0, min(width - 1, int(x1 * width))),
             max(0, min(height - 1, int(y1 * height))))
        b = (max(0, min(width - 1, int(x2 * width))),
             max(0, min(height - 1, int(y2 * height))))
        cv2.rectangle(image, a, b, (0, 0, 255), 3)
        cv2.putText(image, f"FALL  ID {track['id']}", (a[0], max(20, a[1] - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 0, 255), 2)
    for quality in (78, 65, 50):
        ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ok and len(jpeg) <= 2_000_000:
            return jpeg.tobytes()
    raise ValueError('Fall snapshot exceeds 2 MB')


def create_app(factory=Detector, camera_factory=CameraReader, camera_settings=None):
    camera_error = None
    if camera_settings is None:
        try:
            camera_settings = CameraSettings.load()
        except ValueError as exc:
            camera_error = str(exc)
            camera_settings = CameraSettings()

    auth = Auth()

    @asynccontextmanager
    async def lifespan(app):
        app.state.model = None
        app.state.error = None
        app.state.busy = False
        app.state.telegram_last_alert = {}
        app.state.telegram_lock = asyncio.Lock()
        app.state.camera = camera_factory(camera_settings)
        app.state.cctv_view = None
        app.state.cctv_analysis = False
        app.state.cctv_analysis_generation = 0
        app.state.cctv_events = []
        app.state.cctv_alert_tasks = set()
        app.state.cctv_telegram = 'configured' if telegram_configured() else 'not_configured'
        app.state.cctv_telegram_detail = ('Chưa có cảnh báo được gửi.' if telegram_configured()
                                          else 'Thiếu TELEGRAM_GATEWAY_URL hoặc TELEGRAM_GATEWAY_KEY trong .env.')
        app.state.cctv_error = None
        app.state.closing = False
        app.state.cctv_session = 'cctv-' + uuid.uuid4().hex

        async def load():
            try:
                app.state.model = await asyncio.to_thread(factory)
            except Exception:
                logging.exception('Model loading failed')
                app.state.error = 'Chưa thể bắt đầu theo dõi. Vui lòng thử lại sau.'

        task = asyncio.create_task(load())
        monitor = asyncio.create_task(monitor_cctv())
        if camera_settings.autostart and camera_settings.url:
            app.state.camera.start()
        try:
            yield
        finally:
            app.state.closing = True
            app.state.camera.stop()
            await task
            await monitor
            if app.state.cctv_alert_tasks:
                await asyncio.gather(*app.state.cctv_alert_tasks, return_exceptions=True)
            await asyncio.to_thread(app.state.camera.close)

    app = FastAPI(title='FallGuard', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=()'
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'"
        return response

    # Authentication is enforced at the HTTP boundary, including legacy AI/Telegram APIs.
    @app.middleware('http')
    async def auth_gate(request, call_next):
        path = request.url.path
        allowed = path.startswith('/static/') or path in ('/login', '/api/auth/login', '/api/auth/session')
        if not allowed and not auth.valid(request.cookies.get(COOKIE_NAME)):
            if path.startswith('/api/'):
                return JSONResponse({'detail': 'Cần đăng nhập.'}, status_code=401)
            return RedirectResponse('/login', status_code=303)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not same_origin(request.headers):
            return JSONResponse({'detail': 'Yêu cầu khác nguồn bị từ chối.'}, status_code=403)
        return await call_next(request)

    @app.get('/login')
    async def login_page(request: Request):
        if auth.valid(request.cookies.get(COOKIE_NAME)):
            return RedirectResponse('/', status_code=303)
        return FileResponse(ROOT / 'static/login.html')

    @app.get('/api/auth/session')
    async def auth_session(request: Request):
        return {'authenticated': auth.valid(request.cookies.get(COOKIE_NAME)), 'configured': auth.configured}

    @app.post('/api/auth/login')
    async def login(request: Request, payload: LoginPayload):
        ip = request.client.host if request.client else 'unknown'
        token, error = auth.login(payload.password, ip)
        if error:
            raise HTTPException(429 if error == 'too_many_attempts' else 401,
                                'Đăng nhập bị giới hạn tạm thời.' if error == 'too_many_attempts'
                                else 'Mật khẩu không đúng hoặc chưa cấu hình FALLGUARD_PASSWORD (ít nhất 12 ký tự).')
        response = JSONResponse({'authenticated': True})
        secure = request.url.scheme == 'https' or request.headers.get('x-forwarded-proto', '').lower() == 'https'
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_AGE, httponly=True,
                            secure=secure, samesite='strict', path='/')
        return response

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        auth.logout(request.cookies.get(COOKIE_NAME))
        response = JSONResponse({'authenticated': False})
        response.delete_cookie(COOKIE_NAME, path='/')
        return response

    @app.get('/api/status')
    async def status():
        model = app.state.model
        return {
            'ready': model is not None,
            'ai_device': getattr(model, 'device', None) if model is not None else None,
            'gpu_name': getattr(model, 'gpu_name', None) if model is not None else None,
            'error': app.state.error,
            'telegram': {'configured': telegram_configured()},
            'cctv': cctv_status(),
        }

    @app.post('/api/telegram/test')
    async def telegram_test():
        if not telegram_configured():
            raise HTTPException(503, 'Thông báo chưa sẵn sàng.')
        text = (
            'Máy chủ FallGuard đã kết nối thành công với Telegram Gateway.\n'
            f'Thời gian: {datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %z")}'
        )
        try:
            result = await asyncio.to_thread(
                send_notification,
                title='FallGuard - KIỂM TRA KẾT NỐI', message=text, level='info',
            )
            app.state.cctv_telegram = 'sent'
            app.state.cctv_telegram_detail = f"Tin thử đã gửi đến {result.get('recipients', 0)} người đăng ký."
            return result
        except Exception as exc:
            detail = str(exc) if isinstance(exc, TelegramError) else 'Lỗi gửi Telegram. Kiểm tra kết nối và cấu hình.'
            app.state.cctv_telegram = 'error'
            app.state.cctv_telegram_detail = detail
            logging.warning('Telegram test failed: %s', detail)
            # The user is already authenticated; show the safe, sanitized reason.
            raise HTTPException(502, detail) from None

    async def deliver_alert(payload: AlertPayload, source='Camera thiết bị', image_jpeg=None):
        if not telegram_configured():
            return {'sent': False, 'reason': 'not_configured'}
        cooldown = max(15, int(ALERT_COOLDOWN_SECONDS or 60))
        key = (payload.session_id, payload.person_id)
        # Serialize send and cooldown so overlapping alarms don't multiply broadcasts.
        async with app.state.telegram_lock:
            now = time.monotonic()
            recent = app.state.telegram_last_alert
            for old_key, sent_at in list(recent.items()):
                if now - sent_at >= cooldown:
                    del recent[old_key]
            if key in recent:
                return {'sent': False, 'reason': 'cooldown'}
            if len(recent) >= 2048:
                raise HTTPException(429, 'Quá nhiều cảnh báo. Hãy chờ rồi thử lại.')
            body = (
                'Phát hiện dấu hiệu người bị ngã. Hãy kiểm tra ngay.\n'
                f'Camera: {source}\n'
                f'Người trong khung hình: #{payload.person_id}\n'
                f'Điểm model té ngã: {round(payload.score * 100)}%\n'
                f'Xác nhận liên tiếp: {payload.confirmations} lần, duy trì tư thế ngã ít nhất 5 giây\n'
                f'Thời gian: {datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %z")}\n\n'
                'Đây là cảnh báo từ camera AI; cần kiểm tra trực tiếp.'
            )
            # event_id remains stable across retries of the SAME detection event.
            event_id = payload.event_id or ('fallguard-' + uuid.uuid4().hex)
            try:
                result = await asyncio.to_thread(
                    send_notification, title='FALLGUARD - CẢNH BÁO TÉ NGÃ',
                    message=body, level='critical', event_id=event_id,
                    image_jpeg=image_jpeg,
                )
            except Exception as exc:
                detail = str(exc) if isinstance(exc, TelegramError) else 'Lỗi kết nối Telegram Gateway.'
                logging.warning('Telegram Gateway alert failed: %s', detail)
                # Preserve the sanitized client diagnosis for the dashboard and logs.
                raise TelegramError(detail) from None
            # Duplicate means the event was already accepted by Gateway, not a fresh send.
            if result.get('reason') == 'duplicate':
                recent[key] = time.monotonic()
                return result
            recent[key] = time.monotonic()
            return result

    def cctv_status():
        status, _ = app.state.camera.snapshot()
        return {**status, 'error': ('Tạm thời không theo dõi được. Vui lòng thử lại sau.'
                                   if camera_error or app.state.cctv_error or app.state.error else None),
                'telegram': app.state.cctv_telegram,
                'telegram_detail': app.state.cctv_telegram_detail,
                'analysis_enabled': app.state.cctv_analysis,
                'fall_confirm_seconds': 5.0}

    @app.get('/api/cctv/status')
    async def camera_status():
        return cctv_status()

    @app.get('/api/cctv/frame')
    async def cctv_frame(seq: int = 0):
        status, frame = app.state.camera.snapshot()
        if frame is None or (seq > 0 and status['sequence'] == seq):
            return Response(status_code=204, headers={'X-Frame-Sequence': str(status['sequence'])})
        def jpeg_encode():
            height, width = frame.shape[:2]
            ratio = min(1, 960 / max(height, width))
            resized = cv2.resize(frame, (round(width*ratio), round(height*ratio))) if ratio < 1 else frame.copy()
            success, jpeg = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 75])
            if not success:
                raise ValueError('encode failed')
            return jpeg.tobytes()
        try:
            jpeg = await asyncio.to_thread(jpeg_encode)
        except Exception:
            raise HTTPException(503, 'Không đọc được hình CCTV.') from None
        return Response(jpeg, media_type='image/jpeg', headers={'X-Frame-Sequence': str(status['sequence'])})

    @app.post('/api/cctv/analysis')
    async def cctv_analysis(payload: AnalysisPayload):
        if payload.enabled and app.state.model is None:
            raise HTTPException(503, 'Model AI chưa sẵn sàng.')
        if app.state.cctv_analysis != payload.enabled:
            app.state.cctv_analysis = payload.enabled
            app.state.cctv_analysis_generation += 1
            app.state.cctv_view = None
        return cctv_status()

    @app.post('/api/cctv/start')
    async def camera_start():
        if camera_error or not camera_settings.url:
            raise HTTPException(503, 'Camera chưa sẵn sàng. Vui lòng liên hệ người quản lý.')
        app.state.camera.start()
        return cctv_status()

    @app.post('/api/cctv/stop')
    async def camera_stop():
        app.state.camera.stop()
        app.state.cctv_analysis = False
        app.state.cctv_analysis_generation += 1
        app.state.cctv_view = None
        return cctv_status()

    @app.get('/api/cctv/view')
    async def camera_view():
        status = cctv_status()
        view = app.state.cctv_view
        if not status['analysis_enabled'] or status['state'] != 'connected' or not view or view['epoch'] != status['epoch']:
            view = None
        return {'camera': status, 'view': ({**{key: value for key, value in view.items() if key != 'completed_at'}, 'age': time.monotonic()-view['completed_at']}
                                           if view else None),
                'events': app.state.cctv_events}

    async def monitor_cctv():
        tracker = FallTracker()
        last_sequence, last_epoch, last_generation, event_id = -1, -1, -1, 0
        last_infer_time = 0.0
        infer_interval = 0.2          # giây — 1 frame mỗi 0,2 s
        # Delivery jobs stay alive after a confirmed fall, even when later frames
        # lose the person. Previously retries were tied to continuously tracked boxes.
        notification_jobs = {}

        async def notify(track, alert_event, session_id, image_jpeg):
            # Keep one idempotency key for the whole job, including all retries.
            event_key = 'fallguard-' + uuid.uuid4().hex
            for attempt in range(1, 4):
                if app.state.closing:
                    return
                app.state.cctv_telegram = 'sending'
                app.state.cctv_telegram_detail = f"Đang gửi cảnh báo ngã (lần {attempt}/3)..."
                alert_event['telegram'] = 'sending'
                try:
                    result = await deliver_alert(AlertPayload(
                        person_id=track['id'], score=track['fall_score'],
                        confirmations=camera_settings.confirmations,
                        session_id=session_id, event_id=event_key,
                    ), camera_settings.name, image_jpeg=image_jpeg)
                    if result.get('sent'):
                        count = result.get('recipients', 0)
                        app.state.cctv_telegram = 'sent'
                        app.state.cctv_telegram_detail = f'Đã gửi cảnh báo ngã kèm ảnh đến {count} người.'
                        alert_event['telegram'] = 'sent'
                        return
                    reason = result.get('reason')
                    if reason == 'not_configured':
                        app.state.cctv_telegram = 'not_configured'
                        app.state.cctv_telegram_detail = 'Thiếu URL hoặc API key Gateway. Kiểm tra .env rồi khởi động lại.'
                        alert_event['telegram'] = 'not_configured'
                        return
                    if reason == 'cooldown':
                        app.state.cctv_telegram = 'cooldown'
                        app.state.cctv_telegram_detail = 'Đã gửi cảnh báo cho người này gần đây; đang chống gửi lặp.'
                        alert_event['telegram'] = 'cooldown'
                        return
                    if reason == 'duplicate':
                        # A duplicate does NOT prove recipients actually got the message.
                        app.state.cctv_telegram = 'error'
                        app.state.cctv_telegram_detail = ('Gateway đã ghi nhận event_id này nhưng chưa thể '
                                                          'xác nhận gửi thành công. Kiểm tra log Vercel.')
                        alert_event['telegram'] = 'error'
                        return
                    raise TelegramError('Gateway không xác nhận đã gửi cảnh báo.')
                except Exception as exc:
                    detail = (str(exc) if isinstance(exc, TelegramError)
                              else 'Lỗi gửi qua Gateway; xem log FallGuard và Vercel.')
                    logging.warning('Fall event %s: Telegram delivery attempt %d/3 failed: %s',
                                    alert_event['event_id'], attempt, detail)
                    app.state.cctv_telegram = 'retrying' if attempt < 3 else 'error'
                    app.state.cctv_telegram_detail = detail
                    alert_event['telegram'] = app.state.cctv_telegram
                    if attempt < 3:
                        await asyncio.sleep(TELEGRAM_RETRY_SECONDS)

        while not app.state.closing:
            await asyncio.sleep(.1)
            status, frame = app.state.camera.snapshot()
            generation = app.state.cctv_analysis_generation
            if status['epoch'] != last_epoch or generation != last_generation:
                tracker.reset()
                # Do not cancel accepted fall-alert deliveries when camera changes.
                notification_jobs = {k: job for k, job in notification_jobs.items() if not job.done()}
                app.state.cctv_view = None
                last_epoch = status['epoch']
                last_generation = generation
                last_sequence = -1
            now_check = time.monotonic()
            if (not app.state.cctv_analysis or frame is None or not app.state.model or app.state.busy
                    or status['sequence'] == last_sequence
                    or now_check - last_infer_time < infer_interval):
                continue
            last_sequence = status['sequence']
            last_infer_time = now_check
            app.state.busy = True

            def work():
                try:
                    height, width = frame.shape[:2]
                    ratio = min(1, 960/max(height, width))
                    resized = cv2.resize(frame, (round(width*ratio), round(height*ratio))) if ratio < 1 else frame.copy()
                    result = app.state.model.predict(resized)
                    ok, jpeg = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, 78])
                    if not ok:
                        raise ValueError('encode failed')
                    return result, base64.b64encode(jpeg).decode('ascii')
                finally:
                    app.state.busy = False

            try:
                result, image = await asyncio.to_thread(work)
                latest, _ = app.state.camera.snapshot()
                if (not app.state.cctv_analysis or generation != app.state.cctv_analysis_generation
                        or latest['epoch'] != status['epoch'] or latest['state'] != 'connected' or app.state.closing):
                    continue
                now = time.monotonic()
                tracks = tracker.update(result['detections'], camera_settings.threshold,
                                        camera_settings.confirmations, now)
                app.state.cctv_error = None
                app.state.cctv_view = {'width': result['width'], 'height': result['height'], 'image': image, 'tracks': tracks,
                                       'sequence': status['sequence'], 'epoch': status['epoch'],
                                       'completed_at': now}
                for track in tracks:
                    if not track['newAlert']:
                        continue
                    event_id += 1
                    event = {'event_id': event_id, 'id': track['id'],
                             'score': track['fall_score'],
                             'time': datetime.now().astimezone().isoformat(),
                             'source': camera_settings.name,
                             'session': app.state.cctv_session, 'telegram': 'queued'}
                    app.state.cctv_events.insert(0, event)
                    app.state.cctv_events = app.state.cctv_events[:50]
                    logging.info('Confirmed fall: event=%d person=%s score=%.3f; scheduling Gateway delivery',
                                 event_id, track['id'], track['fall_score'])
                    # The worker retries independently of future video frames.
                    key = (status['epoch'], generation, track['id'])
                    if key not in notification_jobs or notification_jobs[key].done():
                        try:
                            snapshot_jpeg = await asyncio.to_thread(make_fall_snapshot, image, track)
                        except Exception:
                            logging.exception('Cannot create fall snapshot; falling back to dashboard JPEG')
                            snapshot_jpeg = base64.b64decode(image)
                        task = asyncio.create_task(notify(dict(track), event, app.state.cctv_session, snapshot_jpeg))
                        notification_jobs[key] = task
                        app.state.cctv_alert_tasks.add(task)
                        task.add_done_callback(app.state.cctv_alert_tasks.discard)
                notification_jobs = {key: job for key, job in notification_jobs.items() if not job.done()}
            except Exception:
                app.state.cctv_error = 'Chưa xử lý được hình ảnh. Vui lòng thử lại.'
                app.state.cctv_view = None
                tracker.reset()
                await asyncio.sleep(1)

    @app.get('/')
    def home():
        return FileResponse(ROOT / 'static/index.html')

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
    return app


app = create_app()
