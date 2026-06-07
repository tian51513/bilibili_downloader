import asyncio
from unittest.mock import AsyncMock, MagicMock


async def test_validate_cookie_valid():
    from platform_video_downloader.bilibili.api import BilibiliAPI
    session = AsyncMock()
    api = BilibiliAPI.__new__(BilibiliAPI)
    api.session = session
    api.headers = {"User-Agent": "test", "Referer": "https://www.bilibili.com/"}
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"code": 0, "data": {"isLogin": True}})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=mock_resp)
    result = await api.validate_cookie()
    assert result is True


async def test_validate_cookie_expired():
    from platform_video_downloader.bilibili.api import BilibiliAPI
    session = AsyncMock()
    api = BilibiliAPI.__new__(BilibiliAPI)
    api.session = session
    api.headers = {"User-Agent": "test", "Referer": "https://www.bilibili.com/"}
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value={"code": 0, "data": {"isLogin": False}})
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)
    session.get = MagicMock(return_value=mock_resp)
    result = await api.validate_cookie()
    assert result is False


async def test_validate_cookie_network_error():
    from platform_video_downloader.bilibili.api import BilibiliAPI
    session = AsyncMock()
    api = BilibiliAPI.__new__(BilibiliAPI)
    api.session = session
    api.headers = {"User-Agent": "test", "Referer": "https://www.bilibili.com/"}
    session.get = MagicMock(side_effect=Exception("network error"))
    result = await api.validate_cookie()
    assert result is False