import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import WebSocket


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class ConnectionManager:
    """Quan ly cac ket noi WebSocket cua dashboard va day su kien realtime."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, event_type: str, payload: Any) -> None:
        message = json.dumps({"type": event_type, "data": payload}, default=_json_default)
        async with self._lock:
            targets = list(self._connections)
        dead: list[WebSocket] = []
        for connection in targets:
            try:
                authorized = getattr(connection.state, 'is_authorized', None)
                if authorized is not None and not authorized():
                    await connection.close(code=1008)
                    dead.append(connection)
                    continue
                await connection.send_text(message)
            except Exception:
                dead.append(connection)
        if dead:
            async with self._lock:
                for connection in dead:
                    self._connections.discard(connection)

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()
