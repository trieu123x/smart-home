import hmac
import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import schemas
from ..config import settings
from ..security import create_token, require_user

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILURES = 5
WINDOW_SECONDS = 60.0
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}

# client IP -> monotonic times of recent failed logins
_failures: dict[str, deque[float]] = {}


def _client_ip(request: Request) -> str:
    host = request.client.host if request.client else "unknown"
    # cloudflared connects from localhost; only then trust the header it adds
    forwarded = request.headers.get("cf-connecting-ip")
    if forwarded and host in _LOOPBACK:
        return forwarded.strip()
    return host


def _recent_failures(ip: str, now: float) -> deque[float]:
    if len(_failures) > 1000:  # keep memory bounded when many IPs fail once
        for key in [k for k, v in _failures.items() if not v or now - v[-1] >= WINDOW_SECONDS]:
            del _failures[key]
    attempts = _failures.setdefault(ip, deque())
    while attempts and now - attempts[0] >= WINDOW_SECONDS:
        attempts.popleft()
    return attempts


def reset_rate_limit() -> None:
    """Forget failed attempts (used by tests)."""
    _failures.clear()


@router.post("/login", response_model=schemas.LoginOut)
async def login(payload: schemas.LoginIn, request: Request):
    # async on purpose: runs on the event loop, so the rate-limit check and update cannot race
    ip = _client_ip(request)
    now = time.monotonic()
    attempts = _recent_failures(ip, now)
    if len(attempts) >= MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Thu lai sau 1 phut")

    expected = settings.dashboard_password.encode()
    if expected and not hmac.compare_digest(payload.password.encode(), expected):
        attempts.append(now)
        raise HTTPException(status_code=401, detail="Sai mat khau")

    if not attempts:
        _failures.pop(ip, None)
    token, expires_at = create_token()
    return schemas.LoginOut(token=token, expires_at=expires_at)


@router.get("/me", dependencies=[Depends(require_user)])
def me():
    return {"ok": True}
