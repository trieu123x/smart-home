import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, SessionLocal, engine
from .realtime import manager
from .routers import automations, dashboard, devices, events, ingest
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
    finally:
        db.close()

    task = asyncio.create_task(background_worker())
    yield
    task.cancel()


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

app.include_router(devices.router)
app.include_router(events.router)
app.include_router(automations.router)
app.include_router(dashboard.router)
app.include_router(ingest.router)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok", "websocket_clients": manager.count}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Dashboard giu mot ket noi o day de nhan du lieu realtime."""
    await manager.connect(websocket)
    try:
        while True:
            # Chi de giu ket noi song; client co the gui "ping"
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)
