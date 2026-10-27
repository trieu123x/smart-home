"""Fall Detection controls under the shared dashboard session."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix='/api/fall', tags=['fall detection'])


class Analysis(BaseModel):
    enabled: bool


def runtime(request):
    value = request.app.state.fall
    if value is None:
        raise HTTPException(503, 'Module phát hiện ngã đang tắt trong cấu hình máy chủ.')
    return value


@router.get('/view')
def view(request: Request):
    return runtime(request).get_view()


@router.get('/frame')
async def frame(request: Request, seq: int = -1):
    data, sequence = await runtime(request).frame(seq)
    return Response(data, status_code=200 if data else 204, media_type='image/jpeg',
                    headers={'X-Frame-Sequence': str(sequence), 'Cache-Control': 'no-store'})


@router.post('/start')
def start(request: Request):
    value = runtime(request)
    if value.camera is None:
        raise HTTPException(503, value.error or 'Camera chưa sẵn sàng.')
    value.camera.start()
    return value.status()


@router.post('/stop')
def stop(request: Request):
    value = runtime(request)
    value.stop_camera()
    return value.status()


@router.post('/analysis')
def analysis(payload: Analysis, request: Request):
    value = runtime(request)
    try:
        value.set_analysis(payload.enabled)
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    return value.status()


@router.post('/telegram/test')
async def telegram_test(request: Request):
    try:
        return await runtime(request).test_telegram()
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from None
    except Exception:
        raise HTTPException(502, 'Chưa gửi được tin kiểm tra. Xem log máy chủ.') from None
