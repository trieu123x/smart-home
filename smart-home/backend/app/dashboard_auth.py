"""One session for the dashboard HTTP API, camera controls and WebSocket."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import hmac
import secrets
import time
from collections import defaultdict, deque

from .config import settings

COOKIE_NAME = 'smarthome_session'
SESSION_AGE = 7 * 24 * 3600


class DashboardAuth:
    def __init__(self, password):
        self.password = password
        self.sessions = {}
        self.failed = defaultdict(deque)

    @property
    def configured(self):
        return len(self.password) >= 12

    def login(self, password, ip):
        now = time.monotonic()
        attempts = self.failed[ip]
        while attempts and now - attempts[0] > 300:
            attempts.popleft()
        if len(attempts) >= 10:
            return None, 'too_many_attempts'
        if not self.configured or not hmac.compare_digest(password.encode(), self.password.encode()):
            attempts.append(now)
            return None, 'invalid_credentials'
        attempts.clear()
        self.sessions = {token: expiry for token, expiry in self.sessions.items() if expiry > time.time()}
        token = secrets.token_urlsafe(32)
        self.sessions[token] = time.time() + SESSION_AGE
        return token, None

    def valid(self, token):
        return bool(token) and self.sessions.get(token, 0) > time.time()

    def logout(self, token):
        self.sessions.pop(token, None)


auth = DashboardAuth(settings.dashboard_password)
router = APIRouter(prefix='/api/auth', tags=['authentication'])


class Login(BaseModel):
    password: str = Field(min_length=1, max_length=512)


@router.get('/session')
def session(request: Request):
    return {'authenticated': auth.valid(request.cookies.get(COOKIE_NAME)), 'configured': auth.configured}


@router.post('/login')
def login(payload: Login, request: Request):
    token, error = auth.login(payload.password, request.client.host if request.client else 'unknown')
    if error:
        if not auth.configured:
            raise HTTPException(503, 'Đặt DASHBOARD_PASSWORD ít nhất 12 ký tự trong backend/.env rồi khởi động lại.')
        raise HTTPException(429 if error == 'too_many_attempts' else 401,
                            'Đăng nhập bị giới hạn tạm thời.' if error == 'too_many_attempts' else 'Mật khẩu không đúng.')
    response = JSONResponse({'authenticated': True, 'configured': True})
    # The backend binds to loopback; the trusted Next.js proxy sets this header.
    secure = request.url.scheme == 'https' or request.headers.get('x-forwarded-proto') == 'https'
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_AGE, httponly=True,
                        secure=secure, samesite='strict', path='/')
    return response


@router.post('/logout')
def logout(request: Request):
    auth.logout(request.cookies.get(COOKIE_NAME))
    response = JSONResponse({'authenticated': False})
    response.delete_cookie(COOKIE_NAME, path='/')
    return response
