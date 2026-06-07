import asyncio
from unittest.mock import AsyncMock, MagicMock


async def test_submit_creates_task():
    from bilibili_downloader.web.task_service import TaskService
    db = AsyncMock()
    db.insert_platform = AsyncMock(return_value=1)
    db.get_platform_by_name = AsyncMock(return_value={"id": 1})
    db.insert_task = AsyncMock(return_value=42)
    db.get_task_by_url = AsyncMock(return_value=None)
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    ts = TaskService(db=db, ws_manager=ws_manager)
    task_id = await ts.submit_task("https://space.bilibili.com/12345")
    assert task_id == 42
    db.insert_task.assert_called_once()


async def test_submit_returns_existing():
    from bilibili_downloader.web.task_service import TaskService
    db = AsyncMock()
    db.get_task_by_url = AsyncMock(return_value={"id": 99, "status": "pending"})
    ws_manager = MagicMock()
    ws_manager.broadcast = AsyncMock()
    ts = TaskService(db=db, ws_manager=ws_manager)
    task_id = await ts.submit_task("https://space.bilibili.com/12345")
    assert task_id == 99
    db.insert_task.assert_not_called()


async def test_submit_invalid_url():
    from bilibili_downloader.web.task_service import TaskService
    db = AsyncMock()
    db.get_task_by_url = AsyncMock(return_value=None)
    db.get_platform_by_name = AsyncMock(return_value=None)
    db.insert_platform = AsyncMock(return_value=1)
    db.insert_task = AsyncMock(return_value=99)
    db.update_task_status = AsyncMock()
    ws_manager = AsyncMock()
    ws_manager.broadcast = AsyncMock()
    ts = TaskService(db=db, ws_manager=ws_manager)
    task_id = await ts.submit_task("https://example.com/invalid")
    assert task_id == 99
    db.update_task_status.assert_called_once_with(99, "failed", error_message="该平台暂不支持，开发中")


async def test_broadcast_calls_ws_manager():
    from bilibili_downloader.web.task_service import TaskService
    db = AsyncMock()
    ws_manager = AsyncMock()
    ws_manager.broadcast = AsyncMock()
    ts = TaskService(db=db, ws_manager=ws_manager)
    await ts._broadcast({"type": "test"})
    ws_manager.broadcast.assert_called_once_with({"type": "test"})


async def test_broadcast_no_ws_manager():
    from bilibili_downloader.web.task_service import TaskService
    db = AsyncMock()
    ts = TaskService(db=db, ws_manager=None)
    await ts._broadcast({"type": "test"})  # Should not raise
