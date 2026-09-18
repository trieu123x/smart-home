from fastapi import Header, HTTPException, status

from .config import settings


def require_device_key(x_device_key: str | None = Header(default=None)) -> None:
    """Xac thuc don gian cho firmware ESP32 bang mot khoa chung trong header."""
    if x_device_key != settings.device_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Thieu hoac sai header X-Device-Key",
        )
