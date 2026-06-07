import pathlib
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from bilibili_downloader.web.routes import create_routes
from bilibili_downloader.web.ws_manager import get_ws_manager

logger = logging.getLogger(__name__)


def create_app(db, task_service=None):
    app = FastAPI(title="Bilibili Downloader Dashboard")
    templates_dir = pathlib.Path(__file__).parent / "templates"

    from jinja2 import Environment, FileSystemLoader
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=True,
    )

    def filesizeformat(value):
        if value is None:
            return "0 B"
        value = int(value)
        for unit in ("B", "KB", "MB", "GB"):
            if abs(value) < 1024:
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"

    env.filters["filesizeformat"] = filesizeformat
    routes = create_routes(db, env, task_service=task_service)
    for path, (handler, methods) in routes.items():
        app.add_api_route(path, handler, methods=methods)

    ws_manager = get_ws_manager()

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        await ws.accept()
        ws_manager.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            ws_manager.disconnect(ws)

    return app
