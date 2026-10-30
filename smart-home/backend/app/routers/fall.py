"""Fall Detection controls under the shared dashboard session."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from typing import Literal

router = APIRouter(prefix='/api/fall', tags=['fall detection'])


class Analysis(BaseModel):
    enabled: bool


class SourceChoice(BaseModel):
    source: Literal['adb', 'droidcam']


class DroidCamConnection(BaseModel):
    host: str = Field(min_length=7, max_length=45)
    port: int = Field(default=4747, ge=1024, le=65535)


def runtime(request):
    value = request.app.state.fall
    if value is None:
        raise HTTPException(503, 'Module phát hiện ngã đang tắt trong cấu hình máy chủ.')
    return value


@router.get('/view')
def view(request: Request):
    return runtime(request).get_view()


@router.get('/frame')
async def frame(request: Request, seq: int = -1, source: Literal['adb', 'droidcam'] = 'adb'):
    data, sequence = await runtime(request).frame(seq, source)
    return Response(data, status_code=200 if data else 204, media_type='image/jpeg',
                    headers={'X-Frame-Sequence': str(sequence), 'Cache-Control': 'no-store'})


@router.post('/start')
def start(request: Request, source: Literal['adb', 'droidcam'] = 'adb'):
    value = runtime(request)
    try:
        value.start_camera(source)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return value.status()


@router.post('/stop')
def stop(request: Request, source: Literal['adb', 'droidcam'] = 'adb'):
    value = runtime(request)
    value.stop_camera(source)
    return value.status()


@router.post('/analysis')
def analysis(payload: Analysis, request: Request):
    value = runtime(request)
    try:
        value.set_analysis(payload.enabled)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    return value.status()


@router.post('/source')
def change_source(payload: SourceChoice, request: Request):
    try:
        return runtime(request).set_source(payload.source)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/droidcam/connect')
def connect_droidcam(payload: DroidCamConnection, request: Request):
    try:
        return runtime(request).connect_droidcam(payload.host, payload.port)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/telegram/test')
async def telegram_test(request: Request):
    try:
        return await runtime(request).test_telegram()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception:
        raise HTTPException(502, 'Chưa gửi được tin kiểm tra. Xem log máy chủ.') from None
