import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDownloadManager:
    async def test_manager_processes_queue(self, tmp_path, db):
        from bilibili_downloader.core.manager import DownloadManager
        from bilibili_downloader.bilibili.api import BilibiliAPI

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(platform_id=pid, remote_id="123", name="TestUP", space_url="https://space.bilibili.com/123")
        await db.insert_video(creator_id=cid, remote_id="BV1aa", title="Video A", duration=60, extra='{"cid": 111}')
        await db.insert_video(creator_id=cid, remote_id="BV1bb", title="Video B", duration=60, extra='{"cid": 222}')

        mock_api = AsyncMock(spec=BilibiliAPI)
        manager = DownloadManager(db=db, api=mock_api, save_dir=str(tmp_path), resolution_priority=["720p"], max_concurrent_downloads=2)

        mock_session = MagicMock()

        async def fake_download(**kwargs):
            await kwargs["db"].update_download_status(kwargs["download_id"], "completed")
            await kwargs["db"].update_download_progress(kwargs["download_id"], 1000)

        with patch("bilibili_downloader.core.manager.download_video", side_effect=fake_download):
            await manager.run(mock_session)

        stats = await db.get_stats()
        assert stats["completed"] == 2
        assert stats["pending"] == 0

    async def test_manager_skips_existing(self, tmp_path, db):
        from bilibili_downloader.core.manager import DownloadManager
        from bilibili_downloader.bilibili.api import BilibiliAPI

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(platform_id=pid, remote_id="123", name="TestUP", space_url="https://space.bilibili.com/123")
        vid = await db.insert_video(creator_id=cid, remote_id="BV1aa", title="Video A", duration=60, extra='{"cid": 111}')
        did = await db.insert_download(video_id=vid, save_path="/old/a.mp4", resolution="720p")
        await db.update_download_status(did, "completed")

        mock_api = AsyncMock(spec=BilibiliAPI)
        manager = DownloadManager(db=db, api=mock_api, save_dir=str(tmp_path), resolution_priority=["720p"], max_concurrent_downloads=2)

        results = await manager._build_queue(cid)
        assert len(results) == 0
