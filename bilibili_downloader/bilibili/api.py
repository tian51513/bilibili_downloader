import logging
from urllib.parse import urlencode

import aiohttp

from bilibili_downloader.bilibili.parser import parse_stream_urls
from bilibili_downloader.config import BILIBILI_API_BASE, REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)


class BilibiliAPI:
    """精简版B站API，仅用于获取视频流URL。

    数据采集（UP主信息、视频列表、合集）由 BilibiliScraper 通过
    Playwright 浏览器上下文完成。此类仅处理流URL获取，
    该接口无需WBI签名。
    """

    def __init__(self, session: aiohttp.ClientSession, cookies: list[dict] | None = None):
        self.session = session
        self.headers = {
            "User-Agent": USER_AGENT,
            "Referer": "https://www.bilibili.com/",
        }
        if cookies:
            self.headers["Cookie"] = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

    async def get_cid(self, bvid: str) -> int:
        """通过bvid获取视频的cid（第一P）。

        /x/web-interface/view 接口无需WBI签名即可获取cid。
        """
        url = f"{BILIBILI_API_BASE}/x/web-interface/view?bvid={bvid}"
        logger.debug(f"[api] get_cid bvid={bvid} url={url}")
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json()
        code = data.get("code", -1)
        if code != 0:
            raise ValueError(f"API error getting cid for {bvid}: code={code}, message={data.get('message')}")
        pages = data.get("data", {}).get("pages", [])
        if not pages:
            raise ValueError(f"No pages found for {bvid}")
        cid = pages[0]["cid"]
        logger.debug(f"[api] get_cid bvid={bvid} cid={cid}")
        return cid

    async def get_video_info(self, bvid: str) -> dict:
        """获取视频详情（cid + tags）。

        /x/web-interface/view 接口返回视频信息包含标签。
        Returns: {"cid": int, "tags": list[str]}
        """
        url = f"{BILIBILI_API_BASE}/x/web-interface/view?bvid={bvid}"
        logger.debug(f"[api] get_video_info bvid={bvid} url={url}")
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json()
        code = data.get("code", -1)
        if code != 0:
            raise ValueError(f"API error getting video info for {bvid}: code={code}, message={data.get('message')}")
        video_data = data.get("data", {})
        pages = video_data.get("pages", [])
        cid = pages[0]["cid"] if pages else None
        tags = [t["tag_name"] for t in video_data.get("tag", [])] if video_data.get("tag") else []
        logger.debug(f"[api] get_video_info bvid={bvid} cid={cid} tags={tags}")
        return {"cid": cid, "tags": tags}

    async def get_stream_urls(
        self, bvid: str, cid: int, priority: list[str] | None = None
    ) -> dict:
        """获取视频DASH流URL，无需WBI签名。"""
        params = {"bvid": bvid, "cid": cid, "qn": 80, "fnval": 16, "fourk": 1}
        url = f"{BILIBILI_API_BASE}/x/player/playurl?{urlencode(params)}"
        logger.debug(f"[api] get_stream_urls bvid={bvid} cid={cid} url={url}")
        async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
            logger.debug(f"[api] get_stream_urls bvid={bvid} status={resp.status}")
            resp.raise_for_status()
            data = await resp.json()
        code = data.get("code", -1)
        if code != 0:
            logger.debug(f"[api] get_stream_urls bvid={bvid} error response: code={code} message={data.get('message')} data={data}")
            raise ValueError(f"API error: code={code}, message={data.get('message')}")
        return parse_stream_urls(data, priority)

    async def validate_cookie(self) -> bool:
        """检查当前cookie/session是否仍然有效。"""
        url = f"{BILIBILI_API_BASE}/x/web-interface/nav"
        try:
            async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                return data.get("code") == 0 and data.get("data", {}).get("isLogin", False)
        except Exception:
            return False
