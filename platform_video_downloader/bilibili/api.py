import logging
from urllib.parse import urlencode

import aiohttp

from platform_video_downloader.bilibili.parser import parse_stream_urls
from platform_video_downloader.config import BILIBILI_API_BASE, REQUEST_TIMEOUT, USER_AGENT

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

        cid 来自 /x/web-interface/view，tags 来自 /x/tag/archive/tags（无需WBI签名）。
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

        # 检测充电专属视频
        if video_data.get("is_upower_exclusive"):
            logger.info(f"[api] {bvid} 为UP主充电专属视频，跳过")
            return {"cid": cid, "tags": [], "is_upower_exclusive": True}

        # Fetch tags from dedicated tag endpoint (more reliable than view API)
        tags = []
        try:
            tag_url = f"{BILIBILI_API_BASE}/x/tag/archive/tags?bvid={bvid}"
            async with self.session.get(tag_url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
                tag_data = await resp.json()
            if tag_data.get("code") == 0 and tag_data.get("data"):
                tags = [t["tag_name"] for t in tag_data["data"]]
        except Exception as e:
            logger.debug(f"[api] get_video_info bvid={bvid} tag fetch failed: {e}")

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

    async def validate_cookie_for_scraping(self) -> bool:
        """检查 cookie 是否可用于采集（测试 arc/search 端点）。

        使用官方账号（mid=2）的公开空间测试，如果返回 -403 则说明 cookie 无效。
        """
        from platform_video_downloader.bilibili.wbi import WbiSigner
        try:
            signer = await WbiSigner.create(self.session)
            params = signer.sign({"mid": "2", "ps": 1, "pn": 1, "order": "pubdate"})
            url = f"{BILIBILI_API_BASE}/x/space/wbi/arc/search?{urlencode(params)}"
            async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status != 200:
                    return False
                data = await resp.json()
                code = data.get("code", -1)
                if code == -403:
                    return False
                return code == 0 or code == -400  # -400=请求错误但不是权限问题
        except Exception:
            return False

    async def get_user_card(self, mid: str) -> dict | None:
        """Get user card info (name, face, etc.) by mid."""
        url = f"{BILIBILI_API_BASE}/x/web-interface/card"
        try:
            async with self.session.get(url, params={"mid": mid}, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if data.get("code") == 0:
                    return data.get("data")
        except Exception:
            pass
        return None

    async def fetch_videos_by_api(
        self, mid: str, existing_bvids: set[str] | None = None,
    ) -> list[dict]:
        """Fetch all videos for a UP主 via arc/search API with WBI signature.

        Used to backfill videos that scrolling didn't collect.
        """
        from platform_video_downloader.bilibili.parser import parse_video_list
        from platform_video_downloader.bilibili.wbi import WbiSigner

        existing_bvids = existing_bvids or set()
        all_videos: list[dict] = []
        seen_bvids = set(existing_bvids)
        page = 1
        total = None
        paid_count = 0

        signer = await WbiSigner.create(self.session)

        while True:
            params = signer.sign({
                "mid": mid,
                "ps": 30,
                "pn": page,
                "order": "pubdate",
            })
            url = f"{BILIBILI_API_BASE}/x/space/wbi/arc/search?{urlencode(params)}"
            async with self.session.get(url, headers=self.headers, timeout=REQUEST_TIMEOUT) as resp:
                resp.raise_for_status()
                data = await resp.json()

            if data.get("code") != 0:
                logger.warning(f"[api] arc/search backfill page {page} error: {data.get('message')}")
                break

            page_data = data["data"]
            total = page_data.get("page", {}).get("count", 0)
            new_videos = []
            for v in data.get("data", {}).get("list", {}).get("vlist", []):
                if v.get('price', 0) and v['price'] > 0:
                    paid_count += 1
            for v in parse_video_list(data):
                if v["remote_id"] not in seen_bvids:
                    new_videos.append(v)
                    seen_bvids.add(v["remote_id"])

            all_videos.extend(new_videos)
            logger.info(f"[api] backfill page {page}: {len(new_videos)} new, seen {len(seen_bvids)}/{total}")

            if len(seen_bvids) >= total:
                break
            page += 1

        if paid_count > 0:
            logger.info(f"[api] backfill 过滤 {paid_count} 个付费/充电专属视频")

        return all_videos
