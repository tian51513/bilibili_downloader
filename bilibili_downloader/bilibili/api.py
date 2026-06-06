import logging
from urllib.parse import urlencode

import aiohttp

from bilibili_downloader.bilibili.parser import (
    parse_sections,
    parse_space_info,
    parse_stream_urls,
    parse_video_list,
)
from bilibili_downloader.bilibili.wbi import WbiSigner
from bilibili_downloader.config import BILIBILI_API_BASE, REQUEST_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)


class BilibiliAPI:
    def __init__(self, session: aiohttp.ClientSession, wbi_signer: WbiSigner | None = None):
        self.session = session
        self.headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}
        self.wbi_signer = wbi_signer

    @classmethod
    async def create(cls, session: aiohttp.ClientSession) -> "BilibiliAPI":
        """创建 BilibiliAPI 实例，自动获取 WBI 签名密钥。

        参考 yutto 实现：先 touch 主页，再获取 WBI 密钥。
        """
        # 先访问主页建立连接上下文
        try:
            async with session.get(
                "https://www.bilibili.com/", headers=cls._default_headers(),
                timeout=aiohttp.ClientTimeout(total=5),
            ):
                pass
        except Exception:
            pass  # 主页访问失败不影响后续请求
        wbi_signer = await WbiSigner.create(session)
        return cls(session, wbi_signer=wbi_signer)

    @staticmethod
    def _default_headers() -> dict:
        return {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}

    async def _get_json(self, url: str, params: dict | None = None, sign: bool = False) -> dict:
        """通用 GET 请求，可选 WBI 签名，检查 API 错误码。"""
        if params is None:
            params = {}
        str_params = {k: str(v) for k, v in params.items()}
        if sign and self.wbi_signer:
            str_params = self.wbi_signer.sign(str_params)
        # 手动构建 URL，避免 aiohttp 二次编码导致 WBI 签名失效
        full_url = url if not str_params else f"{url}?{urlencode(str_params)}"
        async with self.session.get(
            full_url, headers=self.headers, timeout=REQUEST_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
        code = data.get("code", -1)
        if code != 0:
            raise ValueError(f"API error: code={code}, message={data.get('message')}")
        return data

    async def get_space_info(self, mid: str) -> dict:
        url = f"{BILIBILI_API_BASE}/x/space/wbi/acc/info"
        data = await self._get_json(url, params={"mid": mid}, sign=True)
        return parse_space_info(data)

    async def get_video_list(
        self, mid: str, page: int = 1, page_size: int = 50
    ) -> dict:
        url = f"{BILIBILI_API_BASE}/x/space/arc/search"
        data = await self._get_json(
            url, params={"mid": mid, "ps": page_size, "pn": page, "order": "pubdate"}
        )
        videos = parse_video_list(data)
        total = data.get("data", {}).get("page", {}).get("count", 0)
        return {"videos": videos, "total": total}

    async def get_all_videos(self, mid: str) -> list[dict]:
        all_videos = []
        page = 1
        while True:
            result = await self.get_video_list(mid, page=page)
            all_videos.extend(result["videos"])
            if len(all_videos) >= result["total"] or not result["videos"]:
                break
            page += 1
        return all_videos

    async def get_sections(self, mid: str) -> list[dict]:
        url = f"{BILIBILI_API_BASE}/x/space/section/index"
        async with self.session.get(
            url, headers=self.headers, params={"mid": mid}, timeout=REQUEST_TIMEOUT
        ) as resp:
            if resp.status == 404:
                return []
            resp.raise_for_status()
            data = await resp.json()
        if data.get("code") != 0:
            return []
        return parse_sections(data)

    async def get_stream_urls(
        self, bvid: str, cid: int, priority: list[str] | None = None
    ) -> dict:
        url = f"{BILIBILI_API_BASE}/x/player/playurl"
        data = await self._get_json(
            url, params={"bvid": bvid, "cid": cid, "qn": 80, "fnval": 16, "fourk": 1}
        )
        return parse_stream_urls(data, priority)
