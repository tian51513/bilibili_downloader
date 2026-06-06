from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates


def create_routes(db, templates: Jinja2Templates):
    async def index(request: Request) -> HTMLResponse:
        stats = await db.get_stats()
        downloads = await db.get_all_downloads(limit=200)
        return templates.TemplateResponse("index.html", {"request": request, "stats": stats, "downloads": downloads})

    async def api_stats(request: Request) -> JSONResponse:
        stats = await db.get_stats()
        return JSONResponse(stats)

    async def api_downloads(request: Request) -> JSONResponse:
        status = request.query_params.get("status")
        limit = int(request.query_params.get("limit", 100))
        offset = int(request.query_params.get("offset", 0))
        downloads = await db.get_all_downloads(status=status, limit=limit, offset=offset)
        return JSONResponse(downloads)

    async def api_download_detail(request: Request) -> JSONResponse:
        download_id = int(request.path_params["download_id"])
        dl = await db.get_download(download_id)
        if not dl:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(dict(dl))

    return {
        "/": (index, ["GET"]),
        "/api/stats": (api_stats, ["GET"]),
        "/api/downloads": (api_downloads, ["GET"]),
        "/api/downloads/{download_id}": (api_download_detail, ["GET"]),
    }
