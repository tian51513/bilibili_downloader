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
        limit = int(request.query_params.get("limit", 200))
        offset = int(request.query_params.get("offset", 0))
        downloads = await db.get_all_downloads(
            status=status or None,
            creator_id=int(creator_id) if creator_id else None,
            section_name=section_name or None,
            tags=tags,
            limit=limit, offset=offset,
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

    return {
        "/": (index, ["GET"]),
        "/api/stats": (api_stats, ["GET"]),
        "/api/downloads": (api_downloads, ["GET"]),
        "/api/downloads/{download_id}": (api_download_detail, ["GET"]),
        "/api/creators": (api_creators, ["GET"]),
        "/api/sections": (api_sections, ["GET"]),
        "/api/tags": (api_tags, ["GET"]),
        "/api/settings": (api_settings, ["GET", "POST"]),
    }
