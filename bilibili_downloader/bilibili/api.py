import aiohttp

from bilibili_downloader.config import BILIBILI_API_BASE, REQUEST_TIMEOUT, USER_AGENT
from bilibili_downloader.bilibili.parser import (
    parse_space_info,
    parse_video_list,
    parse_sections,
    parse_stream_urls,
)


class BilibiliAPI:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.headers = {"User-Agent": USER_AGENT}

    async def get_space_info(self, mid: str) -> dict:
        url = f"{BILIBILI_API_BASE}/x/space/wbi/acc/info?mid={mid}"
        async with self.session.get(
            url, headers=self.headers, timeout=REQUEST_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            return parse_space_info(await resp.json())

    async def get_video_list(
        self, mid: str, page: int = 1, page_size: int = 50
    ) -> dict:
        url = (
            f"{BILIBILI_API_BASE}/x/space/arc/search"
            f"?mid={mid}&ps={page_size}&pn={page}&order=pubdate"
        )
        async with self.session.get(
            url, headers=self.headers, timeout=REQUEST_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
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
        url = f"{BILIBILI_API_BASE}/x/space/section/index?mid={mid}"
        async with self.session.get(
            url, headers=self.headers, timeout=REQUEST_TIMEOUT
        ) as resp:
            if resp.status == 404:
                return []
            resp.raise_for_status()
            data = await resp.json()
            return parse_sections(data)

    async def get_stream_urls(
        self, bvid: str, cid: int, priority: list[str] | None = None
    ) -> dict:
        url = (
            f"{BILIBILI_API_BASE}/x/player/playurl"
            f"?bvid={bvid}&cid={cid}&qn=80&fnval=16&fourk=1"
        )
        async with self.session.get(
            url, headers=self.headers, timeout=REQUEST_TIMEOUT
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            code = data.get("code", -1)
            if code != 0:
                raise ValueError(
                    f"API error: code={code}, message={data.get('message')}"
                )
            return parse_stream_urls(data, priority)
