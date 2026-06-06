import logging
import os

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from bilibili_downloader.config import SETTINGS_PATH, load_settings, save_settings

logger = logging.getLogger(__name__)


def create_routes(db, env, task_service=None):
    async def index(request: Request) -> HTMLResponse:
        from bilibili_downloader.config import SETTINGS_PATH
        stats = await db.get_stats()
        settings = load_settings()
        template = env.get_template("index.html")
        html = template.render(request=request, stats=stats, settings=settings)
        return HTMLResponse(html)

    async def api_stats(request: Request) -> JSONResponse:
        stats = await db.get_stats()
        return JSONResponse(stats)

    async def api_downloads(request: Request) -> JSONResponse:
        status = request.query_params.get("status")
        creator_id = request.query_params.get("creator_id")
        section_name = request.query_params.get("section_name")
        tags_param = request.query_params.get("tags")
        tags = [t for t in tags_param.split(",") if t] if tags_param else None
        page = int(request.query_params.get("page", 1))
        page_size = int(request.query_params.get("page_size", 20))
        downloads = await db.get_all_downloads(
            status=status or None,
            creator_id=int(creator_id) if creator_id else None,
            section_name=section_name or None,
            tags=tags,
            page=page, page_size=page_size,
        )
        return JSONResponse(downloads)

    async def api_clear_downloads(request: Request) -> JSONResponse:
        try:
            await db.clear_all_downloads()
            return JSONResponse({"ok": True})
        except Exception as e:
            logger.error(f"清空下载记录失败: {e}")
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    async def api_creators(request: Request) -> JSONResponse:
        creators = await db.get_creators_with_stats()
        return JSONResponse(creators)

    async def api_sections(request: Request) -> JSONResponse:
        sections = await db.get_sections()
        return JSONResponse(sections)

    async def api_tags(request: Request) -> JSONResponse:
        tags = await db.get_tags()
        return JSONResponse(tags)

    async def api_download_detail(request: Request) -> JSONResponse:
        download_id = int(request.path_params["download_id"])
        dl = await db.get_download(download_id)
        if not dl:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(dict(dl))

    async def api_settings(request: Request) -> JSONResponse:
        if request.method == "POST":
            data = await request.json()
            logger.info(f"保存设置: {data}")
            current = load_settings()
            allowed_keys = {"max_concurrent_downloads", "max_concurrent_api",
                             "resolution_priority", "name_template", "output_dir", "web_port"}
            for key, value in data.items():
                if key in allowed_keys:
                    current[key] = value
            try:
                save_settings(current)
                logger.info(f"设置已保存到 {SETTINGS_PATH}")
            except Exception as e:
                logger.error(f"保存设置失败: {e}")
                return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
            return JSONResponse({"ok": True, "settings": current})
        else:
            return JSONResponse(load_settings())

    async def api_pick_directory(request: Request) -> JSONResponse:
        """Open native directory picker dialog. Returns selected path."""
        import asyncio
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            return JSONResponse({"ok": False, "error": "tkinter not available"}, status_code=500)

        data = await request.json()
        initial_dir = data.get("current_path", "./downloads")

        def _pick():
            root = tk.Tk()
            root.withdraw()
            result = filedialog.askdirectory(initialdir=initial_dir, title="选择保存目录")
            root.destroy()
            return result

        selected = await asyncio.to_thread(_pick)
        if selected:
            return JSONResponse({"ok": True, "path": selected})
        return JSONResponse({"ok": False, "error": "cancelled"})

    async def api_list_directories(request: Request) -> JSONResponse:
        """List subdirectories of a given path."""
        from pathlib import Path
        data = await request.json()
        path_str = data.get("path", ".")
        try:
            p = Path(path_str)
            if not p.exists():
                return JSONResponse({"ok": False, "error": "path not found"}, status_code=404)
            dirs = []
            for entry in sorted(p.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    dirs.append({"name": entry.name, "path": str(entry.resolve())})
            return JSONResponse({"ok": True, "directories": dirs, "parent": str(p.resolve()), "has_parent": p.parent != p})
        except PermissionError:
            return JSONResponse({"ok": False, "error": "permission denied"}, status_code=403)

    async def api_tasks(request: Request) -> JSONResponse:
        status = request.query_params.get("status")
        page = int(request.query_params.get("page", 1))
        tasks = await db.get_all_tasks(status=status or None, page=page, page_size=50)
        return JSONResponse(tasks)

    async def api_task_submit(request: Request) -> JSONResponse:
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        data = await request.json()
        space_url = data.get("space_url", "").strip()
        if not space_url:
            return JSONResponse({"ok": False, "error": "space_url is required"}, status_code=400)
        try:
            task_id = await task_service.submit_task(space_url)
            return JSONResponse({"ok": True, "task_id": task_id})
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    async def api_task_detail(request: Request) -> JSONResponse:
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(dict(task))

    async def api_task_retry(request: Request) -> JSONResponse:
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        if task["status"] != "failed":
            return JSONResponse({"ok": False, "error": "Only failed tasks can be retried"}, status_code=400)
        await db.update_task_status(task_id, "pending", error_message=None, cookie_status="valid")
        await task_service.submit_task(task["space_url"])
        return JSONResponse({"ok": True})

    async def api_task_force(request: Request) -> JSONResponse:
        """Force re-scrape and re-download all videos for a task's creator."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        if task.get("creator_id"):
            await db.reset_task_downloads(task["creator_id"])
        await db.update_task_status(task_id, "pending", error_message=None, cookie_status="valid",
                                     total_videos=0, scraped_videos=0, downloaded_videos=0, total_downloads=0)
        await task_service.submit_task(task["space_url"])
        return JSONResponse({"ok": True})

    async def api_task_pause(request: Request) -> JSONResponse:
        """Pause a running task (cooperative, checked at phase boundaries)."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        if task["status"] not in ("pending", "scraping", "downloading"):
            return JSONResponse({"ok": False, "error": "Only pending/scraping/downloading tasks can be paused"}, status_code=400)
        task_service.pause_task(task_id)
        await db.update_task_status(task_id, "paused")
        return JSONResponse({"ok": True})

    async def api_task_resume(request: Request) -> JSONResponse:
        """Resume a paused task."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        if task["status"] != "paused":
            return JSONResponse({"ok": False, "error": "Only paused tasks can be resumed"}, status_code=400)
        task_service.resume_task(task_id)
        await db.update_task_status(task_id, "pending", error_message=None, cookie_status="valid")
        await task_service.submit_task(task["space_url"])
        return JSONResponse({"ok": True})

    async def api_task_reset_downloads(request: Request) -> JSONResponse:
        """Reset all downloads for a task's creator to pending (re-download without re-scrape)."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        if not task.get("creator_id"):
            return JSONResponse({"ok": False, "error": "Task has no creator, cannot reset downloads"}, status_code=400)
        await db.reset_task_downloads(task["creator_id"])
        await db.update_task_status(task_id, "pending", error_message=None, cookie_status="valid",
                                     downloaded_videos=0, total_downloads=0)
        await task_service.submit_task(task["space_url"])
        return JSONResponse({"ok": True})

    async def api_task_update_url(request: Request) -> JSONResponse:
        """Update a task's space URL."""
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        data = await request.json()
        space_url = data.get("space_url", "").strip()
        if not space_url:
            return JSONResponse({"ok": False, "error": "space_url is required"}, status_code=400)
        import re as _re
        match = _re.search(r"https?://space\.bilibili\.com/(\d+)", space_url)
        if not match:
            return JSONResponse({"ok": False, "error": "Invalid Bilibili space URL"}, status_code=400)
        await db.update_task_url(task_id, space_url, match.group(1))
        return JSONResponse({"ok": True})

    async def api_task_delete(request: Request) -> JSONResponse:
        """Delete a task and its associated downloads/videos."""
        task_id = int(request.path_params["task_id"])
        task = await db.get_task(task_id)
        if not task:
            return JSONResponse({"error": "not found"}, status_code=404)
        await db.delete_task(task_id)
        return JSONResponse({"ok": True})

    async def api_download_start(request: Request) -> JSONResponse:
        """Start downloading all pending videos."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        started, pending_count = await task_service.start_downloads()
        if started:
            return JSONResponse({"ok": True, "pending": pending_count})
        if pending_count == 0:
            return JSONResponse({"ok": False, "error": "没有待下载的视频"}, status_code=400)
        return JSONResponse({"ok": False, "error": "Download already running"}, status_code=409)

    async def api_download_pause(request: Request) -> JSONResponse:
        """Pause all downloads."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        paused = await task_service.pause_downloads()
        if not paused:
            return JSONResponse({"ok": False, "error": "No download running"}, status_code=409)
        return JSONResponse({"ok": True})

    async def api_download_retry(request: Request) -> JSONResponse:
        """Reset a download to pending so it can be picked up by the download manager."""
        download_id = int(request.path_params["download_id"])
        dl = await db.get_download(download_id)
        if not dl:
            return JSONResponse({"error": "not found"}, status_code=404)
        if dl["status"] == "downloading":
            return JSONResponse({"ok": False, "error": "正在下载中，请先暂停"}, status_code=400)
        await db.update_download_status(download_id, "pending", error_msg=None)
        return JSONResponse({"ok": True})

    async def api_download_batch_start(request: Request) -> JSONResponse:
        """Reset selected downloads to pending and start downloading."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        data = await request.json()
        ids = data.get("ids", [])
        if not ids:
            return JSONResponse({"ok": False, "error": "未选择视频"}, status_code=400)
        reset_count = 0
        for did in ids:
            dl = await db.get_download(int(did))
            if dl and dl["status"] != "downloading":
                await db.update_download_status(int(did), "pending", error_msg=None)
                reset_count += 1
        # Auto-start if not running
        started = False
        if reset_count > 0 and not task_service.is_downloading():
            await task_service.start_downloads()
            started = True
        return JSONResponse({"ok": True, "reset_count": reset_count, "started": started})

    async def api_download_delete(request: Request) -> JSONResponse:
        """Delete a single download record."""
        download_id = int(request.path_params["download_id"])
        dl = await db.get_download(download_id)
        if not dl:
            return JSONResponse({"error": "not found"}, status_code=404)
        await db.delete_download(download_id)
        return JSONResponse({"ok": True})

    async def api_download_status(request: Request) -> JSONResponse:
        """Check if download is currently running."""
        if not task_service:
            return JSONResponse({"running": False})
        return JSONResponse({"running": task_service.is_downloading()})

    async def api_video_file(request: Request) -> FileResponse:
        """Serve a downloaded video file for preview/play."""
        download_id = int(request.path_params["download_id"])
        dl = await db.get_download(download_id)
        if not dl:
            return JSONResponse({"error": "not found"}, status_code=404)
        save_path = dl.get("save_path", "")
        if not save_path or not os.path.exists(save_path):
            return JSONResponse({"error": "file not found"}, status_code=404)
        return FileResponse(
            save_path,
            media_type="video/mp4",
            filename=os.path.basename(save_path),
        )

    async def api_cookie_status(request: Request) -> JSONResponse:
        """Check cookie validity."""
        import json
        from bilibili_downloader.config import DEFAULT_COOKIE_CACHE_PATH
        cookie_path = DEFAULT_COOKIE_CACHE_PATH
        try:
            with open(cookie_path, encoding="utf-8") as f:
                cookies = json.load(f)
            if not cookies or not isinstance(cookies, list):
                return JSONResponse({"valid": False, "exists": True, "uname": None})
            import aiohttp
            async with aiohttp.ClientSession() as session:
                from bilibili_downloader.bilibili.api import BilibiliAPI
                api = BilibiliAPI(session, cookies=cookies)
                valid = await api.validate_cookie()
                if valid:
                    async with session.get(
                        "https://api.bilibili.com/x/web-interface/nav",
                        headers=api.headers, timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        data = await resp.json()
                    uname = data.get("data", {}).get("uname", "")
                else:
                    uname = None
            return JSONResponse({"valid": valid, "exists": True, "uname": uname})
        except FileNotFoundError:
            return JSONResponse({"valid": False, "exists": False})
        except Exception as e:
            logger.error(f"Cookie status check failed: {e}")
            return JSONResponse({"valid": False, "exists": True, "uname": None, "error": str(e)})

    async def api_cookie_clear(request: Request) -> JSONResponse:
        """Clear cookie cache file."""
        from bilibili_downloader.config import DEFAULT_COOKIE_CACHE_PATH
        try:
            os.remove(DEFAULT_COOKIE_CACHE_PATH)
        except FileNotFoundError:
            pass
        return JSONResponse({"ok": True})

    async def api_trigger_login(request: Request) -> JSONResponse:
        """Trigger QR login in a headed browser."""
        if not task_service:
            return JSONResponse({"ok": False, "error": "TaskService not available"}, status_code=503)
        success = await task_service.trigger_qr_login()
        if success:
            return JSONResponse({"ok": True, "message": "QR login completed"})
        return JSONResponse({"ok": False, "error": "QR login failed or timed out"}, status_code=500)

    return {
        "/": (index, ["GET"]),
        "/api/stats": (api_stats, ["GET"]),
        "/api/downloads": (api_downloads, ["GET"]),
        "/api/downloads/clear": (api_clear_downloads, ["POST"]),
        "/api/downloads/batch-start": (api_download_batch_start, ["POST"]),
        "/api/downloads/start": (api_download_start, ["POST"]),
        "/api/downloads/pause": (api_download_pause, ["POST"]),
        "/api/downloads/status": (api_download_status, ["GET"]),
        "/api/downloads/{download_id}": (api_download_detail, ["GET"]),
        "/api/downloads/{download_id}/retry": (api_download_retry, ["POST"]),
        "/api/downloads/{download_id}/delete": (api_download_delete, ["DELETE"]),
        "/api/downloads/{download_id}/play": (api_video_file, ["GET"]),
        "/api/creators": (api_creators, ["GET"]),
        "/api/sections": (api_sections, ["GET"]),
        "/api/tags": (api_tags, ["GET"]),
        "/api/settings": (api_settings, ["GET", "POST"]),
        "/api/pick-directory": (api_pick_directory, ["POST"]),
        "/api/directories": (api_list_directories, ["POST"]),
        "/api/tasks": (api_tasks, ["GET"]),
        "/api/tasks/submit": (api_task_submit, ["POST"]),
        "/api/tasks/{task_id}": (api_task_detail, ["GET"]),
        "/api/tasks/{task_id}/retry": (api_task_retry, ["POST"]),
        "/api/tasks/{task_id}/force": (api_task_force, ["POST"]),
        "/api/tasks/{task_id}/pause": (api_task_pause, ["POST"]),
        "/api/tasks/{task_id}/resume": (api_task_resume, ["POST"]),
        "/api/tasks/{task_id}/reset-downloads": (api_task_reset_downloads, ["POST"]),
        "/api/tasks/{task_id}/url": (api_task_update_url, ["POST"]),
        "/api/tasks/{task_id}/delete": (api_task_delete, ["POST"]),
        "/api/cookie/status": (api_cookie_status, ["GET"]),
        "/api/cookie/clear": (api_cookie_clear, ["POST"]),
        "/api/trigger-login": (api_trigger_login, ["POST"]),
    }
