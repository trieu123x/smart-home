import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import analytics, cloud_sink, mqtt_bridge
from .config import settings
from .database import Base, SessionLocal, engine
from .realtime import manager
from .routers import analytics as analytics_router
from .routers import auth, automations, dashboard, devices, events, ingest, live
from .security import auth_enabled, require_user, verify_token
from .seed import seed_if_empty
from .services import mark_offline_devices, run_auto_off

BACKGROUND_TICK_SECONDS = 2


async def background_worker() -> None:
    """Quet dinh ky: tat thiet bi het gio hen va danh dau thiet bi mat ket noi."""
    sink_task: asyncio.Task | None = None
    last_sink_flush = 0.0
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

        # Analytics gets its own session so a failure there cannot undo the work above
        try:
            db = SessionLocal()
            try:
                await analytics.tick(db)
            finally:
                db.close()
        except Exception as exc:
            print(f"[background] analytics error: {exc!r}")

        # Flush in its own task so a slow cloud endpoint never delays this loop
        now = time.monotonic()
        if (
            settings.cloud_sink_enabled
            and now - last_sink_flush >= settings.cloud_sink_interval
            and (sink_task is None or sink_task.done())
        ):
            last_sink_flush = now
            sink_task = asyncio.create_task(cloud_sink.flush())
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
    if not auth_enabled():
        print("[auth] WARNING: DASHBOARD_PASSWORD is empty, dashboard APIs are open", flush=True)
    elif len(settings.dashboard_password) < 12:
        print("[auth] WARNING: DASHBOARD_PASSWORD is shorter than 12 characters", flush=True)

    mqtt_bridge.start(asyncio.get_running_loop())
    task = asyncio.create_task(background_worker())
    yield
    task.cancel()
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

# Dashboard APIs need a login token (open when DASHBOARD_PASSWORD is empty)
user_auth = [Depends(require_user)]
app.include_router(devices.router, dependencies=user_auth)
app.include_router(events.router, dependencies=user_auth)
app.include_router(automations.router, dependencies=user_auth)
app.include_router(dashboard.router, dependencies=user_auth)
app.include_router(live.router, dependencies=user_auth)
app.include_router(analytics_router.router, dependencies=user_auth)
# Device-facing APIs keep X-Device-Key; login is public
app.include_router(devices.device_router)
app.include_router(ingest.router)
app.include_router(auth.router)


@app.get("/api/health", tags=["health"])
def health():
    return {
        "status": "ok",
        "websocket_clients": manager.count,
        "mqtt_broker": mqtt_bridge.get_state()["broker_ok"],
        "cloud_sink": cloud_sink.status(),
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(default=None)):
    """Dashboard giu mot ket noi o day de nhan du lieu realtime."""
    if auth_enabled() and not verify_token(token):
        # Accept first so the browser sees the 4401 close code instead of a failed handshake
        await websocket.accept()
        await websocket.close(code=4401)
        return
    await manager.connect(websocket)
    try:
        while True:
            # Chi de giu ket noi song; client co the gui "ping"
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
