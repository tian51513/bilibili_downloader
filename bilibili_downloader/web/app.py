import pathlib

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from bilibili_downloader.web.routes import create_routes


def create_app(db):
    app = FastAPI(title="Bilibili Downloader Dashboard")
    templates_dir = pathlib.Path(__file__).parent / "templates"

    # Starlette Jinja2Templates 与 Jinja2 3.1.x 不兼容，直接使用 Jinja2 Environment
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
    routes = create_routes(db, env)
    for path, (handler, methods) in routes.items():
        app.add_api_route(path, handler, methods=methods)
    return app
