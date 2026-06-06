import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_async_iter(chunks):
    """Create an async iterator from a list of byte chunks."""
    async def _aiter():
        for chunk in chunks:
            yield chunk
    return _aiter()


class TestDownloadWorker:
    async def test_download_success(self, tmp_path, db):
        from bilibili_downloader.core.worker import download_video
        from bilibili_downloader.config import DEFAULT_NAME_TEMPLATE

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="TestUP",
            space_url="https://space.bilibili.com/123",
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="Test Video",
            duration=60, extra='{"cid": 456}',
        )
        did = await db.insert_download(
            video_id=vid, save_path=str(tmp_path / "test.mp4"), resolution="720p",
        )

        mock_api = AsyncMock()
        mock_api.get_stream_urls.return_value = {
            "video_url": "http://example.com/video.mp4",
            "audio_url": "http://example.com/audio.mp4",
            "resolution": "720p",
        }

        mock_session = MagicMock()
        video_resp = AsyncMock()
        video_resp.status = 200
        video_resp.headers = {"Content-Length": "1000"}
        video_resp.raise_for_status = MagicMock()
        video_resp.content.iter_chunked = MagicMock(
            return_value=_make_async_iter([b"v" * 1000])
        )
        audio_resp = AsyncMock()
        audio_resp.status = 200
        audio_resp.headers = {"Content-Length": "500"}
        audio_resp.raise_for_status = MagicMock()
        audio_resp.content.iter_chunked = MagicMock(
            return_value=_make_async_iter([b"a" * 500])
        )
        mock_session.get = MagicMock(side_effect=[
            AsyncMock(
                __aenter__=AsyncMock(return_value=video_resp),
                __aexit__=AsyncMock(return_value=False),
            ),
            AsyncMock(
                __aenter__=AsyncMock(return_value=audio_resp),
                __aexit__=AsyncMock(return_value=False),
            ),
        ])

        await download_video(
            db=db, download_id=did,
            video={"id": vid, "remote_id": "BV1xx", "title": "Test Video", "extra": {"cid": 456}},
            creator_name="TestUP", section_name=None, save_dir=str(tmp_path),
            api=mock_api, session=mock_session,
            resolution_priority=["720p"],
            name_template=DEFAULT_NAME_TEMPLATE,
            api_semaphore=AsyncMock(), download_semaphore=AsyncMock(),
        )

        dl = await db.get_download(did)
        assert dl["status"] == "completed"
        assert dl["file_size"] == 1000

    async def test_download_skipped_on_paid(self, tmp_path, db):
        from bilibili_downloader.core.worker import download_video
        from bilibili_downloader.config import DEFAULT_NAME_TEMPLATE

        pid = await db.insert_platform(name="bilibili")
        cid = await db.insert_creator(
            platform_id=pid, remote_id="123", name="TestUP",
            space_url="https://space.bilibili.com/123",
        )
        vid = await db.insert_video(
            creator_id=cid, remote_id="BV1xx", title="Paid Video",
            duration=60, extra='{"cid": 456}',
        )
        did = await db.insert_download(
            video_id=vid, save_path=str(tmp_path / "paid.mp4"), resolution="720p",
        )

        mock_api = AsyncMock()
        mock_api.get_stream_urls.side_effect = ValueError("code=62002, message=需要充值")
        mock_session = MagicMock()

        await download_video(
            db=db, download_id=did,
            video={"id": vid, "remote_id": "BV1xx", "title": "Paid Video", "extra": {"cid": 456}},
            creator_name="TestUP", section_name=None, save_dir=str(tmp_path),
            api=mock_api, session=mock_session,
            resolution_priority=["720p"],
            name_template=DEFAULT_NAME_TEMPLATE,
            api_semaphore=AsyncMock(), download_semaphore=AsyncMock(),
        )

        dl = await db.get_download(did)
        assert dl["status"] == "skipped"
        assert "充值" in dl["error_msg"]
