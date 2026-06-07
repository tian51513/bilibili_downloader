"""WebSocket连接管理器，用于实时广播进度消息。"""

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSManager:
    """管理WebSocket连接并向所有客户端广播消息。"""

    def __init__(self):
        self._connections: set[WebSocket] = set()

    def connect(self, ws: WebSocket):
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    def active_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, message: dict[str, Any]):
        if not self._connections:
            return
        disconnected = set()
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            self.disconnect(ws)
            logger.debug("WebSocket disconnected during broadcast")