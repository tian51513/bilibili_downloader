import asyncio
from unittest.mock import AsyncMock

async def test_broadcast_sends_to_all_connections():
    from platform_video_downloader.web.ws_manager import WSManager
    mgr = WSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    mgr.connect(ws1)
    mgr.connect(ws2)
    await mgr.broadcast({"type": "test", "data": "hello"})
    ws1.send_json.assert_called_once_with({"type": "test", "data": "hello"})
    ws2.send_json.assert_called_once_with({"type": "test", "data": "hello"})

async def test_disconnect_removes_connection():
    from platform_video_downloader.web.ws_manager import WSManager
    mgr = WSManager()
    ws = AsyncMock()
    mgr.connect(ws)
    assert mgr.active_count() == 1
    mgr.disconnect(ws)
    assert mgr.active_count() == 0

async def test_broadcast_empty_does_nothing():
    from platform_video_downloader.web.ws_manager import WSManager
    mgr = WSManager()
    await mgr.broadcast({"type": "test"})  # Should not raise