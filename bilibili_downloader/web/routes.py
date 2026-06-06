import logging

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

from bilibili_downloader.config import SETTINGS_PATH, load_settings, save_settings

logger = logging.getLogger(__name__)


def create_routes(db, env):
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

    return {
        "/": (index, ["GET"]),
        "/api/stats": (api_stats, ["GET"]),
        "/api/downloads": (api_downloads, ["GET"]),
        "/api/downloads/{download_id}": (api_download_detail, ["GET"]),
        "/api/creators": (api_creators, ["GET"]),
        "/api/sections": (api_sections, ["GET"]),
        "/api/tags": (api_tags, ["GET"]),
        "/api/settings": (api_settings, ["GET", "POST"]),
        "/api/pick-directory": (api_pick_directory, ["POST"]),
        "/api/directories": (api_list_directories, ["POST"]),
    }
