import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone

from fastapi import Header, HTTPException, status

from .config import settings

# Used when AUTH_SECRET is empty: tokens then expire when the process restarts
_process_secret = secrets.token_bytes(32)


def require_device_key(x_device_key: str | None = Header(default=None)) -> None:
    """Xac thuc don gian cho firmware ESP32 bang mot khoa chung trong header."""
    if not hmac.compare_digest((x_device_key or "").encode(), settings.device_api_key.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thieu hoac sai header X-Device-Key",
        )


# ---------------------------------------------------------------- dashboard login
def auth_enabled() -> bool:
    return bool(settings.dashboard_password)


def _key() -> bytes:
    # Mixing in the password means a password change invalidates every token
    secret = settings.auth_secret.encode() or _process_secret
    return hashlib.sha256(secret + b"\0" + settings.dashboard_password.encode()).digest()


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> bytes:
    return hmac.new(_key(), payload, hashlib.sha256).digest()


def create_token() -> tuple[str, datetime]:
    """Token = base64url(expiry_unix) + "." + base64url(HMAC_SHA256(key, expiry_unix))."""
    expiry = int(time.time() + settings.auth_token_hours * 3600)
    payload = str(expiry).encode()
    token = f"{_b64encode(payload)}.{_b64encode(_sign(payload))}"
    return token, datetime.fromtimestamp(expiry, tz=timezone.utc)


def verify_token(token: str | None) -> bool:
    if not token or token.count(".") != 1:
        return False
    payload_text, signature_text = token.split(".")
    try:
        payload = _b64decode(payload_text)
        signature = _b64decode(signature_text)
        expiry = int(payload.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return False
    if not hmac.compare_digest(signature, _sign(payload)):
        return False
    return expiry > time.time()


def require_user(authorization: str | None = Header(default=None)) -> None:
    """Bearer token for dashboard APIs. With DASHBOARD_PASSWORD empty, everything is allowed."""
    if not auth_enabled():
        return
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not verify_token(token.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chua dang nhap hoac phien da het han",
            headers={"WWW-Authenticate": "Bearer"},
        )
