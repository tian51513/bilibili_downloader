"""Background task service for managing scrape + download tasks."""

import asyncio
import json
import logging
import re

from bilibili_downloader.config import (
    BILIBILI_SPACE_URL_PATTERN,
    DEFAULT_COOKIE_CACHE_PATH,
    DEFAULT_NAME_TEMPLATE,
    DEFAULT_RESOLUTION_PRIORITY,
    MAX_CONCURRENT_API_REQUESTS,
    MAX_CONCURRENT_DOWNLOADS,
    load_settings,
)
from bilibili_downloader.bilibili.api import BilibiliAPI
from bilibili_downloader.core.manager import DownloadManager

logger = logging.getLogger(__name__)

_COOKIE_FILES = {
    "bilibili": DEFAULT_COOKIE_CACHE_PATH,
}


class TaskService:
    """Manages background scrape + download tasks."""

    def __init__(self, db, ws_manager=None):
        self.db = db
        self.ws_manager = ws_manager
        self._scrape_lock = asyncio.Lock()
        self._scrape_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._background_tasks: set[asyncio.Task] = set()
        self._paused_tasks: set[int] = set()
        self._download_running = False
        self._download_cancel = asyncio.Event()
        self._download_task: asyncio.Task | None = None
        self._paused_tasks: set[int] = set()

    async def submit_task(self, space_url: str) -> int:
        """Submit a new scrape task. Returns task_id (existing if duplicate)."""
        existing = await self.db.get_task_by_url(space_url)
        if existing:
            task_id = existing["id"]
            self._paused_tasks.discard(task_id)
            await self.db.update_task_status(task_id, "init", error_message=None, cookie_status="valid")
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "init"}})
            await self._scrape_queue.put(task_id)
            if not self._running:
                self._running = True
                task = asyncio.create_task(self._process_queue())
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            return task_id

        match = re.search(BILIBILI_SPACE_URL_PATTERN, space_url)
        if not match:
            raise ValueError(f"Invalid Bilibili space URL: {space_url}")
        space_uid = match.group(1)

        platform = await self.db.get_platform_by_name("bilibili")
        if not platform:
            pid = await self.db.insert_platform("bilibili")
        else:
            pid = platform["id"]

        task_id = await self.db.insert_task(platform_id=pid, space_url=space_url, space_uid=space_uid)
        await self.db.update_task_status(task_id, "init")

        # Try to fetch UP主 name in advance via API
        await self._prefill_display_name(task_id, space_uid)

        await self._scrape_queue.put(task_id)

        if not self._running:
            self._running = True
            task = asyncio.create_task(self._process_queue())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return task_id

    async def _prefill_display_name(self, task_id: int, space_uid: str):
        """Try to fetch UP主 name via API to display before scraping."""
        try:
            import aiohttp
            cookies = load_cookies_from_file(_COOKIE_FILES.get("bilibili", "bilibili_cookies.json"))
            if not cookies:
                return
            async with aiohttp.ClientSession() as session:
                api = BilibiliAPI(session, cookies=cookies)
                info = await api.get_user_card(space_uid)
                if info and info.get("name"):
                    await self.db.update_task_status(task_id, "init", display_name=info["name"])
                    logger.info(f"[TaskService] 预填UP主名称: {info['name']}")
        except Exception as e:
            logger.debug(f"[TaskService] 预填UP主名称失败: {e}")

    def pause_task(self, task_id: int):
        """Mark a task as paused (cooperative)."""
        self._paused_tasks.add(task_id)

    def resume_task(self, task_id: int):
        """Remove paused mark so the task can run."""
        self._paused_tasks.discard(task_id)

    def is_paused(self, task_id: int) -> bool:
        return task_id in self._paused_tasks

    async def _process_queue(self):
        """Background loop: process scrape tasks sequentially."""
        while True:
            try:
                task_id = await asyncio.wait_for(self._scrape_queue.get(), timeout=5)
            except asyncio.TimeoutError:
                if self._scrape_queue.empty():
                    self._running = False
                    break
                continue

            try:
                await self._execute_task(task_id)
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}", exc_info=True)
                await self.db.update_task_status(task_id, "failed", error_message=str(e))

    async def _execute_task(self, task_id: int):
        """Execute a single scrape + download task."""
        task = await self.db.get_task(task_id)
        if not task:
            return

        logger.info(f"[TaskService] 开始执行任务 {task_id}: {task['space_url']}")

        # Check if paused before starting
        if self.is_paused(task_id):
            await self.db.update_task_status(task_id, "paused", error_message=None)
            self._paused_tasks.discard(task_id)
            return

        settings = load_settings()

        # Check cookie validity
        await self.db.update_task_status(task_id, "init", cookie_status="checking")
        await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "init"}})
        cookie_valid = await self._check_cookie()
        logger.info(f"[TaskService] 任务 {task_id} Cookie检测结果: {'有效' if cookie_valid else '无效'}")
        if not cookie_valid:
            await self.db.update_task_status(task_id, "init", cookie_status="login_required")
            await self._broadcast({"type": "login_required", "task_id": task_id, "message": "Cookie已失效，请扫码登录"})
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "init"}})
            logged_in = await self._wait_for_login(timeout=120)
            if not logged_in:
                await self.db.update_task_status(task_id, "failed", error_message="登录超时", cookie_status="expired")
                await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "failed"}})
                return

        # Phase 1: Scrape
        if self.is_paused(task_id):
            await self.db.update_task_status(task_id, "paused")
            self._paused_tasks.discard(task_id)
            return
        await self.db.update_task_status(task_id, "scraping", cookie_status="valid")
        await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "scraping"}})

        from bilibili_downloader.browser import (
            PlaywrightBrowser,
            load_cookies_from_file,
            save_cookies_to_file,
        )
        from bilibili_downloader.bilibili.scraper import BilibiliScraper

        cookies = load_cookies_from_file(_COOKIE_FILES.get("bilibili", "bilibili_cookies.json"))
        browser = PlaywrightBrowser(headless=True, cookies=cookies)
        await browser.start()

        try:
            scraper = BilibiliScraper(browser)
            data = await scraper.collect(task["space_uid"])
            space_info = data["space_info"]
            videos = data["videos"]

            if not space_info:
                logger.warning(f"[TaskService] 任务 {task_id} 未获取到UP主信息 (mid={task['space_uid']})")

            # API 补全：滚动采集可能遗漏视频，用 arc/search API 主动分页获取
            if cookies and space_info:
                try:
                    import aiohttp
                    async with aiohttp.ClientSession() as session:
                        from bilibili_downloader.bilibili.api import BilibiliAPI
                        api = BilibiliAPI(session, cookies=cookies)
                        existing_bvids = {v["remote_id"] for v in videos}
                        backfill = await api.fetch_videos_by_api(task["space_uid"], existing_bvids)
                        if backfill:
                            videos.extend(backfill)
                            logger.info(f"[TaskService] 任务 {task_id} API补全 {len(backfill)} 个视频, 总计 {len(videos)}")
                except Exception as e:
                    logger.warning(f"[TaskService] 任务 {task_id} API补全失败，使用滚动采集数据: {e}")

            logger.info(f"[TaskService] 任务 {task_id} 采集完成: {len(videos)} 个视频, UP主: {space_info['name'] if space_info else 'N/A'}")
            sections = data["sections"]
            total = len(videos)

            cid = None
            if space_info:
                await self.db.update_task_status(task_id, "scraping", display_name=space_info["name"])

                pid = task["platform_id"]
                creator = await self.db.get_creator_by_remote(pid, space_info["remote_id"])
                if not creator:
                    cid = await self.db.insert_creator(
                        platform_id=pid, remote_id=space_info["remote_id"],
                        name=space_info["name"], space_url=task["space_url"],
                        avatar_url=space_info.get("avatar_url"),
                    )
                else:
                    cid = creator["id"]
                await self.db.update_task_status(task_id, "scraping", creator_id=cid, total_videos=total, scraped_videos=total)
            else:
                await self.db.update_task_status(task_id, "scraping", total_videos=total, scraped_videos=total)

            # Store videos in database
            section_map = {s["remote_id"]: s for s in sections}
            for video_data in videos:
                if cid is None:
                    continue
                remote_id = video_data["remote_id"]
                sec = section_map.get(remote_id)
                video = await self.db.get_video_by_remote(cid, remote_id)
                if not video:
                    vid = await self.db.insert_video(
                        creator_id=cid, remote_id=remote_id,
                        title=video_data["title"],
                        duration=video_data.get("duration"),
                        pubdate=video_data.get("pubdate"),
                        extra=json.dumps(video_data.get("extra")),
                        section_id=sec["section_id"] if sec else None,
                        section_name=sec["section_name"] if sec else None,
                        tags=video_data.get("tags"),
                    )
                tags = video_data.get("tags", [])
                if tags and video and not video.get("tags"):
                    await self.db.update_video_tags(video["id"], tags)

        finally:
            await browser.close()

        await self._broadcast({"type": "scrape_progress", "task_id": task_id,
                               "data": {"scraped": total, "total": total, "phase": "done"}})

        # Create pending download records for all scraped videos
        if cid:
            settings = load_settings()
            resolution_priority = settings.get("resolution_priority", DEFAULT_RESOLUTION_PRIORITY)
            name_template = settings.get("name_template", DEFAULT_NAME_TEMPLATE)
            save_dir = settings.get("output_dir", "./downloads")
            from bilibili_downloader.storage.files import build_filename, resolve_save_path
            videos = await self.db.get_videos_by_creator(cid)
            dl_count = 0
            for video in videos:
                filename = build_filename(
                    title=video["title"], creator=space_info["name"] if space_info else "",
                    section=video.get("section_name"), bvid=video.get("remote_id", ""),
                    template=name_template,
                )
                save_path = resolve_save_path(save_dir, filename)
                await self.db.insert_download(
                    video_id=video["id"], save_path=save_path,
                    resolution=resolution_priority[0] if resolution_priority else "720p",
                )
                dl_count += 1
            await self.db.update_task_status(task_id, "pending", total_videos=total, scraped_videos=total, total_downloads=dl_count, error_message=None)
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "pending", "total_downloads": dl_count}})
            logger.info(f"[TaskService] 任务 {task_id} 已创建 {dl_count} 个待下载记录")
        else:
            await self.db.update_task_status(task_id, "failed", error_message="无法获取UP主信息")
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "failed"}})

    async def _check_cookie(self) -> bool:
        """Check if cookie is valid."""
        import aiohttp
        from bilibili_downloader.browser import load_cookies_from_file
        cookies = load_cookies_from_file(_COOKIE_FILES.get("bilibili", "bilibili_cookies.json"))
        if not cookies:
            return False
        async with aiohttp.ClientSession() as session:
            api = BilibiliAPI(session, cookies=cookies)
            return await api.validate_cookie()

    async def _wait_for_login(self, timeout: int = 120) -> bool:
        """Wait for QR login to complete."""
        start = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                return False
            if await self._check_cookie():
                await self._broadcast({"type": "login_success", "message": "登录成功"})
                return True
            await asyncio.sleep(2)

    async def trigger_qr_login(self) -> bool:
        """Trigger QR code login in a headed browser."""
        from bilibili_downloader.browser import PlaywrightBrowser, save_cookies_to_file
        from bilibili_downloader.cli.main import _qr_code_login
        browser = PlaywrightBrowser(headless=False)
        await browser.start()
        try:
            login_cookies = await _qr_code_login(browser.page)
            cookie_path = _COOKIE_FILES.get("bilibili", "bilibili_cookies.json")
            save_cookies_to_file(login_cookies, cookie_path)
            return True
        except Exception as e:
            logger.error(f"QR login failed: {e}")
            return False
        finally:
            await browser.close()

    async def _broadcast(self, message: dict):
        if self.ws_manager:
            await self.ws_manager.broadcast(message)

    async def start_downloads(self) -> tuple[bool, int]:
        """Start downloading all pending videos. Returns (started, pending_count)."""
        if self._download_running:
            return (False, -1)
        # Check pending count
        all_pending = []
        page = 1
        while True:
            result = await self.db.get_all_downloads(status="pending", page=page, page_size=200)
            items = result["items"] if isinstance(result, dict) else result
            all_pending.extend(items)
            if len(all_pending) >= result.get("total", 0) or not items:
                break
            page += 1
        if not all_pending:
            return (False, 0)
        self._download_cancel.clear()
        self._download_running = True

        async def _run():
            try:
                from bilibili_downloader.browser import load_cookies_from_file
                settings = load_settings()
                import aiohttp
                cookies = load_cookies_from_file(_COOKIE_FILES.get("bilibili", "bilibili_cookies.json"))
                async with aiohttp.ClientSession() as session:
                    api = BilibiliAPI(session, cookies=cookies)
                    resolution_priority = settings.get("resolution_priority", DEFAULT_RESOLUTION_PRIORITY)
                    speed_limit_bps = int(settings.get("download_speed_limit", 0) * 1024 * 1024)
                    manager = DownloadManager(
                        db=self.db, api=api,
                        save_dir=settings.get("output_dir", "./downloads"),
                        resolution_priority=resolution_priority,
                        max_concurrent_downloads=settings.get("max_concurrent_downloads", MAX_CONCURRENT_DOWNLOADS),
                        max_concurrent_api=settings.get("max_concurrent_api", MAX_CONCURRENT_API_REQUESTS),
                        name_template=settings.get("name_template", DEFAULT_NAME_TEMPLATE),
                        speed_limit_bps=speed_limit_bps,
                        ws_manager=self.ws_manager,
                        cancel_event=self._download_cancel,
                    )
                    await manager.run(session)
            except Exception as e:
                logger.error(f"Download error: {e}", exc_info=True)
            finally:
                self._download_running = False
                await self._broadcast({"type": "download_progress", "status": "stopped"})
                # 下载结束后同步所有任务状态
                try:
                    tasks_result = await self.db.get_all_tasks(page=1, page_size=200)
                    for t in tasks_result.get("items", []):
                        await self.db.sync_task_status_from_downloads(t["id"])
                except Exception as e:
                    logger.error(f"[TaskService] 同步任务状态失败: {e}")

        self._download_task = asyncio.create_task(_run())
        self._background_tasks.add(self._download_task)
        self._download_task.add_done_callback(self._background_tasks.discard)
        await self._broadcast({"type": "download_progress", "status": "started"})
        return (True, len(all_pending))

    async def pause_downloads(self) -> bool:
        """Pause all downloads. Returns False if not running."""
        if not self._download_running:
            return False
        self._download_cancel.set()
        return True

    def is_downloading(self) -> bool:
        return self._download_running
