from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .model import AntiTheftAnalyzer

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
UPLOAD_DIR = BASE_DIR / "uploads"
MODEL_PATH = BASE_DIR / "models" / "best_antitheft_v3.pt"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}

app = FastAPI(title="Anti-Theft IoT AI", version="3.0")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
templates = Jinja2Templates(directory=APP_DIR / "templates")

analyzer = AntiTheftAnalyzer(MODEL_PATH)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "model_epoch": analyzer.epoch,
            "device": str(analyzer.device),
        },
    )


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "model": MODEL_PATH.name,
        "epoch": analyzer.epoch,
        "device": str(analyzer.device),
    }


@app.post("/api/analyze")
async def analyze(
    video: UploadFile = File(...),
    frame_step: int = Form(10),
    window_stride: int = Form(8),
    threshold: float = Form(0.40),
):
    original_name = video.filename or "video.mp4"
    extension = Path(original_name).suffix.lower()

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Định dạng video không hỗ trợ. Hãy dùng MP4, AVI, MOV, MKV, WebM hoặc M4V.",
        )

    if frame_step < 1 or frame_step > 60:
        raise HTTPException(status_code=400, detail="Frame step phải từ 1 đến 60.")
    if window_stride < 1 or window_stride > 64:
        raise HTTPException(status_code=400, detail="Window stride phải từ 1 đến 64.")
    if threshold < 0.05 or threshold > 0.95:
        raise HTTPException(status_code=400, detail="Threshold phải từ 0.05 đến 0.95.")

    temp_name = f"{uuid.uuid4().hex}{extension}"
    temp_path = UPLOAD_DIR / temp_name

    try:
        with temp_path.open("wb") as f:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)

        result = analyzer.analyze_video(
            temp_path,
            frame_step=frame_step,
            window_stride=window_stride,
            threshold=threshold,
        )
        result["filename"] = original_name
        return result

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            if temp_path.exists():
                os.remove(temp_path)
        except OSError:
            pass
