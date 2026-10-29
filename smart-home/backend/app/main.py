import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
from urllib.parse import urlsplit
from fastapi.middleware.cors import CORSMiddleware

from . import mqtt_bridge
from .config import settings
from .database import Base, SessionLocal, engine
from .realtime import manager
from .routers import automations, dashboard, devices, events, ingest, live, fall, push
from .dashboard_auth import auth, COOKIE_NAME, router as auth_router
from fallguard.runtime import FallRuntime
from .fall_events import record_incident, camera_heartbeat
from .seed import seed_if_empty
from .services import mark_offline_devices, run_auto_off

BACKGROUND_TICK_SECONDS = 2


async def background_worker() -> None:
    """Quet dinh ky: tat thiet bi het gio hen va danh dau thiet bi mat ket noi."""
    while True:
        try:
            db = SessionLocal()
            try:
                await run_auto_off(db)
                await mark_offline_devices(db)
                await mqtt_bridge.tick()
                db.commit()
            finally:
                db.close()
        except Exception as exc:  # khong de vong lap chet vi mot loi le
            print(f"[background] loi: {exc}")
        await asyncio.sleep(BACKGROUND_TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        mqtt_bridge.ensure_devices(db)
    finally:
        db.close()

    mqtt_bridge.start(asyncio.get_running_loop())
    task = asyncio.create_task(background_worker())
    app.state.fall = FallRuntime(record_incident, camera_heartbeat) if settings.fall_enabled else None
    if app.state.fall:
        await app.state.fall.start()
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if app.state.fall:
            await app.state.fall.close()
        mqtt_bridge.stop()


app = FastAPI(
    title="Smart Home API",
    description="Backend dashboard nha thong minh: phat hien nga, quat tu dong, den theo chuyen dong.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def trusted_origin(headers):
    if headers.get('sec-fetch-site') == 'cross-site':
        return False
    origin = headers.get('origin')
    if not origin:
        return True
    if origin in settings.cors_origin_list:
        return True
    # Next.js forwards the original host; the backend is private behind that proxy.
    forwarded = headers.get('x-forwarded-host', '').split(',')[0].strip()
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in ('http', 'https') and bool(forwarded) and parsed.netloc == forwarded
    except ValueError:
        return False


@app.middleware('http')
async def dashboard_session(request: Request, call_next):
    if request.method == 'OPTIONS':
        return await call_next(request)
    path = request.url.path.rstrip('/')
    public = path in ('/api/health', '/api/auth/session', '/api/auth/login')
    device = path.startswith('/api/ingest/') or (request.method == 'GET' and path.startswith('/api/devices/') and path.endswith('/commands'))
    if not public and not device and not auth.valid(request.cookies.get(COOKIE_NAME)):
        return JSONResponse({'detail': 'Cần đăng nhập dashboard.'}, status_code=401)
    if not device and request.method not in ('GET', 'HEAD', 'OPTIONS') and not trusted_origin(request.headers):
        return JSONResponse({'detail': 'Yêu cầu khác nguồn bị từ chối.'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


app.include_router(auth_router)
app.include_router(fall.router)
app.include_router(devices.router)
app.include_router(events.router)
app.include_router(automations.router)
app.include_router(dashboard.router)
app.include_router(ingest.router)
app.include_router(live.router)
app.include_router(push.router)


@app.get("/api/health", tags=["health"])
def health():
    return {
        "status": "ok",
        "websocket_clients": manager.count,
        "mqtt_broker": mqtt_bridge.get_state()["broker_ok"],
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Dashboard giu mot ket noi o day de nhan du lieu realtime."""
    token = websocket.cookies.get(COOKIE_NAME)
    if not auth.valid(token) or not trusted_origin(websocket.headers):
        await websocket.close(code=1008)
        return
    websocket.state.is_authorized = lambda: auth.valid(token)
    await manager.connect(websocket)
    try:
        while True:
            # Chi de giu ket noi song; client co the gui "ping"
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=15)
            except asyncio.TimeoutError:
                pass
            if not auth.valid(token):
                await websocket.close(code=1008)
                break
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
    finally:
        await manager.disconnect(websocket)
