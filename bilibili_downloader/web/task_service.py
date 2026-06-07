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
from bilibili_downloader.platforms.base import create_registry

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
        self._registry = create_registry()

    def _add_bg_task(self, coro) -> asyncio.Task:
        """创建后台任务并注册自动清理回调。"""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _cleanup(t: asyncio.Task):
            self._background_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc:
                logger.error(f"后台任务异常结束: {exc}", exc_info=exc)

        task.add_done_callback(_cleanup)
        return task

    def _get_cookie_file(self, platform_name: str) -> str:
        return _COOKIE_FILES.get(platform_name, "")

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
                self._add_bg_task(self._process_queue())
            return task_id

        # 识别平台
        platform = self._registry.identify(space_url)
        if not platform:
            raise ValueError(f"无法识别的 URL: {space_url}")

        parsed = platform.parse_url(space_url)
        space_uid = parsed["creator_id"]

        db_platform = await self.db.get_platform_by_name(platform.name)
        if not db_platform:
            pid = await self.db.insert_platform(platform.name, platform.base_url)
        else:
            pid = db_platform["id"]

        task_id = await self.db.insert_task(platform_id=pid, space_url=space_url, space_uid=space_uid)
        await self.db.update_task_status(task_id, "init")

        # 预填名称
        if parsed.get("creator_name"):
            await self.db.update_task_status(task_id, "init", display_name=parsed["creator_name"])
        elif platform.name == "bilibili":
            await self._prefill_display_name(task_id, space_uid)

        await self._scrape_queue.put(task_id)

        if not self._running:
            self._running = True
            self._add_bg_task(self._process_queue())

        return task_id

    async def _prefill_display_name(self, task_id: int, space_uid: str):
        """Try to fetch UP主 name via API to display before scraping."""
        try:
            import aiohttp
            cookies = self._load_cookies("bilibili")
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

    def _load_cookies(self, platform_name: str) -> list[dict]:
        from bilibili_downloader.browser import load_cookies_from_file
        cookie_file = self._get_cookie_file(platform_name)
        if cookie_file:
            return load_cookies_from_file(cookie_file)
        return []

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
                try:
                    await self.db.update_task_status(task_id, "failed", error_message=str(e))
                except Exception as db_err:
                    logger.error(f"Task {task_id} 状态更新也失败了: {db_err}")
                try:
                    await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "failed", "error": str(e)}})
                except Exception:
                    pass

    async def _execute_task(self, task_id: int):
        """Execute a single scrape + download task (platform-agnostic)."""
        task = await self.db.get_task(task_id)
        if not task:
            return

        logger.info(f"[TaskService] 开始执行任务 {task_id}: {task['space_url']}")

        # Check if paused before starting
        if self.is_paused(task_id):
            await self.db.update_task_status(task_id, "paused", error_message=None)
            self._paused_tasks.discard(task_id)
            return

        # 获取平台
        platform = await self._registry.get_by_db_platform_id(self.db, task["platform_id"])
        if not platform:
            await self.db.update_task_status(task_id, "failed", error_message=f"未知平台 ID: {task['platform_id']}")
            return

        settings = load_settings()

        # Bilibili 需要 Cookie
        if platform.needs_cookie():
            await self.db.update_task_status(task_id, "init", cookie_status="checking")
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "init"}})
            cookie_valid = await self._check_cookie(platform.name)
            logger.info(f"[TaskService] 任务 {task_id} Cookie检测结果: {'有效' if cookie_valid else '无效'}")
            if not cookie_valid:
                await self.db.update_task_status(task_id, "init", cookie_status="login_required")
                await self._broadcast({"type": "login_required", "task_id": task_id, "message": "Cookie已失效，请扫码登录"})
                await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "init"}})
                logged_in = await self._wait_for_login(platform.name, timeout=120)
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

        cookies = self._load_cookies(platform.name) if platform.needs_cookie() else []
        browser = None
        session = None

        if platform.needs_browser():
            from bilibili_downloader.browser import PlaywrightBrowser
            browser = PlaywrightBrowser(headless=True, cookies=cookies)
            await browser.start()

        if platform.needs_cookie() or True:
            import aiohttp
            session = aiohttp.ClientSession()

        try:
            scrape_kwargs = {
                "cookies": cookies,
                "browser": browser,
                "session": session,
            }

            try:
                data = await platform.scrape(task["space_uid"], **scrape_kwargs)
            except ValueError as scrape_err:
                err_msg = str(scrape_err)
                if "-403" in err_msg and platform.needs_cookie():
                    logger.warning(f"[TaskService] 任务 {task_id} 采集遇到 -403，尝试重新登录")
                    # 关闭当前浏览器（释放资源）
                    if browser:
                        try:
                            await browser.close()
                        except Exception:
                            pass
                        browser = None
                    # 触发 QR 登录
                    await self.db.update_task_status(task_id, "init", cookie_status="login_required")
                    await self._broadcast({"type": "login_required", "task_id": task_id, "message": "Cookie已失效（-403），请扫码登录"})
                    logged_in = await self._wait_for_login(platform.name, timeout=120)
                    if not logged_in:
                        await self.db.update_task_status(task_id, "failed", error_message="登录超时（-403重试）", cookie_status="expired")
                        await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "failed"}})
                        return
                    # 重新加载 cookie 和浏览器，重试采集
                    cookies = self._load_cookies(platform.name)
                    if platform.needs_browser():
                        from bilibili_downloader.browser import PlaywrightBrowser
                        browser = PlaywrightBrowser(headless=True, cookies=cookies)
                        await browser.start()
                    scrape_kwargs = {"cookies": cookies, "browser": browser, "session": session}
                    data = await platform.scrape(task["space_uid"], **scrape_kwargs)
                else:
                    raise
            creator_info = data.get("creator_info")
            videos = data["videos"]

            total = len(videos)
            logger.info(f"[TaskService] 任务 {task_id} 采集完成: {total} 个视频, 平台: {platform.display_name}")

            cid = None
            if creator_info:
                await self.db.update_task_status(task_id, "scraping", display_name=creator_info["name"])
                pid = task["platform_id"]
                creator = await self.db.get_creator_by_remote(pid, creator_info["remote_id"])
                if not creator:
                    cid = await self.db.insert_creator(
                        platform_id=pid, remote_id=creator_info["remote_id"],
                        name=creator_info["name"], space_url=task["space_url"],
                        avatar_url=creator_info.get("avatar_url"),
                    )
                else:
                    cid = creator["id"]
                await self.db.update_task_status(task_id, "scraping", creator_id=cid, total_videos=total, scraped_videos=total)
            else:
                await self.db.update_task_status(task_id, "scraping", total_videos=total, scraped_videos=total)

            # 存储视频
            sections = data.get("sections", [])
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
            # 独立清理，防止单个失败导致另一个泄漏
            if browser:
                try:
                    await browser.close()
                except Exception as e:
                    logger.error(f"浏览器关闭失败: {e}")
            if session:
                try:
                    await session.close()
                except Exception as e:
                    logger.error(f"Session 关闭失败: {e}")

        await self._broadcast({"type": "scrape_progress", "task_id": task_id,
                               "data": {"scraped": total, "total": total, "phase": "done"}})

        # 创建待下载记录
        if cid:
            settings = load_settings()
            resolution_priority = settings.get("resolution_priority", DEFAULT_RESOLUTION_PRIORITY)
            name_template = settings.get("name_template", DEFAULT_NAME_TEMPLATE)
            save_dir = settings.get("output_dir", "./downloads")
            from bilibili_downloader.storage.files import build_filename, resolve_save_path
            videos = await self.db.get_videos_by_creator(cid)
            dl_count = 0
            resolution = resolution_priority[0] if resolution_priority else "720p"
            # YouTube 使用 "best" 作为分辨率标识
            if platform.name == "youtube":
                resolution = "best"
            for video in videos:
                filename = build_filename(
                    title=video["title"], creator=creator_info["name"] if creator_info else "",
                    section=video.get("section_name"), bvid=video.get("remote_id", ""),
                    template=name_template,
                )
                save_path = resolve_save_path(save_dir, filename)
                await self.db.insert_download(
                    video_id=video["id"], save_path=save_path,
                    resolution=resolution,
                )
                dl_count += 1
            await self.db.update_task_status(task_id, "pending", total_videos=total, scraped_videos=total, total_downloads=dl_count, error_message=None)
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "pending", "total_downloads": dl_count}})
            logger.info(f"[TaskService] 任务 {task_id} 已创建 {dl_count} 个待下载记录")
        else:
            await self.db.update_task_status(task_id, "failed", error_message="无法获取创作者信息")
            await self._broadcast({"type": "task_status", "task_id": task_id, "data": {"status": "failed"}})

    async def _check_cookie(self, platform_name: str) -> bool:
        """Check if cookie is valid for a platform."""
        if platform_name == "bilibili":
            import aiohttp
            cookies = self._load_cookies(platform_name)
            if not cookies:
                return False
            async with aiohttp.ClientSession() as session:
                api = BilibiliAPI(session, cookies=cookies)
                return await api.validate_cookie()
        return True  # YouTube 不需要 cookie

    async def _wait_for_login(self, platform_name: str, timeout: int = 120) -> bool:
        """Wait for QR login to complete."""
        start = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                return False
            if await self._check_cookie(platform_name):
                await self._broadcast({"type": "login_success", "message": "登录成功"})
                return True
            await asyncio.sleep(2)

    async def trigger_qr_login(self) -> tuple[bool, str]:
        """Trigger QR code login in a headed browser. Returns (success, error_message)."""
        from bilibili_downloader.browser import PlaywrightBrowser, save_cookies_to_file
        from bilibili_downloader.cli.main import _qr_code_login
        browser = PlaywrightBrowser(headless=False)
        try:
            await browser.start()
            login_cookies = await _qr_code_login(browser.page)
            cookie_path = self._get_cookie_file("bilibili") or DEFAULT_COOKIE_CACHE_PATH
            save_cookies_to_file(login_cookies, cookie_path)
            return True, ""
        except Exception as e:
            logger.error(f"QR login failed: {e}", exc_info=True)
            return False, str(e)
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
                settings = load_settings()
                import aiohttp
                cookies = self._load_cookies("bilibili")

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
                    await manager.run(session, auto_discover=False)

                    # YouTube 下载（非 Bilibili 的 pending 下载）
                    if not self._download_cancel.is_set():
                        yt_pending = [d for d in all_pending if d.get("platform_name") == "youtube"]
                        if yt_pending:
                            await self._download_youtube_videos(yt_pending, settings)
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

        self._download_task = self._add_bg_task(_run())
        await self._broadcast({"type": "download_progress", "status": "started"})
        return (True, len(all_pending))

    async def _download_youtube_videos(self, pending_downloads: list[dict], settings: dict):
        """下载 YouTube pending 视频。"""
        yt_platform = self._registry.get("youtube")
        if not yt_platform:
            return

        save_dir = settings.get("output_dir", "./downloads")
        name_template = settings.get("name_template", DEFAULT_NAME_TEMPLATE)
        speed_limit_bps = int(settings.get("download_speed_limit", 0) * 1024 * 1024)
        max_concurrent = settings.get("max_concurrent_downloads", MAX_CONCURRENT_DOWNLOADS)
        sem = asyncio.Semaphore(max_concurrent)

        async def _download_one(dl: dict):
            async with sem:
                if self._download_cancel.is_set():
                    return
                video = await self.db.get_video(dl["video_id"])
                if not video:
                    return
                creator_name = dl.get("creator_name", "")
                await yt_platform.download_single(
                    video=video,
                    save_dir=save_dir,
                    name_template=name_template,
                    download_id=dl["id"],
                    db=self.db,
                    ws_manager=self.ws_manager,
                    cancel_event=self._download_cancel,
                    speed_limit_bps=speed_limit_bps,
                    creator_name=creator_name,
                )

        tasks = [_download_one(dl) for dl in pending_downloads]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def reset_and_backfill(self, task_id: int) -> dict:
        """重置下载 + API补全遗漏视频，不触发完整的 Playwright 采集。"""
        task = await self.db.get_task(task_id)
        if not task or not task.get("creator_id"):
            return {"message": "任务不存在"}

        cid = task["creator_id"]
        platform = self._registry.get(task["platform_id"]) if task.get("platform_id") else None
        result = {"reset": 0, "backfill": 0, "message": ""}

        # 重置失败/跳过的下载
        await self.db.reset_task_downloads(cid)
        # 统计被重置的数量
        cur = await self.db._xq(
            "SELECT COUNT(*) FROM download WHERE video_id IN (SELECT id FROM video WHERE creator_id=?) AND status='pending'",
            (cid,),
        )
        result["reset"] = (await cur.fetchone())[0]

        # 记录补全前已有的 video id，用于区分哪些是真正的新视频
        existing_vids_before = {v["id"] for v in await self.db.get_videos_by_creator(cid)}

        # 对于 Bilibili，使用 API 补全遗漏视频
        new_video_ids: list[int] = []
        backfill_failed = False
        if platform and platform.name == "bilibili" and task.get("space_uid"):
            try:
                import aiohttp
                cookies = self._load_cookies("bilibili")
                if cookies:
                    async with aiohttp.ClientSession() as session:
                        from bilibili_downloader.bilibili.api import BilibiliAPI
                        api = BilibiliAPI(session, cookies=cookies)
                        existing_videos = await self.db.get_videos_by_creator(cid)
                        existing_bvids = {v["remote_id"] for v in existing_videos}
                        backfill = await api.fetch_videos_by_api(task["space_uid"], existing_bvids)
                        if backfill:
                            for v in backfill:
                                vid = await self.db.get_video_by_remote(cid, v["remote_id"])
                                if not vid:
                                    new_vid = await self.db.insert_video(
                                        creator_id=cid, remote_id=v["remote_id"],
                                        title=v["title"], duration=v.get("duration"),
                                        pubdate=v.get("pubdate"),
                                        extra=json.dumps(v.get("extra")),
                                        tags=v.get("tags"),
                                    )
                                    new_video_ids.append(new_vid)
                            logger.info(f"[TaskService] reset_and_backfill {task_id}: API补全 {len(backfill)} 个视频, {len(new_video_ids)} 个新增")
                        else:
                            logger.info(f"[TaskService] reset_and_backfill {task_id}: API补全未发现新视频")
                else:
                    logger.warning(f"[TaskService] reset_and_backfill {task_id}: Cookie不可用，跳过API补全")
                    backfill_failed = True
            except Exception as e:
                logger.warning(f"[TaskService] reset_and_backfill {task_id}: API补全失败: {e}")
                backfill_failed = True

        # 仅对新补全的视频创建下载记录（已有视频的 download 记录不受影响）
        if new_video_ids:
            settings = load_settings()
            resolution_priority = settings.get("resolution_priority", DEFAULT_RESOLUTION_PRIORITY)
            name_template = settings.get("name_template", DEFAULT_NAME_TEMPLATE)
            save_dir = settings.get("output_dir", "./downloads")
            from bilibili_downloader.storage.files import build_filename, resolve_save_path
            creator_name = await self._get_creator_name(cid)
            for vid_id in new_video_ids:
                video = await self.db.get_video(vid_id)
                if video:
                    await self.db.insert_download(
                        video_id=vid_id,
                        save_path=resolve_save_path(
                            save_dir,
                            build_filename(
                                title=video["title"], creator=creator_name,
                                section=video.get("section_name"),
                                bvid=video.get("remote_id", ""),
                                template=name_template,
                            ),
                        ),
                        resolution=resolution_priority[0] if resolution_priority else "720p",
                    )
        result["backfill"] = len(new_video_ids)

        # 同步任务状态
        await self.db.sync_task_status_from_downloads(task_id)

        # 生成反馈消息
        parts = []
        if result["reset"] > 0:
            parts.append(f"{result['reset']} 个视频重置为待下载")
        if result["backfill"] > 0:
            parts.append(f"{result['backfill']} 个新视频待下载")
        if parts:
            result["message"] = "已处理: " + "，".join(parts) + "。请点击下载开始处理。"
        elif backfill_failed:
            result["message"] = "无变化：所有已完成视频保持不变。注意：API补全失败（可能需要重新扫码登录Cookie），无法检查是否有新视频。"
        else:
            result["message"] = "无变化：所有视频均已完成，API补全未发现新视频。"

        return result

    async def _get_creator_name(self, creator_id: int) -> str:
        creator = await self.db.get_creator(creator_id)
        return creator["name"] if creator else ""

    async def pause_downloads(self) -> bool:
        """Pause all downloads. Returns False if not running."""
        if not self._download_running:
            return False
        self._download_cancel.set()
        return True

    def is_downloading(self) -> bool:
        return self._download_running
