"""Tests for scraper API backfill functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


async def test_fetch_videos_by_api():
    """Test API backfill fetches missing videos."""
    from platform_video_downloader.bilibili.api import BilibiliAPI

    session = AsyncMock()
    api = BilibiliAPI.__new__(BilibiliAPI)
    api.session = session
    api.headers = {"User-Agent": "test", "Referer": "https://www.bilibili.com/"}

    mock_signer = MagicMock()
    mock_signer.sign = MagicMock(side_effect=lambda p: p)
    signer_cls = AsyncMock()
    signer_cls.create = AsyncMock(return_value=mock_signer)

    def make_resp(vlist, pn=1, count=None):
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "code": 0,
            "data": {
                "list": {"vlist": vlist},
                "page": {"pn": pn, "count": count or len(vlist)},
            }
        })
        mock_resp.raise_for_status = MagicMock()
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        return mock_resp

    page1 = [{"bvid": f"BV{i}", "title": f"V{i}", "length": "5:00", "created": 0, "tag": "", "cid": 0, "aid": 0} for i in range(30)]
    page2 = [{"bvid": f"BV{i}", "title": f"V{i}", "length": "5:00", "created": 0, "tag": "", "cid": 0, "aid": 0} for i in range(30, 41)]

    session.get = MagicMock(side_effect=[make_resp(page1, 1, 41), make_resp(page2, 2, 41)])

    with patch("platform_video_downloader.bilibili.wbi.WbiSigner", signer_cls):
        result = await api.fetch_videos_by_api("12345", existing_bvids=set(f"BV{i}" for i in range(10)))

    assert len(result) == 31  # 41 total - 10 existing
