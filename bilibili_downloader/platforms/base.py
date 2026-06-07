"""平台抽象基类与注册中心。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BasePlatform(ABC):
    """多平台下载器的抽象基类。

    每个平台需实现 URL 解析、数据采集和下载三个核心接口。
    """

    name: str = ""           # 平台标识: "bilibili" / "youtube"
    display_name: str = ""   # 显示名称
    base_url: str = ""       # 主站 URL
    cookie_domain: str = ""  # Cookie 域名
    cookie_cache_path: str = ""  # Cookie 缓存文件名

    @abstractmethod
    def parse_url(self, url: str) -> dict:
        """解析平台 URL。

        Returns:
            {
                "creator_id": str,   # 平台内唯一 ID（B站 mid / YouTube playlist ID）
                "creator_name": str | None,  # 可选，已知时预填
                "space_url": str,    # 标准化后的 URL
            }
        """

    @abstractmethod
    async def scrape(self, creator_id: str, **kwargs) -> dict:
        """采集创作者的视频列表。

        Args:
            creator_id: 平台内唯一 ID
            **kwargs: 平台特定参数（cookies, browser, session 等）

        Returns:
            {
                "creator_info": dict | None,  # {name, avatar_url, remote_id, ...}
                "videos": list[dict],          # [{remote_id, title, duration, pubdate, extra, tags}, ...]
            }
        """

    @abstractmethod
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
        """下载单个视频。

        Args:
            video: 数据库中的 video 记录
            save_dir: 保存目录
            name_template: 文件名模板
            download_id: 数据库下载记录 ID
            db: 数据库实例
            ws_manager: WebSocket 管理器（进度推送）
            cancel_event: 取消事件
            speed_limit_bps: 限速（字节/秒）
            **kwargs: 平台特定参数

        Returns:
            {"status": "completed"|"skipped"|"failed", "error": str | None, "file_size": int | None}
        """

    def needs_cookie(self) -> bool:
        """该平台是否需要 Cookie 才能工作。默认 False。"""
        return False

    def needs_browser(self) -> bool:
        """该平台是否需要 Playwright 浏览器采集。默认 False。"""
        return False


class PlatformRegistry:
    """平台注册中心，根据 URL 自动识别平台。"""

    def __init__(self):
        self._platforms: dict[str, BasePlatform] = {}

    def register(self, platform: BasePlatform):
        """注册一个平台实现。"""
        self._platforms[platform.name] = platform
        logger.info(f"已注册平台: {platform.name} ({platform.display_name})")

    def get(self, name: str) -> BasePlatform | None:
        return self._platforms.get(name)

    async def get_by_db_platform_id(self, db, platform_id: int) -> BasePlatform | None:
        """通过数据库 platform ID 查找平台实现。"""
        platform_row = await db.get_platform(platform_id)
        if platform_row:
            return self._platforms.get(platform_row["name"])
        return None

    def identify(self, url: str) -> BasePlatform | None:
        """根据 URL 识别对应的平台。"""
        for platform in self._platforms.values():
            try:
                platform.parse_url(url)
                return platform
            except (ValueError, KeyError):
                continue
        return None

    def list_platforms(self) -> list[BasePlatform]:
        return list(self._platforms.values())


def create_registry() -> PlatformRegistry:
    """创建并注册所有已知的平台。"""
    registry = PlatformRegistry()

    from bilibili_downloader.platforms.bilibili import BilibiliPlatform
    registry.register(BilibiliPlatform())

    from bilibili_downloader.platforms.youtube import YouTubePlatform
    registry.register(YouTubePlatform())

    return registry
