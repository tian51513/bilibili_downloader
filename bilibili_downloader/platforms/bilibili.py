"""Bilibili 平台实现 — 封装现有 bilibili/ 模块。"""

from __future__ import annotations

import json
import logging
import re

from bilibili_downloader.config import DEFAULT_COOKIE_CACHE_PATH
from bilibili_downloader.platforms.base import BasePlatform

logger = logging.getLogger(__name__)

_SPACE_URL_PATTERN = re.compile(r"https?://space\.bilibili\.com/(\d+)")


class BilibiliPlatform(BasePlatform):
    name = "bilibili"
    display_name = "Bilibili"
    base_url = "https://www.bilibili.com"
    cookie_domain = ".bilibili.com"
    cookie_cache_path = DEFAULT_COOKIE_CACHE_PATH

    def parse_url(self, url: str) -> dict:
        match = re.search(_SPACE_URL_PATTERN, url)
        if not match:
            raise ValueError(f"无效的 Bilibili 空间 URL: {url}")
        space_uid = match.group(1)
        return {
            "creator_id": space_uid,
            "creator_name": None,
            "space_url": f"https://space.bilibili.com/{space_uid}",
        }

    async def scrape(self, creator_id: str, **kwargs) -> dict:
        from bilibili_downloader.bilibili.api import BilibiliAPI
        from bilibili_downloader.bilibili.scraper import BilibiliScraper

        browser = kwargs.get("browser")
        session = kwargs.get("session")
        cookies = kwargs.get("cookies")

        scraper = BilibiliScraper(browser)
        data = await scraper.collect(creator_id)

        # API 补全
        if session and cookies:
            try:
                api = BilibiliAPI(session, cookies=cookies)
                existing_bvids = {v["remote_id"] for v in data["videos"]}
                backfill = await api.fetch_videos_by_api(creator_id, existing_bvids)
                if backfill:
                    data["videos"].extend(backfill)
                    logger.info(f"[BilibiliPlatform] API 补全 {len(backfill)} 个视频")
            except Exception as e:
                logger.warning(f"[BilibiliPlatform] API 补全失败: {e}")

        space_info = data.get("space_info")
        creator_info = None
        if space_info:
            creator_info = {
                "name": space_info["name"],
                "avatar_url": space_info.get("avatar_url"),
                "remote_id": space_info["remote_id"],
            }

        return {
            "creator_info": creator_info,
            "videos": data["videos"],
            "sections": data.get("sections", []),
        }

    async def download_single(
        self,
        video: dict,
        save_dir: str,
        name_template: str,
        download_id: int,
        db,
        ws_manager=None,
        cancel_event=None,
        speed_limit_bps: int = 0,
        **kwargs,
    ) -> dict:
        import asyncio

        from bilibili_downloader.core.worker import download_video

        api = kwargs.get("api")
        session = kwargs.get("session")
        if not api or not session:
            return {"status": "failed", "error": "缺少 api 或 session 参数"}

        api_semaphore = kwargs.get("api_semaphore", asyncio.Semaphore(10))
        download_semaphore = kwargs.get("download_semaphore", asyncio.Semaphore(5))

        try:
            await download_video(
                db=db,
                download_id=download_id,
                video=video,
                creator_name=kwargs.get("creator_name", ""),
                section_name=video.get("section_name"),
                save_dir=save_dir,
                api=api,
                session=session,
                resolution_priority=kwargs.get("resolution_priority", ["720p"]),
                name_template=name_template,
                api_semaphore=api_semaphore,
                download_semaphore=download_semaphore,
                speed_limit_bps=speed_limit_bps,
                ws_manager=ws_manager,
                cancel_event=cancel_event,
            )
            dl = await db.get_download(download_id)
            return {"status": dl["status"], "error": dl.get("error_msg"), "file_size": dl.get("file_size")}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def needs_cookie(self) -> bool:
        return True

    def needs_browser(self) -> bool:
        return True
